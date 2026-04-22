"""Tests for Server model."""

from __future__ import annotations

import uuid

import pytest

from app.models import Forward, Server


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


# ---------------------------------------------------------------------------
# Forward
# ---------------------------------------------------------------------------


def test_forward_local_to_ssh_spec_without_bind():
    fwd = Forward(type="local", local_port=5432, remote_host="localhost", remote_port=5432)
    assert fwd.to_ssh_spec() == "5432:localhost:5432"


def test_forward_local_to_ssh_spec_with_bind():
    fwd = Forward(type="local", bind_host="127.0.0.1", local_port=8080, remote_host="web", remote_port=80)
    assert fwd.to_ssh_spec() == "127.0.0.1:8080:web:80"


def test_forward_dynamic_to_ssh_spec_without_bind():
    fwd = Forward(type="dynamic", local_port=1080)
    assert fwd.to_ssh_spec() == "1080"


def test_forward_dynamic_to_ssh_spec_with_bind():
    fwd = Forward(type="dynamic", bind_host="127.0.0.1", local_port=1080)
    assert fwd.to_ssh_spec() == "127.0.0.1:1080"


def test_forward_display_local_and_remote_use_arrow():
    local = Forward(type="local", local_port=5432, remote_host="db", remote_port=5432)
    remote = Forward(type="remote", local_port=80, remote_host="inside", remote_port=8080)
    assert local.display() == "L 5432→db:5432"
    assert remote.display() == "R 80→inside:8080"


def test_forward_display_dynamic_shows_port_only():
    fwd = Forward(type="dynamic", local_port=1080)
    assert fwd.display() == "D 1080"


def test_server_forwards_default_is_empty_list():
    server = Server(name="S", host="h", username="u")
    assert server.forwards == []


def test_server_forwards_roundtrip_via_model_validate():
    """Forwards survive JSON serialization/deserialization."""
    original = Server(
        name="S",
        host="h",
        username="u",
        forwards=[
            Forward(type="local", local_port=5432, remote_host="db", remote_port=5432),
            Forward(type="dynamic", local_port=1080),
        ],
    )
    data = original.model_dump(mode="json")
    restored = Server.model_validate(data)
    assert restored.forwards == original.forwards
