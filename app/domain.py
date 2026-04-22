"""Pure domain logic over Server objects.

This module deliberately has no I/O, no Typer, no Rich, no InquirerPy. It holds
the validators, projections and query helpers that the CLI layer composes to
serve commands. Kept importable from anywhere, including tests, without
touching stdin/stdout or the filesystem.
"""

from __future__ import annotations

from .models import Forward, Server


def parse_forward_spec(spec: str, kind: str) -> Forward:
    """Parse an OpenSSH-style forwarding spec into a typed ``Forward``.

    ``kind`` must be one of "local" / "remote" / "dynamic" and selects the
    expected syntax:

    - local / remote: ``[bind:]local_port:remote_host:remote_port``
    - dynamic:        ``[bind:]local_port``

    Raises ``ValueError`` with a user-facing message when the spec is
    malformed so callers can surface it unchanged.
    """
    if kind not in {"local", "remote", "dynamic"}:
        raise ValueError(f"Unknown forward kind: {kind!r}")

    raw = spec.strip()
    if not raw:
        raise ValueError("Empty forwarding spec")

    parts = raw.split(":")

    if kind == "dynamic":
        # Either "port" or "bind:port"
        if len(parts) == 1:
            bind_host, port_str = None, parts[0]
        elif len(parts) == 2:
            bind_host, port_str = parts[0], parts[1]
        else:
            raise ValueError(f"Invalid dynamic forward '{raw}': expected [bind:]port")
        try:
            port = int(port_str)
        except ValueError as exc:
            raise ValueError(f"Invalid port in '{raw}': {port_str}") from exc
        return Forward(type="dynamic", bind_host=bind_host, local_port=port)

    # local / remote share the same syntax
    if len(parts) == 3:
        bind_host = None
        local_port_str, remote_host, remote_port_str = parts
    elif len(parts) == 4:
        bind_host, local_port_str, remote_host, remote_port_str = parts
    else:
        raise ValueError(f"Invalid {kind} forward '{raw}': expected [bind:]port:host:port")

    if not remote_host:
        raise ValueError(f"Invalid {kind} forward '{raw}': remote host is empty")

    try:
        local_port = int(local_port_str)
        remote_port = int(remote_port_str)
    except ValueError as exc:
        raise ValueError(f"Invalid port in '{raw}'") from exc

    return Forward(
        type=kind,
        bind_host=bind_host,
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port,
    )


def auth_label(server: Server) -> str:
    """Return a user-facing auth label for a server."""
    if server.certificate_path:
        return "cert"
    if server.key_path:
        return "key"
    if server.password:
        return "pwd"
    return "auto"


def favorite_label(server: Server) -> str:
    """Return a user-facing favorite label for a server."""
    return "pin" if server.favorite else ""


def sort_servers(servers: list[Server]) -> list[Server]:
    """Sort servers for daily use: pinned first, then recent, then frequent, then name."""

    def sort_key(server: Server) -> tuple[int, float, int, str]:
        last_used_ts = server.last_used_at.timestamp() if server.last_used_at else 0.0
        return (-int(server.favorite), -last_used_ts, -server.use_count, server.name.lower())

    return sorted(servers, key=sort_key)


def parse_tags(raw: str) -> list[str]:
    """Parse a comma-separated tag string into a deduplicated, trimmed list."""
    seen: set[str] = set()
    out: list[str] = []
    for token in raw.split(","):
        t = token.strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def name_conflict(name: str, servers: list[Server], exclude_id: str | None = None) -> Server | None:
    """Return an existing server whose name equals `name` (case-insensitive), if any."""
    target = name.strip().lower()
    if not target:
        return None
    for s in servers:
        if s.id == exclude_id:
            continue
        if s.name.lower() == target:
            return s
    return None


def check_jump_cycle(servers: list[Server], server: Server) -> str | None:
    """Walk the prospective jump chain for `server` over `servers`.

    Returns a human-readable error message if a cycle or missing reference
    would result, or None if the chain is valid.
    """
    if not server.jump_host:
        return None
    by_name = {s.name: s for s in servers if s.id != server.id}
    by_name[server.name] = server  # consider the prospective state
    seen = {server.name}
    current: str | None = server.jump_host
    chain = [server.name]
    while current:
        if current in seen:
            chain.append(current)
            return f"Jump host cycle detected: {' → '.join(chain)}"
        jump = by_name.get(current)
        if jump is None:
            return f"Jump host '{current}' not found in saved servers"
        seen.add(current)
        chain.append(current)
        current = jump.jump_host
    return None


def jump_host_usage_map(all_servers: list[Server]) -> dict[str, int]:
    """Return {name: count} of how many servers use each name as jump_host."""
    counts: dict[str, int] = {}
    for s in all_servers:
        if s.jump_host:
            counts[s.jump_host] = counts.get(s.jump_host, 0) + 1
    return counts


def servers_matching_query(servers: list[Server], query: str) -> list[Server]:
    """Return servers that loosely match the provided query.

    Matches against name, host, username, id prefix, tags, and jump_host
    (all case-insensitive substrings except id which uses prefix). Matching
    by jump_host surfaces both a bastion server and its dependents under one
    search term.
    """
    normalized_query = query.lower()
    return [
        server
        for server in servers
        if normalized_query in server.name.lower()
        or normalized_query in server.host.lower()
        or normalized_query in server.username.lower()
        or server.id.startswith(query)
        or any(normalized_query in tag.lower() for tag in server.tags)
        or (server.jump_host and normalized_query in server.jump_host.lower())
    ]
