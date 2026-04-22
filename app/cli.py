from __future__ import annotations

import json
from pathlib import Path

import click
import pyperclip
import typer
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import storage
from .encryption import decrypt_password, encrypt_password, find_ssh_key, find_ssh_key_for_encryption, is_encrypted
from .models import Server
from .ssh import JumpResolutionError, check_server_availability, connect, resolve_jump_chain
from .ssh_config import get_default_ssh_config_path, import_ssh_config


class OrderCommands(typer.core.TyperGroup):
    """Custom group to sort commands alphabetically in help."""

    def list_commands(self, ctx):
        return sorted(super().list_commands(ctx))

    def resolve_command(self, ctx, args):
        """Treat unknown positional input as a shorthand connect query."""
        if args:
            command = self.get_command(ctx, args[0])
            if command is None and not args[0].startswith("-"):
                connect_command = self.get_command(ctx, "connect")
                if connect_command is not None:
                    return "connect", connect_command, args
        return click.core.Group.resolve_command(self, ctx, args)


app = typer.Typer(
    help="Better SSH: quick server selection, connection and password management.",
    epilog=("Quick start: better-ssh; better-ssh <query>; better-ssh import-ssh-config"),
    cls=OrderCommands,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    add_completion=True,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
NO_SERVERS_MESSAGE = (
    "[yellow]No servers found. Start with [cyan]better-ssh import-ssh-config[/cyan] "
    "or [cyan]better-ssh add[/cyan].[/yellow]"
)


def _print_no_servers_message() -> None:
    """Print onboarding help for an empty server list."""
    console.print(NO_SERVERS_MESSAGE)


def _print_servers(servers: list[Server]) -> None:
    """Print servers table."""
    show_via = any(s.jump_host for s in servers)
    show_keepalive = any(s.keep_alive_interval for s in servers)
    show_tags = any(s.tags for s in servers)
    show_notes = any(s.notes for s in servers)
    table = Table(title="Servers")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Pin", justify="center", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Auth", justify="center", no_wrap=True)
    if show_via:
        table.add_column("Via", style="cyan", no_wrap=True)
    if show_keepalive:
        table.add_column("Alive", style="green", justify="right", no_wrap=True)
    if show_tags:
        table.add_column("Tags", style="magenta", max_width=30, overflow="fold")
    if show_notes:
        table.add_column("Notes", style="dim", max_width=40, overflow="ellipsis")

    for s in _sort_servers(servers):
        auth = _auth_label(s)
        row = [s.id[:8], _favorite_label(s), s.name, f"{s.username}@{s.host}:{s.port}", auth]
        if show_via:
            row.append(s.jump_host or "")
        if show_keepalive:
            row.append(f"{s.keep_alive_interval}s" if s.keep_alive_interval else "")
        if show_tags:
            row.append(", ".join(s.tags) if s.tags else "")
        if show_notes:
            row.append(s.notes or "")
        table.add_row(*row)

    console.print(table)


def _sort_servers(servers: list[Server]) -> list[Server]:
    """Sort servers for daily use: pinned first, then recent, then frequent, then name."""

    def sort_key(server: Server) -> tuple[int, float, int, str]:
        last_used_ts = server.last_used_at.timestamp() if server.last_used_at else 0.0
        return (-int(server.favorite), -last_used_ts, -server.use_count, server.name.lower())

    return sorted(servers, key=sort_key)


# Sentinel for the "(none — direct connection)" option in the jump-host
# picker. Using None here (rather than a magic string) guarantees no
# collision with any user-chosen server name, which must be a non-empty str.
_NONE_JUMP_SENTINEL: object = object()


def _parse_tags(raw: str) -> list[str]:
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


def _prompt_keep_alive_interval(default: int) -> int | None:
    """Prompt for a keep-alive interval; return None when the user enters 0.

    Uses click.IntRange(min=0) so negatives are rejected at the prompt layer
    and both add/edit share one normalization point.
    """
    value = typer.prompt(
        "Interval in seconds (0 to disable)",
        default=default,
        type=click.IntRange(min=0),
    )
    return value if value > 0 else None


def _name_conflict(name: str, servers: list[Server], exclude_id: str | None = None) -> Server | None:
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


def _check_jump_cycle(servers: list[Server], server: Server) -> str | None:
    """Walk the prospective jump chain for `server` over `servers`.

    Returns a human-readable error message if a cycle or missing reference
    would result, or None if the chain is valid.
    """
    if not server.jump_host:
        return None
    by_name = {s.name: s for s in servers if s.id != server.id}
    by_name[server.name] = server  # consider the prospective state
    seen = {server.name}
    current = server.jump_host
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


def _jump_host_usage_map(all_servers: list[Server]) -> dict[str, int]:
    """Return {name: count} of how many servers use each name as jump_host."""
    counts: dict[str, int] = {}
    for s in all_servers:
        if s.jump_host:
            counts[s.jump_host] = counts.get(s.jump_host, 0) + 1
    return counts


def _select_jump_host(
    candidates: list[Server],
    message: str,
    *,
    include_none: bool = False,
    current: str | None = None,
    all_servers: list[Server] | None = None,
) -> tuple[bool, str | None]:
    """Interactively pick a jump host from candidates.

    Returns (changed, new_value). changed=False means user cancelled or kept
    the current value. new_value is the selected server name, or None when the
    user picks "no jump host".
    """
    if not candidates:
        console.print("[yellow]No other servers available as a jump host.[/yellow]")
        console.print("Add one first with [cyan]bssh add[/cyan], then re-run this command.")
        return False, current

    usage = _jump_host_usage_map(all_servers or [])

    def label(s: Server) -> str:
        used_by = usage.get(s.name, 0)
        # Don't count the server being edited as "using itself"
        if current == s.name and used_by > 0:
            used_by -= 1
        suffix = f"  [used by {used_by}]" if used_by else ""
        marker = " [current]" if current == s.name else ""
        return f"{s.display()}{marker}{suffix}"

    sorted_candidates = _sort_servers(candidates)
    choices: list[Choice] = []
    if include_none:
        choices.append(Choice(value=_NONE_JUMP_SENTINEL, name="(none — direct connection)"))
    choices.extend(Choice(value=s.name, name=label(s)) for s in sorted_candidates)

    try:
        picked = inquirer.select(
            message=message,
            choices=choices,
            cycle=True,
            vi_mode=False,
            default=current if current else None,
            instruction="Use arrows to navigate, search by name",
        ).execute()
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled jump host selection.[/dim]")
        return False, current

    if picked is _NONE_JUMP_SENTINEL:
        return (current is not None), None
    return (picked != current), picked


def _select_server(servers: list[Server], message: str) -> Server:
    """Select a server from the interactive menu."""
    sorted_servers = _sort_servers(servers)
    by_id = {s.id: s for s in sorted_servers}

    try:
        selected_id = inquirer.select(
            message=message,
            choices=[Choice(value=s.id, name=s.display()) for s in sorted_servers],
            cycle=True,
            vi_mode=False,
            instruction="Use arrows to navigate, search by name",
        ).execute()
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    server = by_id.get(selected_id)
    if server is None:
        console.print("[red]Failed to identify server[/red]")
        raise typer.Exit(1)
    return server


def _servers_matching_query(servers: list[Server], query: str) -> list[Server]:
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


def _merge_servers_by_name(existing_servers: list[Server], imported_servers: list[Server]) -> list[Server]:
    """Merge imported servers with existing records while preserving user data."""
    merged_by_id = {server.id: server for server in existing_servers}
    existing_by_name = {server.name.lower(): server for server in existing_servers}

    for imported in imported_servers:
        existing = existing_by_name.get(imported.name.lower())
        if existing:
            merged = imported.model_copy(
                update={
                    "id": existing.id,
                    "password": existing.password,
                    "favorite": existing.favorite,
                    "tags": existing.tags,
                    "notes": existing.notes,
                    "use_count": existing.use_count,
                    "last_used_at": existing.last_used_at,
                }
            )
        else:
            merged = imported
        merged_by_id[merged.id] = merged

    return list(merged_by_id.values())


def _auth_label(server: Server) -> str:
    """Return a user-facing auth label for a server."""
    if server.certificate_path:
        return "cert"
    if server.key_path:
        return "key"
    if server.password:
        return "pwd"
    return "auto"


def _favorite_label(server: Server) -> str:
    """Return a user-facing favorite label for a server."""
    return "pin" if server.favorite else ""


@app.callback()
def root(ctx: typer.Context) -> None:
    """Open the connect flow when the CLI is run without a subcommand."""
    if ctx.resilient_parsing or ctx.invoked_subcommand is not None:
        return
    connect_cmd(query=None, no_copy=False)


@app.command("list", help="Show list of servers. Alias: ls. Optional query filters by name/host/user/tag.")
@app.command("ls", hidden=True)
def list_servers(
    query: str | None = typer.Argument(None, help="Filter servers by name, host, username, tag, or id prefix"),
) -> None:
    """Show list of servers (optionally filtered by query)."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        return

    if query:
        matching = _servers_matching_query(servers, query)
        if not matching:
            console.print(f"[yellow]No servers match '{query}'.[/yellow]")
            return
        _print_servers(matching)
        return

    _print_servers(servers)


@app.command("add", help="Add a new server. Alias: a")
@app.command("a", hidden=True)
def add_server(
    name: str | None = typer.Option(None, prompt=True, help="Server name"),
    host: str | None = typer.Option(None, prompt=True),
    port: int = typer.Option(22, prompt=True),
    username: str | None = typer.Option(None, prompt=True),
    jump: str | None = typer.Option(None, "--jump", "-J", help="Use this saved server as ProxyJump"),
    keep_alive: int | None = typer.Option(
        None,
        "--keep-alive",
        "-K",
        help="SSH keep-alive interval in seconds (0 to disable)",
        min=0,
    ),
    key: str | None = typer.Option(None, "--key", help="Path to SSH private key"),
    certificate: str | None = typer.Option(None, "--certificate", help="Path to SSH certificate"),
    password_flag: str | None = typer.Option(
        None,
        "--password",
        help="Password (WARNING: visible in shell history; prefer interactive prompt)",
    ),
    note: str | None = typer.Option(None, "--notes", help="Free-form note attached to the server"),
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="Tag (repeatable: -t prod -t db)"),
):
    """Add a new server."""
    try:
        existing_servers = storage.load_servers()

        # Uniqueness check up front so we fail before prompting for credentials
        if name:
            conflict = _name_conflict(name, existing_servers)
            if conflict:
                console.print(f"[red]A server named '{conflict.name}' already exists (id: {conflict.id[:8]}).[/red]")
                console.print("Pick a different name or edit the existing one with [cyan]bssh edit[/cyan].")
                raise typer.Exit(1)

        key_path: str | None = None
        if key is not None:
            key_path = key or None
        elif typer.confirm("Add SSH key?", default=False):
            default_key = find_ssh_key()
            if default_key:
                key_path = typer.prompt("Path to private key", default=str(default_key)) or None
            else:
                key_path = typer.prompt("Path to private key (e.g. ~/.ssh/id_rsa)") or None

        certificate_path: str | None = certificate or None

        password: str | None = None
        if password_flag is not None:
            password = password_flag or None
        elif typer.confirm("Add password?", default=False):
            password = typer.prompt("Password", hide_input=True, confirmation_prompt=True) or None

        jump_host: str | None = None
        if jump:
            # Non-interactive: validate reference (case-insensitive, like name uniqueness)
            match = next((s for s in existing_servers if s.name.lower() == jump.lower()), None)
            if match is None:
                console.print(f"[red]Jump host '{jump}' not found in saved servers.[/red]")
                raise typer.Exit(1)
            jump_host = match.name  # store the canonical casing
        elif typer.confirm("Use a jump host (ProxyJump)?", default=False):
            candidates = [s for s in existing_servers if s.name != name]
            _, jump_host = _select_jump_host(
                candidates,
                "Select jump host:",
                include_none=False,
                all_servers=existing_servers,
            )

        notes: str | None = None
        if note is not None:
            notes = note or None
        elif typer.confirm("Add a note?", default=False):
            notes = typer.prompt("Note") or None

        tags: list[str] = []
        if tag is not None:
            # Non-interactive: use flags, deduplicated/trimmed
            tags = _parse_tags(",".join(tag))
        elif typer.confirm("Add tags?", default=False):
            tags = _parse_tags(typer.prompt("Comma-separated tags"))

        keep_alive_interval: int | None = None
        if keep_alive is not None:
            # Non-interactive: keep_alive > 0 enables; 0 keeps disabled (consistent with helper)
            keep_alive_interval = keep_alive if keep_alive > 0 else None
        elif typer.confirm("Enable SSH keep-alive?", default=False):
            keep_alive_interval = _prompt_keep_alive_interval(60)

        server = Server(
            name=name,
            host=host,
            port=port,
            username=username,
            password=password,
            key_path=key_path,
            certificate_path=certificate_path,
            jump_host=jump_host,
            notes=notes,
            keep_alive_interval=keep_alive_interval,
            tags=tags,
        )

        error = _check_jump_cycle(existing_servers, server)
        if error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1)

        storage.upsert_server(server)
        console.print(f"[green]Added:[/green] {server.display()}  (id: {server.id})")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("view", help="Show a detailed card for one server. Alias: v")
@app.command("v", hidden=True)
def view(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Show a detailed card for one server."""
    all_servers = storage.load_servers()
    if not all_servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    if query is None:
        srv = _select_server(all_servers, "Select server to view:")
    else:
        srv = storage.find_server(query, all_servers)
        if not srv:
            matching = _servers_matching_query(all_servers, query)
            if matching:
                srv = _select_server(matching, f"Select server to view for '{query}':")
            else:
                console.print(f"[red]No server matches '{query}'.[/red]")
                raise typer.Exit(1)

    # Build a two-column detail table
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value")

    table.add_row("Name", f"[bold]{srv.name}[/bold]")
    table.add_row("ID", srv.id)
    table.add_row("Host", f"{srv.username}@{srv.host}:{srv.port}")

    # Authentication
    if srv.certificate_path:
        auth_line = f"certificate [dim]({srv.certificate_path})[/dim]"
        if srv.key_path:
            auth_line += f" + key [dim]({srv.key_path})[/dim]"
    elif srv.key_path:
        auth_line = f"key [dim]({srv.key_path})[/dim]"
    elif srv.password:
        auth_line = "password [dim](set)[/dim]"
    else:
        auth_line = "OpenSSH default (no key/password/cert pinned)"
    table.add_row("Auth", auth_line)

    # Jump chain
    if srv.jump_host:
        try:
            chain = resolve_jump_chain(srv, all_servers)
            chain_str = " → ".join(f"{j.username}@{j.host}:{j.port}" for j in chain) + f" → {srv.name}"
            table.add_row("Jump chain", f"[cyan]{chain_str}[/cyan]")
        except JumpResolutionError as exc:
            table.add_row("Jump chain", f"[red]broken: {exc}[/red]")

    # Keep-alive
    if srv.keep_alive_interval:
        table.add_row("Keep-alive", f"[green]{srv.keep_alive_interval}s[/green]")

    # Tags
    if srv.tags:
        table.add_row("Tags", "[magenta]" + ", ".join(srv.tags) + "[/magenta]")

    # Notes (full, not truncated)
    if srv.notes:
        table.add_row("Notes", srv.notes)

    # Usage stats
    table.add_row("Pinned", "yes" if srv.favorite else "no")
    table.add_row("Used", f"{srv.use_count} time(s)")
    if srv.last_used_at:
        table.add_row("Last used", srv.last_used_at.isoformat(timespec="seconds"))
    else:
        table.add_row("Last used", "[dim]never[/dim]")

    # Servers that reference this one as jump host
    dependents = [s.name for s in all_servers if s.jump_host == srv.name and s.id != srv.id]
    if dependents:
        label = "server uses" if len(dependents) == 1 else "servers use"
        table.add_row("Used as jump by", f"[yellow]{len(dependents)} {label}: {', '.join(dependents)}[/yellow]")

    console.print(Panel(table, title=f"[bold]{srv.name}[/bold]", border_style="cyan", expand=False))


@app.command("remove", help="Remove a server. Alias: rm")
@app.command("rm", hidden=True)
def remove(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Remove a server."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to remove:")
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    # Check if this server is used as a jump host by others
    all_servers = storage.load_servers()
    dependents = [s for s in all_servers if s.jump_host == srv.name and s.id != srv.id]

    try:
        if not typer.confirm(f"Remove '{srv.name}' ({srv.username}@{srv.host}:{srv.port})?"):
            raise typer.Exit(0)

        if dependents:
            label = "server references" if len(dependents) == 1 else "servers reference"
            console.print(
                f"[yellow]Warning:[/yellow] {len(dependents)} {label} "
                f"this as a jump host: [cyan]{', '.join(s.name for s in dependents)}[/cyan]"
            )
            if not typer.confirm(
                "Clear jump_host on those servers so they connect directly?",
                default=True,
            ):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)
            # Clear dependents' jump_host and save them alongside the removal
            remaining = [s for s in all_servers if s.id != srv.id]
            for dep in remaining:
                if dep.jump_host == srv.name:
                    dep.jump_host = None
            storage.save_servers(remaining)
            console.print(f"[green]Removed.[/green] Cleared jump_host on {len(dependents)} dependent server(s).")
            return

        ok = storage.remove_server(srv.id)
        if ok:
            console.print("[green]Removed.[/green]")
        else:
            console.print("[yellow]Nothing to remove.[/yellow]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("edit", help="Edit a server. Alias: e")
@app.command("e", hidden=True)
def edit(
    query: str | None = typer.Argument(None, help="ID/name/partial name (optional)"),
    name_opt: str | None = typer.Option(None, "--name", help="Rename the server"),
    host_opt: str | None = typer.Option(None, "--host", help="New host"),
    port_opt: int | None = typer.Option(None, "--port", help="New port", min=1, max=65535),
    username_opt: str | None = typer.Option(None, "--username", help="New username"),
    key: str | None = typer.Option(None, "--key", help="SSH private key path (empty string clears)"),
    certificate: str | None = typer.Option(None, "--certificate", help="SSH certificate path (empty string clears)"),
    password_flag: str | None = typer.Option(
        None,
        "--password",
        help="Password (empty string clears; WARNING: visible in shell history)",
    ),
    jump: str | None = typer.Option(
        None, "--jump", "-J", help="Saved server name to use as ProxyJump (empty string clears)"
    ),
    keep_alive: int | None = typer.Option(
        None, "--keep-alive", "-K", help="Keep-alive interval in seconds (0 disables)", min=0
    ),
    note: str | None = typer.Option(None, "--notes", help="Free-form note (empty string clears)"),
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="Tag (repeatable; replaces existing tags)"),
):
    """Edit a server."""
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to edit:")
    else:
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    # Warn if this server is used as a jump host by others
    all_servers = storage.load_servers()
    used_by = [s.name for s in all_servers if s.jump_host == srv.name and s.id != srv.id]
    if used_by:
        label = "server uses" if len(used_by) == 1 else "servers use"
        console.print(
            f"[yellow]Note:[/yellow] {len(used_by)} {label} this as a jump host: [cyan]{', '.join(used_by)}[/cyan]"
        )
        console.print("[dim]Renaming will update their references automatically.[/dim]")

    try:
        # Name
        if name_opt is not None:
            name = name_opt
        else:
            name = typer.prompt("Name", default=srv.name)
        if name != srv.name:
            conflict = _name_conflict(name, all_servers, exclude_id=srv.id)
            if conflict:
                console.print(f"[red]A server named '{conflict.name}' already exists (id: {conflict.id[:8]}).[/red]")
                console.print("[dim]No changes saved.[/dim]")
                raise typer.Exit(1)

        # Host / Port / Username
        host = host_opt if host_opt is not None else typer.prompt("Host", default=srv.host)
        port = port_opt if port_opt is not None else typer.prompt("Port", default=srv.port, type=int)
        username = username_opt if username_opt is not None else typer.prompt("Username", default=srv.username)

        # Key path
        if key is not None:
            key_path = key or None
        else:
            key_path = srv.key_path
            if srv.key_path:
                if typer.confirm(f"Change key path? [{srv.key_path}]", default=False):
                    key_path = typer.prompt("New key path (empty to clear)", default="", show_default=False) or None
            elif typer.confirm("Add key path?", default=False):
                key_path = typer.prompt("Key path", show_default=False) or None

        # Certificate path
        if certificate is not None:
            certificate_path = certificate or None
        else:
            certificate_path = srv.certificate_path
            if srv.certificate_path:
                if typer.confirm(f"Change certificate path? [{srv.certificate_path}]", default=False):
                    certificate_path = (
                        typer.prompt("New certificate path (empty to clear)", default="", show_default=False) or None
                    )
            elif typer.confirm("Add certificate path?", default=False):
                certificate_path = typer.prompt("Certificate path", show_default=False) or None

        # Password
        if password_flag is not None:
            password = password_flag or None
        else:
            password = srv.password
            if srv.password:
                if typer.confirm("Change password?", default=False):
                    password = typer.prompt(
                        "New password (empty to clear)",
                        default="",
                        hide_input=True,
                        show_default=False,
                        confirmation_prompt=True,
                    )
                    password = password or None
            elif typer.confirm("Add password?", default=False):
                password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)

        # Jump host
        if jump is not None:
            if jump == "":
                jump_host = None
            else:
                match = next((s for s in all_servers if s.id != srv.id and s.name.lower() == jump.lower()), None)
                if match is None:
                    console.print(f"[red]Jump host '{jump}' not found in saved servers.[/red]")
                    console.print("[dim]No changes saved.[/dim]")
                    raise typer.Exit(1)
                jump_host = match.name
        else:
            jump_host = srv.jump_host
            if srv.jump_host:
                if typer.confirm(f"Change jump host? [{srv.jump_host}]", default=False):
                    candidates = [s for s in all_servers if s.name != srv.name]
                    _, jump_host = _select_jump_host(
                        candidates,
                        "Select jump host:",
                        include_none=True,
                        current=srv.jump_host,
                        all_servers=all_servers,
                    )
            elif typer.confirm("Use a jump host (ProxyJump)?", default=False):
                candidates = [s for s in all_servers if s.name != srv.name]
                _, jump_host = _select_jump_host(
                    candidates,
                    "Select jump host:",
                    include_none=False,
                    all_servers=all_servers,
                )

        # Notes
        if note is not None:
            notes = note or None
        else:
            notes = srv.notes
            if srv.notes:
                if typer.confirm(
                    f"Change note? [{srv.notes[:40]}{'...' if len(srv.notes) > 40 else ''}]", default=False
                ):
                    notes = typer.prompt("New note (empty to clear)", default="", show_default=False) or None
            elif typer.confirm("Add a note?", default=False):
                notes = typer.prompt("Note") or None

        # Keep-alive
        if keep_alive is not None:
            keep_alive_interval = keep_alive if keep_alive > 0 else None
        else:
            keep_alive_interval = srv.keep_alive_interval
            if srv.keep_alive_interval:
                if typer.confirm(f"Change keep-alive interval? [{srv.keep_alive_interval}s]", default=False):
                    keep_alive_interval = _prompt_keep_alive_interval(srv.keep_alive_interval)
            elif typer.confirm("Enable SSH keep-alive?", default=False):
                keep_alive_interval = _prompt_keep_alive_interval(60)

        # Tags
        if tag is not None:
            tags = _parse_tags(",".join(tag))
        else:
            tags = srv.tags
            if srv.tags:
                if typer.confirm(f"Change tags? [{', '.join(srv.tags)}]", default=False):
                    tags = _parse_tags(
                        typer.prompt("New comma-separated tags (empty to clear)", default="", show_default=False)
                    )
            elif typer.confirm("Add tags?", default=False):
                tags = _parse_tags(typer.prompt("Comma-separated tags"))

        old_name = srv.name
        srv.name = name
        srv.host = host
        srv.port = port
        srv.username = username
        srv.key_path = key_path or None
        srv.certificate_path = certificate_path or None
        srv.password = password
        srv.jump_host = jump_host
        srv.notes = notes
        srv.keep_alive_interval = keep_alive_interval
        srv.tags = tags

        # Validate the prospective jump chain before saving
        prospective = [s if s.id != srv.id else srv for s in all_servers]
        # If we're renaming, dependents' jump_host will be updated — simulate that
        if old_name != name:
            for other in prospective:
                if other.id != srv.id and other.jump_host == old_name:
                    other.jump_host = name
        error = _check_jump_cycle(prospective, srv)
        if error:
            console.print(f"[red]{error}[/red]")
            console.print("[dim]No changes saved.[/dim]")
            raise typer.Exit(1)

        # Cascade rename: update jump_host references in other servers
        if old_name != name and used_by:
            for other in all_servers:
                if other.id != srv.id and other.jump_host == old_name:
                    other.jump_host = name
            # Replace this server in the list, save all
            all_servers = [s if s.id != srv.id else srv for s in all_servers]
            storage.save_servers(all_servers)
            console.print(
                f"[green]Saved.[/green] Updated {len(used_by)} jump-host reference(s): "
                f"[cyan]{old_name}[/cyan] → [cyan]{name}[/cyan]"
            )
        else:
            storage.upsert_server(srv)
            console.print("[green]Saved.[/green]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("pin", help="Pin a server to the top of lists.")
def pin_server(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Pin a server for quick access."""
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to pin:")
    else:
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    if srv.favorite:
        console.print(f"[yellow]Already pinned:[/yellow] {srv.name}")
        return

    if not storage.set_server_favorite(srv.id, True):
        console.print("[red]Failed to pin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Pinned:[/green] {srv.name}")


@app.command("unpin", help="Remove a server from pinned favorites.")
def unpin_server(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Remove a server from favorites."""
    if query is None:
        servers = [server for server in storage.load_servers() if server.favorite]
        if not servers:
            console.print("[yellow]No pinned servers found. Pin one with [cyan]better-ssh pin <query>[/cyan].[/yellow]")
            raise typer.Exit(0)
        srv = _select_server(servers, "Select server to unpin:")
    else:
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    if not srv.favorite:
        console.print(f"[yellow]Server is not pinned:[/yellow] {srv.name}")
        return

    if not storage.set_server_favorite(srv.id, False):
        console.print("[red]Failed to unpin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Unpinned:[/green] {srv.name}")


@app.command("connect", help="Connect to a server. Alias: c")
@app.command("c", hidden=True)
def connect_cmd(
    query: str | None = typer.Argument(None, help="ID/name/partial name (optional)"),
    no_copy: bool = typer.Option(False, help="Don't copy password"),
):
    """Connect to a server."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    if query is None:
        srv = _select_server(servers, "Select server to connect:")
    else:
        srv = storage.find_server(query, servers)
        if not srv:
            matching_servers = _servers_matching_query(servers, query)
            if matching_servers:
                srv = _select_server(matching_servers, f"Select server to connect for '{query}':")
            else:
                srv = _select_server(servers, f"No direct match for '{query}'. Select server to connect:")

    rc = connect(srv, copy_password=not no_copy, all_servers=servers)
    if rc in (0, 130):
        storage.record_server_use(srv.id)
    raise typer.Exit(rc)


@app.command("copy-pass", help="Copy password to clipboard. Alias: cp")
@app.command("cp", hidden=True)
def copy_pass(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Copy password to clipboard."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        servers_with_pwd = [s for s in servers if s.password]
        if not servers_with_pwd:
            if not servers:
                _print_no_servers_message()
            else:
                console.print("[yellow]No servers with saved passwords.[/yellow]")
            raise typer.Exit(1)
        srv = _select_server(servers_with_pwd, "Select server to copy password:")
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv or not srv.password:
            console.print("[red]Server not found or has no password[/red]")
            raise typer.Exit(1)

    if is_encrypted(srv.password):
        if storage.is_encryption_enabled():
            console.print("[red]Password could not be decrypted. SSH key may be missing or changed.[/red]")
            console.print("Check encryption status: [cyan]bssh es[/cyan]")
        else:
            console.print("[red]Password is encrypted but encryption is disabled.[/red]")
            console.print("Re-enable and then properly disable: [cyan]bssh enc[/cyan] → [cyan]bssh dec[/cyan]")
        raise typer.Exit(1)

    try:
        pyperclip.copy(srv.password)
        console.print("[green]Password copied.[/green]")
    except Exception as e:
        console.print(f"[yellow]Clipboard not available: {e}[/yellow]")
        console.print(f"Use [cyan]bssh show-pass {srv.name}[/cyan] to display the password.")
        raise typer.Exit(1)


@app.command("show-pass", help="Show password. Alias: sp")
@app.command("sp", hidden=True)
def show_pass(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Show password."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        servers_with_pwd = [s for s in servers if s.password]
        if not servers_with_pwd:
            if not servers:
                _print_no_servers_message()
            else:
                console.print("[yellow]No servers with saved passwords.[/yellow]")
            raise typer.Exit(1)
        srv = _select_server(servers_with_pwd, "Select server to show password:")
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv or not srv.password:
            console.print("[red]Server not found or has no password[/red]")
            raise typer.Exit(1)

    if is_encrypted(srv.password):
        if storage.is_encryption_enabled():
            console.print("[red]Password could not be decrypted. SSH key may be missing or changed.[/red]")
            console.print("Check encryption status: [cyan]bssh es[/cyan]")
        else:
            console.print("[red]Password is encrypted but encryption is disabled.[/red]")
            console.print("Re-enable and then properly disable: [cyan]bssh enc[/cyan] → [cyan]bssh dec[/cyan]")
        raise typer.Exit(1)

    console.print(f"[bold]{srv.password}[/bold]")


@app.command("ping", help="Check server availability. Alias: p")
@app.command("p", hidden=True)
def ping_server(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Check if server is reachable on SSH port."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to ping:")
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    console.print(f"Checking [bold]{srv.name}[/bold] ({srv.host}:{srv.port})...")
    is_available, message, response_time = check_server_availability(srv)

    connection = f"{srv.username}@{srv.host}:{srv.port}"
    if is_available:
        console.print(f"{connection} - [green]{message}[/green] [dim]({response_time:.0f}ms)[/dim]")
    else:
        console.print(f"{connection} - [red]{message}[/red] [dim]({response_time:.0f}ms)[/dim]")
        raise typer.Exit(1)


@app.command("health", help="Check all servers availability. Alias: h")
@app.command("h", hidden=True)
def health_check():
    """Check availability of all servers."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    console.print(f"Checking {len(servers)} server(s)...\n")

    # Create results table
    table = Table(title="Server Health Check")
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Status")

    available_count = 0
    for srv in sorted(servers, key=lambda x: x.name.lower()):
        is_available, message, response_time = check_server_availability(srv, timeout=5.0)

        if is_available:
            available_count += 1
            status_style = "green"
        else:
            status_style = "red"

        table.add_row(
            srv.name,
            f"{srv.username}@{srv.host}:{srv.port}",
            f"[{status_style}]{message}[/{status_style}] [dim]({response_time:.0f}ms)[/dim]",
        )

    console.print(table)
    console.print(f"\n[bold]Summary:[/bold] {available_count}/{len(servers)} servers available")

    if available_count < len(servers):
        raise typer.Exit(1)


@app.command("encrypt", help="Enable password encryption. Alias: enc")
@app.command("enc", hidden=True)
def enable_encryption():
    """Enable password encryption (SSH key based)."""
    # Check current status
    if storage.is_encryption_enabled():
        console.print("[yellow]Encryption is already enabled.[/yellow]")
        return

    # Check for SSH key
    ssh_key = find_ssh_key_for_encryption()
    if not ssh_key:
        console.print("[red]Error: SSH key not found (id_ed25519 or id_rsa) in ~/.ssh/[/red]")
        console.print("Create SSH key: [cyan]ssh-keygen -t ed25519[/cyan]")
        raise typer.Exit(1)

    # Show disclaimer
    disclaimer = f"""
[bold yellow][!] WARNING: Enabling Password Encryption[/bold yellow]

[bold]How it works:[/bold]
- Passwords will be encrypted using your SSH key
- Using key: [cyan]{ssh_key}[/cyan]
- Encryption key is derived from SSH key content

[bold red]IMPORTANT:[/bold red]
- If you [bold]delete or change[/bold] the SSH key, you will [bold]lose access[/bold] to passwords
- Passwords can only be decrypted on this computer with this SSH key
- Make a [bold]backup[/bold] of the SSH key: {ssh_key}
- Make a [bold]backup[/bold] of the password file (before encryption)

[bold green]Benefits:[/bold green]
- Passwords are protected even if servers.json file is leaked
- No need to enter master password on every run
- SSH key is already protected by OS file permissions
"""

    console.print(Panel(disclaimer, title="Password Encryption", border_style="yellow"))

    try:
        console.print("\n[bold yellow]Do you understand the risks and want to enable encryption?[/bold yellow]")
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    # Load servers BEFORE enabling encryption so we get the raw state.
    # If passwords are stuck (encrypted but encryption is disabled), try to
    # recover them with the current salt; clear and warn if irrecoverable.
    servers = storage.load_servers()

    stuck: list[str] = []
    if not storage.is_encryption_enabled():
        salt = storage.get_or_create_encryption_salt()
        for server in servers:
            if server.password and is_encrypted(server.password):
                try:
                    server.password = decrypt_password(server.password, salt)
                except Exception:
                    stuck.append(server.name)
                    server.password = None

    if stuck:
        console.print(f"\n[yellow]Warning: {len(stuck)} server(s) had unrecoverable passwords:[/yellow]")
        for name in stuck:
            console.print(f"  [dim]• {name}[/dim]")
        console.print("[yellow]These passwords have been cleared. Re-enter with [cyan]bssh edit <name>[/cyan][/yellow]")

    # Enable encryption
    settings = storage.load_settings()
    settings["encryption_enabled"] = True
    settings["encryption_key_source"] = str(ssh_key)
    storage.save_settings(settings)

    storage.save_servers(servers)

    console.print("\n[bold green]Encryption enabled.[/bold green]")
    console.print(f"Using SSH key: [cyan]{ssh_key}[/cyan]")
    console.print(f"Encrypted servers: [cyan]{len([s for s in servers if s.password])}[/cyan]")


@app.command("decrypt", help="Disable password encryption. Alias: dec")
@app.command("dec", hidden=True)
def disable_encryption():
    """Disable password encryption (decrypt all passwords)."""
    if not storage.is_encryption_enabled():
        console.print("[yellow]Encryption is already disabled.[/yellow]")
        return

    # Warning
    warning = """
[bold yellow][!] Disabling Encryption[/bold yellow]

All passwords will be decrypted and saved in [bold red]plaintext[/bold red] \
in servers.json file.

[bold red]This is insecure![/bold red] The password file will be accessible \
to anyone with access to your computer.
"""

    console.print(Panel(warning, title="Warning", border_style="red"))

    try:
        console.print("\n[bold red]Are you sure you want to disable encryption?[/bold red]")
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    # Load servers (auto-decrypts with current salt).
    # Any passwords that still look encrypted after load are irrecoverable —
    # clear them and warn rather than saving ciphertext as "plaintext".
    servers = storage.load_servers()

    stuck: list[str] = []
    for server in servers:
        if server.password and is_encrypted(server.password):
            stuck.append(server.name)
            server.password = None

    if stuck:
        console.print(f"\n[yellow]Warning: {len(stuck)} server(s) had unrecoverable passwords:[/yellow]")
        for name in stuck:
            console.print(f"  [dim]• {name}[/dim]")
        console.print("[yellow]These passwords have been cleared. Re-enter with [cyan]bssh edit <name>[/cyan][/yellow]")

    # Disable encryption
    settings = storage.load_settings()
    settings["encryption_enabled"] = False
    storage.save_settings(settings)

    # Save servers in plaintext
    storage.save_servers(servers)

    console.print("\n[bold yellow]Encryption disabled.[/bold yellow]")
    console.print("[yellow]Passwords are now stored in plaintext![/yellow]")


@app.command("encryption-status", help="Show encryption status. Alias: es")
@app.command("es", hidden=True)
def encryption_status():
    """Show encryption status."""
    enabled = storage.is_encryption_enabled()
    settings = storage.load_settings()

    if enabled:
        ssh_key = settings.get("encryption_key_source", "unknown")
        ssh_key_exists = Path(ssh_key).exists() if ssh_key != "unknown" else False

        key_status = "[green]exists[/green]" if ssh_key_exists else "[red]not found![/red]"
        status = f"""
[bold green]Encryption enabled[/bold green]

SSH key: [cyan]{ssh_key}[/cyan]
Key status: {key_status}

Passwords are automatically encrypted on save and decrypted on read.
"""
        console.print(Panel(status, title="Encryption Status", border_style="green"))
    else:
        available_key = find_ssh_key_for_encryption()
        status = """
[bold yellow]Encryption disabled[/bold yellow]

Passwords are stored in [bold red]plaintext[/bold red] in servers.json file.

To enable encryption use: [cyan]better-ssh encrypt[/cyan]
"""
        if available_key:
            status += f"\nAvailable SSH key: [cyan]{available_key}[/cyan]"
        else:
            status += "\n[yellow]SSH key not found. Create one: ssh-keygen -t ed25519[/yellow]"

        console.print(Panel(status, title="Encryption Status", border_style="yellow"))


@app.command("export", help="Export servers to JSON file. Alias: ex")
@app.command("ex", hidden=True)
def export_servers(
    output: str = typer.Argument(..., help="Output file path (e.g., backup.json)"),
):
    """Export servers configuration to JSON file."""
    servers = storage.load_servers()

    if not servers:
        console.print("[yellow]No servers to export.[/yellow]")
        raise typer.Exit(1)

    # Check if any server has password
    servers_with_passwords = [s for s in servers if s.password]
    export_plaintext = False

    # Ask about password format if encryption is enabled and there are passwords
    if storage.is_encryption_enabled() and servers_with_passwords:
        console.print(f"\n[bold]Found {len(servers_with_passwords)} server(s) with passwords.[/bold]")

        try:
            password_mode = inquirer.select(
                message="Select password export mode:",
                choices=[
                    "Plaintext - passwords in readable format (for migration to other machines)",
                    "Encrypted - keep passwords encrypted (only works on this machine)",
                ],
                cycle=True,
                vi_mode=False,
            ).execute()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        export_plaintext = "Plaintext" in password_mode

        if export_plaintext:
            console.print("\n[cyan]Plaintext mode:[/cyan] Passwords will be readable in export file.")
        else:
            console.print(
                "\n[yellow]Encrypted mode:[/yellow] Passwords can only be decrypted "
                "on this machine with the same SSH key."
            )
        console.print()

    output_path = Path(output)

    # Check if file exists
    if output_path.exists():
        try:
            if not typer.confirm(f"File '{output}' already exists. Overwrite?", default=False):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)
        except (KeyboardInterrupt, typer.Abort):
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    # Prepare servers for export
    # Note: servers are already decrypted by load_servers()
    # If we want encrypted export, we need to re-encrypt them
    servers_to_export = servers
    if not export_plaintext and storage.is_encryption_enabled():
        # Re-encrypt passwords for export
        salt = storage.get_or_create_encryption_salt()
        servers_to_export = []
        for srv in servers:
            srv_copy = srv.model_copy(deep=True)
            if srv_copy.password:
                try:
                    srv_copy.password = encrypt_password(srv_copy.password, salt)
                except Exception as e:
                    console.print(f"[yellow]Warning: could not re-encrypt password for '{srv.name}': {e}[/yellow]")
                    console.print("[yellow]This server's password will be exported in plaintext.[/yellow]")
            servers_to_export.append(srv_copy)

    # Prepare export data
    export_data = {
        "version": 1,
        "exported_from": "better-ssh",
        "encryption_enabled": storage.is_encryption_enabled(),
        "passwords_encrypted": not export_plaintext and storage.is_encryption_enabled(),
        "servers": [s.model_dump(mode="json") for s in servers_to_export],
    }

    # Write to file
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]Exported {len(servers)} server(s) to:[/green] {output_path.absolute()}")
    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("import", help="Import servers from JSON file. Alias: im")
@app.command("im", hidden=True)
def import_servers(
    input_file: str = typer.Argument(..., help="Input file path (e.g., backup.json)"),
):
    """Import servers configuration from JSON file."""
    input_path = Path(input_file)

    if not input_path.exists():
        console.print(f"[red]File not found:[/red] {input_path}")
        raise typer.Exit(1)

    # Read import file
    try:
        import_data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[red]Failed to read file: {e}[/red]")
        raise typer.Exit(1)

    # Validate format
    if "servers" not in import_data:
        console.print("[red]Invalid file format: missing 'servers' field.[/red]")
        raise typer.Exit(1)

    try:
        imported_servers = [Server.model_validate(srv_data) for srv_data in import_data["servers"]]
    except Exception as e:
        console.print(f"[red]Invalid server data: {e}[/red]")
        raise typer.Exit(1)

    if not imported_servers:
        console.print("[yellow]No servers found in import file.[/yellow]")
        raise typer.Exit(1)

    # Show what will be imported
    console.print(f"\n[bold]Found {len(imported_servers)} server(s) to import:[/bold]")
    for srv in imported_servers:
        console.print(f"  - {srv.name} ({srv.username}@{srv.host}:{srv.port}) [{_auth_label(srv)}]")

    # Ask for import mode if there are existing servers
    existing_servers = storage.load_servers()
    merge_mode = False

    if existing_servers:
        console.print(f"\n[yellow]You have {len(existing_servers)} existing server(s).[/yellow]")

        try:
            mode_choice = inquirer.select(
                message="Select import mode:",
                choices=[
                    "Replace all - delete existing servers and import new ones",
                    "Merge - keep existing servers and add/update from import",
                ],
                cycle=True,
                vi_mode=False,
            ).execute()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        merge_mode = "Merge" in mode_choice

        if merge_mode:
            console.print("\n[cyan]Merge mode:[/cyan] Existing servers will be kept.")
            console.print("Servers with same ID will be updated.\n")
        else:
            console.print("\n[red]Replace mode:[/red] All existing servers will be deleted!\n")

    # Final confirmation
    try:
        if not typer.confirm("Continue with import?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    # Perform import
    if merge_mode:
        # Merge: update existing or add new
        existing_by_id = {s.id: s for s in existing_servers}
        for srv in imported_servers:
            existing_by_id[srv.id] = srv
        final_servers = list(existing_by_id.values())
    else:
        # Replace: use only imported
        final_servers = imported_servers

    storage.save_servers(final_servers)
    console.print(f"[green]Successfully imported {len(imported_servers)} server(s).[/green]")
    console.print(f"Total servers: {len(final_servers)}")


@app.command("import-ssh-config", help="Import hosts from SSH config. Alias: isc")
@app.command("isc", hidden=True)
def import_ssh_config_cmd(
    config_file: str | None = typer.Argument(None, help="SSH config path (default: ~/.ssh/config)"),
):
    """Import servers from an OpenSSH config file."""
    config_path = Path(config_file).expanduser() if config_file else get_default_ssh_config_path()

    if not config_path.exists():
        console.print(f"[red]SSH config not found:[/red] {config_path}")
        raise typer.Exit(1)

    try:
        imported_servers = import_ssh_config(config_path)
    except RuntimeError as e:
        console.print(f"[red]SSH config import failed:[/red] {e}")
        raise typer.Exit(1)

    if not imported_servers:
        console.print("[yellow]No importable hosts found in SSH config.[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Found {len(imported_servers)} SSH host(s) in:[/bold] {config_path}")
    for srv in imported_servers:
        console.print(f"  - {srv.name} ({srv.username}@{srv.host}:{srv.port}) [{_auth_label(srv)}]")

    existing_servers = storage.load_servers()
    merge_mode = True

    if existing_servers:
        console.print(f"\n[yellow]You have {len(existing_servers)} existing server(s).[/yellow]")

        try:
            mode_choice = inquirer.select(
                message="Select SSH config import mode:",
                choices=[
                    "Merge - update matching host names and keep everything else",
                    "Replace all - delete existing servers and use only SSH config hosts",
                ],
                cycle=True,
                vi_mode=False,
            ).execute()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        merge_mode = "Merge" in mode_choice

        if merge_mode:
            console.print("\n[cyan]Merge mode:[/cyan] Matching names will be updated, metadata will be preserved.\n")
        else:
            console.print("\n[red]Replace mode:[/red] All existing servers will be deleted!\n")

    try:
        if not typer.confirm("Continue with SSH config import?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    if merge_mode:
        final_servers = _merge_servers_by_name(existing_servers, imported_servers)
    else:
        final_servers = imported_servers

    storage.save_servers(final_servers)
    console.print(f"[green]Successfully imported {len(imported_servers)} SSH host(s).[/green]")
    console.print(f"Total servers: {len(final_servers)}")


def main():
    app()


if __name__ == "__main__":
    main()
