"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def runner() -> CliRunner:
    """Provide Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Create temporary config directory and patch storage paths."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Patch get_config_paths to use temp directory
    def mock_get_config_paths() -> tuple[Path, Path, Path]:
        cfg_file = config_dir / "servers.json"
        settings_file = config_dir / "settings.json"
        return config_dir, cfg_file, settings_file

    monkeypatch.setattr("app.storage.get_config_paths", mock_get_config_paths)
    return config_dir


@pytest.fixture
def temp_ssh_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Create temporary SSH directory for key-based tests."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)

    # Patch Path.home() to use temp directory
    def mock_home() -> Path:
        return tmp_path

    monkeypatch.setattr(Path, "home", mock_home)
    return ssh_dir


@pytest.fixture
def sample_servers_data() -> list[dict]:
    """Provide sample server data for tests."""
    return [
        {
            "id": "test-id-001",
            "name": "TestServer1",
            "host": "192.168.1.10",
            "port": 22,
            "username": "admin",
            "password": "secret123",
            "key_path": None,
            "tags": ["prod", "web"],
            "notes": "Production web server",
        },
        {
            "id": "test-id-002",
            "name": "TestServer2",
            "host": "192.168.1.20",
            "port": 2222,
            "username": "root",
            "password": None,
            "key_path": "/home/user/.ssh/id_rsa",
            "tags": ["dev"],
            "notes": None,
        },
        {
            "id": "test-id-003",
            "name": "TestServer3",
            "host": "example.com",
            "port": 22,
            "username": "user",
            "password": None,
            "key_path": None,
            "tags": [],
            "notes": None,
        },
    ]


@pytest.fixture
def servers_json_file(temp_config_dir: Path, sample_servers_data: list[dict]) -> Path:
    """Create servers.json file with sample data."""
    cfg_file = temp_config_dir / "servers.json"
    payload = {
        "version": 1,
        "servers": sample_servers_data,
    }
    cfg_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_file


@pytest.fixture
def mock_ssh_key(temp_ssh_dir: Path) -> Path:
    """Create a mock SSH private key for encryption tests."""
    key_path = temp_ssh_dir / "id_ed25519"
    # Create a realistic-looking (but fake) SSH key
    key_content = b"""-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDjsrj6F0k2YI9L3y0fG5J9p5m3F0k2YI9L3y0fG5J9pwAAAJjx4j5Z8eI+
WQAAAAtzc2gtZWQyNTUxOQAAACDjsrj6F0k2YI9L3y0fG5J9p5m3F0k2YI9L3y0fG5J9pw
AAAECcV8kEKF0k2YI9L3y0fG5J9p5m3F0k2YI9L3y0fG5J9uOyuPoXSTZgj0vfLR8bkn2n
mbcXSTZgj0vfLR8bkn2nAAAAFHRlc3RAZXhhbXBsZS5sb2NhbAECAw==
-----END OPENSSH PRIVATE KEY-----
"""
    key_path.write_bytes(key_content)
    return key_path
