"""Tests for the `bssh exec` broadcast command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.cli.exec_cmd import ExecResult, _build_ssh_exec_command, _color_for
from app.models import Server
from app.storage import save_servers

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_build_ssh_exec_command_minimal_server():
    """Test basic argv has BatchMode, ConnectTimeout, port, user@host and the command at the end."""
    srv = Server(name="a", host="a.example", username="u", port=22)
    argv = _build_ssh_exec_command(srv, "uptime", [srv], connect_timeout=10)
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "ConnectTimeout=10" in argv
    assert "-p" in argv
    assert "22" in argv
    assert "u@a.example" in argv
    # The remote command is the final positional argument
    assert argv[-1] == "uptime"


def test_build_ssh_exec_command_passes_key_and_cert_and_jump():
    """Test auth fields and jump_host chain propagate to the argv."""
    bastion = Server(name="b", host="b.example", username="ops", port=2222)
    target = Server(
        name="t",
        host="t.example",
        username="deploy",
        port=22,
        key_path="/k/id_ed25519",
        certificate_path="/k/id_ed25519-cert.pub",
        jump_host="b",
        keep_alive_interval=45,
    )
    argv = _build_ssh_exec_command(target, "whoami", [bastion, target], connect_timeout=5)
    assert "-i" in argv
    assert "/k/id_ed25519" in argv
    assert "CertificateFile=/k/id_ed25519-cert.pub" in argv
    assert "-J" in argv
    assert "ops@b.example:2222" in argv
    assert "ServerAliveInterval=45" in argv


def test_color_for_cycles_through_palette():
    """Test _color_for returns the same color for the same index and rotates."""
    first = _color_for(0)
    same = _color_for(0)
    next_one = _color_for(1)
    assert first == same
    assert first != next_one


# ---------------------------------------------------------------------------
# CLI orchestration (patch _run_on_server to keep the tests sync and fast)
# ---------------------------------------------------------------------------


def _fake_result_factory(success: bool = True, stdout: str = "ok", exit_code: int = 0):
    """Return an async function that emits a predictable ExecResult per server."""

    async def fake(server, remote_cmd, all_servers, timeout, connect_timeout):  # noqa: ASYNC109
        return ExecResult(
            server=server,
            returncode=0 if success else exit_code,
            stdout=stdout if success else "",
            stderr="" if success else "boom",
            duration=0.05,
            error=None,
        )

    return fake


def test_exec_runs_on_all_matching_servers(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh exec <cmd> <query>` runs on every server matching the query."""
    save_servers(
        [
            Server(id="a", name="prod-web", host="w.example", username="u", tags=["prod"]),
            Server(id="b", name="prod-db", host="d.example", username="u", tags=["prod"]),
            Server(id="c", name="dev-web", host="x.example", username="u", tags=["dev"]),
        ]
    )
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("app.cli.exec_cmd._run_on_server", _fake_result_factory(success=True, stdout="running"))

    result = runner.invoke(app, ["exec", "uptime", "prod"])

    assert result.exit_code == 0
    # Both prod-web and prod-db should appear in prefixed output
    assert "prod-web" in result.stdout
    assert "prod-db" in result.stdout
    # dev-web does not match the 'prod' query
    assert "dev-web" not in result.stdout
    # Summary shows all succeeded
    assert "2/2 ok" in result.stdout


def test_exec_all_flag_runs_on_every_server(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --all bypasses the query filter and targets every saved server."""
    save_servers(
        [
            Server(id="a", name="alpha", host="a.example", username="u"),
            Server(id="b", name="beta", host="b.example", username="u"),
        ]
    )
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("app.cli.exec_cmd._run_on_server", _fake_result_factory(success=True, stdout="fine"))

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 0
    assert "alpha" in result.stdout
    assert "beta" in result.stdout
    assert "2/2 ok" in result.stdout


def test_exec_without_query_or_all_flag_errors(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test omitting both the query argument and --all surfaces a usage error."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")

    result = runner.invoke(app, ["exec", "uptime"])

    assert result.exit_code == 2
    assert "Provide a query or --all" in result.stdout


def test_exec_unmatched_query_exits_1(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test a query with no matches prints a friendly message and exits 1."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")

    result = runner.invoke(app, ["exec", "uptime", "ghost-query"])

    assert result.exit_code == 1
    assert "No servers match 'ghost-query'" in result.stdout


def test_exec_with_failing_server_returns_exit_1(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test non-zero exit from a single host makes the aggregate exit non-zero."""
    save_servers(
        [
            Server(id="a", name="alpha", host="a.example", username="u"),
            Server(id="b", name="beta", host="b.example", username="u"),
        ]
    )

    async def fake(server, remote_cmd, all_servers, timeout, connect_timeout):  # noqa: ASYNC109
        # alpha succeeds, beta fails
        if server.name == "alpha":
            return ExecResult(server, 0, "fine", "", 0.1)
        return ExecResult(server, 1, "", "something broke", 0.1)

    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("app.cli.exec_cmd._run_on_server", fake)

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 1
    assert "1/2 ok" in result.stdout
    # stderr lines from beta should be tagged red (raw text check)
    assert "something broke" in result.stdout


def test_exec_reports_connection_level_error(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test errors like timeouts or spawn failures render as 'error:' lines."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])

    async def fake(server, remote_cmd, all_servers, timeout, connect_timeout):  # noqa: ASYNC109
        return ExecResult(server, 124, "", "", 30.0, error="timed out after 30s")

    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("app.cli.exec_cmd._run_on_server", fake)

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 1
    assert "error:" in result.stdout
    assert "timed out after 30s" in result.stdout


def test_exec_no_ssh_on_path_exits_127(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test missing ssh binary causes a clean exit 127."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: None)

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 127
    assert "ssh not found" in result.stdout


def test_exec_empty_server_db_exits_1(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test exec with no saved servers surfaces the add-one onboarding hint."""
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 1
    assert "No servers saved" in result.stdout


# ---------------------------------------------------------------------------
# Output rendering: colored per-host prefix + escape of brackets
# ---------------------------------------------------------------------------


def test_exec_output_includes_bracketed_prefix_per_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test each line of output carries a [<name>] prefix."""
    save_servers([Server(id="a", name="srv", host="h.example", username="u")])
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("app.cli.exec_cmd._run_on_server", _fake_result_factory(success=True, stdout="line1\nline2"))

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 0
    # The host-name prefix wraps every output line
    assert "[srv] line1" in result.stdout
    assert "[srv] line2" in result.stdout


def test_exec_escapes_rich_markup_in_output(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test square brackets in remote output render literally."""
    save_servers([Server(id="a", name="srv", host="h.example", username="u")])
    monkeypatch.setattr("app.cli.exec_cmd.shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr(
        "app.cli.exec_cmd._run_on_server",
        _fake_result_factory(success=True, stdout="[red]not a tag[/red]"),
    )

    result = runner.invoke(app, ["exec", "uptime", "--all"])

    assert result.exit_code == 0
    assert "[red]not a tag[/red]" in result.stdout
