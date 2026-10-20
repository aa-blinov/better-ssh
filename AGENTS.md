# AGENTS.md — agent context for `better-ssh`

A command-line tool that stores SSH servers and drives the system `ssh`, `sftp` and `scp` binaries. It is a Python package (`app/`) with a Typer front end, a JSON store, and optional password encryption keyed to the user's SSH private key. This file is what you need to work on the project without reading all of it.

## Run / build / test

```bash
uv sync                        # install the runtime dependencies and the dev group
uv run bssh --help             # run the tool from the checkout
uv run pytest                  # the test suite, nine files, with branch coverage
uv run pytest tests/test_ssh.py -k jump   # one file, one topic
uv run ruff check app tests    # lint, the same command CI runs
uv run ruff format app tests   # format
uv run pre-commit install      # the git hooks: ruff, trailing whitespace, EOF, yaml, toml
uv build                       # the wheel and the sdist, built by hatchling
```

Python 3.12 or higher, `uv`, and an OpenSSH client on PATH. There is no build step for the application itself; `uv build` produces the distribution.

CI runs the linter, the formatter check and the tests on Ubuntu, Windows and macOS with Python 3.12, then uploads the coverage to Codecov. The `tests.yml` workflow also lints every Markdown file with markdownlint, with `continue-on-error: true`, so a Markdown warning does not fail the build.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/models.py` | The Pydantic `Server` model, the `Forward` model, and the rendering of a forward as an OpenSSH spec. |
| `app/domain.py` | Pure logic: sorting, the query matcher, tag and env parsing, name uniqueness, the jump-chain walk. No I/O, no Typer, no Rich, no InquirerPy. |
| `app/storage.py` | The JSON store, the `find_server` match order, and the transparent encrypt-on-save / decrypt-on-load layer. |
| `app/encryption.py` | Fernet and the PBKDF2-HMAC-SHA256 derivation from the SSH key file. |
| `app/ssh.py` | The `ssh` and `sftp` command construction, the jump resolution, the pre and post hooks, the TCP availability probe. |
| `app/ssh_config.py` | The `~/.ssh/config` importer, through `ssh -G`, and the renderer that writes `Host` blocks back out. |
| `app/cli/__init__.py` | The package entry point. It imports every command module so the `@app.command` decorators run, and it re-exports the names the tests patch. |
| `app/cli/_shared.py` | The Typer app instance, the Rich console, the pickers, the server table, the merge helper. |
| `app/cli/connection.py` | `connect`, `copy-pass`, `show-pass`, and the root callback that opens the picker when there is no subcommand. |
| `app/cli/manage.py` | `add`, `edit`, `remove`, `view`. The biggest module, and the one with the most prompting logic. |
| `app/cli/organize.py` | `list`, `pin`, `unpin`, `recent`. |
| `app/cli/crypto.py` | `encrypt`, `decrypt`, `encryption-status`. |
| `app/cli/backup.py` | `export`, `import`, `import-ssh-config`, `export-ssh-config`. |
| `app/cli/health.py` | `ping`, `health`. The parallel probe uses `asyncio.to_thread` around the blocking socket call. |
| `app/cli/transfer.py` | `put`, `get`, `sftp`, the `scp` wrappers. |
| `app/cli/exec_cmd.py` | `exec`, the parallel broadcast. |
| `tests/conftest.py` | The `runner`, `temp_config_dir`, `temp_ssh_dir` and `sample_servers_data` fixtures. |
| `tests/test_cli.py` | 173 tests of the command surface, driven through Typer's `CliRunner`. |
| `docs/` | The landing page: a static `index.html` and `style.css`, published to GitHub Pages on every change to that folder. |
| `.ruff.toml` | Line length 120, target `py312`, and the rule selection. |

## Traps

- **A mistyped command becomes a connect query.** `OrderCommands.resolve_command` in `app/cli/_shared.py` maps an unknown first argument to `connect`. `bssh lss` does not report an unknown command; it opens the picker looking for a server named "lss". A typo in a subcommand name is a silent different command.
- **A missing SSH key writes the password back in plaintext.** `storage.save_servers` wraps `encrypt_password` in `contextlib.suppress(RuntimeError, ValueError)`. When neither `~/.ssh/id_ed25519` nor `~/.ssh/id_rsa` exists, `encrypt_password` raises `RuntimeError("Failed to initialize encryption")`, the suppression swallows it, and the password is written to `servers.json` in the clear while `settings.json` still says encryption is on. Check that the key exists before turning encryption on.
- **The salt and the key live in different files.** The salt is in `settings.json`, the key material is in the SSH key file. Deleting `settings.json` makes `get_or_create_encryption_salt` generate a new 32-byte salt, and every stored password becomes undecryptable. `load_servers` suppresses `InvalidToken`, so the ciphertext string ends up in the model; `is_encrypted` still reports it as encrypted, and `bssh show-pass` answers "Password could not be decrypted". The `enc` and `dec` commands clear such a password and warn about it.
- **`pytest.ini` wins over `pyproject.toml`.** Both carry a pytest configuration. pytest reads `pytest.ini` first, so the `[tool.pytest.ini_options]` block in `pyproject.toml` has no effect. The `addopts` in `pytest.ini` include `--cov=app --cov-branch --cov-report=html`, which is why a test run leaves an `htmlcov/` directory behind.
- **The tests patch `app.cli.<name>`, and the re-exports are load-bearing.** `app/cli/__init__.py` re-exports `typer`, `inquirer` and `pyperclip` so that `monkeypatch.setattr("app.cli.typer.prompt", fake)` reaches the call sites, and each submodule rebinds the app functions it uses so that `app.cli.connect` resolves to the patched one. A submodule that writes `from typer import prompt` instead of `import typer` breaks every test that patches it.
- **A new command module has to be imported in `app/cli/__init__.py`.** The `@app.command` decorators run at import time. A module that is never imported registers no command, and the CLI silently does not have it.
- **Every user string has to be escaped before it reaches Rich.** A server named `[red]x[/red]` is markup to Rich, not text. `escape()` is applied to names, hosts, notes, tags and the printed command line in the tables, the card, the picker labels and the `SSH:` line. A new output path that prints any of those without `escape()` is a rendering bug.
- **The port flag is lowercase for `ssh` and uppercase for the other two.** `ssh` takes `-p`, `sftp` and `scp` take `-P`.
- **`bssh recent` has to keep the time order.** `sort_servers` sorts by pinned, then most recent, then most used, then name. `bssh recent` calls `_print_servers(..., sort=False)` so a pinned server stays in its real recent position instead of jumping to the top.
- **The post hook is committed once the pre hook has succeeded.** The body of `connect()` is wrapped in a `try` / `finally` for exactly this reason, and the contract is documented in the README: setup implies teardown, even when SSH never starts. An early return that escapes the `try` block skips the cleanup.
- **`exec` runs with `BatchMode=yes`, `connect` does not.** `connect` runs a plain `ssh`, so a password-only host works. `exec` runs `ssh -o BatchMode=yes -o ConnectTimeout=N`, so the same host fails fast with an authentication error. The `scp` wrapper does not set `BatchMode` either, and prompts for the password. The CHANGELOG says `put` and `get` use `BatchMode`; the code does not.
- **The importer calls `ssh -G` twice per alias.** One call with the user config and one with an empty temporary config, and the difference between the two is how an explicit `IdentityFile` is told apart from a default one. A config with many hosts is slow to import. Aliases containing `*`, `?` or `!` are skipped, and so is a host with no `User`.
- **A name is unique, case-insensitively.** `name_conflict` is checked before the credential prompts in `add` and before the save in `edit`. A rename rewrites the `jump_host` of every server that pointed at the old name, in the same save.
- **An ambiguous match opens a picker instead of failing.** `storage.find_server` returns `None` when the broad match finds more than one server, and the command then puts the candidates in front of the user. Only a query that matches nothing is an error.
- **The prompt styles are not interchangeable.** Notes and tags use a direct prompt with "(Enter to skip)", because a confirm-then-prompt pair loses the typed text when the answer is not "y". The pre and post hooks use confirm-then-prompt, because a stray "n" typed at a direct prompt would be stored as a shell command and run on every connect.

## Style / safety rails

- **No `Co-Authored-By: Claude` trailers, and no "Generated with Claude Code" footers.** All commits are authored by the human. AI assistance stays out of the git metadata. If a template or a hook would add one, suppress it.
- **Never force-push to `master` without an explicit human confirmation in the same turn.** Never skip the hooks with `--no-verify`, and never bypass signing, unless the human asks for it in that turn.
- **`app/domain.py` stays free of I/O, Typer, Rich and InquirerPy.** It is importable from anywhere, including the tests, without touching stdin, stdout or the filesystem. That is what makes the validators testable in isolation.
- **The tool builds command lines and runs the system binaries.** It does not implement the SSH protocol. Adding an SSH library would change the whole product, and the update path of every user with a working `ssh` depends on the system client staying the one that runs.
- **The dependency set is small and deliberate.** typer, rich, platformdirs, pydantic, inquirerpy, pyperclip, cryptography. `uv.lock` is committed, and a new runtime dependency needs a reason in the pull request.
- **Comments explain why, never what.** The comments in this codebase are unusually good on this point. The ones above the `try` block in `connect()`, above the `contextlib.suppress` in `storage.py` and next to the prompt-style branches in `manage.py` are the model.
- **Exit codes are part of the contract.** 0 for success, 1 for a declined prompt or a failed lookup, 2 for a misused flag combination, 124 for an `exec` timeout, 127 for a missing `ssh`, `sftp` or `scp`, 130 for an interrupted session. Changing one is a breaking change.
- **The README is the reference manual and `docs/` is the pitch.** When a flag, an exit code or a default changes, the README and the CHANGELOG change with it in the same commit.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing the behaviour of the tool, and write the change there when the behaviour changes.
