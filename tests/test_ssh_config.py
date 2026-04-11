"""Tests for SSH config import helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.ssh_config import collect_host_aliases, import_ssh_config


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
