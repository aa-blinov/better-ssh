"""Availability commands: ping (single server), health (all servers)."""

from __future__ import annotations

import asyncio

import typer
from rich.markup import escape
from rich.table import Table

from .. import storage
from ..models import Server
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


async def _check_one(
    srv: Server,
    timeout: float,  # noqa: ASYNC109 — forwarded to the blocking sync probe, not an asyncio.timeout
) -> tuple[Server, bool, str, float]:
    """Run the blocking socket probe on a worker thread so asyncio can gather them."""
    is_available, message, response_time = await asyncio.to_thread(check_server_availability, srv, timeout=timeout)
    return srv, is_available, message, response_time


async def _check_all(
    servers: list[Server],
    timeout: float,  # noqa: ASYNC109
) -> list[tuple[Server, bool, str, float]]:
    """Probe every server concurrently. Total wall time is ~max(timeout, slowest_host)."""
    return await asyncio.gather(*[_check_one(srv, timeout) for srv in servers])


@app.command("health", help="Check all servers availability. Alias: h")
@app.command("h", hidden=True)
def health_check(
    timeout: float = typer.Option(
        5.0,
        "--timeout",
        help="Per-server probe timeout in seconds (same name as `bssh exec --timeout`).",
        min=0.1,
    ),
):
    """Check availability of all servers."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    console.print(f"Checking {len(servers)} server(s) in parallel (timeout {timeout:.0f}s)...\n")

    # Probe concurrently via asyncio.to_thread so a single slow server
    # doesn't serialize the whole scan. Before this was a for-loop that
    # took N * timeout in the worst case; now it's just timeout.
    results = asyncio.run(_check_all(servers, timeout))

    table = Table(title="Server Health Check")
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Status")

    # Sort results by name for stable presentation — concurrent gather
    # returns in submission order, not alphabetical.
    results_sorted = sorted(results, key=lambda r: r[0].name.lower())

    available_count = 0
    for srv, is_available, message, response_time in results_sorted:
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
