"""Broadcast remote-command execution: `bssh exec <cmd> <query>`.

Runs a single shell command on every server matched by the query, in parallel,
with a per-host colored prefix on each output line and an aggregated summary.
Designed for fleet-level checks like uptime, disk, service status.

Intentional limitations:
- Uses `ssh -o BatchMode=yes` so runs never block on a password prompt —
  password-only servers will surface a clear auth failure instead of hanging
  a parallel sweep. Key / certificate / ProxyJump auth all work.
- No concurrency cap in v1; each matched server gets its own `ssh` process
  via asyncio. Adequate up to low hundreds of hosts.
- Port forwards and X11 don't apply to non-interactive exec — they're
  connection-only features and are ignored here.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from time import perf_counter

import typer
from rich.markup import escape

from .. import storage
from ..domain import servers_matching_query
from ..models import Server
from ..ssh import JumpResolutionError, resolve_jump_chain
from ._shared import app, console


@dataclass
class ExecResult:
    """Outcome of running a single command on a single server."""

    server: Server
    returncode: int
    stdout: str
    stderr: str
    duration: float
    error: str | None = None  # connection-level failure that bypassed the shell


# Rotating palette so each host gets a distinct, consistent color throughout
# its prefixed output lines.
_PALETTE = ["cyan", "magenta", "green", "yellow", "blue", "bright_cyan", "bright_magenta", "bright_green"]


def _color_for(index: int) -> str:
    return _PALETTE[index % len(_PALETTE)]


def _build_ssh_exec_command(
    server: Server, remote_cmd: str, all_servers: list[Server], connect_timeout: int
) -> list[str]:
    """Build the ssh argv for running `remote_cmd` non-interactively on `server`."""
    cmd: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-p",
        str(server.port),
    ]
    if server.keep_alive_interval and server.keep_alive_interval > 0:
        cmd += ["-o", f"ServerAliveInterval={server.keep_alive_interval}"]
    if server.jump_host:
        chain = resolve_jump_chain(server, all_servers)
        jump_spec = ",".join(f"{j.username}@{j.host}:{j.port}" for j in chain)
        cmd += ["-J", jump_spec]
    if server.key_path:
        cmd += ["-i", server.key_path]
    if server.certificate_path:
        cmd += ["-o", f"CertificateFile={server.certificate_path}"]
    cmd += [f"{server.username}@{server.host}", remote_cmd]
    return cmd


async def _run_on_server(
    server: Server,
    remote_cmd: str,
    all_servers: list[Server],
    timeout: float,  # noqa: ASYNC109
    connect_timeout: int,
) -> ExecResult:
    """Execute `remote_cmd` on one server, returning the complete result."""
    start = perf_counter()

    try:
        argv = _build_ssh_exec_command(server, remote_cmd, all_servers, connect_timeout)
    except JumpResolutionError as exc:
        return ExecResult(server, 1, "", "", perf_counter() - start, error=str(exc))

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return ExecResult(server, 1, "", "", perf_counter() - start, error=f"spawn failed: {exc}")

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ExecResult(server, 124, "", "", perf_counter() - start, error=f"timed out after {timeout}s")

    return ExecResult(
        server=server,
        returncode=proc.returncode or 0,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        duration=perf_counter() - start,
    )


def _print_result(result: ExecResult, color: str) -> None:
    """Render one ExecResult as colored prefixed lines plus a trailing status tag."""
    # Escape the literal "[name]" label so Rich doesn't parse it as an unknown
    # style tag and swallow the brackets. Only the outer color wrapper should
    # be live Rich markup.
    label = escape(f"[{result.server.name}]")
    name_tag = f"[{color}]{label}[/{color}]"

    if result.error:
        console.print(f"{name_tag} [red]error:[/red] {escape(result.error)}")
        return

    for line in result.stdout.rstrip("\n").splitlines():
        console.print(f"{name_tag} {escape(line)}")
    for line in result.stderr.rstrip("\n").splitlines():
        console.print(f"{name_tag} [red]{escape(line)}[/red]")

    status = "[green]ok[/green]" if result.returncode == 0 else f"[red]exit {result.returncode}[/red]"
    console.print(f"{name_tag} [dim]({result.duration:.1f}s, {status})[/dim]")


async def _run_all(
    targets: list[Server],
    command: str,
    all_servers: list[Server],
    timeout: float,  # noqa: ASYNC109
    connect_timeout: int,
) -> list[ExecResult]:
    tasks = [_run_on_server(s, command, all_servers, timeout, connect_timeout) for s in targets]
    return await asyncio.gather(*tasks)


@app.command("exec", help="Run a command on one or more servers in parallel.")
def exec_cmd(
    command: str = typer.Argument(..., help="Remote shell command to run"),
    query: str | None = typer.Argument(None, help="Server filter (name / host / user / tag / id prefix)"),
    run_all: bool = typer.Option(False, "--all", help="Run on every saved server instead of filtering"),
    timeout: float = typer.Option(30.0, "--timeout", help="Per-host overall timeout in seconds", min=1.0),
    connect_timeout: int = typer.Option(
        10, "--connect-timeout", help="TCP connect timeout in seconds (ssh -o ConnectTimeout)", min=1
    ),
):
    """Broadcast a command and aggregate per-host output."""
    if shutil.which("ssh") is None:
        console.print("[red]ssh not found on PATH.[/red]")
        raise typer.Exit(127)

    servers = storage.load_servers()
    if not servers:
        console.print("[yellow]No servers saved. Add one with [cyan]bssh add[/cyan].[/yellow]")
        raise typer.Exit(1)

    if run_all:
        targets = servers
    elif query:
        targets = servers_matching_query(servers, query)
        if not targets:
            console.print(f"[yellow]No servers match '{escape(query)}'.[/yellow]")
            raise typer.Exit(1)
    else:
        console.print("[red]Provide a query or --all.[/red]")
        raise typer.Exit(2)

    names = ", ".join(s.name for s in targets)
    console.print(f"[bold]Running on {len(targets)} server(s):[/bold] [cyan]{escape(names)}[/cyan]")

    start = perf_counter()
    results = asyncio.run(_run_all(targets, command, servers, timeout, connect_timeout))
    total = perf_counter() - start

    for index, result in enumerate(results):
        _print_result(result, _color_for(index))

    ok = sum(1 for r in results if r.returncode == 0 and not r.error)
    summary_color = "green" if ok == len(results) else "yellow"
    console.print(
        f"\n[bold {summary_color}]Summary:[/bold {summary_color}] {ok}/{len(results)} ok in [bold]{total:.1f}s[/bold]"
    )

    if ok < len(results):
        raise typer.Exit(1)
