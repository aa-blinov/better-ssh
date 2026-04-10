"""Tests for Server model."""

from __future__ import annotations

import uuid

import pytest

from app.models import Server


def test_server_creation_minimal():
    """Test creating server with minimal required fields."""
    server = Server(
        name="TestServer",
        host="192.168.1.1",
        username="admin",
    )

    assert server.name == "TestServer"
    assert server.host == "192.168.1.1"
    assert server.username == "admin"
    assert server.port == 22  # default
    assert server.password is None
    assert server.key_path is None
    assert server.certificate_path is None
    assert server.favorite is False
    assert server.use_count == 0
    assert server.last_used_at is None
    assert server.tags == []
    assert server.notes is None
    # UUID should be generated
    assert uuid.UUID(server.id)


def test_server_creation_full():
    """Test creating server with all fields."""
    server = Server(
        id="custom-id-123",
        name="FullServer",
        host="example.com",
        port=2222,
        username="root",
        password="secret",
        key_path="/home/user/.ssh/id_rsa",
        certificate_path="/home/user/.ssh/id_rsa-cert.pub",
        favorite=True,
        use_count=12,
        last_used_at="2026-04-10T12:00:00+00:00",
        tags=["prod", "web"],
        notes="Production server",
    )

    assert server.id == "custom-id-123"
    assert server.name == "FullServer"
    assert server.host == "example.com"
    assert server.port == 2222
    assert server.username == "root"
    assert server.password == "secret"
    assert server.key_path == "/home/user/.ssh/id_rsa"
    assert server.certificate_path == "/home/user/.ssh/id_rsa-cert.pub"
    assert server.favorite is True
    assert server.use_count == 12
    assert server.last_used_at == "2026-04-10T12:00:00+00:00"
    assert server.tags == ["prod", "web"]
    assert server.notes == "Production server"


@pytest.mark.parametrize(
    ("password", "key_path", "certificate_path", "expected_auth"),
    [
        (None, None, None, "auto"),
        ("secret", None, None, "pwd"),
        (None, "/path/to/key", None, "key"),
        ("secret", "/path/to/key", None, "key"),
        (None, "/path/to/key", "/path/to/key-cert.pub", "cert"),
    ],
)
def test_server_display_auth(
    password: str | None,
    key_path: str | None,
    certificate_path: str | None,
    expected_auth: str,
):
    """Test display() method shows correct auth type."""
    server = Server(
        name="Test",
        host="192.168.1.1",
        username="user",
        password=password,
        key_path=key_path,
        certificate_path=certificate_path,
    )

    display = server.display()
    assert expected_auth in display


def test_server_display_format():
    """Test display() output format."""
    server = Server(
        name="MyServer",
        host="example.com",
        port=2222,
        username="admin",
        password="secret",
    )

    display = server.display()
    assert "MyServer" in display
    assert "admin@example.com:2222" in display
    assert "pwd" in display


def test_server_display_marks_pinned_servers():
    """Test display() marks pinned servers clearly."""
    server = Server(
        name="PinnedServer",
        host="example.com",
        username="admin",
        favorite=True,
    )

    display = server.display()
    assert display.startswith("[pin] PinnedServer")


def test_server_unique_ids():
    """Test that auto-generated IDs are unique."""
    server1 = Server(name="S1", host="h1", username="u1")
    server2 = Server(name="S2", host="h2", username="u2")

    assert server1.id != server2.id
    assert uuid.UUID(server1.id)
    assert uuid.UUID(server2.id)


def test_server_model_copy():
    """Test that server can be deep copied."""
    server = Server(
        name="Original",
        host="192.168.1.1",
        username="user",
        password="secret",
        tags=["tag1"],
    )

    copy = server.model_copy(deep=True)
    assert copy.id == server.id
    assert copy.password == server.password
    assert copy.tags == server.tags
    assert copy.tags is not server.tags  # deep copy
