from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pyperclip
import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import storage
from .encryption import encrypt_password, find_ssh_key_for_encryption
from .models import Server
from .ssh import check_server_availability, connect


def find_default_ssh_key() -> str | None:
    """Find default SSH key in ~/.ssh/."""
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.exists():
        return None

    # Priority: ed25519 > rsa > ecdsa > dsa
    for key_name in ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]:
        key_path = ssh_dir / key_name
        if key_path.exists():
            return str(key_path)
    return None


class OrderCommands(typer.core.TyperGroup):
    """Custom group to sort commands alphabetically in help."""

    def list_commands(self, ctx):
        return sorted(super().list_commands(ctx))


app = typer.Typer(
    help="Better SSH: quick server selection, connection and password management.",
    cls=OrderCommands,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()


def _print_servers(servers: list[Server]) -> None:
    """Print servers table."""
    table = Table(title="Servers")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Connection")
    table.add_column("Auth", justify="center", no_wrap=True)

    for s in servers:
        auth = "key" if s.key_path else ("pwd" if s.password else "---")
        table.add_row(s.id[:8], s.name, f"{s.username}@{s.host}:{s.port}", auth)

    console.print(table)


@app.command("list", help="Show list of servers. Alias: ls")
@app.command("ls", hidden=True)
def list_servers() -> None:
    """Show list of servers."""
    servers = storage.load_servers()
    if not servers:
        console.print("[yellow]No servers found. Add one: better-ssh add[/yellow]")
        return
    _print_servers(servers)


@app.command("add", help="Add a new server. Alias: a")
@app.command("a", hidden=True)
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


@app.command("remove", help="Remove a server. Alias: rm")
@app.command("rm", hidden=True)
def remove(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Remove a server."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        if not servers:
            console.print("[yellow]No servers found.[/yellow]")
            raise typer.Exit(1)

        choices = [(s.display(), s.id) for s in sorted(servers, key=lambda x: x.name.lower())]
        try:
            selected_display = inquirer.select(
                message="Select server to remove:",
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


@app.command("edit", help="Edit a server. Alias: e")
@app.command("e", hidden=True)
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


@app.command("connect", help="Connect to a server. Alias: c")
@app.command("c", hidden=True)
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


@app.command("copy-pass", help="Copy password to clipboard. Alias: cp")
@app.command("cp", hidden=True)
def copy_pass(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Copy password to clipboard."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        servers_with_pwd = [s for s in servers if s.password]
        if not servers_with_pwd:
            console.print("[yellow]No servers with saved passwords.[/yellow]")
            raise typer.Exit(1)

        choices = [(s.display(), s.id) for s in sorted(servers_with_pwd, key=lambda x: x.name.lower())]
        try:
            selected_display = inquirer.select(
                message="Select server to copy password:",
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
        for s in servers_with_pwd:
            if s.display() == selected_display:
                srv = s
                break

        if not srv:
            console.print("[red]Failed to identify server[/red]")
            raise typer.Exit(1)
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv or not srv.password:
            console.print("[red]Server not found or has no password[/red]")
            raise typer.Exit(1)

    pyperclip.copy(srv.password)
    console.print("[green]Password copied.[/green]")


@app.command("show-pass", help="Show password. Alias: sp")
@app.command("sp", hidden=True)
def show_pass(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Show password."""
    # If no query provided, show interactive selection
    if query is None:
        servers = storage.load_servers()
        servers_with_pwd = [s for s in servers if s.password]
        if not servers_with_pwd:
            console.print("[yellow]No servers with saved passwords.[/yellow]")
            raise typer.Exit(1)

        choices = [(s.display(), s.id) for s in sorted(servers_with_pwd, key=lambda x: x.name.lower())]
        try:
            selected_display = inquirer.select(
                message="Select server to show password:",
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
        for s in servers_with_pwd:
            if s.display() == selected_display:
                srv = s
                break

        if not srv:
            console.print("[red]Failed to identify server[/red]")
            raise typer.Exit(1)
    else:
        # Use query to find server
        srv = storage.find_server(query)
        if not srv or not srv.password:
            console.print("[red]Server not found or has no password[/red]")
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
            console.print("[yellow]No servers found.[/yellow]")
            raise typer.Exit(1)

        choices = [(s.display(), s.id) for s in sorted(servers, key=lambda x: x.name.lower())]
        try:
            selected_display = inquirer.select(
                message="Select server to ping:",
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
        console.print("[yellow]No servers found.[/yellow]")
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
        servers_to_export = []
        for srv in servers:
            srv_copy = srv.model_copy(deep=True)
            if srv_copy.password:
                with contextlib.suppress(Exception):
                    srv_copy.password = encrypt_password(srv_copy.password)
            servers_to_export.append(srv_copy)

    # Prepare export data
    export_data = {
        "version": 1,
        "exported_from": "better-ssh",
        "encryption_enabled": storage.is_encryption_enabled(),
        "passwords_encrypted": not export_plaintext and storage.is_encryption_enabled(),
        "servers": [s.model_dump() for s in servers_to_export],
    }

    # Write to file
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]✓ Exported {len(servers)} server(s) to:[/green] {output_path.absolute()}")
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
        auth = "key" if srv.key_path else ("pwd" if srv.password else "---")
        console.print(f"  • {srv.name} ({srv.username}@{srv.host}:{srv.port}) [{auth}]")

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
    console.print(f"[green]✓ Successfully imported {len(imported_servers)} server(s)![/green]")
    console.print(f"Total servers: {len(final_servers)}")


def main():
    app()


if __name__ == "__main__":
    main()
