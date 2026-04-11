"""Tests for SSH command construction."""

from __future__ import annotations

import socket

import pyperclip

from app.models import Server
from app.ssh import (
    _clipboard_failure_message,
    _paste_hint,
    check_server_availability,
    connect,
    has_ssh,
)

# ---------------------------------------------------------------------------
# has_ssh
# ---------------------------------------------------------------------------

def test_has_ssh_when_present(monkeypatch):
    """Test SSH client detection when it exists on PATH."""
    monkeypatch.setattr("app.ssh.shutil.which", lambda _: "/usr/bin/ssh")
    assert has_ssh() is True


def test_has_ssh_when_absent(monkeypatch):
    """Test SSH client detection when it is not on PATH."""
    monkeypatch.setattr("app.ssh.shutil.which", lambda _: None)
    assert has_ssh() is False


# ---------------------------------------------------------------------------
# _paste_hint
# ---------------------------------------------------------------------------

def test_paste_hint_macos(monkeypatch):
    """Test macOS paste hint uses Cmd+V."""
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Darwin")
    assert "Cmd+V" in _paste_hint()


def test_paste_hint_linux(monkeypatch):
    """Test Linux paste hint is generic (no keyboard shortcut assumed)."""
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Linux")
    hint = _paste_hint()
    assert "clipboard" in hint
    assert "Cmd+V" not in hint
    assert "Ctrl+Shift+V" not in hint


# ---------------------------------------------------------------------------
# _clipboard_failure_message
# ---------------------------------------------------------------------------

def test_clipboard_failure_message_linux_suggests_clipboard_tools(monkeypatch):
    """Test Linux clipboard failure message lists wl-clipboard, xclip, xsel."""
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Linux")
    msg = _clipboard_failure_message(Exception("no mechanism"))
    assert "wl-clipboard" in msg
    assert "xclip" in msg
    assert "xsel" in msg


def test_clipboard_failure_message_non_linux_only_show_pass(monkeypatch):
    """Test non-Linux clipboard failure message does not mention Linux tools."""
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Darwin")
    msg = _clipboard_failure_message(Exception("no mechanism"))
    assert "show-pass" in msg
    assert "wl-clipboard" not in msg


# ---------------------------------------------------------------------------
# connect — no SSH client
# ---------------------------------------------------------------------------

def test_connect_no_ssh_returns_127(monkeypatch):
    """Test connect returns exit code 127 when SSH client is missing."""
    monkeypatch.setattr("app.ssh.has_ssh", lambda: False)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.ssh.console.print", lambda _: None)

    rc = connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert rc == 127


def test_connect_no_ssh_macos_suggests_brew(monkeypatch):
    """Test macOS no-SSH message mentions brew install openssh."""
    messages: list[str] = []
    monkeypatch.setattr("app.ssh.has_ssh", lambda: False)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Darwin")
    monkeypatch.setattr("app.ssh.console.print", lambda m: messages.append(str(m)))

    connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert any("brew install openssh" in m for m in messages)


def test_connect_no_ssh_linux_suggests_apt(monkeypatch):
    """Test Linux no-SSH message mentions apt install."""
    messages: list[str] = []
    monkeypatch.setattr("app.ssh.has_ssh", lambda: False)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.ssh.console.print", lambda m: messages.append(str(m)))

    connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert any("apt install" in m for m in messages)


def test_connect_no_ssh_windows_suggests_winget(monkeypatch):
    """Test Windows no-SSH message mentions winget."""
    messages: list[str] = []
    monkeypatch.setattr("app.ssh.has_ssh", lambda: False)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.ssh.console.print", lambda m: messages.append(str(m)))

    connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert any("winget" in m for m in messages)


# ---------------------------------------------------------------------------
# connect — subprocess errors
# ---------------------------------------------------------------------------

def test_connect_keyboard_interrupt_returns_130(monkeypatch):
    """Test that Ctrl+C during SSH session returns exit code 130."""
    def raise_interrupt(_cmd):
        raise KeyboardInterrupt

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.subprocess.call", raise_interrupt)

    rc = connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert rc == 130


def test_connect_subprocess_error_returns_1(monkeypatch):
    """Test that an unexpected subprocess error returns exit code 1."""
    messages: list[str] = []

    def raise_error(_cmd):
        raise OSError("permission denied")

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.subprocess.call", raise_error)
    monkeypatch.setattr("app.ssh.console.print", lambda m: messages.append(str(m)))

    rc = connect(Server(name="s", host="h", username="u"), copy_password=False)
    assert rc == 1
    assert any("SSH execution error" in m for m in messages)


# ---------------------------------------------------------------------------
# connect — existing tests kept intact
# ---------------------------------------------------------------------------

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


def test_connect_copies_password_with_windows_specific_paste_hint(monkeypatch):
    """Test password copy uses a Windows-friendly paste hint."""
    commands: list[list[str]] = []
    copied_passwords: list[str] = []
    printed_messages: list[str] = []

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.ssh.pyperclip.copy", lambda password: copied_passwords.append(password))
    monkeypatch.setattr("app.ssh.subprocess.call", lambda command: commands.append(command) or 0)
    monkeypatch.setattr("app.ssh.console.print", lambda message: printed_messages.append(str(message)))

    server = Server(name="prod", host="prod.example.com", username="deploy", password="secret123")
    exit_code = connect(server)

    assert exit_code == 0
    assert copied_passwords == ["secret123"]
    assert commands == [["ssh", "-p", "22", "deploy@prod.example.com"]]
    assert any("Ctrl+Shift+V or right-click" in message for message in printed_messages)


def test_connect_clipboard_failure_shows_linux_specific_fallback(monkeypatch):
    """Test clipboard failures explain Linux clipboard dependencies and the fallback command."""
    commands: list[list[str]] = []
    printed_messages: list[str] = []

    monkeypatch.setattr("app.ssh.has_ssh", lambda: True)
    monkeypatch.setattr("app.ssh.platform.system", lambda: "Linux")

    def fail_copy(_: str) -> None:
        raise pyperclip.PyperclipException("Pyperclip could not find a copy/paste mechanism")

    monkeypatch.setattr("app.ssh.pyperclip.copy", fail_copy)
    monkeypatch.setattr("app.ssh.subprocess.call", lambda command: commands.append(command) or 0)
    monkeypatch.setattr("app.ssh.console.print", lambda message: printed_messages.append(str(message)))

    server = Server(name="prod", host="prod.example.com", username="deploy", password="secret123")
    exit_code = connect(server)

    assert exit_code == 0
    assert commands == [["ssh", "-p", "22", "deploy@prod.example.com"]]
    assert any("wl-clipboard" in message for message in printed_messages)
    assert any("xclip" in message for message in printed_messages)
    assert any("better-ssh show-pass" in message for message in printed_messages)


# ---------------------------------------------------------------------------
# check_server_availability
# ---------------------------------------------------------------------------

class _MockSocket:
    """Socket stub that returns a fixed connect_ex result or raises an exception."""

    def __init__(self, connect_result=0, connect_raises=None):
        self._connect_result = connect_result
        self._connect_raises = connect_raises
        self.connected_to: tuple | None = None

    def settimeout(self, _timeout): pass

    def connect_ex(self, addr):
        self.connected_to = addr
        if self._connect_raises is not None:
            raise self._connect_raises
        return self._connect_result

    def close(self): pass


def test_check_availability_reachable(monkeypatch):
    """Test that a successful TCP connection is reported as reachable."""
    monkeypatch.setattr("app.ssh.socket.socket", lambda *a, **kw: _MockSocket(connect_result=0))

    available, msg, elapsed = check_server_availability(
        Server(name="s", host="prod.example.com", username="u", port=22)
    )

    assert available is True
    assert msg == "reachable"
    assert elapsed >= 0


def test_check_availability_port_closed(monkeypatch):
    """Test that a refused connection is reported as port closed."""
    monkeypatch.setattr("app.ssh.socket.socket", lambda *a, **kw: _MockSocket(connect_result=111))

    available, msg, elapsed = check_server_availability(
        Server(name="s", host="prod.example.com", username="u")
    )

    assert available is False
    assert msg == "port closed"
    assert elapsed >= 0


def test_check_availability_dns_error(monkeypatch):
    """Test that a DNS failure is reported correctly."""
    monkeypatch.setattr(
        "app.ssh.socket.socket",
        lambda *a, **kw: _MockSocket(connect_raises=socket.gaierror("Name or service not known")),
    )

    available, msg, elapsed = check_server_availability(
        Server(name="s", host="nonexistent.invalid", username="u")
    )

    assert available is False
    assert msg == "DNS error"
    assert elapsed >= 0


def test_check_availability_timeout(monkeypatch):
    """Test that a timeout is reported correctly."""
    monkeypatch.setattr(
        "app.ssh.socket.socket",
        lambda *a, **kw: _MockSocket(connect_raises=TimeoutError()),
    )

    available, msg, elapsed = check_server_availability(
        Server(name="s", host="10.255.255.1", username="u")
    )

    assert available is False
    assert msg == "timeout"
    assert elapsed >= 0


def test_check_availability_unexpected_error(monkeypatch):
    """Test that unexpected socket errors surface the error message."""
    monkeypatch.setattr(
        "app.ssh.socket.socket",
        lambda *a, **kw: _MockSocket(connect_raises=OSError("network unreachable")),
    )

    available, msg, elapsed = check_server_availability(
        Server(name="s", host="h", username="u")
    )

    assert available is False
    assert "network unreachable" in msg
    assert elapsed >= 0


def test_check_availability_uses_server_host_and_port(monkeypatch):
    """Test that the correct host and port from the server are passed to the socket."""
    sock = _MockSocket(connect_result=0)
    monkeypatch.setattr("app.ssh.socket.socket", lambda *a, **kw: sock)

    check_server_availability(Server(name="s", host="custom.host", username="u", port=2222))

    assert sock.connected_to == ("custom.host", 2222)
