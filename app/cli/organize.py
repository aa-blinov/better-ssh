"""Organization commands: list, pin, unpin."""

from __future__ import annotations

import typer
from rich.markup import escape

from .. import storage
from ..domain import servers_matching_query
from ._shared import _print_no_servers_message, _print_servers, _select_server, app, console


@app.command("recent", help="Show recently used servers, newest first. Alias: r.")
@app.command("r", hidden=True)
def recent_servers(
    limit: int = typer.Option(10, "--limit", "-n", help="Max servers to show", min=1),
) -> None:
    """Show servers sorted by most recently used, ignoring pin status.

    Pulls last_used_at timestamps that `connect` records on successful runs
    and presents them newest first. Pinned favorites appear in their actual
    recent position (not forced to the top), which is what users expect from
    a time-based list.
    """
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        return

    used = [s for s in servers if s.last_used_at is not None]
    if not used:
        console.print(
            "[yellow]No recent connections yet.[/yellow] "
            "Connect once with [cyan]bssh <name>[/cyan] to populate the list."
        )
        return

    used.sort(key=lambda s: s.last_used_at, reverse=True)
    _print_servers(used[:limit], sort=False, title=f"Recent {min(limit, len(used))} of {len(used)}")


@app.command(
    "list",
    help="Show list of servers. Alias: ls. Optional query filters by name/host/user/tag/jump/id-prefix.",
)
@app.command("ls", hidden=True)
def list_servers(
    query: str | None = typer.Argument(
        None,
        help="Filter servers by name/host/user/tag/jump (case-insensitive substring) or id prefix.",
    ),
) -> None:
    """Show list of servers (optionally filtered by query)."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        return

    if query:
        matching = servers_matching_query(servers, query)
        if not matching:
            console.print(f"[yellow]No servers match '{escape(query)}'.[/yellow]")
            return
        _print_servers(matching)
        return

    _print_servers(servers)


@app.command("pin", help="Pin a server to the top of lists.")
def pin_server(
    query: str | None = typer.Argument(None, help="Server id or substring (optional; matches name/host/user/tag/jump)"),
):
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
        console.print(f"[yellow]Already pinned:[/yellow] {escape(srv.name)}")
        return

    if not storage.set_server_favorite(srv.id, True):
        console.print("[red]Failed to pin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Pinned:[/green] {escape(srv.name)}")


@app.command("unpin", help="Remove a server from pinned favorites.")
def unpin_server(
    query: str | None = typer.Argument(None, help="Server id or substring (optional; matches name/host/user/tag/jump)"),
):
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
        console.print(f"[yellow]Server is not pinned:[/yellow] {escape(srv.name)}")
        return

    if not storage.set_server_favorite(srv.id, False):
        console.print("[red]Failed to unpin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Unpinned:[/green] {escape(srv.name)}")
