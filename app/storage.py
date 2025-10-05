from __future__ import annotations

import contextlib
import json
from pathlib import Path

from platformdirs import user_config_dir

from .encryption import decrypt_password, encrypt_password, is_encrypted
from .models import Server

APP_NAME = "better-ssh"


def get_config_paths() -> tuple[Path, Path, Path]:
    cfg_dir = Path(user_config_dir(APP_NAME, appauthor=False))
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "servers.json"
    settings_file = cfg_dir / "settings.json"
    return cfg_dir, cfg_file, settings_file


def load_settings() -> dict:
    """Load application settings."""
    _, _, settings_file = get_config_paths()
    if not settings_file.exists():
        return {"encryption_enabled": False}
    try:
        return json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:
        return {"encryption_enabled": False}


def save_settings(settings: dict) -> None:
    """Save application settings."""
    cfg_dir, _, settings_file = get_config_paths()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def is_encryption_enabled() -> bool:
    """Check if encryption is enabled."""
    return load_settings().get("encryption_enabled", False)


def load_servers() -> list[Server]:
    """Load servers, auto-decrypting passwords if encryption is enabled."""
    _, cfg_file, _ = get_config_paths()
    if not cfg_file.exists():
        save_servers([])
        return []
    data = json.loads(cfg_file.read_text(encoding="utf-8") or "{}")
    servers_raw = data.get("servers", [])
    servers = [Server.model_validate(item) for item in servers_raw]

    # Decrypt passwords if encryption is enabled
    if is_encryption_enabled():
        for server in servers:
            if server.password and is_encrypted(server.password):
                # If decryption fails, leave as is
                with contextlib.suppress(Exception):
                    server.password = decrypt_password(server.password)

    return servers


def save_servers(servers: list[Server]) -> None:
    """Save servers, auto-encrypting passwords if encryption is enabled."""
    cfg_dir, cfg_file, _ = get_config_paths()

    # Encrypt passwords if encryption is enabled
    servers_to_save = []
    if is_encryption_enabled():
        for server in servers:
            server_copy = server.model_copy(deep=True)
            if server_copy.password and not is_encrypted(server_copy.password):
                # If encryption fails, save as is
                with contextlib.suppress(Exception):
                    server_copy.password = encrypt_password(server_copy.password)
            servers_to_save.append(server_copy)
    else:
        servers_to_save = servers

    payload = {
        "version": 1,
        "servers": [s.model_dump() for s in servers_to_save],
    }
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_server(server: Server) -> None:
    """Insert or update a server."""
    servers = load_servers()
    by_id = {s.id: s for s in servers}
    by_id[server.id] = server
    save_servers(list(by_id.values()))


def remove_server(server_id: str) -> bool:
    """Remove a server by ID. Returns True if removed."""
    servers = load_servers()
    new_servers = [s for s in servers if s.id != server_id]
    changed = len(new_servers) != len(servers)
    if changed:
        save_servers(new_servers)
    return changed


def find_server(query: str) -> Server | None:
    """Find server by ID, exact name, or partial name match."""
    servers = load_servers()
    # exact id
    for s in servers:
        if s.id == query:
            return s
    # case-insensitive unique name
    matches = [s for s in servers if s.name.lower() == query.lower()]
    if len(matches) == 1:
        return matches[0]
    # partial name contains
    contains = [s for s in servers if query.lower() in s.name.lower()]
    if len(contains) == 1:
        return contains[0]
    return None
