# better-ssh

A command-line tool for managing SSH connections with an interactive interface, password management, and optional encryption. Every server keeps its jump chain, port forwards, environment variables and hooks, so a connection is one word instead of a long `ssh` line. Underneath, it drives the OpenSSH client that is already on the machine.

[![Website](https://img.shields.io/badge/website-aa--blinov.github.io%2Fbetter--ssh-0ea5e9?logo=github)](https://aa-blinov.github.io/better-ssh/)
[![Tests](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml/badge.svg)](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/aa-blinov/better-ssh/branch/master/graph/badge.svg)](https://codecov.io/gh/aa-blinov/better-ssh)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Quick start

Python 3.12 or higher, [uv](https://github.com/astral-sh/uv), and an OpenSSH client.

```bash
git clone https://github.com/aa-blinov/better-ssh.git
cd better-ssh
uv tool install .
bssh --help
```

`bssh` and `better-ssh` are both registered as entry points and work identically.

Then pull in the hosts you already have, and connect:

```bash
bssh import-ssh-config
bssh
```

`bssh` on its own opens the interactive connect menu. `bssh <query>` connects straight away when the query matches exactly one server, and falls back to the menu when the match is ambiguous or missing.

For a development install, from a clone:

```bash
uv sync
uv run bssh --help
```

Shell completion:

```bash
bssh --install-completion   # install for the current shell
bssh --show-completion      # preview without installing
```

### The SSH client

The tool shells out to the system SSH client, so one has to be present.

**Windows:**

The client is an optional part of the system. In Windows Settings, go to Apps and add the OpenSSH Client from the optional-feature list, or install it with winget:

```powershell
winget install --id Microsoft.OpenSSH.Client -e
```

**macOS:**

SSH client is pre-installed. If needed:

```bash
brew install openssh
```

**Linux:**

```bash
sudo apt install openssh-client     # Ubuntu, Debian
sudo dnf install openssh-clients    # Fedora, RHEL
sudo pacman -S openssh              # Arch
```

## What it does

- **Connect from a picker.** `bssh` opens a searchable menu of saved servers, ordered by pinned first, then most recently used, then most used, then name.
- **Connect with one word.** `bssh prod-db` goes straight through when the query names a single server.
- **Keep passwords.** Passwords are stored with the server and copied to the clipboard before the SSH client starts, so the password prompt is a paste.
- **Use a key or a certificate.** A private key path and a certificate path are stored per server and passed to OpenSSH. When a key is added interactively, the first of `~/.ssh/id_ed25519`, `id_rsa`, `id_ecdsa` or `id_dsa` that exists is offered as the default.
- **Encrypt the stored passwords.** Optional encryption keyed to the SSH private key, with a random per-installation salt. No master password is asked for.
- **Import the hosts you already have.** `bssh import-ssh-config` reads `~/.ssh/config` through `ssh -G`, so `Host *`, `Include`, and explicit `IdentityFile` and `CertificateFile` are reflected.
- **Export back to OpenSSH.** `bssh export-ssh-config` writes `Host` blocks that `ssh`, `scp`, `rsync`, `git` and IDEs read directly.
- **Chain through bastions.** A jump host is another saved server, referenced by name, with cycle detection and cascading cleanup.
- **Attach port forwards to the server.** Local `-L`, remote `-R` and dynamic SOCKS `-D` presets are stored with the profile and passed on every connect.
- **Push environment variables.** Per-server variables are sent with OpenSSH's `SetEnv`.
- **Forward X11.** `ssh -X` on the servers that need it.
- **Keep the connection alive.** An optional `ServerAliveInterval` per server, for hosts behind a NAT.
- **Run shell commands around the session.** A pre-connect and a post-connect hook per server, for a VPN, an SSO refresh, or a mount.
- **Transfer files.** `bssh put` and `bssh get` wrap `scp` and reuse the stored profile. `bssh sftp` opens a full interactive session.
- **Run one command on many hosts.** `bssh exec` runs it in parallel over every server a query matches, with a per-host prefix and a summary.
- **Check that a host is up.** `bssh ping` for one server, `bssh health` for all of them at once.
- **Organize.** Notes, tags, pins, a recents list, a filter that matches on name, host, user, tag, jump host or id prefix, and a detailed card per server.
- **Script it.** Every prompt has a flag, and every destructive operation has a non-interactive form and a meaningful exit code.
- **Run it on three operating systems.** Windows 10 and 11, macOS 10.15 and later, and Linux with Python 3.12. Every dependency is cross-platform, and the only external requirement is a system SSH client, which is usually already there on macOS and Linux.

### The command set

| Command | Alias | What it does |
| --- | --- | --- |
| `add` | `a` | Add a new server. |
| `connect` | `c` | Connect to a server. |
| `copy-pass` | `cp` | Copy password to clipboard. |
| `decrypt` | `dec` | Disable password encryption. |
| `edit` | `e` | Edit a server. |
| `encrypt` | `enc` | Enable password encryption. |
| `encryption-status` | `es` | Show encryption status. |
| `exec` | | Run a command on one or more servers in parallel. |
| `export` | `ex` | Export servers to JSON file. |
| `export-ssh-config` | `esc` | Export servers to SSH config. |
| `get` | | Download a remote file/dir (scp). |
| `health` | `h` | Check all servers availability. |
| `import` | `im` | Import servers from JSON file. |
| `import-ssh-config` | `isc` | Import hosts from SSH config. |
| `list` | `ls` | Show list of servers. |
| `pin` | | Pin a server to the top of lists. |
| `ping` | `p` | Check server availability. |
| `put` | | Upload a local file/dir (scp). |
| `recent` | `r` | Show recently used servers. |
| `remove` | `rm` | Remove a server. |
| `sftp` | | Open an interactive SFTP session. |
| `show-pass` | `sp` | Show password. |
| `unpin` | | Remove a server from pinned favorites. |
| `view` | `v` | Show a detailed card for a server. |

Most commands work without arguments and open an interactive menu. `bssh <command> --help` prints the full help for that command.

### Connecting

```bash
bssh                          # the picker
bssh prod-db                  # connect when the match is unique
bssh connect prod-db          # the same thing, spelled out
bssh connect prod-db --no-copy  # do not touch the clipboard
```

For a password-based host, `bssh` copies the saved password to the clipboard before starting OpenSSH. The password is not injected into the `ssh` command line; the SSH client asks for it and you paste it.

`bssh connect` exits with the exit code of the SSH client, and 130 when the session is interrupted with Ctrl+C. A connection that ends this way is recorded as a use, so it appears in `bssh recent`.

### Listing, pinning and recents

`bssh ls` prints a table. Its columns are ID, Pin, Name, Connection and Auth, plus Via, Alive, Fwd, Last used, Tags and Notes when at least one server has a value for them. The ID column shows the first 8 characters of the server id, Notes is cut at 40 characters and Tags at 30.

`bssh ls <query>` filters the table by substring against name, host, username, tags, jump host, and id prefix. Every field is matched case-insensitively, except the id prefix.

```bash
bssh ls prod          # matches name/host/user/tag/jump containing "prod"
bssh ls bastion       # surfaces both the bastion itself and everything routed through it
bssh ls a1b2          # id-prefix match
```

When nothing matches, the command prints a single friendly line instead of an empty table.

`bssh pin <query>` keeps a host above the normal ordering, and `bssh unpin <query>` takes it back out. A pinned host still sits in its own recent position in `bssh recent`.

`bssh recent` (alias `r`) lists servers by most-recently-connected, newest first, independent of pin status. `--limit N` and `-n N` cap the list, default 10. Servers that were never connected through `bssh` do not appear. The `Last used` column shows a relative timestamp: `just now`, `5m ago`, `2h ago`, `3d ago`, or an ISO date for anything older than 30 days. The same column appears in `bssh ls` once at least one server has a recorded connection.

`bssh view <name>` (alias `v`) renders a full card for one server in a panel. Nothing is cut short there: the complete note, the resolved jump chain, and the list of servers that use this one as their jump host. A broken jump-host reference is flagged in red instead of failing quietly.

### Finding a server

Every command that takes a `<query>` (`connect`, `edit`, `view`, `remove`, `pin`, `unpin`, `ping`, `put`, `get`, `copy-pass`, `show-pass`, `ls`, `exec`, `health`) resolves it the same way:

1. Exact server ID
2. Unique server-ID prefix
3. Exact name, case-insensitive
4. Unique broad match: a case-insensitive substring of the name, host, username, any tag, or the jump host

If step 4 finds more than one server, the command opens a picker over the candidates, the same set `bssh ls <query>` would print. If nothing matches at all, it reports that the server was not found.

`bssh ls <query>` and `bssh exec <query>` act on every matching server directly and skip the picker.

Names are unique, case-insensitively. Adding or renaming to a name that is already in use is refused with an error pointing at the existing entry.

### Adding and editing servers

`bssh add` asks for Name, Host, Port and Username, then walks through the optional fields. Binary and complex fields (SSH key, password, jump host, keep-alive, forwards, environment variables, pre and post hooks) use a y/N confirm before the value is asked for. Free-text fields (note, tags) use a direct prompt with "(Enter to skip)", so a stray keystroke does not turn into a yes-or-no question with the text lost.

Every field also has a flag, so the whole flow can be scripted. Pair it with `-s` and `--skip` to suppress the "Add SSH key?", "Add password?", "Use a jump host?" confirms. Any field not passed as a flag stays unset.

```bash
# Minimal non-interactive add:
bssh add --name prod-db --host 10.0.0.5 --username deploy -s

# With the full profile populated via flags:
bssh add \
  --name prod-db \
  --host 10.0.0.5 \
  --port 22 \
  --username deploy \
  --key ~/.ssh/prod_ed25519 \
  --certificate ~/.ssh/prod_ed25519-cert.pub \
  --jump bastion \
  --keep-alive 60 \
  --notes "main postgres" \
  -t prod -t db \
  -s
```

Without `-s`, `bssh add` drops into the interactive confirm sequence for any field you did not pre-populate, which is friendly for a person and inconvenient for an Ansible-style run.

| Flag | Short | Purpose |
| --- | --- | --- |
| `--key <path>` | | Path to SSH private key |
| `--certificate <path>` | | Path to SSH certificate |
| `--password <value>` | | Password (see the security note below) |
| `--jump <name>` | `-J` | Saved server name to use as ProxyJump (case-insensitive) |
| `--keep-alive <seconds>` | `-K` | `ServerAliveInterval` in seconds; `0` leaves it disabled |
| `--notes <text>` | | Free-form note attached to the server |
| `--tag <value>` | `-t` | Tag (repeatable: `-t prod -t db`) |
| `--local-forward <spec>` | `-L` | Local forward, repeatable: `[bind:]port:host:port` |
| `--remote-forward <spec>` | `-R` | Remote forward, repeatable: `[bind:]port:host:port` |
| `--dynamic-forward <spec>` | `-D` | Dynamic SOCKS forward, repeatable: `[bind:]port` |
| `--x11` | | Enable X11 forwarding (`ssh -X`) |
| `--env <K=V>` | `-e` | Environment variable pushed via `ssh -o SetEnv` (repeatable) |
| `--pre <cmd>` | | Shell command run locally BEFORE each connect (empty string clears) |
| `--post <cmd>` | | Shell command run locally AFTER each connect (empty string clears) |
| `--skip` | `-s` | Skip all interactive "Add X?" confirms (provisioning / scripts) |

Passing an empty string (`--key ""`, `--notes ""`) stores `None`, which lets a script clear a field on purpose.

A password passed with `--password` ends up in the shell history (`~/.bash_history`), in `/proc/<pid>/cmdline`, and in the output of process-listing tools. The interactive prompt is the safer route. The flag exists for provisioning scripts that read the value from a secret store at invocation time.

`bssh edit` takes the same flag set, plus `--name`, `--host`, `--port` and `--username` for in-place updates. By default the flags you pass are applied and the rest of the fields is reviewed interactively.

```bash
# Apply the listed fields, interactively review the rest
bssh edit prod --keep-alive 60 --notes "updated" -t prod -t eu

# Update one field, then interactively review the rest
bssh edit prod --host 10.0.0.9
```

With `-s` and `--skip`, the interactive review is skipped entirely: only the flags you pass are applied, and everything else is preserved verbatim.

```bash
# Clear just the pre-connect hook, no prompts
bssh edit prod --no-pre -s

# Update only the host, no prompts
bssh edit prod --host 10.0.0.9 -s
```

Empty-string clearing works as well: `--jump ""` drops the ProxyJump, `--notes ""` wipes the note. The dedicated `--no-pre`, `--no-post`, `--no-env` and `--no-forwards` flags do the same thing without quoting an empty string, which matters on PowerShell, where `--pre ""` is eaten before it reaches the CLI.

Boolean toggles use Typer's `--x11/--no-x11` syntax on `bssh edit`: pass `--x11` to enable, `--no-x11` to disable, or omit both to keep the current value.

`bssh rm` asks for confirmation, and `--yes` and `-y` skip it.

### Jump hosts

A jump host is another saved server, referenced by name. `bssh` resolves the chain and passes it to OpenSSH as `ProxyJump` (`-J`).

```bash
bssh add --name prod --host prod.example --username deploy --jump bastion
bssh add --name prod --host prod.example --username deploy -J bastion
```

The reference is matched case-insensitively, and the canonical spelling of the saved server is what gets stored. In the interactive picker, each candidate shows how many other servers already use it as a jump host.

- `bssh edit` always asks "Change jump host?" when one is set, with a `(none, direct connection)` choice first in the list.
- Renaming a server that others use as a jump host updates every referencing server in the same save.
- `bssh rm` warns when the target is used as a jump host and then asks whether to clear `jump_host` on the servers that depend on it. The default is yes, and declining aborts the removal.
- A cycle (`A` to `B` to `A`) and an unknown reference are refused at save time.
- `bssh isc` reads the `ProxyJump` directive and sets `jump_host` when the referenced target matches another imported alias, case-insensitively.

Three limits are worth knowing before a chain fails on a remote host:

- The credentials of a bastion are not forwarded into `ssh -J`. Only `user@host:port` is passed for each hop, and OpenSSH resolves the bastion credentials through its own mechanisms (`~/.ssh/config`, `ssh-agent`, default keys). A `key_path` or a `password` stored on the bastion entry in `bssh` is not used during a jump connection. Declare it with `IdentityFile` in `~/.ssh/config` or add it to `ssh-agent`.
- The password clipboard covers only the target. The bastion asks for its password separately.
- Multi-hop `ProxyJump h1,h2` specs and inline `user@host:port` specs in `~/.ssh/config` are skipped during the import. Only single-hop alias references to other imported hosts are kept. A longer chain is built by adding each bastion as its own server and chaining `jump_host` references.

### Port forwarding

Port-forward presets are stored per server and passed to OpenSSH on every connect.

| Type | Flag | Example | Meaning |
| --- | --- | --- | --- |
| Local | `-L` | `-L 5432:localhost:5432` | Forward local port 5432 to `localhost:5432` on the remote side, the usual way to tunnel a remote database to a laptop. |
| Remote | `-R` | `-R 9000:internal:9000` | Forward remote port 9000 back to `internal:9000` on the local network, the usual way to expose a local service to the remote host. |
| Dynamic | `-D` | `-D 1080` | Open a SOCKS proxy on local port 1080 that routes through the server. |

All three accept an optional bind address, for example `127.0.0.1:5432:localhost:5432`.

```bash
bssh add --name prod-db --host 10.0.0.5 --username deploy \
  -L 5432:localhost:5432 \
  -L 6379:redis-internal:6379 \
  -D 1080
```

Interactively, `bssh add` and `bssh edit` ask "Configure port forwards?". Answering yes opens a small loop where the type is chosen and a spec is entered, repeated until `(done)` is picked.

When editing an existing server:

- Passing any `-L`, `-R` or `-D` flag to `bssh edit` replaces the whole list, the same way `--tag` replaces the tags.
- `bssh edit <name> --no-forwards` clears all of them.
- Passing no forward-related flag keeps the existing list, and opens the interactive prompt when no other flag has put the command into non-interactive mode.

`bssh ls` shows a `Fwd` column with the count, hidden when nobody has any. `bssh view <name>` lists each forward on its own line.

### Environment variables

Per-server environment variables are pushed to every `bssh connect` with OpenSSH's `SetEnv`.

```bash
bssh add --name prod --host h --username u \
  -e LANG=en_US.UTF-8 \
  -e DEPLOY_ENV=prod \
  -s

bssh edit prod --env LANG=en_US.UTF-8  # replaces the whole env dict
bssh edit prod --no-env                # clears all env vars
bssh view prod                         # shows "Environment: LANG=..., DEPLOY_ENV=..."
```

- Each pair becomes a separate `-o SetEnv=KEY=VALUE` on the SSH command line.
- `SetEnv` (OpenSSH 7.8 and newer) pushes a literal value and does not need `AcceptEnv` on the remote `sshd`. Older servers drop unknown environment variables without a word.
- Passing any `--env` to `bssh edit` replaces the stored dictionary, the same way `--tag` replaces the tags. `--no-env` clears it.
- An empty value is allowed (`--env FOO=`), which is useful for unsetting an inherited pattern. A value may contain `=`, because the pair is split on the first one only.

### X11 forwarding

Set X11 forwarding on a server and `bssh connect` passes `-X` to OpenSSH. GUI applications started on the remote side try to render through the local display.

```bash
bssh add --name workstation --host ws.example --username dev --x11
bssh edit workstation --x11       # turn on
bssh edit workstation --no-x11    # turn off
bssh view workstation             # shows "X11: enabled (ssh -X)" row when on
```

On the client side:

- **Linux** usually has an X11 display already running, and nothing extra to install.
- **macOS** needs [XQuartz](https://www.xquartz.org/). Install it and log out and in once, so that `$DISPLAY` is set.
- **Windows** needs an X server: VcXsrv, Xming, or WSLg on Windows 11. Without one, OpenSSH logs `X11 forwarding request failed` and the GUI applications fail with `Can't open display`.

`bssh` emits `-X`, the untrusted mode, which is the safer default. Some X11 applications, an older `xterm` or certain Matplotlib backends, fail under the X11 SECURITY extension and need the trusted mode `-Y`. When `BadAccess` or `SECURITY` errors show up, enable `ForwardX11Trusted yes` for that host in `~/.ssh/config`; the `-X` that `bssh` emits composes with the SSH config, so the directive takes effect.

### Pre- and post-connect hooks

Two optional per-server shell commands run locally around every `bssh connect`. The usual reasons are bringing up a corporate VPN, refreshing an AWS SSO token, mounting `sshfs`, posting to Slack, or writing an audit log.

```bash
# Bring a VPN up before each connect, tear it down after:
bssh edit prod-db --pre "openvpn-connect corp" --post "openvpn-disconnect corp"

# Refresh SSO credentials before each connect:
bssh edit prod --pre "aws sso login --profile prod"

# Mount a remote filesystem alongside the interactive session:
bssh edit dev --pre "sshfs dev:/srv ~/remote-dev" --post "fusermount -u ~/remote-dev"

# Clear both:
bssh edit prod --no-pre --no-post          # explicit clear
bssh edit prod --pre "" --post ""          # empty-string form works too
```

- The pre hook runs before SSH and is a prerequisite. A non-zero exit aborts the connect with the hook's exit code, and the SSH client is never started. The post hook does not run in that case.
- The post hook always runs once the pre hook has succeeded, or when there was no pre hook: after a successful session, after Ctrl+C (exit code 130), after an authentication failure, and after a configuration error such as a broken jump-host reference where SSH was never launched. That is where cleanup belongs, and the setup-then-teardown contract holds even when SSH itself never starts. A non-zero post exit is reported as a yellow warning and does not override the final exit code.
- The commands run through the platform shell, `sh -c` on POSIX and `cmd.exe /c` on Windows, so pipes, redirects and environment variable expansion all work.
- The hooks apply to `bssh connect` and to the interactive `bssh <query>` shortcut. `bssh exec`, `bssh put` and `bssh get` deliberately do not run them, because running a hook per host in a non-interactive flow would surprise.

The commands run on the local machine, with the local shell and the local privileges. A `servers.json` from an untrusted source can carry a hostile pre or post hook, so an imported configuration is worth reading before it is allowed to run.

### File transfer

`bssh put` uploads and `bssh get` downloads. Both use `scp` and compose with the server's stored profile: port, key, certificate, jump host and keep-alive.

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

| Flag | Short | Purpose |
| --- | --- | --- |
| `--recursive` | `-r` | Recurse into directories (scp `-r`) |
| `--compress` | `-C` | Enable scp compression |
| `--preserve` | `-p` | Preserve modification times, access times, and modes (scp `-p`) |

- Port forwards and X11 on the server profile are not applied to a transfer. They are connection-only settings.
- The password prompt comes from OpenSSH itself. The clipboard copy is wired into `bssh connect` and `bssh sftp` only, not into `put` and `get`.
- The ProxyJump chain is the server's stored `jump_host` chain, the same one `connect` uses.
- `scp` has to be on PATH. It ships with the OpenSSH client tools, and a missing binary exits with code 127.

### Interactive SFTP session

`bssh put` and `bssh get` work when the remote path is known. When it is not, `bssh sftp` opens a full SFTP session.

```bash
bssh sftp                    # pick from the interactive menu
bssh sftp prod-db            # go straight to this server
bssh sftp prod-db --no-copy  # skip the password-to-clipboard copy
```

Then the SFTP prompt is yours:

```text
sftp> cd /var/log
sftp> ls -la
sftp> get app.log
sftp> put ./local-patch.sh /tmp/
sftp> bye
```

The session reuses the full profile, port, key, certificate, jump-host chain and keep-alive, and it honors the same pre and post hooks that `bssh connect` honors. A VPN-up hook, an `aws sso login` refresh, or an `sshfs` mount configured for a server runs here too. Forwards, X11 and `SetEnv` are connection-oriented and do not apply to a file-transfer session.

`sftp` has to be on PATH. It ships with the OpenSSH client package, and a missing binary exits with code 127.

### Parallel command broadcast

`bssh exec` runs one shell command on every server a query matches, in parallel, with a per-host colored prefix on each output line and an aggregated summary at the end.

```bash
bssh exec "uptime" prod           # every server matched by the 'prod' query
bssh exec "df -h /" --all         # every saved server
bssh exec "systemctl is-active nginx" web --timeout 15
```

The query matches the same fields as `bssh ls`: name, host, username, tag, id prefix or jump host. `--all` skips the filter.

| Flag | Purpose | Default |
| --- | --- | --- |
| `--all` | Run on every saved server instead of filtering | off |
| `--timeout <seconds>` | Per-host overall timeout (the remote command is killed after it) | 30 |
| `--connect-timeout <seconds>` | TCP connect timeout (`ssh -o ConnectTimeout`) | 10 |

Each host's standard output lines are tagged with `[<name>]` in its own color, the error lines are red, and a `(<duration>, ok)` or `(<duration>, exit N)` status line closes the output of each host. The summary reports how many hosts succeeded, for example `Summary: 8/10 ok in 2.3s`. The exit code is 0 only when every host returned 0 without a connection-level error.

Three caveats:

- The runs use `ssh -o BatchMode=yes`, so a password prompt never interleaves with a parallel sweep. A password-only server fails fast with a clear authentication error. Use key or certificate authentication, or `ssh-agent`, for `exec`.
- Port forwards and X11 on the server profile are ignored, since they belong to an interactive connection.
- There is no concurrency cap in this version. Every matched server gets its own `ssh` process, which is fine up to the low hundreds of hosts.

### Availability checks

`bssh ping <query>` opens a TCP connection to the SSH port of one server and reports the result with the round-trip time in milliseconds. The probe times out after 3 seconds.

`bssh health` probes every saved server at the same time, with a per-server probe timeout of 5 seconds by default and `--timeout` to change it. The whole scan takes about the timeout rather than the timeout times the number of servers. The table is sorted by name, and the command exits with 1 when at least one server is unreachable.

### Import and export

`bssh import-ssh-config` reads the hosts from an OpenSSH config file, and `~/.ssh/config` by default.

```bash
bssh isc
bssh isc ~/.ssh/work-config
```

The importer resolves each host through `ssh -G`, so `Host *`, `Include`, an explicit `IdentityFile` and an explicit `CertificateFile` are all reflected in the imported entries. The default OpenSSH keys stay implicit: a host that works with a plain `ssh host` because of the default keys or `ssh-agent` keeps working that way, and no key path is pinned unless the SSH config says so explicitly.

`bssh import` and `bssh isc` both ask how to reconcile when servers already exist locally: keep what is there and add the new ones (merge), or wipe everything and replace it. Flags pick the mode in a script.

```bash
# Interactive: mode picker + explicit safety confirm naming the counts
bssh import backup.json
bssh isc

# Non-interactive: pre-pick the mode
bssh import backup.json --merge
bssh isc --replace

# CI / scripted (skip the safety prompt entirely):
bssh import backup.json --replace --yes    # WIPES everything and imports
bssh isc --merge -y
```

The safety confirmation spells the destructive action out with counts: `DELETE all 12 existing server(s) and import 3 from 'backup.json'?`, so a reflex `y` cannot wipe the store. Passing `--merge` and `--replace` together is rejected with exit code 2.

`bssh export <file>` writes the servers to a JSON file. When encryption is on and some servers have passwords, the export asks whether the passwords go out in plaintext or stay encrypted. The plaintext form is for a move to another machine, the encrypted form only works on the machine that has the key and the salt.

`bssh export-ssh-config` (alias `esc`) does the opposite of the import. It turns every saved server into `Host` blocks:

```bash
bssh export-ssh-config ~/.ssh/config.bssh
bssh esc ~/.ssh/config.d/bssh.conf
```

Each block carries the fields that have an `ssh_config` equivalent:

- `HostName`, `User`, and `Port` when it is not 22
- `IdentityFile`, `CertificateFile`
- `ProxyJump`
- `ServerAliveInterval` and `ServerAliveCountMax 3` when the keep-alive is set
- `ForwardX11 yes` when X11 is enabled
- `LocalForward`, `RemoteForward` and `DynamicForward`, one line per forward, with the bind host preserved

The fields that have no `ssh_config` syntax, the password, the tags and the notes, are written as leading comments, so the context survives for whoever opens the file later.

Activate the exported file by adding

```text
Include ~/.ssh/config.bssh
```

to `~/.ssh/config`, or by passing `-F ~/.ssh/config.bssh` to `ssh` directly. Overwriting an existing file asks for confirmation, and `-f` and `--force` skip the prompt for scripts and CI. The exit code is 0 when the file was written and 1 when the overwrite was declined, so a pipeline can tell the two apart.

## How it works

```
CLI command
  -> storage.load_servers()      read servers.json, decrypt the passwords
  -> domain / storage.find_server()  resolve the query to one server
  -> ssh.connect()               build the ssh argv, run it
  -> storage.record_server_use() count the use, stamp the time, save
```

The package is `app/`, and the command layer is split by subject.

| Path | What it holds |
| --- | --- |
| `app/models.py` | The Pydantic `Server` model and the `Forward` model, with the rendering of a forward as an OpenSSH spec. |
| `app/domain.py` | Pure logic: sorting, the query matcher, tag and env parsing, name uniqueness, the jump-chain walk. No I/O, no Typer, no Rich. |
| `app/storage.py` | The JSON store, and the transparent encrypt-on-save and decrypt-on-load layer over it. |
| `app/encryption.py` | Fernet and the PBKDF2 key derivation from an SSH key. |
| `app/ssh.py` | The OpenSSH command construction, the jump resolution, the pre and post hooks, and the availability probe. |
| `app/ssh_config.py` | The `~/.ssh/config` importer, through `ssh -G`, and the renderer that writes `Host` blocks back out. |
| `app/cli/` | The Typer application, split into one module per subject. |

A few decisions are visible in the code and worth knowing before changing it.

**The tool never speaks the SSH protocol.** It builds an argument list and runs `ssh`, `sftp` or `scp`. The command it is about to run is printed first, so the user can see it. Whatever `~/.ssh/config` says still applies, because the tool adds options rather than replacing them.

**The option order is fixed.** The `ssh` command line is built as port, keep-alive, forwards, environment, X11, jump host, key, certificate, and finally the target. The environment variables keep their insertion order, so the same server always produces the same command line.

**The jump chain excludes the target.** `resolve_jump_chain` walks `jump_host` references and returns the hops in the order OpenSSH expects for `-J`, and raises on a cycle or an unknown reference.

**The pre and post hooks are committed to each other.** Once the pre hook has succeeded, the post hook runs on every exit path, including a configuration error and a Ctrl+C. The code says so in a comment above the `try` block, and the contract is that setup implies teardown.

**The query grammar is one grammar.** `storage.find_server` and `domain.servers_matching_query` are aligned on purpose, so that `bssh connect prod` and `bssh ls prod` agree about what "prod" means.

**The store is plain JSON.** `servers.json` holds the servers and the encrypted passwords, `settings.json` holds the encryption flag, the key source and the salt. The file is written with the servers in the order they are saved, and the tables are sorted at display time.

**The tables hide what is empty.** A column appears only when at least one server has a value for it, so a small store prints a small table.

## Configuration

The configuration lives in a platform-specific directory.

| Platform | Path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\better-ssh\` |
| macOS | `~/Library/Application Support/better-ssh/` |
| Linux | `~/.config/better-ssh/` |

Two files are there:

- `servers.json` holds the server configurations and the encrypted passwords.
- `settings.json` holds the application settings: the encryption status, the key source and the salt.

### Password encryption

By default, passwords are stored in plaintext. The application can encrypt them, using the SSH private key as the source of the key material.

```bash
bssh es            # check encryption status
bssh enc           # enable encryption (interactive)
bssh dec           # disable encryption (interactive)

# For scripts / CI, skip the "are you sure?" prompt:
bssh enc -y
bssh dec -y
```

The key derivation is PBKDF2-HMAC-SHA256 over the content of the SSH private key, with 100,000 iterations and a random 32-byte salt that is created once per installation and kept in `settings.json`. The passwords themselves are encrypted with Fernet and stored base64-encoded. The key is looked for as `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`.

Passwords are encrypted on save and decrypted on load, so the rest of the application never sees a ciphertext. When the export runs, it asks whether the passwords go out in plaintext or stay encrypted.

Four things to know before turning it on:

- **The key is the key.** Delete or change the SSH key and the encrypted passwords cannot be read any more.
- **The machine is part of it.** Decryption needs the same SSH key and the same salt, on the same machine.
- **Back up both.** The SSH key and `settings.json` are what make the store readable.
- **It is automatic.** There is nothing to remember for daily use.

What this buys:

- The passwords stay protected when `servers.json` is copied or leaked.
- No master password is asked for on every run.
- The SSH key is already protected by the file permissions of the operating system.
- The random per-installation salt stops a precomputed attack against the key.

## Development

```bash
uv sync                 # install the dependencies, including the dev group
uv run bssh --help      # run the tool from the checkout
uv run pytest           # run the tests
uv run ruff check app tests       # lint
uv run ruff format app tests      # format
uv run pre-commit install         # install the git hooks
```

`uv run pytest` runs the nine test files under `tests/`, with branch coverage reported by default. The CI workflow runs the same commands on Ubuntu, Windows and macOS with Python 3.12, uploads the coverage to Codecov, and lints the Markdown files with markdownlint.

The code follows PEP 8, with type hints on every signature, a docstring on every public function and class, and a 120-character line limit set in `.ruff.toml`.

| Path | What it holds |
| --- | --- |
| `app/models.py` | The Pydantic `Server` model. |
| `app/domain.py` | Pure logic: sorting, filtering, validation, tag parsing, jump-chain walking. |
| `app/storage.py` | The JSON file I/O and the transparent encryption layering. |
| `app/encryption.py` | Fernet and the PBKDF2 key derivation from an SSH key. |
| `app/ssh.py` | The OpenSSH command construction, the jump resolution, the availability check. |
| `app/ssh_config.py` | The `~/.ssh/config` importer, through `ssh -G`. |
| `app/cli/__init__.py` | The package entry point. It builds the Typer app and re-exports the names the tests patch. |
| `app/cli/_shared.py` | The Typer app instance, the console, the pickers and the common helpers. |
| `app/cli/connection.py` | `connect`, `copy-pass`, `show-pass`, and the root callback. |
| `app/cli/manage.py` | `add`, `edit`, `remove`, `view`. |
| `app/cli/organize.py` | `list`, `pin`, `unpin`, `recent`. |
| `app/cli/crypto.py` | `encrypt`, `decrypt`, `encryption-status`. |
| `app/cli/backup.py` | `export`, `import`, `import-ssh-config`, `export-ssh-config`. |
| `app/cli/health.py` | `ping`, `health`. |
| `app/cli/transfer.py` | `put`, `get`, `sftp`, the `scp` wrappers. |
| `app/cli/exec_cmd.py` | `exec`, the parallel broadcast. |
| `tests/` | The test suite, one file per module. |
| `docs/` | The landing page, a static HTML file with its stylesheet. |

`docs/` is published to GitHub Pages on every push that touches it, and the page lives at <https://aa-blinov.github.io/better-ssh/>.

Contributions are welcome. The process, the code standards and the checklist for a pull request are in [CONTRIBUTING.md](CONTRIBUTING.md), and the history of the releases is in [CHANGELOG.md](CHANGELOG.md).

## License

MIT, © 2025 Alexander Blinov. See [LICENSE](LICENSE).
