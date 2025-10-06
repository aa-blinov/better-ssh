from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import time

import pyperclip
from rich.console import Console

from .models import Server

console = Console()


def has_ssh() -> bool:
    """Check if SSH client is available."""
    return shutil.which("ssh") is not None


def connect(server: Server, copy_password: bool = True) -> int:
    """Connect to SSH server. Returns exit code."""
    if not has_ssh():
        console.print("[red]SSH client not found.[/red]")
        system = platform.system()
        if system == "Windows":
            console.print(
                "Install OpenSSH Client:\n"
                "  • Via Windows Features: Settings → Apps → Optional Features → OpenSSH Client\n"
                "  • Via winget: [cyan]winget install --id Microsoft.OpenSSH.Client -e[/cyan]"
            )
        elif system == "Darwin":
            console.print("SSH client should be installed by default on macOS.\nTry: [cyan]brew install openssh[/cyan]")
        else:  # Linux and others
            console.print(
                "Install SSH client via package manager:\n"
                "  • Ubuntu/Debian: [cyan]sudo apt install openssh-client[/cyan]\n"
                "  • Fedora/RHEL: [cyan]sudo dnf install openssh-clients[/cyan]\n"
                "  • Arch: [cyan]sudo pacman -S openssh[/cyan]"
            )
        return 127

    # Copy password to clipboard if available
    if copy_password and server.password:
        try:
            pyperclip.copy(server.password)
            console.print("[green]Password copied to clipboard.[/green] When prompted for Password: paste with Ctrl+V.")
        except Exception as e:
            console.print(f"[yellow]Failed to copy password: {e}[/yellow]")

    cmd = ["ssh", "-p", str(server.port)]
    if server.key_path:
        cmd += ["-i", server.key_path]
    cmd += [f"{server.username}@{server.host}"]

    console.print(f"[cyan]SSH: {' '.join(cmd)}[/cyan]")
    try:
        return subprocess.call(cmd)  # noqa: S603
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        console.print(f"[red]SSH execution error: {e}[/red]")
        return 1


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
