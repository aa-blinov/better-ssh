from __future__ import annotations

import base64
import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import InvalidToken
from platformdirs import user_config_dir

from .domain import servers_matching_query
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


def get_or_create_encryption_salt() -> bytes:
    """Get or create a unique per-installation encryption salt stored in settings."""
    settings = load_settings()
    salt_b64 = settings.get("encryption_salt")
    if salt_b64:
        return base64.b64decode(salt_b64)
    salt = os.urandom(32)
    settings["encryption_salt"] = base64.b64encode(salt).decode("ascii")
    save_settings(settings)
    return salt


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
        salt = get_or_create_encryption_salt()
        for server in servers:
            if server.password and is_encrypted(server.password):
                with contextlib.suppress(InvalidToken, InvalidSignature, ValueError):
                    server.password = decrypt_password(server.password, salt)

    return servers


def save_servers(servers: list[Server]) -> None:
    """Save servers, auto-encrypting passwords if encryption is enabled."""
    cfg_dir, cfg_file, _ = get_config_paths()

    # Encrypt passwords if encryption is enabled
    servers_to_save = []
    if is_encryption_enabled():
        salt = get_or_create_encryption_salt()
        for server in servers:
            server_copy = server.model_copy(deep=True)
            if server_copy.password and not is_encrypted(server_copy.password):
                with contextlib.suppress(RuntimeError, ValueError):
                    server_copy.password = encrypt_password(server_copy.password, salt)
            servers_to_save.append(server_copy)
    else:
        servers_to_save = servers

    payload = {
        "version": 1,
        "servers": [s.model_dump(mode="json") for s in servers_to_save],
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


def record_server_use(server_id: str) -> bool:
    """Update usage metadata for a server after a connection attempt."""
    servers = load_servers()

    for server in servers:
        if server.id == server_id:
            server.use_count += 1
            server.last_used_at = datetime.now(UTC)
            save_servers(servers)
            return True

    return False


def set_server_favorite(server_id: str, favorite: bool) -> bool:
    """Set favorite state for a server."""
    servers = load_servers()

    for server in servers:
        if server.id == server_id:
            server.favorite = favorite
            save_servers(servers)
            return True

    return False


def find_server(query: str, servers: list[Server] | None = None) -> Server | None:
    """Find a single server that unambiguously matches the query.

    Match order (first unique hit wins):
      1. exact id
      2. unique id prefix
      3. exact name (case-insensitive)
      4. unique broad match — same fields that `bssh ls <query>` filters by
         (name / host / username / tags / jump_host, all case-insensitive
         substrings; id by prefix)

    Returns None when the query is ambiguous (multiple candidates at the
    broad-match stage) or has no matches — callers fall back to a picker
    or report a "not found" error accordingly. Aligning the uniqueness
    check with the `ls` semantics keeps `bssh connect prod` consistent
    with `bssh ls prod`.
    """
    if servers is None:
        servers = load_servers()
    # exact id
    for s in servers:
        if s.id == query:
            return s
    # unique id prefix
    prefix_matches = [s for s in servers if s.id.startswith(query)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    # case-insensitive exact name (name uniqueness is enforced at add/edit,
    # so this is always 0 or 1 — the for-else pattern keeps it O(n))
    for s in servers:
        if s.name.lower() == query.lower():
            return s
    # unique broad match across name/host/user/tag/jump_host
    broad = servers_matching_query(servers, query)
    if len(broad) == 1:
        return broad[0]
    return None
