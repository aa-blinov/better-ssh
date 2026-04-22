from __future__ import annotations

import glob
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import Server


def expand_ssh_path(path: str | Path) -> Path:
    """Expand paths using Path.home() so tests and SSH defaults stay consistent."""
    value = str(path)
    if value == "~":
        return Path.home()
    if value.startswith(("~/", "~\\")):
        return Path.home() / value[2:]
    return Path(value)


def get_default_ssh_config_path() -> Path:
    """Return the default SSH config path for the current user."""
    return Path.home() / ".ssh" / "config"


def collect_host_aliases(config_path: Path) -> list[str]:
    """Collect explicit host aliases from an SSH config and its includes."""
    aliases: list[str] = []
    seen_aliases: set[str] = set()
    visited_files: set[Path] = set()

    def visit(path: Path) -> None:
        resolved_path = expand_ssh_path(path).resolve()
        if resolved_path in visited_files or not resolved_path.exists():
            return
        visited_files.add(resolved_path)

        for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
            tokens = shlex.split(raw_line, comments=True, posix=True)
            if len(tokens) < 2:
                continue

            directive = tokens[0].lower()
            values = tokens[1:]

            if directive == "include":
                for pattern in values:
                    include_pattern = expand_ssh_path(pattern)
                    if not include_pattern.is_absolute():
                        include_pattern = resolved_path.parent / include_pattern
                    for match in sorted(glob.glob(str(include_pattern), recursive=True)):
                        visit(Path(match))
                continue

            if directive != "host":
                continue

            for alias in values:
                if any(char in alias for char in "*?!"):
                    continue
                if alias.lower() not in seen_aliases:
                    aliases.append(alias)
                    seen_aliases.add(alias.lower())

    visit(config_path)
    return aliases


def resolve_host_options(alias: str, config_path: Path) -> dict[str, list[str]]:
    """Resolve final SSH options for a host using OpenSSH itself."""
    if shutil.which("ssh") is None:
        raise RuntimeError("SSH client not found.")

    result = subprocess.run(  # noqa: S603
        ["ssh", "-G", alias, "-F", str(expand_ssh_path(config_path))],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to resolve SSH config for host '{alias}'.")

    options: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        if not key or not value:
            continue
        options.setdefault(key.lower(), []).append(value.strip())
    return options


def resolve_default_host_options(alias: str) -> dict[str, list[str]]:
    """Resolve SSH options without user config to identify implicit defaults."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as temp_config:
        temp_config_path = Path(temp_config.name)

    try:
        temp_config_path.write_text("", encoding="utf-8")
        return resolve_host_options(alias, temp_config_path)
    finally:
        temp_config_path.unlink(missing_ok=True)


def normalize_option_path(path: str) -> str:
    """Normalize SSH option paths for stable comparison."""
    return str(expand_ssh_path(path).resolve(strict=False)).lower()


def filter_explicit_option_paths(option_paths: list[str], default_paths: list[str]) -> list[str]:
    """Keep only paths that differ from OpenSSH's implicit defaults."""
    default_path_set = {normalize_option_path(path) for path in default_paths}
    return [path for path in option_paths if normalize_option_path(path) not in default_path_set]


def resolve_existing_path(paths: list[str]) -> str | None:
    """Return the first existing path from resolved SSH options."""
    for candidate in paths:
        expanded = expand_ssh_path(candidate)
        if expanded.exists():
            return str(expanded)
    return None


def import_ssh_config(config_path: Path) -> list[Server]:
    """Import SSH hosts from a config file into server models.

    ProxyJump directives are imported only when the referenced target matches
    another imported alias (case-insensitive). Inline ``user@host:port`` jump
    specs are dropped since our model requires jump_host to reference a saved
    server; a warning is attached via the jump_host field being left as None.
    """
    aliases = collect_host_aliases(config_path)
    alias_lookup = {alias.lower(): alias for alias in aliases}
    servers: list[Server] = []

    for alias in aliases:
        options = resolve_host_options(alias, config_path)
        default_options = resolve_default_host_options(alias)
        host = options.get("hostname", [alias])[0]
        username = options.get("user", [""])[0]
        port = int(options.get("port", ["22"])[0])
        explicit_identity_files = filter_explicit_option_paths(
            options.get("identityfile", []),
            default_options.get("identityfile", []),
        )
        explicit_certificate_files = filter_explicit_option_paths(
            options.get("certificatefile", []),
            default_options.get("certificatefile", []),
        )
        key_path = resolve_existing_path(explicit_identity_files)
        certificate_path = resolve_existing_path(explicit_certificate_files)

        # Resolve ProxyJump: keep only references that match another imported alias
        jump_host: str | None = None
        proxyjump_values = options.get("proxyjump", [])
        if proxyjump_values:
            raw = proxyjump_values[0].strip()
            # Only handle single-hop alias references; skip "none" (ssh sentinel)
            # and inline user@host:port specs (no corresponding saved server).
            if raw.lower() not in {"", "none"} and "," not in raw and "@" not in raw and ":" not in raw:
                resolved = alias_lookup.get(raw.lower())
                if resolved:
                    jump_host = resolved

        if not username:
            continue

        servers.append(
            Server(
                name=alias,
                host=host,
                port=port,
                username=username,
                key_path=key_path,
                certificate_path=certificate_path,
                jump_host=jump_host,
            )
        )

    return servers
