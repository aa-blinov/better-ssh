# Architecture

How `better-ssh` is put together.

## The shape

The tool is a Python package, `app/`, with a Typer front end over a JSON
store. It never speaks the SSH protocol: it builds an argument list and runs
the `ssh`, `sftp` and `scp` binaries that are already on the machine.

```
CLI command
  -> storage.load_servers()            read servers.json, decrypt the passwords
  -> domain / storage.find_server()    resolve the query to one server
  -> ssh.connect()                     build the ssh argv, run it
  -> storage.record_server_use()       count the use, stamp the time, save
```

The command layer is split by subject, one module per group of commands,
and every module talks to the same three layers below it.

| Module | What it is responsible for |
| --- | --- |
| `app/models.py` | The Pydantic `Server` and `Forward` models, and the rendering of a forward as an OpenSSH spec. |
| `app/domain.py` | Pure logic: sorting, the query matcher, tag and env parsing, name uniqueness, the jump-chain walk. No I/O, no Typer, no Rich. |
| `app/storage.py` | The JSON store, the `find_server` match order, and the transparent encrypt-on-save and decrypt-on-load layer. |
| `app/encryption.py` | Fernet, and the PBKDF2-HMAC-SHA256 derivation from the SSH key file. |
| `app/ssh.py` | The `ssh` and `sftp` command construction, the jump resolution, the pre and post hooks, the TCP availability probe. |
| `app/ssh_config.py` | The `~/.ssh/config` importer, through `ssh -G`, and the renderer that writes `Host` blocks back out. |
| `app/cli/__init__.py` | The package entry point. It imports every command module so the decorators run, and re-exports the names the tests patch. |
| `app/cli/_shared.py` | The Typer app instance, the Rich console, the pickers, the server table, the merge helper. |
| `app/cli/connection.py` | `connect`, `copy-pass`, `show-pass`, and the root callback that opens the picker when there is no subcommand. |
| `app/cli/manage.py` | `add`, `edit`, `remove`, `view`. The largest module, and the one with most of the prompting logic. |
| `app/cli/organize.py` | `list`, `pin`, `unpin`, `recent`. |
| `app/cli/crypto.py` | `encrypt`, `decrypt`, `encryption-status`. |
| `app/cli/backup.py` | `export`, `import`, `import-ssh-config`, `export-ssh-config`. |
| `app/cli/health.py` | `ping`, `health`. |
| `app/cli/transfer.py` | `put`, `get`, `sftp`, the `scp` wrappers. |
| `app/cli/exec_cmd.py` | `exec`, the parallel broadcast. |
| `tests/` | The suite: nine files, one per module, plus `conftest.py` with the shared fixtures. |

## The data flow

A connection is the shortest path through the package, and every other
command is a variation on it.

```
servers.json
  |  storage.load_servers(): parse, validate, decrypt the passwords
  v
[Server, Server, ...]
  |  storage.find_server(query): id, id prefix, exact name, broad match
  v
one Server
  |  ssh.connect(): resolve the jump chain, build the argv, copy the password
  v
ssh user@host
  |  storage.record_server_use(): use_count += 1, last_used_at = now
  v
servers.json
```

The store holds the servers in the order they were saved. Sorting happens at
display time, in `domain.sort_servers`, so the file on disk stays in the
order the user built it and a diff of the file means something.

The two files live in the platform's configuration directory, resolved
through `platformdirs`: `%LOCALAPPDATA%\better-ssh\` on Windows,
`~/Library/Application Support/better-ssh/` on macOS and
`~/.config/better-ssh/` on Linux. `servers.json` holds the servers and the
encrypted passwords. `settings.json` holds the encryption flag, the key
source and the salt.

## Decisions worth knowing about

### The tool runs the system client

There is no SSH library in the dependency list. The tool builds an argument
list and calls `ssh`, `sftp` or `scp`, and it prints the command before it
runs it. The cost is that the tool can only do what OpenSSH's command line
can do, and that the user's own `~/.ssh/config` still applies, because the
tool adds options rather than replacing them.

### The option order on the command line is fixed

The `ssh` argv is assembled as port, keep-alive, forwards, environment, X11,
jump host, key, certificate, and the target. The environment pairs keep
their insertion order, so the same server always produces the same command
line, and a screenshot of one session can be compared with another.

### The jump chain excludes the target

`ssh.resolve_jump_chain` walks the `jump_host` references and returns the
hops in the order OpenSSH expects for `-J`, without the server itself. It
raises on a cycle and on an unknown reference, and the caller turns that
into a red message and exit code 1 without starting `ssh`.

### The pre hook commits the post hook

Once the pre-connect hook has succeeded, the post-connect hook runs on every
exit path: a successful session, a Ctrl+C, an authentication failure, and a
configuration error where `ssh` was never launched. The body of `connect`
is wrapped in a `try` / `finally` for that reason. The contract is that setup
implies teardown, and an early return that escapes the `try` block breaks
it.

### The query grammar is one grammar

`storage.find_server` and `domain.servers_matching_query` are aligned on
purpose, so `bssh connect prod` and `bssh ls prod` agree about what "prod"
means. A query is matched in four steps: an exact id, a unique id prefix, an
exact name, and then a broad substring match over the name, the host, the
username, the tags and the jump host. A broad match that finds more than one
server returns nothing, and the command opens a picker over the candidates
instead of failing.

### The importer asks OpenSSH

`app/ssh_config.py` reads the config file to collect the aliases, and then
resolves each one with `ssh -G`. It runs that command twice, once against
the user's config and once against an empty temporary config, and the
difference between the two results is how an explicit `IdentityFile` is told
apart from a default one. The cost is that an import of many hosts is slow.

### Encryption is keyed to the SSH key

The key material comes from `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`, run
through PBKDF2-HMAC-SHA256 with 100,000 iterations and a random 32-byte
salt that is created once per installation. Fernet encrypts the passwords,
which are stored base64-encoded. The salt lives in `settings.json` and the
key material lives in the SSH key file, so losing either one makes the
stored passwords unreadable.

## Boundaries

- **`app/domain.py` does no I/O.** It imports neither Typer, nor Rich, nor
  InquirerPy, and it touches neither the filesystem nor the standard
  streams. That is what makes the validators testable in isolation.
- **`app/models.py` holds no behaviour beyond rendering.** The models carry
  the fields and the two functions that turn a model into text.
- **`app/cli/` owns the prompt.** Every question the user is asked is asked
  in the command layer. The layers below never call `typer.prompt` and never
  print.
- **`app/ssh.py` owns the exit code.** The command layer passes the code
  through with `typer.Exit(rc)` and does not reinterpret it.
- **The command layer does not reach around the layers below.** A command
  reads the store through `storage` and builds a command line through
  `ssh`; it does not write JSON itself and does not assemble an `ssh` argv
  itself.
- **A new command module has to be imported in `app/cli/__init__.py`.** The
  `@app.command` decorators run at import time, so a module that is never
  imported registers nothing.
