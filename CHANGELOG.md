# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-04-24

First tagged release (Beta). `0.1.0` was the initial scaffold and was
never published; this release is the point where the CLI surface
stabilizes. Requires **Python 3.12+** and an OpenSSH client.

### Installation

```bash
# Recommended: install as a uv tool (isolated environment)
uv tool install https://github.com/aa-blinov/better-ssh/releases/download/v0.2.0/better_ssh-0.2.0-py3-none-any.whl

# Or via pip (into the current environment):
pip install https://github.com/aa-blinov/better-ssh/releases/download/v0.2.0/better_ssh-0.2.0-py3-none-any.whl

# Or from source at this tag:
uv tool install git+https://github.com/aa-blinov/better-ssh.git@v0.2.0
```

Both `bssh` and `better-ssh` are registered as entry points and behave
identically. Verify with `bssh --help`.

### Core commands

- `bssh` (interactive picker), `bssh <query>` (direct connect when the
  query uniquely matches), `bssh connect` / `c`
- `bssh add` / `a`, `bssh edit` / `e`, `bssh remove` / `rm`,
  `bssh view` / `v`, `bssh list` / `ls`
- `bssh ping` / `p`, `bssh health` / `h`
- `bssh pin`, `bssh unpin`, `bssh recent` / `r`
- `bssh copy-pass` / `cp`, `bssh show-pass` / `sp`
- `bssh encrypt` / `enc`, `bssh decrypt` / `dec`,
  `bssh encryption-status` / `es`
- `bssh import` / `im`, `bssh export` / `ex`,
  `bssh import-ssh-config` / `isc`, `bssh export-ssh-config` / `esc`
- `bssh put`, `bssh get` (scp wrappers), `bssh exec` (parallel broadcast)

### Connection features

- ProxyJump / bastion chain support (`-J` under the hood)
- Port forwarding — local (`-L`), remote (`-R`), dynamic SOCKS (`-D`)
- X11 forwarding (`-X`) per server
- Per-server SSH keep-alive (`ServerAliveInterval`)
- Per-server `SetEnv` environment variables
- Pre- and post-connect local shell hooks (VPN setup, cleanup, etc.)
- SSH key and certificate authentication
- Automatic password clipboard integration (Windows / macOS / Linux)

### Storage & crypto

- Password encryption via your SSH private key (Fernet + PBKDF2-HMAC-SHA256,
  100k iterations, random per-installation salt)
- Transparent encrypt-on-save / decrypt-on-load
- Graceful handling of irrecoverable passwords (key rotation, etc.)
- Round-trip with OpenSSH config — `isc` imports Host blocks via `ssh -G`,
  `esc` writes them back out for other tools to consume

### UX

- Unified query semantics across every single-target command — matches by
  id, name, host, username, tag, or jump host
- Interactive pickers prioritize recently-used servers
- Pinned favorites stay above the normal list
- Per-server last-used timestamp surfaced in `ls` and `recent`
- Direct prompts for free-text optional fields (note, tags) — no more
  "Add a note? [y/N]: my note" trap
- Confirm-then-prompt for shell commands (pre/post) so a stray `n` doesn't
  become a command that runs on every connect
- Explicit destructive prompts on `import`: `DELETE all 12 existing
  server(s) and import 3 from 'backup.json'?`

### Non-interactive / scripting

- `--skip/-s` on `add` and `edit` — apply only the flags, skip prompts
- `--yes/-y` on `encrypt`, `decrypt`, `remove`, `import`, `isc`
- `--force/-f` on `export`, `esc` — overwrite without prompting;
  rc=1 when the user declines (scripts can tell whether the file was
  actually written)
- `--merge` / `--replace` on `import` / `isc` — pre-pick the mode
- `--no-forwards` / `--no-env` / `--no-pre` / `--no-post` clear flags
  (friendly to PowerShell, which eats `--flag ""`)
- Every destructive operation surfaces a meaningful exit code

### Parallelism

- `bssh exec` runs commands across matched servers concurrently with
  per-host colored output and an aggregated summary
- `bssh health` probes all servers in parallel — wall time is
  `~max(timeout, slowest_host)` instead of `N × timeout`

### Cross-platform

- Windows 10/11, macOS 10.15+, Linux (any distro with Python 3.12+)
- Platform-specific paste hints, clipboard fallback messages,
  SSH-client-missing install instructions

### Known limitations

- **`bssh` does not forward bastion auth through `ssh -J`.** Only
  `user@host:port` is passed for each hop; OpenSSH resolves bastion
  credentials through its own mechanisms (`~/.ssh/config`, ssh-agent,
  default keys). A `key_path` or `password` stored on the bastion entry
  in `bssh` is not used during a jump connection.
- **Password clipboard covers only the target server**, not the bastion.
  Users are prompted for the bastion password separately.
- **Multi-hop `ProxyJump h1,h2` and inline `user@host:port`** specs in
  `~/.ssh/config` are skipped on `bssh isc`. Only single-hop alias
  references to other imported hosts are preserved; multi-hop chains
  must be rebuilt manually via per-hop `jump_host` references.
- **`bssh exec` and `bssh put`/`get` use `-o BatchMode=yes`** to avoid
  interleaved password prompts in parallel runs. Password-only servers
  fail fast — use key/cert auth or ssh-agent for these commands.

### Testing

- Extensive test suite (~85% branch coverage), GitHub Actions CI,
  Codecov integration.

[0.2.0]: https://github.com/aa-blinov/better-ssh/releases/tag/v0.2.0
