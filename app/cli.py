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
from .ssh import check_server_availability, connect
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
    table = Table(title="Servers")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Pin", justify="center", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Auth", justify="center", no_wrap=True)
    table.add_column("Via", style="cyan", no_wrap=True)

    for s in _sort_servers(servers):
        auth = _auth_label(s)
        via = s.jump_host or ""
        table.add_row(s.id[:8], _favorite_label(s), s.name, f"{s.username}@{s.host}:{s.port}", auth, via)

    console.print(table)


def _sort_servers(servers: list[Server]) -> list[Server]:
    """Sort servers for daily use: pinned first, then recent, then frequent, then name."""

    def sort_key(server: Server) -> tuple[int, float, int, str]:
        last_used_ts = server.last_used_at.timestamp() if server.last_used_at else 0.0
        return (-int(server.favorite), -last_used_ts, -server.use_count, server.name.lower())

    return sorted(servers, key=sort_key)


def _select_jump_host(candidates: list[Server], message: str) -> str | None:
    """Interactively pick a jump host from candidate servers by name.

    Returns the chosen server's name, or None if the user cancels or no
    candidates are available.
    """
    if not candidates:
        console.print("[yellow]No other servers to use as jump host. Add one first.[/yellow]")
        return None
    sorted_candidates = _sort_servers(candidates)
    try:
        name = inquirer.select(
            message=message,
            choices=[Choice(value=s.name, name=s.display()) for s in sorted_candidates],
            cycle=True,
            vi_mode=False,
            instruction="Use arrows to navigate, search by name",
        ).execute()
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled jump host selection.[/dim]")
        return None
    return name


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
    """Return servers that loosely match the provided query."""
    normalized_query = query.lower()
    return [
        server
        for server in servers
        if normalized_query in server.name.lower()
        or normalized_query in server.host.lower()
        or normalized_query in server.username.lower()
        or server.id.startswith(query)
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


@app.command("list", help="Show list of servers. Alias: ls")
@app.command("ls", hidden=True)
def list_servers() -> None:
    """Show list of servers."""
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        return
    _print_servers(servers)


@app.command("add", help="Add a new server. Alias: a")
@app.command("a", hidden=True)
def add_server(
    name: str | None = typer.Option(None, prompt=True, help="Server name"),
    host: str | None = typer.Option(None, prompt=True),
    port: int = typer.Option(22, prompt=True),
    username: str | None = typer.Option(None, prompt=True),
):
    """Add a new server."""
    try:
        key_path: str | None = None
        if typer.confirm("Add SSH key?", default=False):
            default_key = find_ssh_key()
            if default_key:
                key_path = typer.prompt("Path to private key", default=str(default_key)) or None
            else:
                key_path = typer.prompt("Path to private key (e.g. ~/.ssh/id_rsa)") or None

        password: str | None = None
        if typer.confirm("Add password?", default=False):
            password = typer.prompt("Password", hide_input=True, confirmation_prompt=True) or None

        jump_host: str | None = None
        if typer.confirm("Use a jump host (ProxyJump)?", default=False):
            existing = [s for s in storage.load_servers() if s.name != name]
            jump_host = _select_jump_host(existing, "Select jump host:")

        server = Server(
            name=name,
            host=host,
            port=port,
            username=username,
            password=password,
            key_path=key_path,
            jump_host=jump_host,
        )
        storage.upsert_server(server)
        console.print(f"[green]Added:[/green] {server.display()}  (id: {server.id})")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


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

    try:
        if not typer.confirm(f"Remove '{srv.name}' ({srv.username}@{srv.host}:{srv.port})?"):
            raise typer.Exit(0)
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
def edit(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
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

    try:
        name = typer.prompt("Name", default=srv.name)
        host = typer.prompt("Host", default=srv.host)
        port = typer.prompt("Port", default=srv.port, type=int)
        username = typer.prompt("Username", default=srv.username)

        key_path = srv.key_path
        if srv.key_path:
            if typer.confirm(f"Change key path? [{srv.key_path}]", default=False):
                key_path = typer.prompt("New key path (empty to clear)", default="", show_default=False) or None
        else:
            if typer.confirm("Add key path?", default=False):
                key_path = typer.prompt("Key path", show_default=False) or None

        certificate_path = srv.certificate_path
        if srv.certificate_path:
            if typer.confirm(f"Change certificate path? [{srv.certificate_path}]", default=False):
                certificate_path = (
                    typer.prompt("New certificate path (empty to clear)", default="", show_default=False) or None
                )
        else:
            if typer.confirm("Add certificate path?", default=False):
                certificate_path = typer.prompt("Certificate path", show_default=False) or None

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

        jump_host = srv.jump_host
        if srv.jump_host:
            if typer.confirm(f"Change jump host? [{srv.jump_host}]", default=False):
                if typer.confirm("Clear jump host (use direct connection)?", default=False):
                    jump_host = None
                else:
                    candidates = [s for s in storage.load_servers() if s.name != srv.name]
                    jump_host = _select_jump_host(candidates, "Select jump host:") or srv.jump_host
        elif typer.confirm("Use a jump host (ProxyJump)?", default=False):
            candidates = [s for s in storage.load_servers() if s.name != srv.name]
            jump_host = _select_jump_host(candidates, "Select jump host:")

        srv.name = name
        srv.host = host
        srv.port = port
        srv.username = username
        srv.key_path = key_path or None
        srv.certificate_path = certificate_path or None
        srv.password = password
        srv.jump_host = jump_host
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
