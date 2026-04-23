"""Shared state and helpers across CLI command modules.

Holds the single Typer `app` instance, the `Console`, and the presentation
helpers that more than one command module uses (pickers, empty-state message,
server table, merge logic for import flows). Leading-underscore names are
kept for the helpers that `tests/test_cli.py` monkey-patches by string path.
"""

from __future__ import annotations

import click
import typer
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ..domain import (
    auth_label,
    favorite_label,
    format_relative_time,
    jump_host_usage_map,
    parse_env_spec,
    parse_forward_spec,
    sort_servers,
)
from ..models import Forward, Server


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


def _print_servers(
    servers: list[Server],
    *,
    sort: bool = True,
    title: str = "Servers",
) -> None:
    """Print servers table.

    When ``sort`` is True (default) rows are re-ordered via ``sort_servers``
    (pinned first, then recent, then frequent, then name). Pass ``sort=False``
    to preserve the caller's order — e.g. `bssh recent` passes a time-sorted
    list and must not reshuffle favorites to the top.
    """
    show_via = any(s.jump_host for s in servers)
    show_keepalive = any(s.keep_alive_interval for s in servers)
    show_forwards = any(s.forwards for s in servers)
    show_last_used = any(s.last_used_at for s in servers)
    show_tags = any(s.tags for s in servers)
    show_notes = any(s.notes for s in servers)
    table = Table(title=title)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Pin", justify="center", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Auth", justify="center", no_wrap=True)
    if show_via:
        table.add_column("Via", style="cyan", no_wrap=True)
    if show_keepalive:
        table.add_column("Alive", style="green", justify="right", no_wrap=True)
    if show_forwards:
        table.add_column("Fwd", style="blue", justify="right", no_wrap=True)
    if show_last_used:
        table.add_column("Last used", style="dim", no_wrap=True)
    if show_tags:
        table.add_column("Tags", style="magenta", max_width=30, overflow="fold")
    if show_notes:
        table.add_column("Notes", style="dim", max_width=40, overflow="ellipsis")

    rows = sort_servers(servers) if sort else servers
    for s in rows:
        auth = auth_label(s)
        # Escape every user-provided string before it reaches the Rich table;
        # otherwise a server named "[red]evil[/red]" (or similar) would be
        # parsed as markup and distort the rendered row.
        row = [
            s.id[:8],
            favorite_label(s),
            escape(s.name),
            escape(f"{s.username}@{s.host}:{s.port}"),
            auth,
        ]
        if show_via:
            row.append(escape(s.jump_host) if s.jump_host else "")
        if show_keepalive:
            row.append(f"{s.keep_alive_interval}s" if s.keep_alive_interval else "")
        if show_forwards:
            row.append(str(len(s.forwards)) if s.forwards else "")
        if show_last_used:
            row.append(format_relative_time(s.last_used_at) if s.last_used_at else "")
        if show_tags:
            row.append(escape(", ".join(s.tags)) if s.tags else "")
        if show_notes:
            row.append(escape(s.notes) if s.notes else "")
        table.add_row(*row)

    console.print(table)


# Sentinel for the "(none — direct connection)" option in the jump-host
# picker. Using a unique object (rather than a magic string) guarantees no
# collision with any user-chosen server name, which must be a non-empty str.
_NONE_JUMP_SENTINEL: object = object()


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

    usage = jump_host_usage_map(all_servers or [])

    def label(s: Server) -> str:
        used_by = usage.get(s.name, 0)
        # Don't count the server being edited as "using itself"
        if current == s.name and used_by > 0:
            used_by -= 1
        suffix = f"  [used by {used_by}]" if used_by else ""
        marker = " [current]" if current == s.name else ""
        return f"{s.display()}{marker}{suffix}"

    sorted_candidates = sort_servers(candidates)
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
    sorted_servers = sort_servers(servers)
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


def _parse_forward_flags(
    local_specs: list[str] | None,
    remote_specs: list[str] | None,
    dynamic_specs: list[str] | None,
) -> list[Forward]:
    """Convert the raw -L / -R / -D flag lists into Forward objects.

    Surfaces any parser ValueError as a red CLI error and exits 1, so the
    caller doesn't need a try/except.
    """
    result: list[Forward] = []
    for kind, specs in (("local", local_specs), ("remote", remote_specs), ("dynamic", dynamic_specs)):
        for spec in specs or []:
            try:
                result.append(parse_forward_spec(spec, kind))
            except ValueError as exc:
                console.print(f"[red]{escape(str(exc))}[/red]")
                raise typer.Exit(1)
    return result


def _prompt_forwards_interactively() -> list[Forward]:
    """Interactively collect port-forward specs until the user picks (done)."""
    forwards: list[Forward] = []
    while True:
        try:
            kind = inquirer.select(
                message="Add a port forward?",
                choices=[
                    Choice(value="local", name="Local  -L  (port -> remote host:port)"),
                    Choice(value="remote", name="Remote -R  (remote port -> local host:port)"),
                    Choice(value="dynamic", name="Dynamic -D  (SOCKS proxy on local port)"),
                    Choice(value="__done__", name="(done)"),
                ],
                cycle=True,
                vi_mode=False,
            ).execute()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled forward configuration.[/dim]")
            break
        if kind == "__done__":
            break
        if kind == "dynamic":
            spec = typer.prompt("Local port (or bind:port)")
        else:
            label = "Local" if kind == "local" else "Remote"
            spec = typer.prompt(f"{label} forward spec (port:host:port or bind:port:host:port)")
        try:
            forwards.append(parse_forward_spec(spec, kind))
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
    return forwards


def _parse_env_flags(specs: list[str] | None) -> dict[str, str]:
    """Convert raw `--env KEY=VALUE` flag values into an ordered dict.

    Later entries with the same key override earlier ones. Parser ValueError is
    surfaced as a red CLI message and exit 1, matching the forward-flag helper.
    """
    result: dict[str, str] = {}
    for raw in specs or []:
        try:
            key, value = parse_env_spec(raw)
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)
        result[key] = value
    return result


def _prompt_env_interactively() -> dict[str, str]:
    """Collect env-var pairs in a loop until the user submits an empty line."""
    env: dict[str, str] = {}
    while True:
        raw = typer.prompt("KEY=VALUE (empty to finish)", default="", show_default=False)
        if not raw:
            break
        try:
            key, value = parse_env_spec(raw)
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            continue
        env[key] = value
    return env


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
