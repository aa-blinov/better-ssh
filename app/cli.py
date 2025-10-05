from __future__ import annotations

from pathlib import Path

import pyperclip
import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import storage
from .encryption import find_ssh_key_for_encryption
from .models import Server
from .ssh import connect


def find_default_ssh_key() -> str | None:
    """Find default SSH key in ~/.ssh/."""
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.exists():
        return None

    # Приоритет: ed25519 > rsa > ecdsa > dsa
    for key_name in ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]:
        key_path = ssh_dir / key_name
        if key_path.exists():
            return str(key_path)
    return None


app = typer.Typer(help="Better SSH: quick server selection, connection and password management.")
console = Console()


def _print_servers(servers: list[Server]) -> None:
    """Print servers table."""
    table = Table(title="Servers")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Auth", justify="center", no_wrap=True)

    for s in servers:
        auth = "key" if s.key_path else ("pwd" if s.password else "auto")
        table.add_row(s.id[:8], s.name, f"{s.username}@{s.host}:{s.port}", auth)

    console.print(table)


@app.command("list")
def list_servers() -> None:
    """Show list of servers."""
    servers = storage.load_servers()
    if not servers:
        console.print("[yellow]No servers found. Add one: better-ssh add[/yellow]")
        return
    _print_servers(servers)


@app.command("add")
def add_server(
    name: str | None = typer.Option(None, prompt=True, help="Server name"),
    host: str | None = typer.Option(None, prompt=True),
    port: int = typer.Option(22, prompt=True),
    username: str | None = typer.Option(None, prompt=True),
    use_key: bool = typer.Option(False, "--key", help="Use private key"),
    key_path: str | None = typer.Option(None, help="Path to key"),
    with_password: bool = typer.Option(False, "--password", help="Save password"),
):
    """Add a new server."""
    try:
        password = None
        if with_password:
            password = typer.prompt("Password (not encrypted)", hide_input=True, confirmation_prompt=True)
        if use_key and not key_path:
            default_key = find_default_ssh_key()
            if default_key:
                key_path = typer.prompt("Path to private key", default=default_key)
            else:
                key_path = typer.prompt("Path to private key (e.g. ~/.ssh/id_rsa)")

        server = Server(
            name=name, host=host, port=port, username=username, password=password, key_path=key_path or None
        )
        storage.upsert_server(server)
        console.print(f"[green]Added:[/green] {server.display()}  (id: {server.id})")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command()
def remove(query: str = typer.Argument(..., help="ID/name/partial name")):
    """Remove a server."""
    srv = storage.find_server(query)
    if not srv:
        console.print("[red]Server not found[/red]")
        raise typer.Exit(1)
    try:
        if not typer.confirm(f"Remove '{srv.name}' ({srv.username}@{srv.host}:{srv.port})?"):
            raise typer.Exit(1)
        ok = storage.remove_server(srv.id)
        if ok:
            console.print("[green]Removed.[/green]")
        else:
            console.print("[yellow]Nothing to remove.[/yellow]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command()
def edit(query: str = typer.Argument(..., help="ID/name/partial name")):
    """Edit a server."""
    srv = storage.find_server(query)
    if not srv:
        console.print("[red]Server not found[/red]")
        raise typer.Exit(1)

    try:
        name = typer.prompt("Name", default=srv.name)
        host = typer.prompt("Host", default=srv.host)
        port = typer.prompt("Port", default=str(srv.port))
        username = typer.prompt("Username", default=srv.username)

        # Offer current key or default if no key
        default_key_for_edit = srv.key_path or find_default_ssh_key() or ""
        key_path = typer.prompt("Key path (empty for none)", default=default_key_for_edit)

        change_pwd = typer.confirm("Change password?", default=False)
        password = srv.password
        if change_pwd:
            if typer.confirm("Clear password?", default=False):
                password = None
            else:
                password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)

        srv.name = name
        srv.host = host
        srv.port = int(port)
        srv.username = username
        srv.key_path = key_path or None
        srv.password = password
        storage.upsert_server(srv)
        console.print("[green]Saved.[/green]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("connect")
def connect_cmd(
    query: str | None = typer.Argument(None, help="ID/name/partial name (optional)"),
    no_copy: bool = typer.Option(False, help="Don't copy password"),
):
    """Connect to a server."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        if not servers:
            console.print("[yellow]No servers found. Add one: better-ssh add[/yellow]")
            raise typer.Exit(1)

        choices = [(s.display(), s.id) for s in sorted(servers, key=lambda x: x.name.lower())]
        try:
            selected_display = inquirer.select(
                message="Select server to connect:",
                choices=[c[0] for c in choices],
                cycle=True,
                vi_mode=False,
                instruction="↑↓ navigate, search by name",
            ).execute()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        # Find selected server
        srv = None
        for s in servers:
            if s.display() == selected_display:
                srv = s
                break

        if not srv:
            console.print("[red]Failed to identify server[/red]")
            raise typer.Exit(1)
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    rc = connect(srv, copy_password=not no_copy)
    raise typer.Exit(rc)


@app.command("copy-pass")
def copy_pass(query: str = typer.Argument(..., help="ID/name/partial name")):
    """Copy password to clipboard."""
    srv = storage.find_server(query)
    if not srv or not srv.password:
        console.print("[red]Server not found or has no password[/red]")
        raise typer.Exit(1)
    pyperclip.copy(srv.password)
    console.print("[green]Password copied.[/green]")


@app.command("show-pass")
def show_pass(
    query: str = typer.Argument(..., help="ID/name/partial name"),
    plain: bool = typer.Option(False, help="Show in plaintext"),
):
    """Show password."""
    srv = storage.find_server(query)
    if not srv or not srv.password:
        console.print("[red]Server not found or has no password[/red]")
        raise typer.Exit(1)
    if plain:
        console.print(f"[bold]{srv.password}[/bold]")
    else:
        masked = "*" * max(4, len(srv.password) - 2)
        console.print(f"[bold]{srv.password[:1]}{masked}{srv.password[-1:]}[/bold]")


@app.command("run")
def run_menu():
    """Interactive server selection menu."""
    while True:
        servers = storage.load_servers()
        if not servers:
            console.print("[yellow]No servers found. Add one?[/yellow]")
            try:
                if not typer.confirm("Add a server now?"):
                    break
                # Interactive add right here
                name = typer.prompt("Name")
                host = typer.prompt("Host")
                port = typer.prompt("Port", default="22")
                username = typer.prompt("Username")

                with_password = typer.confirm("Save password?", default=True)
                password = None
                if with_password:
                    password = typer.prompt("Password (not encrypted)", hide_input=True, confirmation_prompt=True)

                use_key = typer.confirm("Use private key?", default=False)
                key_path = None
                if use_key:
                    default_key = find_default_ssh_key()
                    if default_key:
                        key_path = typer.prompt("Key path", default=default_key)
                    else:
                        key_path = typer.prompt("Key path (e.g. ~/.ssh/id_rsa)")

                server = Server(
                    name=name, host=host, port=int(port), username=username, password=password, key_path=key_path
                )
                storage.upsert_server(server)
                console.print(f"[green]Added:[/green] {server.display()}")
                continue
            except (KeyboardInterrupt, typer.Abort):
                console.print("\n[dim]Cancelled.[/dim]")
                break

        choices = [(s.display(), s.id) for s in sorted(servers, key=lambda x: x.name.lower())]
        try:
            selected_id = inquirer.select(
                message="Select server (Enter to connect, Ctrl+C to exit):",
                choices=[c[0] for c in choices],
                cycle=True,
                vi_mode=False,
                instruction="↑↓ navigate, search by name",
            ).execute()
        except KeyboardInterrupt:
            # Ctrl+C или Esc
            console.print("\n[dim]Exiting...[/dim]")
            break
        except Exception:
            # Handle other exceptions during exit
            console.print("\n[dim]Exiting...[/dim]")
            break

        picked: Server | None = None
        for s in servers:
            if s.display() == selected_id:
                picked = s
                break

        if not picked:
            console.print("[red]Failed to identify server[/red]")
            continue

        console.rule(f"[bold]Connecting to {picked.name}")
        rc = connect(picked, copy_password=True)
        if rc != 0:
            console.print(f"[yellow]ssh exited with code {rc}[/yellow]")
        console.rule("[dim]Back to menu")


@app.command("encrypt")
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
[bold yellow]⚠️  WARNING: Enabling Password Encryption[/bold yellow]

[bold]How it works:[/bold]
• Passwords will be encrypted using your SSH key
• Using key: [cyan]{ssh_key}[/cyan]
• Encryption key is derived from SSH key content

[bold red]IMPORTANT:[/bold red]
• If you [bold]delete or change[/bold] the SSH key — you will [bold]lose access[/bold] to passwords
• Passwords can only be decrypted on this computer with this SSH key
• Make a [bold]backup[/bold] of the SSH key: {ssh_key}
• Make a [bold]backup[/bold] of the password file (before encryption)

[bold green]Benefits:[/bold green]
• Passwords are protected even if servers.json file is leaked
• No need to enter master password on every run
• SSH key is already protected by OS file permissions
"""

    console.print(Panel(disclaimer, title="🔐 Password Encryption", border_style="yellow"))

    try:
        console.print("\n[bold yellow]Do you understand the risks and want to enable encryption?[/bold yellow]")
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    # Enable encryption
    settings = storage.load_settings()
    settings["encryption_enabled"] = True
    settings["encryption_key_source"] = str(ssh_key)
    storage.save_settings(settings)

    # Rewrite all servers to encrypt passwords
    servers = storage.load_servers()  # load in plaintext
    storage.save_servers(servers)  # save encrypted

    console.print("\n[bold green]✓ Encryption enabled![/bold green]")
    console.print(f"Using SSH key: [cyan]{ssh_key}[/cyan]")
    console.print(f"Encrypted servers: [cyan]{len([s for s in servers if s.password])}[/cyan]")


@app.command("decrypt")
def disable_encryption():
    """Disable password encryption (decrypt all passwords)."""
    if not storage.is_encryption_enabled():
        console.print("[yellow]Encryption is already disabled.[/yellow]")
        return

    # Warning
    warning = """
[bold yellow]⚠️  Disabling Encryption[/bold yellow]

All passwords will be decrypted and saved in [bold red]plaintext[/bold red] \
in servers.json file.

[bold red]This is insecure![/bold red] The password file will be accessible \
to anyone with access to your computer.
"""

    console.print(Panel(warning, title="⚠️  Warning", border_style="red"))

    try:
        console.print("\n[bold red]Are you sure you want to disable encryption?[/bold red]")
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    # Load servers (they will be decrypted automatically)
    servers = storage.load_servers()

    # Disable encryption
    settings = storage.load_settings()
    settings["encryption_enabled"] = False
    storage.save_settings(settings)

    # Save servers (now in plaintext)
    storage.save_servers(servers)

    console.print("\n[bold yellow]Encryption disabled.[/bold yellow]")
    console.print("[yellow]Passwords are now stored in plaintext![/yellow]")


@app.command("encryption-status")
def encryption_status():
    """Show encryption status."""
    enabled = storage.is_encryption_enabled()
    settings = storage.load_settings()

    if enabled:
        ssh_key = settings.get("encryption_key_source", "unknown")
        ssh_key_exists = Path(ssh_key).exists() if ssh_key != "unknown" else False

        key_status = "[green]✓ exists[/green]" if ssh_key_exists else "[red]✗ not found![/red]"
        status = f"""
[bold green]✓ Encryption enabled[/bold green]

SSH key: [cyan]{ssh_key}[/cyan]
Key status: {key_status}

Passwords are automatically encrypted on save and decrypted on read.
"""
        console.print(Panel(status, title="🔐 Encryption Status", border_style="green"))
    else:
        available_key = find_ssh_key_for_encryption()
        status = """
[bold yellow]✗ Encryption disabled[/bold yellow]

Passwords are stored in [bold red]plaintext[/bold red] in servers.json file.

To enable encryption use: [cyan]better-ssh encrypt[/cyan]
"""
        if available_key:
            status += f"\nAvailable SSH key: [cyan]{available_key}[/cyan]"
        else:
            status += "\n[yellow]SSH key not found. Create one: ssh-keygen -t ed25519[/yellow]"

        console.print(Panel(status, title="⚠️  Encryption Status", border_style="yellow"))


def main():
    app()


if __name__ == "__main__":
    main()
