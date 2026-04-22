"""Availability commands: ping (single server), health (all servers)."""

from __future__ import annotations

import typer
from rich.markup import escape
from rich.table import Table

from .. import storage
from ..ssh import check_server_availability
from ._shared import _print_no_servers_message, _select_server, app, console


@app.command("ping", help="Check server availability. Alias: p")
@app.command("p", hidden=True)
def ping_server(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Check if server is reachable on SSH port."""
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to ping:")
    else:
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    console.print(f"Checking [bold]{escape(srv.name)}[/bold] ({escape(srv.host)}:{srv.port})...")
    is_available, message, response_time = check_server_availability(srv)

    connection = escape(f"{srv.username}@{srv.host}:{srv.port}")
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
            escape(srv.name),
            escape(f"{srv.username}@{srv.host}:{srv.port}"),
            f"[{status_style}]{message}[/{status_style}] [dim]({response_time:.0f}ms)[/dim]",
        )

    console.print(table)
    console.print(f"\n[bold]Summary:[/bold] {available_count}/{len(servers)} servers available")

    if available_count < len(servers):
        raise typer.Exit(1)
