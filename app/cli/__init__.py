"""CLI package entry point.

Importing the submodules registers their @app.command decorators onto the
shared Typer instance.

Re-exports at the `app.cli` level keep the test monkeypatch paths stable after
the split. In particular, tests call:

    monkeypatch.setattr("app.cli.typer.prompt", fake)
    monkeypatch.setattr("app.cli.inquirer.select", fake)
    monkeypatch.setattr("app.cli.connect", fake_connect)

These work because `typer`/`inquirer`/`pyperclip` are module objects shared
across all submodules (attribute lookups happen at call time), and the
`connect`/`check_server_availability`/etc. aliases are re-bound on each
submodule's namespace so patching the submodule path flips the resolution.
"""

from __future__ import annotations

# Re-export third-party modules at the package level so monkeypatch paths like
# "app.cli.typer.prompt" keep working. These resolve to the same module objects
# that every submodule imports, so patching an attribute here affects all call
# sites in the package.
import pyperclip
import typer
from InquirerPy import inquirer

# Expose key symbols at the package level for tests and external callers that
# used to access them directly from the monolithic cli module. Tests patch
# `app.cli.<name>` for functions like `connect`, `check_server_availability`,
# etc.; keeping these bindings here means those tests need no update.
from ..encryption import find_ssh_key_for_encryption
from ..ssh import check_server_availability, connect
from ..ssh_config import get_default_ssh_config_path, import_ssh_config

# Import command modules so their @app.command decorators run at import time.
# Order doesn't matter for correctness; alphabetical for readability.
from . import backup as _backup  # noqa: F401
from . import connection as _connection  # noqa: F401
from . import crypto as _crypto  # noqa: F401
from . import health as _health  # noqa: F401
from . import manage as _manage  # noqa: F401
from . import organize as _organize  # noqa: F401
from . import transfer as _transfer  # noqa: F401
from ._shared import (
    _NONE_JUMP_SENTINEL,
    _prompt_keep_alive_interval,
    app,
    console,
)
from .connection import connect_cmd


def main() -> None:
    """Entry point for the `better-ssh` / `bssh` console scripts."""
    app()


__all__ = [
    "_NONE_JUMP_SENTINEL",
    "_prompt_keep_alive_interval",
    "app",
    "check_server_availability",
    "connect",
    "connect_cmd",
    "console",
    "find_ssh_key_for_encryption",
    "get_default_ssh_config_path",
    "import_ssh_config",
    "inquirer",
    "main",
    "pyperclip",
    "typer",
]


if __name__ == "__main__":
    main()
