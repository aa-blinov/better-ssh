"""Tests for SSH config import helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import Forward, Server
from app.ssh_config import (
    collect_host_aliases,
    import_ssh_config,
    render_server_as_ssh_config_block,
    render_servers_as_ssh_config,
)


def test_collect_host_aliases_reads_explicit_hosts_and_includes(temp_ssh_dir: Path):
    """Test host alias discovery across config includes."""
    config_file = temp_ssh_dir / "config"
    include_dir = temp_ssh_dir / "config.d"
    include_dir.mkdir(parents=True, exist_ok=True)
    included_file = include_dir / "extra.conf"

    config_file.write_text(
        "Host prod stage\n  HostName example.com\nInclude config.d/*.conf\nHost *\n  User ignored",
        encoding="utf-8",
    )
    included_file.write_text(
        "Host db\n  HostName db.internal\nHost *.wildcard\n  User ignored\nHost !negated\n  User ignored",
        encoding="utf-8",
    )

    aliases = collect_host_aliases(config_file)

    assert aliases == ["prod", "stage", "db"]


def test_import_ssh_config_resolves_identity_files(
    temp_ssh_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test SSH config import keeps only explicit auth paths from `ssh -G`."""
    config_file = temp_ssh_dir / "config"
    config_file.write_text("Host prod db\n", encoding="utf-8")

    default_key_file = temp_ssh_dir / "id_ed25519"
    default_key_file.write_text("default-key", encoding="utf-8")
    custom_key_file = temp_ssh_dir / "work_ed25519"
    custom_key_file.write_text("custom-key", encoding="utf-8")
    custom_cert_file = temp_ssh_dir / "work_ed25519-cert.pub"
    custom_cert_file.write_text("custom-cert", encoding="utf-8")

    user_outputs = {
        "prod": (
            "host prod\n"
            "hostname prod.example.com\n"
            "user deploy\n"
            "port 2222\n"
            "identityfile ~/.ssh/id_ed25519\n"
            "identityfile ~/.ssh/work_ed25519\n"
            "certificatefile ~/.ssh/work_ed25519-cert.pub"
        ),
        "db": ("host db\nhostname 10.0.0.10\nuser postgres\nport 22\nidentityfile ~/.ssh/id_ed25519"),
    }
    default_outputs = {
        "prod": ("host prod\nhostname prod.example.com\nuser deploy\nport 2222\nidentityfile ~/.ssh/id_ed25519"),
        "db": ("host db\nhostname 10.0.0.10\nuser postgres\nport 22\nidentityfile ~/.ssh/id_ed25519"),
    }

    def fake_run(command, check, capture_output, text):
        alias = command[2]
        config_path = command[4]
        output = user_outputs[alias] if config_path == str(config_file) else default_outputs[alias]
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr("app.ssh_config.shutil.which", lambda _: "ssh")
    monkeypatch.setattr("app.ssh_config.subprocess.run", fake_run)

    servers = import_ssh_config(config_file)

    assert len(servers) == 2
    assert servers[0].name == "prod"
    assert servers[0].host == "prod.example.com"
    assert servers[0].username == "deploy"
    assert servers[0].port == 2222
    assert servers[0].key_path == str(custom_key_file)
    assert servers[0].certificate_path == str(custom_cert_file)
    assert servers[1].name == "db"
    assert servers[1].key_path is None
    assert servers[1].certificate_path is None


def test_import_ssh_config_resolves_proxyjump_to_sibling_alias(
    temp_ssh_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test ProxyJump <alias> is imported as jump_host when the alias is another imported host."""
    config_file = temp_ssh_dir / "config"
    config_file.write_text("Host bastion prod\n", encoding="utf-8")

    outputs = {
        "bastion": "host bastion\nhostname bastion.example.com\nuser ops\nport 22",
        "prod": "host prod\nhostname prod.example.com\nuser deploy\nport 22\nproxyjump bastion",
    }

    def fake_run(command, check, capture_output, text):
        alias = command[2]
        config_path = command[4]
        output = outputs[alias] if config_path == str(config_file) else outputs[alias].split("\nproxyjump")[0]
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr("app.ssh_config.shutil.which", lambda _: "ssh")
    monkeypatch.setattr("app.ssh_config.subprocess.run", fake_run)

    servers = import_ssh_config(config_file)

    by_name = {s.name: s for s in servers}
    assert by_name["bastion"].jump_host is None
    assert by_name["prod"].jump_host == "bastion"


def test_import_ssh_config_skips_inline_proxyjump_spec(
    temp_ssh_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test inline user@host:port ProxyJump is skipped (no matching saved server)."""
    config_file = temp_ssh_dir / "config"
    config_file.write_text("Host prod\n", encoding="utf-8")

    outputs = {
        "prod": "host prod\nhostname prod.example.com\nuser deploy\nport 22\nproxyjump ops@external.example.com:22",
    }

    def fake_run(command, check, capture_output, text):
        alias = command[2]
        config_path = command[4]
        output = outputs[alias] if config_path == str(config_file) else outputs[alias].split("\nproxyjump")[0]
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr("app.ssh_config.shutil.which", lambda _: "ssh")
    monkeypatch.setattr("app.ssh_config.subprocess.run", fake_run)

    servers = import_ssh_config(config_file)

    assert len(servers) == 1
    assert servers[0].jump_host is None


# ---------------------------------------------------------------------------
# render_server_as_ssh_config_block / render_servers_as_ssh_config
# ---------------------------------------------------------------------------


def test_render_block_minimal_server_uses_only_required_directives():
    """Test a server with only name/host/user renders the essential three lines and no more."""
    srv = Server(name="minimal", host="h.example", username="deploy")
    block = render_server_as_ssh_config_block(srv)
    assert "Host minimal" in block
    assert "    HostName h.example" in block
    assert "    User deploy" in block
    # Port 22 is the default — should be omitted
    assert "Port" not in block
    # Nothing else set -> no IdentityFile / ProxyJump / ForwardX11 lines
    assert "IdentityFile" not in block
    assert "ProxyJump" not in block
    assert "ForwardX11" not in block
    assert "LocalForward" not in block


def test_render_block_emits_all_supported_fields():
    """Test a fully-populated server renders every mapped directive."""
    srv = Server(
        name="full",
        host="h.example",
        username="deploy",
        port=2222,
        key_path="/keys/id_ed25519",
        certificate_path="/keys/id_ed25519-cert.pub",
        jump_host="bastion",
        keep_alive_interval=60,
        x11_forwarding=True,
        tags=["prod", "db"],
        notes="primary cluster",
        forwards=[
            Forward(type="local", local_port=5432, remote_host="localhost", remote_port=5432),
            Forward(type="remote", local_port=9000, remote_host="internal", remote_port=9000),
            Forward(type="dynamic", local_port=1080),
        ],
    )
    block = render_server_as_ssh_config_block(srv)

    assert "# Note: primary cluster" in block
    assert "# Tags: prod, db" in block
    assert "Host full" in block
    assert "    HostName h.example" in block
    assert "    User deploy" in block
    assert "    Port 2222" in block
    assert "    IdentityFile /keys/id_ed25519" in block
    assert "    CertificateFile /keys/id_ed25519-cert.pub" in block
    assert "    ProxyJump bastion" in block
    assert "    ServerAliveInterval 60" in block
    assert "    ServerAliveCountMax 3" in block
    assert "    ForwardX11 yes" in block
    assert "    LocalForward 5432 localhost:5432" in block
    assert "    RemoteForward 9000 internal:9000" in block
    assert "    DynamicForward 1080" in block


def test_render_block_preserves_bind_host_on_forwards():
    """Test bind-host-qualified forwards render with the `bind:port` prefix."""
    srv = Server(
        name="bound",
        host="h.example",
        username="u",
        forwards=[
            Forward(type="local", bind_host="127.0.0.1", local_port=8080, remote_host="web", remote_port=80),
            Forward(type="dynamic", bind_host="127.0.0.1", local_port=1080),
        ],
    )
    block = render_server_as_ssh_config_block(srv)
    assert "    LocalForward 127.0.0.1:8080 web:80" in block
    assert "    DynamicForward 127.0.0.1:1080" in block


def test_render_block_mentions_password_but_does_not_emit_it():
    """Test a server with a password gets a warning comment, never the value."""
    srv = Server(name="pwd", host="h.example", username="u", password="super-secret")
    block = render_server_as_ssh_config_block(srv)
    assert "super-secret" not in block
    assert "Password is stored in bssh but not exported here." in block


def test_render_full_file_includes_header_and_blocks():
    """Test the top-level renderer wraps blocks with a header comment."""
    servers = [
        Server(name="a", host="a.example", username="u"),
        Server(name="b", host="b.example", username="u"),
    ]
    text = render_servers_as_ssh_config(servers)
    assert "# ~/.ssh/config fragment exported from better-ssh" in text
    assert "2 server(s)" in text
    assert "Host a" in text
    assert "Host b" in text
    # Each block ends with its own newline
    assert text.count("Host ") == 2
