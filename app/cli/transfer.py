"""File transfer commands: put, get (thin wrappers over scp).

scp is the simplest universally-available tool for quick one-off transfers
and composes naturally with the server-profile fields we already track
(port, key, certificate, jump host, keep-alive). Forwards and X11 don't
apply to scp, so they're silently ignored.
"""

from __future__ import annotations

import shutil
import subprocess

import typer
from rich.markup import escape

from .. import storage
from ..domain import servers_matching_query
from ..models import Server
from ..ssh import JumpResolutionError, resolve_jump_chain, sftp_session
from ._shared import _print_no_servers_message, _select_server, app, console


def has_scp() -> bool:
    """Return True if `scp` is available on PATH."""
    return shutil.which("scp") is not None


def _build_scp_command(
    server: Server,
    source: str,
    dest: str,
    *,
    recursive: bool,
    compress: bool,
    preserve: bool,
    all_servers: list[Server],
) -> list[str]:
    """Build the `scp` argv for a given server profile and source/dest pair.

    Mirrors the auth/jump/keep-alive pieces of ssh.connect; flags unique to
    scp (`-P` for port, `-r` for recursion, `-C` for compression, `-p` for
    preserving mtime/atime/mode) are added here. Forwards and X11 are
    intentionally omitted — they don't apply to a single file transfer.
    """
    cmd: list[str] = ["scp", "-P", str(server.port)]
    if recursive:
        cmd.append("-r")
    if compress:
        cmd.append("-C")
    if preserve:
        cmd.append("-p")
    if server.keep_alive_interval and server.keep_alive_interval > 0:
        cmd += ["-o", f"ServerAliveInterval={server.keep_alive_interval}", "-o", "ServerAliveCountMax=3"]
    if server.jump_host:
        chain = resolve_jump_chain(server, all_servers)
        jump_spec = ",".join(f"{j.username}@{j.host}:{j.port}" for j in chain)
        cmd += ["-J", jump_spec]
    if server.key_path:
        cmd += ["-i", server.key_path]
    if server.certificate_path:
        cmd += ["-o", f"CertificateFile={server.certificate_path}"]
    cmd += [source, dest]
    return cmd


def _resolve_server_or_exit(query: str, servers: list[Server]) -> Server:
    srv = storage.find_server(query, servers)
    if not srv:
        console.print(f"[red]Server not found:[/red] {escape(query)}")
        raise typer.Exit(1)
    return srv


def _run_scp(cmd: list[str]) -> int:
    console.print(f"[cyan]SCP:[/cyan] {escape(' '.join(cmd))}")
    try:
        return subprocess.call(cmd)  # noqa: S603
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        console.print(f"[red]SCP execution error:[/red] {escape(str(exc))}")
        return 1


@app.command("put", help="Upload a local file or directory to a saved server.")
def put_cmd(
    query: str = typer.Argument(..., help="ID / name / partial name of the target server"),
    local: str = typer.Argument(..., help="Local source path"),
    remote: str = typer.Argument(..., help="Remote destination path"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Copy directories recursively"),
    compress: bool = typer.Option(False, "--compress", "-C", help="Enable scp compression"),
    preserve: bool = typer.Option(
        False,
        "--preserve",
        "-p",
        help="Preserve modification times, access times, and modes (scp -p)",
    ),
):
    """Upload via `scp` using the server's stored profile."""
    if not has_scp():
        console.print("[red]scp not found on PATH. Install OpenSSH client tools.[/red]")
        raise typer.Exit(127)

    servers = storage.load_servers()
    if not servers:
        console.print("[yellow]No servers saved. Add one with [cyan]bssh add[/cyan].[/yellow]")
        raise typer.Exit(1)

    srv = _resolve_server_or_exit(query, servers)
    remote_spec = f"{srv.username}@{srv.host}:{remote}"

    try:
        cmd = _build_scp_command(
            srv,
            local,
            remote_spec,
            recursive=recursive,
            compress=compress,
            preserve=preserve,
            all_servers=servers,
        )
    except JumpResolutionError as exc:
        console.print(f"[red]Jump host error:[/red] {escape(str(exc))}")
        raise typer.Exit(1)

    raise typer.Exit(_run_scp(cmd))


@app.command(
    "sftp",
    help=(
        "Open an interactive SFTP session to a saved server.\n\n"
        "Unlike `bssh put` / `bssh get` (one-shot transfers), this drops you "
        "into the sftp prompt so you can browse, upload, and download without "
        "knowing exact paths in advance. Uses the server's stored profile — "
        "port, key, certificate, jump chain, keep-alive — plus any pre/post "
        "hooks configured for that server."
    ),
)
def sftp_cmd(
    query: str | None = typer.Argument(None, help="Server id or substring (optional; matches name/host/user/tag/jump)"),
    copy: bool = typer.Option(
        True,
        "--copy/--no-copy",
        help="Copy the server's password to clipboard before launching sftp (disable with --no-copy).",
    ),
):
    """Drop into an interactive SFTP session against a saved server.

    Usage pattern when you don't know the exact remote path:

        bssh sftp prod-db
        sftp> cd /var/log
        sftp> ls
        sftp> get app.log
        sftp> bye
    """
    servers = storage.load_servers()
    if not servers:
        _print_no_servers_message()
        raise typer.Exit(1)

    if query is None:
        srv = _select_server(servers, "Select server for SFTP:")
    else:
        srv = storage.find_server(query, servers)
        if not srv:
            matching = servers_matching_query(servers, query)
            if matching:
                srv = _select_server(matching, f"Select server for SFTP for '{query}':")
            else:
                console.print(f"[red]No server matches '{escape(query)}'.[/red]")
                raise typer.Exit(1)

    rc = sftp_session(srv, copy_password=copy, all_servers=servers)
    # Count an interactive sftp session as a connection for recency tracking,
    # same as bssh connect — the user touched the host from bssh.
    if rc in (0, 130):
        storage.record_server_use(srv.id)
    raise typer.Exit(rc)


@app.command("get", help="Download a remote file or directory from a saved server.")
def get_cmd(
    query: str = typer.Argument(..., help="ID / name / partial name of the source server"),
    remote: str = typer.Argument(..., help="Remote source path"),
    local: str = typer.Argument(..., help="Local destination path"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Copy directories recursively"),
    compress: bool = typer.Option(False, "--compress", "-C", help="Enable scp compression"),
    preserve: bool = typer.Option(
        False,
        "--preserve",
        "-p",
        help="Preserve modification times, access times, and modes (scp -p)",
    ),
):
    """Download via `scp` using the server's stored profile."""
    if not has_scp():
        console.print("[red]scp not found on PATH. Install OpenSSH client tools.[/red]")
        raise typer.Exit(127)

    servers = storage.load_servers()
    if not servers:
        console.print("[yellow]No servers saved. Add one with [cyan]bssh add[/cyan].[/yellow]")
        raise typer.Exit(1)

    srv = _resolve_server_or_exit(query, servers)
    remote_spec = f"{srv.username}@{srv.host}:{remote}"

    try:
        cmd = _build_scp_command(
            srv,
            remote_spec,
            local,
            recursive=recursive,
            compress=compress,
            preserve=preserve,
            all_servers=servers,
        )
    except JumpResolutionError as exc:
        console.print(f"[red]Jump host error:[/red] {escape(str(exc))}")
        raise typer.Exit(1)

    raise typer.Exit(_run_scp(cmd))
