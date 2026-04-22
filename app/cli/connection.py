"""Connection commands: root callback, connect, copy-pass, show-pass."""

from __future__ import annotations

import pyperclip
import typer

from .. import storage
from ..domain import servers_matching_query
from ..encryption import is_encrypted
from ..ssh import connect
from ._shared import _print_no_servers_message, _select_server, app, console


@app.callback()
def root(ctx: typer.Context) -> None:
    """Open the connect flow when the CLI is run without a subcommand."""
    if ctx.resilient_parsing or ctx.invoked_subcommand is not None:
        return
    connect_cmd(query=None, no_copy=False)


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
            matching_servers = servers_matching_query(servers, query)
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
