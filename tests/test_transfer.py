"""Tests for the put / get SCP wrapper commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.models import Server
from app.storage import save_servers


def _patch_scp_capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Patch scp presence + subprocess.call; return the list where cmds land."""
    captured: list[list[str]] = []
    monkeypatch.setattr("app.cli.transfer.has_scp", lambda: True)
    monkeypatch.setattr("app.cli.transfer.subprocess.call", lambda cmd: captured.append(cmd) or 0)
    return captured


# ---------------------------------------------------------------------------
# put
# ---------------------------------------------------------------------------


def test_put_builds_scp_upload_command(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh put` issues a local->remote scp invocation with port and target."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="deploy", port=2222)])
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["put", "Srv", "./local.sql", "/var/backups/backup.sql"])

    assert result.exit_code == 0
    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[0] == "scp"
    assert "-P" in cmd
    assert "2222" in cmd
    assert "./local.sql" in cmd
    assert "deploy@h.example:/var/backups/backup.sql" in cmd


def test_put_honors_recursive_and_compress_flags(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test -r / -C translate to scp's own -r / -C flags."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="u")])
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["put", "Srv", "./dir", "/remote/dir", "-r", "-C"])

    assert result.exit_code == 0
    assert "-r" in captured[0]
    assert "-C" in captured[0]


def test_put_passes_key_and_certificate(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test stored key_path and certificate_path propagate into -i / -o CertificateFile."""
    save_servers(
        [
            Server(
                id="s-1",
                name="Srv",
                host="h.example",
                username="u",
                key_path="/keys/id_ed25519",
                certificate_path="/keys/id_ed25519-cert.pub",
            )
        ]
    )
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["put", "Srv", "./f", "/remote/f"])

    assert result.exit_code == 0
    cmd = captured[0]
    assert "-i" in cmd
    assert "/keys/id_ed25519" in cmd
    assert "CertificateFile=/keys/id_ed25519-cert.pub" in cmd


def test_put_emits_proxyjump_from_stored_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test jump_host on the target server produces scp -J user@host:port."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops", port=22),
            Server(
                id="t-1",
                name="Target",
                host="t.example",
                username="deploy",
                jump_host="Bastion",
            ),
        ]
    )
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["put", "Target", "./x", "/remote/x"])

    assert result.exit_code == 0
    cmd = captured[0]
    assert "-J" in cmd
    assert "ops@b.example:22" in cmd


def test_put_includes_server_alive_interval_when_set(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test a server with keep_alive_interval propagates to scp via -o ServerAliveInterval=N."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="u", keep_alive_interval=45)])
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["put", "Srv", "./f", "/remote/f"])

    assert result.exit_code == 0
    cmd = captured[0]
    assert "ServerAliveInterval=45" in cmd


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_builds_scp_download_command(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh get` issues a remote->local scp invocation with reversed args."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="deploy")])
    captured = _patch_scp_capture(monkeypatch)

    result = runner.invoke(app, ["get", "Srv", "/var/log/app.log", "./app.log"])

    assert result.exit_code == 0
    cmd = captured[0]
    assert "deploy@h.example:/var/log/app.log" in cmd
    assert "./app.log" in cmd
    # Source must come before destination in the argv
    assert cmd.index("deploy@h.example:/var/log/app.log") < cmd.index("./app.log")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_put_without_scp_binary_exits_127(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test missing scp on PATH returns exit code 127 with an install hint."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="u")])
    monkeypatch.setattr("app.cli.transfer.has_scp", lambda: False)

    result = runner.invoke(app, ["put", "Srv", "./f", "/remote/f"])

    assert result.exit_code == 127
    assert "scp not found" in result.stdout


def test_put_unknown_server_exits_1(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh put <unknown>` fails cleanly with a server-not-found message."""
    save_servers([Server(id="s-1", name="Srv", host="h.example", username="u")])
    monkeypatch.setattr("app.cli.transfer.has_scp", lambda: True)

    result = runner.invoke(app, ["put", "Ghost", "./f", "/remote/f"])

    assert result.exit_code == 1
    assert "Server not found" in result.stdout


def test_put_with_no_servers_shows_empty_state(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test put on an empty DB tells the user to add a server first."""
    monkeypatch.setattr("app.cli.transfer.has_scp", lambda: True)

    result = runner.invoke(app, ["put", "Srv", "./f", "/remote/f"])

    assert result.exit_code == 1
    assert "No servers saved" in result.stdout
