"""Organization commands: list, pin, unpin."""

from __future__ import annotations

import typer
from rich.markup import escape

from .. import storage
from ..domain import servers_matching_query
from ._shared import _print_no_servers_message, _print_servers, _select_server, app, console


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
        matching = servers_matching_query(servers, query)
        if not matching:
            console.print(f"[yellow]No servers match '{escape(query)}'.[/yellow]")
            return
        _print_servers(matching)
        return

    _print_servers(servers)


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
        console.print(f"[yellow]Already pinned:[/yellow] {escape(srv.name)}")
        return

    if not storage.set_server_favorite(srv.id, True):
        console.print("[red]Failed to pin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Pinned:[/green] {escape(srv.name)}")


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
        console.print(f"[yellow]Server is not pinned:[/yellow] {escape(srv.name)}")
        return

    if not storage.set_server_favorite(srv.id, False):
        console.print("[red]Failed to unpin server[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Unpinned:[/green] {escape(srv.name)}")
