from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import time

import pyperclip
from rich.console import Console
from rich.markup import escape

from .models import Server

console = Console()


class JumpResolutionError(Exception):
    """Raised when a jump host chain cannot be resolved."""


def resolve_jump_chain(server: Server, all_servers: list[Server]) -> list[Server]:
    """Walk server.jump_host references and return the ordered chain.

    Returns [first_hop, ..., last_hop] (excluding the target itself).
    Raises JumpResolutionError on cycles or missing references.
    """
    if not server.jump_host:
        return []
    by_name = {s.name: s for s in all_servers}
    chain: list[Server] = []
    seen: set[str] = {server.name}
    current_name = server.jump_host
    while current_name:
        if current_name in seen:
            raise JumpResolutionError(f"Jump host cycle detected: {current_name} already in chain")
        jump = by_name.get(current_name)
        if jump is None:
            raise JumpResolutionError(f"Jump host '{current_name}' not found in saved servers")
        chain.append(jump)
        seen.add(current_name)
        current_name = jump.jump_host
    # order: first hop (outermost) ... last hop (closest to target)
    # as walked, chain[0] is the server's direct jump, chain[-1] is the last one before target.
    # ssh -J expects the same order: -J user1@host1,user2@host2,...
    return chain


def has_ssh() -> bool:
    """Check if SSH client is available."""
    return shutil.which("ssh") is not None


def _paste_hint() -> str:
    """Return a platform-appropriate paste hint for terminal prompts."""
    system = platform.system()
    if system == "Windows":
        return "paste with Ctrl+Shift+V or right-click"
    if system == "Darwin":
        return "paste with Cmd+V"
    return "paste from clipboard using your terminal shortcut"


def _clipboard_failure_message(error: Exception) -> str:
    """Return a user-facing clipboard failure message with a practical fallback."""
    base_message = f"[yellow]Failed to copy password: {escape(str(error))}[/yellow]"
    if platform.system() == "Linux":
        return (
            f"{base_message} Install [cyan]wl-clipboard[/cyan], [cyan]xclip[/cyan], or [cyan]xsel[/cyan], "
            "or use [cyan]better-ssh show-pass[/cyan]."
        )
    return f"{base_message} Use [cyan]better-ssh show-pass[/cyan] if needed."


def _run_shell_hook(command: str, label: str) -> int:
    """Run a user-provided shell command (pre/post hook).

    Goes through the platform shell (sh on POSIX, cmd.exe on Windows) so the
    user can compose pipes, redirects, and env references inline. Output is
    inherited (progress / prompts reach the terminal live).
    """
    console.print(f"[cyan]{label}:[/cyan] {escape(command)}")
    try:
        return subprocess.call(command, shell=True)  # noqa: S602 - intentional user shell command
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        console.print(f"[red]{label} error:[/red] {escape(str(exc))}")
        return 1


def connect(server: Server, copy_password: bool = True, all_servers: list[Server] | None = None) -> int:
    """Connect to SSH server. Returns exit code.

    If server.jump_host is set, all_servers must be provided so the chain
    can be resolved into a -J argument.
    """
    if not has_ssh():
        console.print("[red]SSH client not found.[/red]")
        system = platform.system()
        if system == "Windows":
            console.print(
                "Install OpenSSH Client:\n"
                "  - Via Windows Features: Settings -> Apps -> Optional Features -> OpenSSH Client\n"
                "  - Via winget: [cyan]winget install --id Microsoft.OpenSSH.Client -e[/cyan]"
            )
        elif system == "Darwin":
            console.print("SSH client should be installed by default on macOS.\nTry: [cyan]brew install openssh[/cyan]")
        else:  # Linux and others
            console.print(
                "Install SSH client via package manager:\n"
                "  - Ubuntu/Debian: [cyan]sudo apt install openssh-client[/cyan]\n"
                "  - Fedora/RHEL: [cyan]sudo dnf install openssh-clients[/cyan]\n"
                "  - Arch: [cyan]sudo pacman -S openssh[/cyan]"
            )
        return 127

    # Pre-connect hook: run user-provided setup command (VPN, SSO, mount ...).
    # If it fails, abort the connect entirely — the hook is a prerequisite.
    # Post-connect hook is NOT run in this case since there's nothing to clean up.
    if server.pre_connect_cmd:
        pre_rc = _run_shell_hook(server.pre_connect_cmd, "Pre-connect")
        if pre_rc != 0:
            console.print(f"[red]Pre-connect hook failed (exit {pre_rc}); aborting connect.[/red]")
            return pre_rc

    # Copy password to clipboard if available
    if copy_password and server.password:
        try:
            pyperclip.copy(server.password)
            console.print(f"[green]Password copied to clipboard.[/green] When prompted for Password: {_paste_hint()}.")
        except Exception as e:
            console.print(_clipboard_failure_message(e))

    cmd = ["ssh", "-p", str(server.port)]

    # Keep-alive: emit OpenSSH ServerAliveInterval/CountMax when the user
    # has opted in. CountMax=3 matches OpenSSH's documented default and
    # gives ~3*interval grace before declaring the connection dead.
    if server.keep_alive_interval and server.keep_alive_interval > 0:
        cmd += [
            "-o",
            f"ServerAliveInterval={server.keep_alive_interval}",
            "-o",
            "ServerAliveCountMax=3",
        ]

    # Port forwards: local (-L), remote (-R), dynamic/SOCKS (-D). Render each
    # via Forward.to_ssh_spec so bind-host handling stays in one place.
    for fwd in server.forwards:
        flag = {"local": "-L", "remote": "-R", "dynamic": "-D"}[fwd.type]
        cmd += [flag, fwd.to_ssh_spec()]

    # Environment variables: emit one `-o SetEnv=KEY=VALUE` per pair. SetEnv
    # pushes a literal value to the remote session (OpenSSH 7.8+); no sshd-side
    # AcceptEnv allowlist needed. Iteration order matches insertion (Python 3.7+
    # dict guarantee) so the ssh command stays deterministic across runs.
    for key, value in server.environment.items():
        cmd += ["-o", f"SetEnv={key}={value}"]

    # X11 forwarding: emit `-X` (untrusted mode — the SAFER variant) when
    # the user opted in. Some X11 apps misbehave under the SECURITY extension
    # and need trusted mode (`ssh -Y`) instead; users who hit that can enable
    # it via `ForwardX11Trusted yes` in ~/.ssh/config.
    if server.x11_forwarding:
        cmd += ["-X"]

    # ProxyJump chain
    if server.jump_host:
        try:
            chain = resolve_jump_chain(server, all_servers or [])
        except JumpResolutionError as exc:
            console.print(f"[red]Jump host error:[/red] {escape(str(exc))}")
            return 1
        jump_spec = ",".join(f"{j.username}@{j.host}:{j.port}" for j in chain)
        cmd += ["-J", jump_spec]

    if server.key_path:
        cmd += ["-i", server.key_path]
    if server.certificate_path:
        cmd += ["-o", f"CertificateFile={server.certificate_path}"]
    cmd += [f"{server.username}@{server.host}"]

    # `cmd` contains user-provided strings (username, host, paths, forward
    # specs); escape before printing so Rich renders brackets literally.
    console.print(f"[cyan]SSH:[/cyan] {escape(' '.join(cmd))}")
    try:
        ssh_rc = subprocess.call(cmd)  # noqa: S603
    except KeyboardInterrupt:
        ssh_rc = 130
    except Exception as e:
        console.print(f"[red]SSH execution error:[/red] {escape(str(e))}")
        ssh_rc = 1

    # Post-connect hook: always runs after an ssh attempt (even if ssh failed
    # or the user Ctrl+C'd the session). This is the place for cleanup like
    # unmounting SSHFS or disconnecting a VPN. A non-zero post exit is
    # reported as a warning but does not override ssh's rc.
    if server.post_connect_cmd:
        post_rc = _run_shell_hook(server.post_connect_cmd, "Post-connect")
        if post_rc != 0:
            console.print(f"[yellow]Post-connect hook exited {post_rc} (ssh rc was {ssh_rc}).[/yellow]")

    return ssh_rc


def check_server_availability(server: Server, timeout: float = 3.0) -> tuple[bool, str, float]:
    """
    Check if server is reachable on SSH port.
    Returns (is_available, message, response_time_ms).
    """
    start_time = time.perf_counter()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((server.host, server.port))
        sock.close()

        elapsed = (time.perf_counter() - start_time) * 1000  # convert to ms

        if result == 0:
            return True, "reachable", elapsed
        return False, "port closed", elapsed
    except socket.gaierror:
        elapsed = (time.perf_counter() - start_time) * 1000
        return False, "DNS error", elapsed
    except TimeoutError:
        elapsed = (time.perf_counter() - start_time) * 1000
        return False, "timeout", elapsed
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        return False, f"error: {e}", elapsed
