"""Backup and import/export commands: export, import, import-ssh-config."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from InquirerPy import inquirer
from rich.markup import escape

from .. import storage
from ..domain import auth_label
from ..encryption import encrypt_password
from ..models import Server
from ..ssh_config import get_default_ssh_config_path, import_ssh_config
from ._shared import _merge_servers_by_name, app, console


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

    servers_with_passwords = [s for s in servers if s.password]
    export_plaintext = False

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

    if output_path.exists():
        try:
            if not typer.confirm(f"File '{output}' already exists. Overwrite?", default=False):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)
        except (KeyboardInterrupt, typer.Abort):
            console.print("\n[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    # Prepare servers for export.
    # load_servers already decrypts; if we want encrypted export, re-encrypt.
    servers_to_export = servers
    if not export_plaintext and storage.is_encryption_enabled():
        salt = storage.get_or_create_encryption_salt()
        servers_to_export = []
        for srv in servers:
            srv_copy = srv.model_copy(deep=True)
            if srv_copy.password:
                try:
                    srv_copy.password = encrypt_password(srv_copy.password, salt)
                except Exception as e:
                    console.print(
                        f"[yellow]Warning: could not re-encrypt password for '{escape(srv.name)}': {e}[/yellow]"
                    )
                    console.print("[yellow]This server's password will be exported in plaintext.[/yellow]")
            servers_to_export.append(srv_copy)

    export_data = {
        "version": 1,
        "exported_from": "better-ssh",
        "encryption_enabled": storage.is_encryption_enabled(),
        "passwords_encrypted": not export_plaintext and storage.is_encryption_enabled(),
        "servers": [s.model_dump(mode="json") for s in servers_to_export],
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]Exported {len(servers)} server(s) to:[/green] {escape(str(output_path.absolute()))}")
    except Exception as e:
        console.print(f"[red]Export failed:[/red] {escape(str(e))}")
        raise typer.Exit(1)


@app.command("import", help="Import servers from JSON file. Alias: im")
@app.command("im", hidden=True)
def import_servers(
    input_file: str = typer.Argument(..., help="Input file path (e.g., backup.json)"),
):
    """Import servers configuration from JSON file."""
    input_path = Path(input_file)

    if not input_path.exists():
        console.print(f"[red]File not found:[/red] {escape(str(input_path))}")
        raise typer.Exit(1)

    try:
        import_data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[red]Failed to read file:[/red] {escape(str(e))}")
        raise typer.Exit(1)

    if "servers" not in import_data:
        console.print("[red]Invalid file format: missing 'servers' field.[/red]")
        raise typer.Exit(1)

    try:
        imported_servers = [Server.model_validate(srv_data) for srv_data in import_data["servers"]]
    except Exception as e:
        console.print(f"[red]Invalid server data:[/red] {escape(str(e))}")
        raise typer.Exit(1)

    if not imported_servers:
        console.print("[yellow]No servers found in import file.[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Found {len(imported_servers)} server(s) to import:[/bold]")
    for srv in imported_servers:
        console.print(
            f"  - {escape(srv.name)} ({escape(srv.username)}@{escape(srv.host)}:{srv.port}) [{auth_label(srv)}]"
        )

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

    try:
        if not typer.confirm("Continue with import?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    if merge_mode:
        existing_by_id = {s.id: s for s in existing_servers}
        for srv in imported_servers:
            existing_by_id[srv.id] = srv
        final_servers = list(existing_by_id.values())
    else:
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
        console.print(f"[red]SSH config not found:[/red] {escape(str(config_path))}")
        raise typer.Exit(1)

    try:
        imported_servers = import_ssh_config(config_path)
    except RuntimeError as e:
        console.print(f"[red]SSH config import failed:[/red] {escape(str(e))}")
        raise typer.Exit(1)

    if not imported_servers:
        console.print("[yellow]No importable hosts found in SSH config.[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Found {len(imported_servers)} SSH host(s) in:[/bold] {escape(str(config_path))}")
    for srv in imported_servers:
        console.print(
            f"  - {escape(srv.name)} ({escape(srv.username)}@{escape(srv.host)}:{srv.port}) [{auth_label(srv)}]"
        )

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
