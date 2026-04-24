"""Password encryption commands: encrypt, decrypt, encryption-status."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape
from rich.panel import Panel

from .. import storage
from ..encryption import decrypt_password, find_ssh_key_for_encryption, is_encrypted
from ._shared import app, console


@app.command("encrypt", help="Enable password encryption. Alias: enc")
@app.command("enc", hidden=True)
def enable_encryption(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-confirm the safety prompt (for scripts / CI).",
    ),
):
    """Enable password encryption (SSH key based)."""
    if storage.is_encryption_enabled():
        console.print("[yellow]Encryption is already enabled.[/yellow]")
        return

    ssh_key = find_ssh_key_for_encryption()
    if not ssh_key:
        console.print("[red]Error: SSH key not found (id_ed25519 or id_rsa) in ~/.ssh/[/red]")
        console.print("Create SSH key: [cyan]ssh-keygen -t ed25519[/cyan]")
        raise typer.Exit(1)

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

    # Keep the disclaimer panel visible even under --yes (informational, low
    # cost); only the interactive confirm is skipped so scripts/CI can run.
    if not yes:
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
            console.print(f"  [dim]• {escape(name)}[/dim]")
        console.print("[yellow]These passwords have been cleared. Re-enter with [cyan]bssh edit <name>[/cyan][/yellow]")

    settings = storage.load_settings()
    settings["encryption_enabled"] = True
    settings["encryption_key_source"] = str(ssh_key)
    storage.save_settings(settings)

    storage.save_servers(servers)

    console.print("\n[bold green]Encryption enabled.[/bold green]")
    console.print(f"Using SSH key: [cyan]{escape(str(ssh_key))}[/cyan]")
    console.print(f"Encrypted servers: [cyan]{len([s for s in servers if s.password])}[/cyan]")


@app.command("decrypt", help="Disable password encryption. Alias: dec")
@app.command("dec", hidden=True)
def disable_encryption(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-confirm the safety prompt (for scripts / CI).",
    ),
):
    """Disable password encryption (decrypt all passwords)."""
    if not storage.is_encryption_enabled():
        console.print("[yellow]Encryption is already disabled.[/yellow]")
        return

    warning = """
[bold yellow][!] Disabling Encryption[/bold yellow]

All passwords will be decrypted and saved in [bold red]plaintext[/bold red] \
in servers.json file.

[bold red]This is insecure![/bold red] The password file will be accessible \
to anyone with access to your computer.
"""

    console.print(Panel(warning, title="Warning", border_style="red"))

    if not yes:
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
            console.print(f"  [dim]• {escape(name)}[/dim]")
        console.print("[yellow]These passwords have been cleared. Re-enter with [cyan]bssh edit <name>[/cyan][/yellow]")

    settings = storage.load_settings()
    settings["encryption_enabled"] = False
    storage.save_settings(settings)

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

SSH key: [cyan]{escape(str(ssh_key))}[/cyan]
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
            status += f"\nAvailable SSH key: [cyan]{escape(str(available_key))}[/cyan]"
        else:
            status += "\n[yellow]SSH key not found. Create one: ssh-keygen -t ed25519[/yellow]"

        console.print(Panel(status, title="Encryption Status", border_style="yellow"))
