"""Tests for storage module."""

from __future__ import annotations

import json
from pathlib import Path

from app.encryption import encrypt_password
from app.models import Server
from app.storage import (
    find_server,
    get_config_paths,
    is_encryption_enabled,
    load_servers,
    load_settings,
    remove_server,
    save_servers,
    save_settings,
    upsert_server,
)


def test_get_config_paths(temp_config_dir: Path):
    """Test config paths are created correctly."""
    cfg_dir, cfg_file, settings_file = get_config_paths()

    assert cfg_dir.exists()
    assert cfg_file.parent == cfg_dir
    assert settings_file.parent == cfg_dir


def test_load_settings_default(temp_config_dir: Path):
    """Test loading settings returns defaults when file doesn't exist."""
    settings = load_settings()
    assert settings == {"encryption_enabled": False}


def test_save_and_load_settings(temp_config_dir: Path):
    """Test settings persistence."""
    settings = {"encryption_enabled": True, "custom_key": "value"}
    save_settings(settings)

    loaded = load_settings()
    assert loaded == settings


def test_is_encryption_enabled(temp_config_dir: Path):
    """Test encryption status check."""
    assert is_encryption_enabled() is False

    save_settings({"encryption_enabled": True})
    assert is_encryption_enabled() is True


def test_load_servers_empty(temp_config_dir: Path):
    """Test loading servers when file doesn't exist."""
    servers = load_servers()
    assert servers == []

    # Should create empty file
    _, cfg_file, _ = temp_config_dir, temp_config_dir / "servers.json", temp_config_dir / "settings.json"
    assert cfg_file.exists()


def test_save_and_load_servers(temp_config_dir: Path):
    """Test server persistence."""
    servers = [
        Server(name="Server1", host="192.168.1.1", username="user1", password="pass1"),
        Server(name="Server2", host="192.168.1.2", username="user2", key_path="/path/to/key"),
    ]

    save_servers(servers)
    loaded = load_servers()

    assert len(loaded) == 2
    assert loaded[0].name == "Server1"
    assert loaded[0].password == "pass1"
    assert loaded[1].name == "Server2"
    assert loaded[1].key_path == "/path/to/key"


def test_load_servers_with_data(servers_json_file: Path):
    """Test loading servers from existing file."""
    servers = load_servers()

    assert len(servers) == 3
    assert servers[0].name == "TestServer1"
    assert servers[0].password == "secret123"
    assert servers[1].key_path == "/home/user/.ssh/id_rsa"


def test_save_servers_encryption(temp_config_dir: Path, mock_ssh_key: Path):
    """Test servers are encrypted when encryption is enabled."""
    save_settings({"encryption_enabled": True})

    servers = [
        Server(name="Server1", host="host1", username="user1", password="plaintext_password"),
    ]

    save_servers(servers)

    # Read raw JSON to check password is encrypted
    cfg_file = temp_config_dir / "servers.json"
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    saved_password = data["servers"][0]["password"]

    # Password should be encrypted (not plaintext)
    assert saved_password != "plaintext_password"
    assert saved_password.startswith("Z0FBQUFB")  # Fernet token indicator


def test_load_servers_decryption(temp_config_dir: Path, mock_ssh_key: Path):
    """Test servers are decrypted when loaded with encryption enabled."""
    save_settings({"encryption_enabled": True})

    # Manually create encrypted server data
    encrypted_password = encrypt_password("original_password")
    cfg_file = temp_config_dir / "servers.json"
    data = {
        "version": 1,
        "servers": [
            {
                "id": "test-id",
                "name": "Server1",
                "host": "host1",
                "username": "user1",
                "password": encrypted_password,
                "key_path": None,
                "tags": [],
                "notes": None,
                "port": 22,
            }
        ],
    }
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    # Load and verify decryption
    servers = load_servers()
    assert len(servers) == 1
    assert servers[0].password == "original_password"


def test_upsert_server_new(temp_config_dir: Path):
    """Test inserting new server."""
    server = Server(name="NewServer", host="192.168.1.1", username="user")
    upsert_server(server)

    servers = load_servers()
    assert len(servers) == 1
    assert servers[0].name == "NewServer"


def test_upsert_server_update(servers_json_file: Path):
    """Test updating existing server."""
    servers = load_servers()
    server = servers[0]
    server.password = "new_password"

    upsert_server(server)

    loaded = load_servers()
    updated = next(s for s in loaded if s.id == server.id)
    assert updated.password == "new_password"


def test_remove_server_exists(servers_json_file: Path):
    """Test removing existing server."""
    servers = load_servers()
    server_id = servers[0].id

    result = remove_server(server_id)
    assert result is True

    remaining = load_servers()
    assert len(remaining) == 2
    assert all(s.id != server_id for s in remaining)


def test_remove_server_not_exists(servers_json_file: Path):
    """Test removing non-existent server."""
    result = remove_server("non-existent-id")
    assert result is False

    servers = load_servers()
    assert len(servers) == 3  # unchanged


def test_find_server_by_id(servers_json_file: Path):
    """Test finding server by exact ID."""
    servers = load_servers()
    target_id = servers[0].id

    found = find_server(target_id)
    assert found is not None
    assert found.id == target_id


def test_find_server_by_exact_name(servers_json_file: Path):
    """Test finding server by exact name (case-insensitive)."""
    found = find_server("TestServer1")
    assert found is not None
    assert found.name == "TestServer1"

    found_lower = find_server("testserver1")
    assert found_lower is not None
    assert found_lower.name == "TestServer1"


def test_find_server_by_partial_name(servers_json_file: Path):
    """Test finding server by partial name match."""
    found = find_server("Server1")
    assert found is not None
    assert found.name == "TestServer1"


def test_find_server_not_found(servers_json_file: Path):
    """Test finding non-existent server."""
    found = find_server("NonExistent")
    assert found is None


def test_find_server_multiple_partial_matches(servers_json_file: Path):
    """Test that partial match returns None if multiple servers match."""
    # "TestServer" matches both TestServer1 and TestServer2
    found = find_server("TestServer")
    assert found is None  # ambiguous


def test_find_server_unique_partial(servers_json_file: Path):
    """Test that unique partial match works."""
    found = find_server("Server3")  # unique partial - only TestServer3 matches
    assert found is not None
    assert found.name == "TestServer3"
