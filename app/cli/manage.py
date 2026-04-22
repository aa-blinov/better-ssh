"""Server management commands: add, edit, remove, view."""

from __future__ import annotations

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .. import storage
from ..domain import check_jump_cycle, name_conflict, parse_tags, servers_matching_query
from ..encryption import find_ssh_key
from ..models import Server
from ..ssh import JumpResolutionError, resolve_jump_chain
from ._shared import (
    _parse_forward_flags,
    _print_no_servers_message,
    _prompt_forwards_interactively,
    _prompt_keep_alive_interval,
    _select_jump_host,
    _select_server,
    app,
    console,
)


@app.command("add", help="Add a new server. Alias: a")
@app.command("a", hidden=True)
def add_server(
    name: str | None = typer.Option(None, prompt=True, help="Server name"),
    host: str | None = typer.Option(None, prompt=True),
    port: int = typer.Option(22, prompt=True),
    username: str | None = typer.Option(None, prompt=True),
    jump: str | None = typer.Option(None, "--jump", "-J", help="Use this saved server as ProxyJump"),
    keep_alive: int | None = typer.Option(
        None,
        "--keep-alive",
        "-K",
        help="SSH keep-alive interval in seconds (0 to disable)",
        min=0,
    ),
    key: str | None = typer.Option(None, "--key", help="Path to SSH private key"),
    certificate: str | None = typer.Option(None, "--certificate", help="Path to SSH certificate"),
    password_flag: str | None = typer.Option(
        None,
        "--password",
        help="Password (WARNING: visible in shell history; prefer interactive prompt)",
    ),
    note: str | None = typer.Option(None, "--notes", help="Free-form note attached to the server"),
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="Tag (repeatable: -t prod -t db)"),
    local_forward: list[str] | None = typer.Option(
        None, "-L", help=r"Local forward, repeatable: \[bind:]port:host:port"
    ),
    remote_forward: list[str] | None = typer.Option(
        None, "-R", help=r"Remote forward, repeatable: \[bind:]port:host:port"
    ),
    dynamic_forward: list[str] | None = typer.Option(
        None, "-D", help=r"Dynamic SOCKS forward, repeatable: \[bind:]port"
    ),
):
    """Add a new server."""
    try:
        existing_servers = storage.load_servers()

        # Uniqueness check up front so we fail before prompting for credentials
        if name:
            conflict = name_conflict(name, existing_servers)
            if conflict:
                console.print(
                    f"[red]A server named '{escape(conflict.name)}' already exists (id: {conflict.id[:8]}).[/red]"
                )
                console.print("Pick a different name or edit the existing one with [cyan]bssh edit[/cyan].")
                raise typer.Exit(1)

        key_path: str | None = None
        if key is not None:
            key_path = key or None
        elif typer.confirm("Add SSH key?", default=False):
            default_key = find_ssh_key()
            if default_key:
                key_path = typer.prompt("Path to private key", default=str(default_key)) or None
            else:
                key_path = typer.prompt("Path to private key (e.g. ~/.ssh/id_rsa)") or None

        certificate_path: str | None = certificate or None

        password: str | None = None
        if password_flag is not None:
            password = password_flag or None
        elif typer.confirm("Add password?", default=False):
            password = typer.prompt("Password", hide_input=True, confirmation_prompt=True) or None

        jump_host: str | None = None
        if jump is not None:
            # --jump "" explicitly skips the prompt (leaves jump_host as None);
            # --jump <name> looks up the reference case-insensitively.
            if jump:
                match = next((s for s in existing_servers if s.name.lower() == jump.lower()), None)
                if match is None:
                    console.print(f"[red]Jump host '{escape(jump)}' not found in saved servers.[/red]")
                    raise typer.Exit(1)
                jump_host = match.name
        elif typer.confirm("Use a jump host (ProxyJump)?", default=False):
            candidates = [s for s in existing_servers if s.name != name]
            _, jump_host = _select_jump_host(
                candidates,
                "Select jump host:",
                include_none=False,
                all_servers=existing_servers,
            )

        notes: str | None = None
        if note is not None:
            notes = note or None
        elif typer.confirm("Add a note?", default=False):
            notes = typer.prompt("Note") or None

        tags: list[str] = []
        if tag is not None:
            tags = parse_tags(",".join(tag))
        elif typer.confirm("Add tags?", default=False):
            tags = parse_tags(typer.prompt("Comma-separated tags"))

        keep_alive_interval: int | None = None
        if keep_alive is not None:
            keep_alive_interval = keep_alive if keep_alive > 0 else None
        elif typer.confirm("Enable SSH keep-alive?", default=False):
            keep_alive_interval = _prompt_keep_alive_interval(60)

        if local_forward or remote_forward or dynamic_forward:
            forwards = _parse_forward_flags(local_forward, remote_forward, dynamic_forward)
        elif typer.confirm("Configure port forwards?", default=False):
            forwards = _prompt_forwards_interactively()
        else:
            forwards = []

        server = Server(
            name=name,
            host=host,
            port=port,
            username=username,
            password=password,
            key_path=key_path,
            certificate_path=certificate_path,
            jump_host=jump_host,
            notes=notes,
            keep_alive_interval=keep_alive_interval,
            tags=tags,
            forwards=forwards,
        )

        error = check_jump_cycle(existing_servers, server)
        if error:
            console.print(f"[red]{escape(error)}[/red]")
            raise typer.Exit(1)

        storage.upsert_server(server)
        console.print(f"[green]Added:[/green] {escape(server.display())}  (id: {server.id})")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("edit", help="Edit a server. Alias: e")
@app.command("e", hidden=True)
def edit(
    query: str | None = typer.Argument(None, help="ID/name/partial name (optional)"),
    name_opt: str | None = typer.Option(None, "--name", help="Rename the server"),
    host_opt: str | None = typer.Option(None, "--host", help="New host"),
    port_opt: int | None = typer.Option(None, "--port", help="New port", min=1, max=65535),
    username_opt: str | None = typer.Option(None, "--username", help="New username"),
    key: str | None = typer.Option(None, "--key", help="SSH private key path (empty string clears)"),
    certificate: str | None = typer.Option(None, "--certificate", help="SSH certificate path (empty string clears)"),
    password_flag: str | None = typer.Option(
        None,
        "--password",
        help="Password (empty string clears; WARNING: visible in shell history)",
    ),
    jump: str | None = typer.Option(
        None, "--jump", "-J", help="Saved server name to use as ProxyJump (empty string clears)"
    ),
    keep_alive: int | None = typer.Option(
        None, "--keep-alive", "-K", help="Keep-alive interval in seconds (0 disables)", min=0
    ),
    note: str | None = typer.Option(None, "--notes", help="Free-form note (empty string clears)"),
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="Tag (repeatable; replaces existing tags)"),
    local_forward: list[str] | None = typer.Option(
        None, "-L", help="Local forward (repeatable; any -L/-R/-D flag replaces existing forwards)"
    ),
    remote_forward: list[str] | None = typer.Option(None, "-R", help="Remote forward (repeatable)"),
    dynamic_forward: list[str] | None = typer.Option(None, "-D", help="Dynamic SOCKS forward (repeatable)"),
    clear_forwards: bool = typer.Option(False, "--no-forwards", help="Clear all port forwards"),
):
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

    all_servers = storage.load_servers()
    used_by = [s.name for s in all_servers if s.jump_host == srv.name and s.id != srv.id]
    if used_by:
        label = "server uses" if len(used_by) == 1 else "servers use"
        console.print(
            f"[yellow]Note:[/yellow] {len(used_by)} {label} this as a jump host: "
            f"[cyan]{escape(', '.join(used_by))}[/cyan]"
        )
        console.print("[dim]Renaming will update their references automatically.[/dim]")

    try:
        if name_opt is not None:
            name = name_opt
        else:
            name = typer.prompt("Name", default=srv.name)
        if name != srv.name:
            conflict = name_conflict(name, all_servers, exclude_id=srv.id)
            if conflict:
                console.print(
                    f"[red]A server named '{escape(conflict.name)}' already exists (id: {conflict.id[:8]}).[/red]"
                )
                console.print("[dim]No changes saved.[/dim]")
                raise typer.Exit(1)

        host = host_opt if host_opt is not None else typer.prompt("Host", default=srv.host)
        port = port_opt if port_opt is not None else typer.prompt("Port", default=srv.port, type=int)
        username = username_opt if username_opt is not None else typer.prompt("Username", default=srv.username)

        if key is not None:
            key_path = key or None
        else:
            key_path = srv.key_path
            if srv.key_path:
                if typer.confirm(f"Change key path? [{srv.key_path}]", default=False):
                    key_path = typer.prompt("New key path (empty to clear)", default="", show_default=False) or None
            elif typer.confirm("Add key path?", default=False):
                key_path = typer.prompt("Key path", show_default=False) or None

        if certificate is not None:
            certificate_path = certificate or None
        else:
            certificate_path = srv.certificate_path
            if srv.certificate_path:
                if typer.confirm(f"Change certificate path? [{srv.certificate_path}]", default=False):
                    certificate_path = (
                        typer.prompt("New certificate path (empty to clear)", default="", show_default=False) or None
                    )
            elif typer.confirm("Add certificate path?", default=False):
                certificate_path = typer.prompt("Certificate path", show_default=False) or None

        if password_flag is not None:
            password = password_flag or None
        else:
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

        if jump is not None:
            if jump == "":
                jump_host = None
            else:
                match = next((s for s in all_servers if s.id != srv.id and s.name.lower() == jump.lower()), None)
                if match is None:
                    console.print(f"[red]Jump host '{escape(jump)}' not found in saved servers.[/red]")
                    console.print("[dim]No changes saved.[/dim]")
                    raise typer.Exit(1)
                jump_host = match.name
        else:
            jump_host = srv.jump_host
            if srv.jump_host:
                if typer.confirm(f"Change jump host? [{srv.jump_host}]", default=False):
                    candidates = [s for s in all_servers if s.name != srv.name]
                    _, jump_host = _select_jump_host(
                        candidates,
                        "Select jump host:",
                        include_none=True,
                        current=srv.jump_host,
                        all_servers=all_servers,
                    )
            elif typer.confirm("Use a jump host (ProxyJump)?", default=False):
                candidates = [s for s in all_servers if s.name != srv.name]
                _, jump_host = _select_jump_host(
                    candidates,
                    "Select jump host:",
                    include_none=False,
                    all_servers=all_servers,
                )

        if note is not None:
            notes = note or None
        else:
            notes = srv.notes
            if srv.notes:
                if typer.confirm(
                    f"Change note? [{srv.notes[:40]}{'...' if len(srv.notes) > 40 else ''}]", default=False
                ):
                    notes = typer.prompt("New note (empty to clear)", default="", show_default=False) or None
            elif typer.confirm("Add a note?", default=False):
                notes = typer.prompt("Note") or None

        if keep_alive is not None:
            keep_alive_interval = keep_alive if keep_alive > 0 else None
        else:
            keep_alive_interval = srv.keep_alive_interval
            if srv.keep_alive_interval:
                if typer.confirm(f"Change keep-alive interval? [{srv.keep_alive_interval}s]", default=False):
                    keep_alive_interval = _prompt_keep_alive_interval(srv.keep_alive_interval)
            elif typer.confirm("Enable SSH keep-alive?", default=False):
                keep_alive_interval = _prompt_keep_alive_interval(60)

        if tag is not None:
            tags = parse_tags(",".join(tag))
        else:
            tags = srv.tags
            if srv.tags:
                if typer.confirm(f"Change tags? [{', '.join(srv.tags)}]", default=False):
                    tags = parse_tags(
                        typer.prompt("New comma-separated tags (empty to clear)", default="", show_default=False)
                    )
            elif typer.confirm("Add tags?", default=False):
                tags = parse_tags(typer.prompt("Comma-separated tags"))

        if clear_forwards:
            forwards = []
        elif local_forward or remote_forward or dynamic_forward:
            forwards = _parse_forward_flags(local_forward, remote_forward, dynamic_forward)
        else:
            forwards = srv.forwards
            if srv.forwards:
                summary = ", ".join(f.display() for f in srv.forwards)
                if typer.confirm(
                    f"Change port forwards? [{summary[:60]}{'...' if len(summary) > 60 else ''}]",
                    default=False,
                ):
                    forwards = _prompt_forwards_interactively()
            elif typer.confirm("Configure port forwards?", default=False):
                forwards = _prompt_forwards_interactively()

        old_name = srv.name
        srv.name = name
        srv.host = host
        srv.port = port
        srv.username = username
        srv.key_path = key_path or None
        srv.certificate_path = certificate_path or None
        srv.password = password
        srv.jump_host = jump_host
        srv.notes = notes
        srv.keep_alive_interval = keep_alive_interval
        srv.tags = tags
        srv.forwards = forwards

        prospective = [s if s.id != srv.id else srv for s in all_servers]
        if old_name != name:
            for other in prospective:
                if other.id != srv.id and other.jump_host == old_name:
                    other.jump_host = name
        error = check_jump_cycle(prospective, srv)
        if error:
            console.print(f"[red]{escape(error)}[/red]")
            console.print("[dim]No changes saved.[/dim]")
            raise typer.Exit(1)

        if old_name != name and used_by:
            for other in all_servers:
                if other.id != srv.id and other.jump_host == old_name:
                    other.jump_host = name
            all_servers = [s if s.id != srv.id else srv for s in all_servers]
            storage.save_servers(all_servers)
            console.print(
                f"[green]Saved.[/green] Updated {len(used_by)} jump-host reference(s): "
                f"[cyan]{escape(old_name)}[/cyan] -> [cyan]{escape(name)}[/cyan]"
            )
        else:
            storage.upsert_server(srv)
            console.print("[green]Saved.[/green]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("remove", help="Remove a server. Alias: rm")
@app.command("rm", hidden=True)
def remove(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Remove a server."""
    if query is None:
        servers = storage.load_servers()
        if not servers:
            _print_no_servers_message()
            raise typer.Exit(1)
        srv = _select_server(servers, "Select server to remove:")
    else:
        srv = storage.find_server(query)
        if not srv:
            console.print("[red]Server not found[/red]")
            raise typer.Exit(1)

    all_servers = storage.load_servers()
    dependents = [s for s in all_servers if s.jump_host == srv.name and s.id != srv.id]

    try:
        if not typer.confirm(f"Remove '{srv.name}' ({srv.username}@{srv.host}:{srv.port})?"):
            raise typer.Exit(0)

        if dependents:
            label = "server references" if len(dependents) == 1 else "servers reference"
            console.print(
                f"[yellow]Warning:[/yellow] {len(dependents)} {label} "
                f"this as a jump host: [cyan]{escape(', '.join(s.name for s in dependents))}[/cyan]"
            )
            if not typer.confirm(
                "Clear jump_host on those servers so they connect directly?",
                default=True,
            ):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)
            remaining = [s for s in all_servers if s.id != srv.id]
            for dep in remaining:
                if dep.jump_host == srv.name:
                    dep.jump_host = None
            storage.save_servers(remaining)
            console.print(f"[green]Removed.[/green] Cleared jump_host on {len(dependents)} dependent server(s).")
            return

        ok = storage.remove_server(srv.id)
        if ok:
            console.print("[green]Removed.[/green]")
        else:
            console.print("[yellow]Nothing to remove.[/yellow]")
    except (KeyboardInterrupt, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0)


@app.command("view", help="Show a detailed card for one server. Alias: v")
@app.command("v", hidden=True)
def view(query: str | None = typer.Argument(None, help="ID/name/partial name (optional)")):
    """Show a detailed card for one server."""
    all_servers = storage.load_servers()
    if not all_servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    if query is None:
        srv = _select_server(all_servers, "Select server to view:")
    else:
        srv = storage.find_server(query, all_servers)
        if not srv:
            matching = servers_matching_query(all_servers, query)
            if matching:
                srv = _select_server(matching, f"Select server to view for '{escape(query)}':")
            else:
                console.print(f"[red]No server matches '{escape(query)}'.[/red]")
                raise typer.Exit(1)

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value")

    # Escape every user-provided string before it reaches Rich, so names,
    # hosts, notes etc. containing square brackets render as literal text
    # instead of being parsed as style tags.
    table.add_row("Name", f"[bold]{escape(srv.name)}[/bold]")
    table.add_row("ID", srv.id)
    table.add_row("Host", escape(f"{srv.username}@{srv.host}:{srv.port}"))

    if srv.certificate_path:
        auth_line = f"certificate [dim]({escape(srv.certificate_path)})[/dim]"
        if srv.key_path:
            auth_line += f" + key [dim]({escape(srv.key_path)})[/dim]"
    elif srv.key_path:
        auth_line = f"key [dim]({escape(srv.key_path)})[/dim]"
    elif srv.password:
        auth_line = "password [dim](set)[/dim]"
    else:
        auth_line = "OpenSSH default (no key/password/cert pinned)"
    table.add_row("Auth", auth_line)

    if srv.jump_host:
        try:
            chain = resolve_jump_chain(srv, all_servers)
            hops = [escape(f"{j.username}@{j.host}:{j.port}") for j in chain]
            hops.append(escape(srv.name))
            table.add_row("Jump chain", f"[cyan]{' -> '.join(hops)}[/cyan]")
        except JumpResolutionError as exc:
            table.add_row("Jump chain", f"[red]broken: {escape(str(exc))}[/red]")

    if srv.keep_alive_interval:
        table.add_row("Keep-alive", f"[green]{srv.keep_alive_interval}s[/green]")

    if srv.forwards:
        lines = "\n".join(escape(f.display()) for f in srv.forwards)
        table.add_row("Forwards", f"[blue]{lines}[/blue]")

    if srv.tags:
        table.add_row("Tags", f"[magenta]{escape(', '.join(srv.tags))}[/magenta]")

    if srv.notes:
        table.add_row("Notes", escape(srv.notes))

    table.add_row("Pinned", "yes" if srv.favorite else "no")
    table.add_row("Used", f"{srv.use_count} time(s)")
    if srv.last_used_at:
        table.add_row("Last used", srv.last_used_at.isoformat(timespec="seconds"))
    else:
        table.add_row("Last used", "[dim]never[/dim]")

    dependents = [s.name for s in all_servers if s.jump_host == srv.name and s.id != srv.id]
    if dependents:
        label = "server uses" if len(dependents) == 1 else "servers use"
        dependents_str = escape(", ".join(dependents))
        table.add_row("Used as jump by", f"[yellow]{len(dependents)} {label}: {dependents_str}[/yellow]")

    console.print(Panel(table, title=f"[bold]{escape(srv.name)}[/bold]", border_style="cyan", expand=False))
