# better-ssh

[![Tests](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml/badge.svg)](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/aa-blinov/better-ssh/branch/master/graph/badge.svg)](https://codecov.io/gh/aa-blinov/better-ssh)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A command-line tool for managing SSH connections with an interactive interface, password management, and optional encryption.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
  - [Filtering the Server List](#filtering-the-server-list)
  - [Adding Servers Non-Interactively](#adding-servers-non-interactively)
  - [Server Notes, Tags, and Keep-Alive](#server-notes-tags-and-keep-alive)
  - [Port Forwarding](#port-forwarding)
  - [File Transfer (put / get)](#file-transfer-put--get)
  - [X11 Forwarding](#x11-forwarding)
  - [Viewing a Single Server](#viewing-a-single-server)
- [Jump Hosts (ProxyJump)](#jump-hosts-proxyjump)
- [Configuration](#configuration)
- [Password Encryption](#password-encryption)
- [Platform Support](#platform-support)
- [Contributing](#contributing)
- [License](#license)

## Overview

better-ssh simplifies SSH connection management by providing an interactive terminal interface for selecting and connecting to servers. It supports password storage with optional SSH key-based encryption, automatic password clipboard integration, and works across Windows, macOS, and Linux.

## Features

- Interactive server selection menu with search capabilities
- Pinned favorites that stay above recent history
- Interactive menus prioritize recently used servers automatically
- Import existing hosts from `~/.ssh/config`
- Password storage with optional SSH key-based encryption
- Automatic password clipboard integration
- Support for SSH private key and certificate authentication
- ProxyJump support — connect through a bastion host (or a chain of hosts)
- Optional SSH keep-alive per server (ServerAliveInterval)
- Per-server port forwarding presets (local `-L`, remote `-R`, dynamic SOCKS `-D`)
- Optional X11 forwarding per server (`ssh -X`)
- File transfer (`bssh put` / `bssh get`) that reuses a server's stored profile
- Free-form notes and tags attached to each server
- Detailed per-server card view (`bssh view <name>`)
- Time-sorted "recents" list (`bssh recent`) with a relative `Last used` column
- Server management (add, edit, remove, list)
- `bssh ls <query>` filter by name, host, user, tag, id prefix, or jump host
- Server availability checking (ping individual or health check all)
- Configuration backup and restore (export/import)
- Cross-platform compatibility (Windows, macOS, Linux)
- Short command aliases for faster workflow
- Flexible server identification (by name, partial name, or ID)
- Non-interactive CLI flags for scripted provisioning
- Auto-detection of SSH keys in standard locations

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- SSH client (OpenSSH)

### Steps

1. Clone the repository:

```bash
git clone https://github.com/aa-blinov/better-ssh.git
cd better-ssh
```

2. Install as a global tool:

```bash
uv tool install .
```

3. Verify installation:

```bash
bssh --help
```

Both `bssh` and `better-ssh` are registered as entry points and work identically.

For development instead of a global install:

```bash
uv sync
uv run bssh --help
```

### SSH Client Installation

The tool requires a system SSH client.

**Windows:**

```powershell
# Via Windows Settings
Settings -> Apps -> Optional Features -> OpenSSH Client

# Via winget
winget install --id Microsoft.OpenSSH.Client -e
```

**macOS:**

SSH client is pre-installed. If needed:

```bash
brew install openssh
```

**Linux:**

```bash
# Ubuntu/Debian
sudo apt install openssh-client

# Fedora/RHEL
sudo dnf install openssh-clients

# Arch Linux
sudo pacman -S openssh
```

### Shell Completion

```bash
bssh --install-completion   # install for current shell
bssh --show-completion      # preview without installing
```

## Usage

### Quick Start

```bash
bssh
bssh <query>
bssh import-ssh-config
```

- `bssh` opens the interactive connect menu immediately
- `bssh <query>` connects directly when the match is unique
- `bssh import-ssh-config` bootstraps your saved hosts from `~/.ssh/config`

### Available Commands

```text
Usage: bssh [OPTIONS] COMMAND [ARGS]...

Better SSH: quick server selection, connection and password management.

Commands:
  add                 Add a new server.               Alias: a
  connect             Connect to a server.            Alias: c
  copy-pass           Copy password to clipboard.     Alias: cp
  decrypt             Disable password encryption.    Alias: dec
  edit                Edit a server.                  Alias: e
  encrypt             Enable password encryption.     Alias: enc
  encryption-status   Show encryption status.         Alias: es
  export              Export servers to JSON file.    Alias: ex
  get                 Download a remote file/dir (scp).
  health              Check all servers availability. Alias: h
  import              Import servers from JSON file.  Alias: im
  import-ssh-config   Import hosts from SSH config.   Alias: isc
  list                Show list of servers.           Alias: ls
  pin                 Pin a server to the top of lists.
  ping                Check server availability.      Alias: p
  put                 Upload a local file/dir (scp).
  recent              Show recently used servers.     Alias: r
  remove              Remove a server.                Alias: rm
  show-pass           Show password.                  Alias: sp
  unpin               Remove a server from pinned favorites.
  view                Show a detailed card for a server. Alias: v
```

Run `bssh` without a subcommand to open the interactive connect menu immediately.

Run `bssh <query>` to connect directly when the match is unique. If the query is ambiguous or missing, the tool falls back to an interactive menu.

Use `bssh pin <query>` to keep critical hosts above the normal recent/frequent ordering, and `bssh unpin <query>` to remove them from favorites.

`bssh recent` (alias `r`) lists servers by most-recently-connected, newest first — independent of pin status. Cap the list with `--limit N` / `-n N` (default 10). Servers that were never connected via `bssh` don't appear. The rendered table includes a `Last used` column with a relative timestamp (`just now`, `5m ago`, `2h ago`, `3d ago`, or an ISO date for anything older than 30 days). The same column is shown in `bssh ls` once at least one server has a recorded connection.

Most commands work without arguments and will present an interactive menu.

`bssh add` interactively asks whether to set an SSH key, password, jump host, note, and keep-alive after the basic fields. All of these also have non-interactive flags for scripted use (see [Adding Servers Non-Interactively](#adding-servers-non-interactively)).

For password-based hosts, `bssh` copies the saved password to your clipboard before starting OpenSSH. You still paste it into the SSH password prompt manually; the password is not injected into the `ssh` command automatically.

For detailed help on any command, use `--help`:

```bash
bssh connect --help
bssh add --help
```

### Filtering the Server List

`bssh ls` accepts an optional query that filters the table by substring against name, host, username, tags, jump host, and id prefix (all case-insensitive except the id prefix):

```bash
bssh ls prod          # matches name/host/user/tag/jump containing "prod"
bssh ls bastion       # surfaces both the bastion itself and everything routed through it
bssh ls a1b2          # id-prefix match
```

When nothing matches, the command prints a single friendly line instead of an empty table. Omitting the query lists everything as before.

### Adding Servers Non-Interactively

Every field `bssh add` prompts for has an equivalent flag, so the full flow can be scripted:

```bash
bssh add \
  --name prod-db \
  --host 10.0.0.5 \
  --port 22 \
  --username deploy \
  --key ~/.ssh/prod_ed25519 \
  --certificate ~/.ssh/prod_ed25519-cert.pub \
  --jump bastion \
  --keep-alive 60 \
  --notes "main postgres"
```

Flag reference:

| Flag | Short | Purpose |
| --- | --- | --- |
| `--key <path>` | — | Path to SSH private key |
| `--certificate <path>` | — | Path to SSH certificate |
| `--password <value>` | — | Password (see security note below) |
| `--jump <name>` | `-J` | Saved server name to use as ProxyJump (case-insensitive) |
| `--keep-alive <seconds>` | `-K` | `ServerAliveInterval` in seconds; `0` leaves it disabled |
| `--notes <text>` | — | Free-form note attached to the server |
| `--tag <value>` | `-t` | Tag (repeatable: `-t prod -t db`) |
| `-L <spec>` | — | Local forward, repeatable: `-L [bind:]port:host:port` |
| `-R <spec>` | — | Remote forward, repeatable: `-R [bind:]port:host:port` |
| `-D <spec>` | — | Dynamic SOCKS forward, repeatable: `-D [bind:]port` |
| `--x11` | — | Enable X11 forwarding (`ssh -X`) |

Passing an empty string (`--key ""`, `--notes ""`) stores `None` — useful when a script wants to be explicit about clearing a field.

> **`--password` security note:** values passed on the command line end up in shell history (e.g. `~/.bash_history`), `/proc/<pid>/cmdline`, and process-listing tools. Prefer the interactive prompt when possible. The flag exists for provisioning scripts that source the password from a secure secret store at invocation time.

The same flag set is also available on `bssh edit`, plus `--name`, `--host`, `--port`, and `--username` for in-place field updates. Only flags you pass are applied — everything else still goes through the interactive prompts, so mixing is fine:

```bash
# Fully non-interactive
bssh edit prod --keep-alive 60 --notes "updated" -t prod -t eu

# Update one field, then interactively review the rest
bssh edit prod --host 10.0.0.9
```

Empty-string clearing works here too: `--jump ""` drops the ProxyJump, `--notes ""` wipes the note, etc.

Boolean toggles use Typer's `--x11/--no-x11` syntax on `bssh edit`: pass `--x11` to enable, `--no-x11` to disable, or omit both to keep the current value.

### Server Notes, Tags, and Keep-Alive

Four optional per-server fields surface as columns in the `ls` / `recent` tables when at least one server has them set:

- **Notes** — free-form text attached to a server (`Notes` column, truncated at 40 chars). Edit with `bssh edit` or set at creation time with `--notes`.
- **Tags** — small labels (e.g. `prod`, `db`, `eu-west`) used to organize and filter the list (`Tags` column). Tags are comma-separated in the interactive prompt or passed repeatedly as `-t prod -t db`. `bssh ls <query>` matches on tags, so `bssh ls prod` pulls every server labeled that way.
- **Keep-Alive** — a `ServerAliveInterval` value in seconds. When set, `bssh connect` passes `-o ServerAliveInterval=<N> -o ServerAliveCountMax=3` to OpenSSH, preventing NAT/idle disconnects (`Alive` column, e.g. `60s`). Enter `0` at the prompt (or `--keep-alive 0`) to leave it disabled.
- **Last used** — a relative timestamp (`5m ago`, `2h ago`, `3d ago`, or an ISO date for older) automatically recorded on every successful `bssh connect`. Surfaces in both `ls` and `recent` so you can see freshness at a glance.

All four columns are auto-hidden when no server has a value set.

### Port Forwarding

`bssh` stores per-server port-forward presets and passes them to OpenSSH automatically on every `bssh connect`. Three forwarding types are supported, matching OpenSSH flags:

| Type | Flag | Example | Meaning |
| --- | --- | --- | --- |
| Local | `-L` | `-L 5432:localhost:5432` | Forward local port 5432 to `localhost:5432` on the remote side (typical: tunnel a remote DB to your laptop). |
| Remote | `-R` | `-R 9000:internal:9000` | Forward remote port 9000 back to `internal:9000` on your network (typical: expose a local service to the remote host). |
| Dynamic | `-D` | `-D 1080` | Open a SOCKS proxy on local port 1080 that routes through the server. |

All three accept an optional bind address (e.g. `127.0.0.1:5432:localhost:5432`).

Non-interactive provisioning:

```bash
bssh add --name prod-db --host 10.0.0.5 --username deploy \
  -L 5432:localhost:5432 \
  -L 6379:redis-internal:6379 \
  -D 1080
```

Interactive flow: `bssh add` and `bssh edit` ask "Configure port forwards?" — picking yes opens a small loop where you choose local/remote/dynamic and enter a spec, repeating until you pick `(done)`.

Editing an existing server's forwards:

- Passing any `-L`/`-R`/`-D` flag to `bssh edit` **replaces** the entire forwards list (consistent with `--tag`).
- `bssh edit <name> --no-forwards` clears all forwards.
- Passing no forward-related flags keeps the existing list and opens the interactive prompt when no other flags trigger non-interactive mode.

`bssh ls` shows a `Fwd` column with the count (hidden when nobody has any). `bssh view <name>` lists each forward on its own line.

### File Transfer (put / get)

`bssh put` uploads and `bssh get` downloads, using `scp` under the hood and composing with the server's saved profile (port, key, certificate, jump host, keep-alive).

```bash
# Upload
bssh put prod-db ./backup.sql /var/backups/backup.sql
bssh put prod-db ./releases -r -C              # directory with compression
bssh put prod-db ./archive.tar.gz /var/backups/ -p   # keep mtime/atime/mode

# Download
bssh get prod-db /var/log/app.log ./app.log
bssh get prod-db /etc/nginx -r ./nginx-snapshot
bssh get prod-db /var/snapshots/data.bin ./data.bin -p   # preserve timestamps
```

Flag reference:

| Flag | Short | Purpose |
| --- | --- | --- |
| `--recursive` | `-r` | Recurse into directories (scp `-r`) |
| `--compress` | `-C` | Enable scp compression |
| `--preserve` | `-p` | Preserve modification times, access times, and modes (scp `-p`) |

Notes:

- Port forwards (`-L`/`-R`/`-D`) and X11 on the server profile are **not** applied to transfers — they're connection-only settings.
- Password authentication prompts come from OpenSSH itself; `bssh`'s clipboard copy is only wired into `bssh connect`, not put/get.
- ProxyJump uses the server's stored `jump_host` chain, same as `connect`.
- Requires `scp` on PATH (shipped with OpenSSH client tools). Missing binary -> exit code 127.

### X11 Forwarding

Set `x11_forwarding` on a server to have `bssh connect` pass `-X` to OpenSSH. GUI apps launched on the remote side will try to render through a local X11 display.

```bash
bssh add --name workstation --host ws.example --username dev --x11
bssh edit workstation --x11       # turn on
bssh edit workstation --no-x11    # turn off
bssh view workstation             # shows "X11: enabled (ssh -X)" row when on
```

**Prerequisites on the client side:**

- **Linux** — an X11 display is usually already running; nothing extra to install.
- **macOS** — install [XQuartz](https://www.xquartz.org/) and log out/in once so `$DISPLAY` is set.
- **Windows** — install an X server: VcXsrv, Xming, or use WSLg (Windows 11). Without one, OpenSSH will log `X11 forwarding request failed` and GUI apps will fail with `Can't open display`.

**`-X` vs `-Y`:** `bssh` emits `-X` (untrusted mode) which is the safer default. Some X11 apps — older `xterm`, certain Matplotlib backends — fail under the X11 SECURITY extension and need trusted mode (`-Y`). If you hit `BadAccess` / `SECURITY` errors, enable `ForwardX11Trusted yes` for that host in `~/.ssh/config` — `bssh`'s `-X` composes with your SSH config, so the directive takes effect.

### Viewing a Single Server

`bssh view <name>` (alias `v`) renders a full-fidelity card for one server in a Rich panel. Unlike `ls`, nothing gets truncated — useful when you want to see the complete notes, the resolved jump chain (`user@bastion:port → target-name`), and the list of other servers that reference this one as a jump host.

```bash
bssh view prod
bssh v prod-db
```

The view also flags a broken jump-host reference in red instead of failing silently, so you can spot stale ProxyJump targets before a connection attempt.

### Importing From SSH Config

Import hosts from your OpenSSH config:

```bash
bssh isc
```

Or import from a custom path:

```bash
bssh isc ~/.ssh/work-config
```

The importer resolves each host through `ssh -G`, so `Host *`, `Include`, explicit `IdentityFile`, and explicit `CertificateFile` are reflected in imported entries.

Default OpenSSH keys remain implicit. If a host works with plain `ssh host` because of default keys or `ssh-agent`, `bssh` will keep using that behavior without pinning a key path unless your SSH config explicitly does so.

### Server Identification

Servers can be identified by:

- Full name (case-insensitive)
- Partial name match
- Server ID prefix

Names are unique (case-insensitive): adding or renaming to a name already in use is rejected with an error pointing at the existing entry.

## Jump Hosts (ProxyJump)

`bssh` supports connecting through one or more bastion hosts using OpenSSH's `ProxyJump` (`-J`). A jump host is just another saved server referenced by name.

### Setting a jump host

During `bssh add`, after the basic fields, the tool asks:

```text
Use a jump host (ProxyJump)? [y/N]
```

Confirming opens a picker over your other saved servers. The picker marks the current selection and shows how many other servers already use each candidate as a jump host.

For non-interactive use (scripts, automation), pass the name directly:

```bash
bssh add --name prod --host prod.example --username deploy --jump bastion
# short form
bssh add --name prod --host prod.example --username deploy -J bastion
```

Reference matching is case-insensitive; the canonical casing from the saved server is stored.

### Editing and removal

- `bssh edit` always shows "Change jump host?" when one is set, opening the picker with a `(none — direct connection)` option first.
- Renaming a server used as a jump host by others **automatically updates** all referencing servers in one save.
- `bssh rm` warns when the target is used as a jump host by others and offers to clear `jump_host` on those dependents (default yes). Declining aborts the removal entirely.
- Cycles (`A → B → A`) and unknown references are rejected at save time, not silently accepted.

### Importing from `~/.ssh/config`

`bssh isc` reads the `ProxyJump` directive and sets `jump_host` when the referenced target matches another imported alias (case-insensitive).

### Known limitations

- **Bastion auth is not forwarded into `ssh -J`.** We pass only `user@host:port` for each hop; OpenSSH resolves credentials for the bastion through its own mechanisms (`~/.ssh/config`, `ssh-agent`, default keys). A `key_path` or `password` saved on the bastion entry in `bssh` is **not** used during a jump connection — if the bastion needs a specific key, declare it via `IdentityFile` in `~/.ssh/config` or add it to `ssh-agent`. This is a limitation of `ssh -J` itself, not `bssh`.
- **Password clipboard covers only the target**, not the bastion. You'll be prompted for the bastion's password separately during connection.
- **Multi-hop `ProxyJump h1,h2` and inline `user@host:port`** specs in `~/.ssh/config` are **skipped** during import. Only single-hop alias references to other imported hosts are preserved. Set multi-hop chains manually by adding each bastion as its own server and chaining `jump_host` references.

## Configuration

Configuration files are stored in platform-specific directories:

- **Windows:** `%LOCALAPPDATA%\better-ssh\`
- **macOS:** `~/Library/Application Support/better-ssh/`
- **Linux:** `~/.config/better-ssh/`

### Configuration Files

- `servers.json` — server configurations and encrypted passwords
- `settings.json` — application settings (encryption status, key source, salt)

## Password Encryption

By default, passwords are stored in plaintext. The application offers optional encryption using your SSH private key as the encryption key source.

### Managing Encryption

```bash
bssh es    # check encryption status
bssh enc   # enable encryption (interactive)
bssh dec   # disable encryption (interactive)
```

When exporting servers, you can choose to export passwords in plaintext or encrypted format through an interactive prompt.

### How It Works

The encryption system uses your SSH private key (`~/.ssh/id_ed25519` or `id_rsa`) to derive an encryption key via PBKDF2-HMAC-SHA256 with 100,000 iterations and a random per-installation salt stored in `settings.json`. Passwords are encrypted using Fernet (symmetric encryption) and stored in base64 format.

### Important Considerations

- **Key Dependency:** If you delete or modify your SSH key, encrypted passwords become inaccessible
- **Machine Specific:** Decryption requires the same SSH key and salt on the same machine
- **Backup Recommended:** Back up your SSH key and `settings.json` before enabling encryption
- **Automatic Operation:** Passwords are automatically encrypted on save and decrypted on load

### Security Properties

- Passwords remain protected if the `servers.json` file is compromised
- No master password required for daily use
- SSH key protected by operating system file permissions
- Random per-installation salt prevents precomputed key attacks

## Platform Support

- Windows 10/11
- macOS 10.15+
- Linux (any distribution with Python 3.12+)

All Python dependencies are cross-platform. The only external requirement is a system SSH client, which is typically pre-installed on macOS and Linux.

## Contributing

Contributions are welcome. Please follow these guidelines:

### Reporting Issues

- Check existing issues before creating a new one
- Include your operating system and Python version
- Provide steps to reproduce the problem
- Include relevant error messages or logs

### Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/aa-blinov/better-ssh.git`
3. Create a virtual environment: `uv sync`
4. Create a feature branch: `git checkout -b feature-name`
5. Make your changes

### Code Standards

- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Run linting: `uv run ruff check app tests`
- Format code: `uv run ruff format app tests`
- Ensure all checks pass before submitting

### Testing

```bash
uv run pytest                                    # run all tests
uv run pytest -v                                 # verbose output
uv run pytest tests/test_models.py              # specific file
uv run pytest --cov=app --cov-report=html       # with coverage report
```

**Test Structure:**

- `tests/test_models.py` — Server model tests
- `tests/test_domain.py` — Pure domain helpers (tag parsing, name uniqueness, jump-chain validation, sort/filter)
- `tests/test_encryption.py` — Encryption/decryption tests
- `tests/test_storage.py` — Configuration persistence tests
- `tests/test_ssh.py` — SSH command and availability tests
- `tests/test_ssh_config.py` — SSH config importer tests
- `tests/test_transfer.py` — put / get scp wrapper tests
- `tests/test_cli.py` — CLI commands and interface tests

**Source Layout:**

```text
app/
  models.py         Pydantic Server model
  domain.py         Pure logic (sort/filter, validation, tag parsing, jump-chain walking)
  storage.py        JSON file I/O with transparent encryption layering
  encryption.py     Fernet + PBKDF2 key derivation from an SSH key
  ssh.py            OpenSSH command construction, jump resolution, availability check
  ssh_config.py     ~/.ssh/config importer via `ssh -G`
  cli/
    __init__.py     Package entry: builds the Typer app, re-exports for tests
    _shared.py      Typer app instance, Console, pickers, common helpers
    connection.py   connect, copy-pass, show-pass + root callback
    manage.py       add, edit, remove, view
    organize.py     list, pin, unpin
    crypto.py       encrypt, decrypt, encryption-status
    backup.py       export, import, import-ssh-config
    health.py       ping, health
    transfer.py     put, get (scp wrappers)
```

### Submitting Changes

1. Ensure all tests pass: `uv run pytest`
2. Run linting: `uv run ruff check app tests`
3. Format code: `uv run ruff format app tests`
4. Commit your changes with clear, descriptive messages
5. Push to your fork
6. Submit a pull request with a description of your changes
7. Ensure all CI checks pass

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
