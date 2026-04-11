"""Tests for Server model."""

from __future__ import annotations

import uuid

import pytest

from app.models import Server


def test_server_defaults():
    """Test non-trivial defaults: port 22, auto-generated UUID, empty tags list."""
    server = Server(name="Test", host="example.com", username="user")
    assert server.port == 22
    assert server.favorite is False
    assert server.use_count == 0
    assert server.tags == []
    assert uuid.UUID(server.id)  # valid UUID format


def test_server_auto_generated_ids_are_unique():
    """Test that auto-generated IDs are unique across instances."""
    s1 = Server(name="S1", host="h1", username="u1")
    s2 = Server(name="S2", host="h2", username="u2")
    assert s1.id != s2.id


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
