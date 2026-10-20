# Product

<!-- impeccable:product-schema 1 -->

## Platform

cli

A terminal application. Python 3.12 or higher, built on Typer for the command surface and Rich for the tables, the panels and the pickers, with a Pydantic model for the stored server records. It runs on Windows 10 and 11, on macOS 10.15 and later, and on Linux.

The application does not implement SSH. It builds an argument list and runs the system `ssh`, `sftp` and `scp`, so the OpenSSH client has to be on PATH. The dependency is the reason the tool behaves the same on three operating systems, and the reason a user's own `~/.ssh/config` keeps working.

A static landing page lives in `docs/` and is published to GitHub Pages. It is a separate artifact from the tool, and it is the only part of the project that a browser sees.

## Users

The people who already use SSH several times a day and have run out of ways to remember the command. The landing page names four groups:

- developers who juggle dev, staging and prod across several clients or VPS providers
- SREs who manage a fleet of tens to low hundreds of hosts
- anyone whose `~/.ssh/config` is longer than their `~/.bashrc`
- anyone who still pastes passwords out of a password manager into a terminal

The job is the same for all of them: reach a known host, with a known jump chain and a known set of options, without retyping the command and without keeping a scratchpad of the pieces. The groups differ in the number of hosts and in how many times a day the tool is opened.

There is no second audience yet. The project is at version 0.3.0, marked Beta, and there is no download count to report. The README also names the case where the tool is the wrong answer: three servers and the commands already in muscle memory, where plain `ssh` is the right tool.

## Product Purpose

The tool stores a per-server profile and turns it into an OpenSSH command line. The profile holds the host, the port, the user, the key and certificate paths, the password, the jump host, the port forwards, the environment variables, the X11 flag, the keep-alive interval, the notes, the tags and the two hooks. Everything the connection needs is on the record.

The shortest path is one word. `bssh` opens the picker, `bssh prod-db` connects when the name is unique. Everything else, the flags, the import, the export, the broadcast, exists so that this path stays short and so that the failures stay visible.

Success for the user: the session opens without retyping, and the password is already in the clipboard when the prompt appears. Success for the product: the store stays readable in both directions, because `bssh isc` reads the OpenSSH config that already exists and `bssh esc` writes it back as `Host` blocks that the rest of the toolchain reads.

## Positioning

Plain `ssh` stores the connection in `~/.ssh/config` and leaves the rest of the workflow to the person. A jump chain has to be remembered, a port forward has to be rebuilt, a password has to be fetched from somewhere else, and the shell history fills with the fragments of last week's command. The tool takes the profile as the unit and keeps the rest of the arguments with it.

A password manager is a different tool with a different job. The password here belongs to a host, and it is stored next to that host, encrypted with a key the machine already has. There is no vault, no account and no sync.

An SSH client with a window is a different tool as well. This one stays in the terminal, keeps the system's `ssh`, `sftp` and `scp`, and lets the user's own `~/.ssh/config` do what it already does.

The part a neighbour would have to build to compete is the round trip. The store is plain JSON, and the schema is not a secret, but `isc` and `esc` are what let the tool be a layer on top of OpenSSH rather than a replacement for it. A competitor that can only import is a one-way trip, and a competitor that can only export is a scratchpad with extra steps.

## Operating Context

The tool is run from a terminal, often dozens of times a day, usually while something else is going on. The picker has to open fast and be usable with the keyboard alone, because the person is in another window, in another application, and mid-task.

The person is often in another window when the password prompt arrives. The clipboard is filled before the SSH client starts, not after, because after the handover the tool no longer has the terminal. The paste is the last thing the person does.

The tool runs on the local machine, with the local privileges and the local shell. That is what makes a pre-connect hook able to bring up a VPN, refresh an AWS SSO token or mount `sshfs`, and what makes an imported `servers.json` a risk that the README warns about.

The remote side is a fleet of unknown `sshd` versions and unknown configurations. The tool emits conservative options for that reason: `SetEnv` needs OpenSSH 7.8 or newer, X11 is the untrusted `-X` mode by default, and `exec` refuses to prompt with `BatchMode=yes`.

## Capabilities and Constraints

Confirmed by the code:

- Twenty-four commands, reachable through two entry points, `bssh` and `better-ssh`, which behave identically.
- An interactive picker over the saved servers, ordered by pinned, then most recent, then most used, then name.
- A single query grammar for every command that takes one: exact id, unique id prefix, exact name, then a unique broad match over name, host, username, tags and jump host.
- Password storage with optional encryption: Fernet over a key derived from the SSH private key with PBKDF2-HMAC-SHA256, 100,000 iterations, and a random 32-byte salt created once per installation.
- The password reaches the clipboard before the SSH client starts, for `connect` and for `sftp`.
- ProxyJump chains of saved servers, with cycle detection at save time, a cascade when a bastion is renamed, and a cleanup when one is removed.
- Per-server port forwards (`-L`, `-R`, `-D`), X11 forwarding (`-X`), environment variables (`SetEnv`), a keep-alive (`ServerAliveInterval` and `ServerAliveCountMax 3`), and two local hooks.
- File transfer with `scp` through `put` and `get`, and an interactive `sftp` session.
- A parallel broadcast, `exec`, with a per-host prefix and a summary, and a parallel availability probe, `health`.
- A round trip with the OpenSSH config: `isc` resolves every host through `ssh -G`, `esc` writes `Host` blocks back.
- A non-interactive form for every prompt, and an exit code that says what happened: 0, 1, 2, 124, 127, 130.

Deliberately not true, and worth knowing before a change:

- The tool does not speak the SSH protocol, and a bastion's stored key or password is not forwarded into `ssh -J`.
- The password clipboard covers the target only. A bastion asks for its password separately.
- `exec` runs with `BatchMode=yes`, so a password-only host fails fast instead of prompting.
- Port forwards, X11 and `SetEnv` are not applied to a transfer or to `exec`. They belong to an interactive session.
- `exec` has no concurrency cap. Every matched server gets its own `ssh` process.
- A multi-hop `ProxyJump h1,h2` or an inline `user@host:port` in `~/.ssh/config` is skipped on import.
- The store is a plain JSON file, and the encryption is bound to one machine, one SSH key and one salt.
- There is no account, no sync, no team sharing and no remote store.

## Brand Commitments

**Name:** better-ssh. **Tagline:** "Remember your servers, not their arguments." The name says what the tool is, a layer over SSH, and the tagline says what it does with the arguments.

**Voice:** plain and technical. The interface speaks in short sentences about the machine it is on and the host it is reaching. It says "port closed" rather than "unreachable", and "Password could not be decrypted. SSH key may be missing or changed." rather than anything reassuring.

**The command is shown before it runs.** Every session prints the argument list it is about to execute, so nothing about the connection is a surprise. This is the commitment that keeps the tool trustworthy when the command line grows long.

**The exit code is part of the promise.** A declined overwrite is 1, a misused flag combination is 2, a missing binary is 127. Scripts are allowed to depend on these.

**A destructive action names its cost.** The confirmation before a replace import reads "DELETE all 12 existing server(s) and import 3 from 'backup.json'?", with the counts in it.

## Evidence on Hand

- `README.md` is the reference manual, and it carries the command table, the flag tables and the known limitations.
- `docs/index.html` is the landing page, with the before-and-after comparison and the list of who the tool is for.
- `CHANGELOG.md` records 0.2.0 and 0.3.0, and the 0.2.0 entry has a section of known limitations of its own.
- `app/` is the implementation: six core modules and a `cli/` package of eight command modules, from the Pydantic model to the `scp` wrapper.
- The test suite is nine files and 378 tests, run in CI on Ubuntu, Windows and macOS, with the coverage uploaded to Codecov.
- `pyproject.toml` pins the runtime dependencies: typer, rich, platformdirs, pydantic, inquirerpy, pyperclip, cryptography.

Absent, and not to be invented: no download counts, no install numbers, no user testimonials, no benchmark against another tool, and no comparison with a named product. The project is a public beta with no count to publish, and the comparisons in the landing page are between the tool and the manual alternative, not between two products.

## Product Principles

1. **Show the command.** The argument list is printed before it is executed, and the exit code is meaningful. A user who reads the output can reconstruct what happened.
2. **The profile is the unit.** Everything a connection needs lives on the server record, and the record travels with the server to every command that uses it: connect, transfer, broadcast, probe.
3. **One grammar for a query.** The same string means the same thing to every command, and the same fields decide what matches. `bssh connect prod` and `bssh ls prod` never disagree.
4. **Every prompt has a flag.** An operation that can be done by a person can be done by a script, and the script gets the same result and a meaningful exit code.
5. **Never write a secret to disk in the clear by accident.** A failure of the encryption path is a loud failure, not a silent downgrade to plaintext.

## Accessibility & Inclusion

- **The interface is the keyboard.** The pickers are arrow-key driven, with type-to-filter and a cycling selection, and a command that needs a choice does not need a pointer.
- **The terminal is handed over cleanly.** The tool prints its lines and then gives the terminal to OpenSSH, so a screen reader that is following the session sees the connection output and not a redrawn table.
- **Colour carries meaning in places, and nothing else does.** The broadcast gives each host one of eight colours, and the tables colour the status. The text of every status is written out, so the colour is a second signal rather than the only one.
- **No colour-blind palette and no `--no-color` switch.** Neither is in the code, and the colours come from Rich's default theme. Whether the tool needs one is not decided.
- **No screen-reader run has been recorded.** The output is plain lines, which is what a screen reader reads, but nothing in the repository shows that a session was tested with one.
- **A contrast standard has not been set** for the terminal output, and the landing page has no accessibility statement.

## Open questions

The code and the existing documents do not answer these, and they are not guessed here:

- Whether the tool is meant to grow a shared or remote store, or whether a local JSON file is the intended end state.
- Whether the pre and post hooks should be sandboxed, or whether running them with the user's shell and privileges is the accepted trade.
- What the accessibility expectations are for a terminal application, and whether the landing page needs an accessibility statement of its own.
- Who the maintainers of the project are beyond its author, and how contributions are reviewed.
