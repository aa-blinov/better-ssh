"""Tests for SSH command construction."""

from __future__ import annotations

from app.models import Server
from app.ssh import connect


def test_connect_uses_plain_ssh_without_explicit_key(monkeypatch):
    """Test OpenSSH defaults are left untouched when no key is pinned."""
    commands: list[list[str]] = []

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.subprocess.call", lambda command: commands.append(command) or 0)

    server = Server(name="prod", host="prod.example.com", username="deploy")
    exit_code = connect(server, copy_password=False)

    assert exit_code == 0
    assert commands == [["ssh", "-p", "22", "deploy@prod.example.com"]]


def test_connect_passes_explicit_key_and_certificate(monkeypatch):
    """Test explicit key and certificate paths are forwarded to ssh."""
    commands: list[list[str]] = []

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.subprocess.call", lambda command: commands.append(command) or 0)

    server = Server(
        name="prod",
        host="prod.example.com",
        username="deploy",
        port=2222,
        key_path="/keys/work_ed25519",
        certificate_path="/keys/work_ed25519-cert.pub",
    )
    exit_code = connect(server, copy_password=False)

    assert exit_code == 0
    assert commands == [
        [
            "ssh",
            "-p",
            "2222",
            "-i",
            "/keys/work_ed25519",
            "-o",
            "CertificateFile=/keys/work_ed25519-cert.pub",
            "deploy@prod.example.com",
        ]
    ]
