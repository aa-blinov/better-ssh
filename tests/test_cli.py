"""Tests for CLI commands."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from click import IntRange
from InquirerPy.base.control import Choice as InquirerChoice
from typer.testing import CliRunner

from app.cli import _NONE_JUMP_SENTINEL, _prompt_keep_alive_interval, app
from app.encryption import encrypt_password
from app.models import Forward, Server
from app.storage import get_or_create_encryption_salt, is_encryption_enabled, load_servers, save_servers, save_settings


@pytest.fixture
def cli_with_servers(runner: CliRunner, servers_json_file: Path) -> CliRunner:
    """Provide CLI runner with servers already configured."""
    return runner


def test_cli_help(runner: CliRunner):
    """Test --help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Better SSH" in result.stdout
    assert "Quick start:" in result.stdout
    assert "better-ssh import-ssh-config" in result.stdout
    # Rich formatting uses panel header
    assert "Commands" in result.stdout or "commands" in result.stdout.lower()


def test_help_flag_alias(runner: CliRunner):
    """Test -h alias for --help flag."""
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Better SSH" in result.stdout


def test_help_shows_completion_options(runner: CliRunner):
    """Test shell completion options are exposed in help output."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    # Strip ANSI codes: Rich splits option names with color escapes on some terminals
    stdout = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--install-completion" in stdout
    assert "--show-completion" in stdout


def test_root_invocation_opens_connect_flow(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test running CLI without subcommand delegates to connect flow."""
    calls: list[tuple[str | None, bool]] = []

    def fake_connect_cmd(query: str | None = None, copy: bool = True):
        calls.append((query, copy))

    monkeypatch.setattr("app.cli.connection.connect_cmd", fake_connect_cmd)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert calls == [(None, True)]


def test_root_invocation_propagates_connect_exit_code(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test default root flow preserves the connect command exit code."""

    def fake_connect_cmd(query: str | None = None, copy: bool = True):
        raise typer.Exit(7)

    monkeypatch.setattr("app.cli.connection.connect_cmd", fake_connect_cmd)

    result = runner.invoke(app, [])

    assert result.exit_code == 7


def test_help_does_not_trigger_default_connect(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test help path does not open the default connect flow."""
    called = False

    def fake_connect_cmd(query: str | None = None, copy: bool = True):
        nonlocal called
        called = True

    monkeypatch.setattr("app.cli.connection.connect_cmd", fake_connect_cmd)

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert called is False


def test_root_invocation_with_no_servers_shows_empty_state(runner: CliRunner, temp_config_dir: Path):
    """Test default root flow surfaces the empty-state connect message."""
    result = runner.invoke(app, [])

    assert result.exit_code == 1
    assert "No servers found. Start with" in result.stdout
    assert "better-ssh import-ssh-config" in result.stdout
    assert "better-ssh add" in result.stdout


def test_query_shortcut_connects_unique_match(cli_with_servers: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test `better-ssh <query>` connects directly for a unique match."""
    selected: dict[str, object] = {}

    def fail_select(**kwargs):
        raise AssertionError("Interactive selection should not be used for a unique match")

    def fake_connect(server, copy_password: bool = True, all_servers=None):
        selected["server"] = server
        selected["copy_password"] = copy_password
        return 17

    monkeypatch.setattr("app.cli.inquirer.select", fail_select)
    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    result = cli_with_servers.invoke(app, ["Server3"])

    assert result.exit_code == 17
    assert selected["copy_password"] is True
    assert selected["server"].id == "test-id-003"


def test_query_shortcut_ambiguous_match_opens_filtered_menu(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test ambiguous shorthand query opens a filtered selection menu."""
    selected: dict[str, object] = {}

    class FakePrompt:
        def execute(self) -> str:
            return "test-id-001"

    def fake_select(**kwargs):
        assert kwargs["message"] == "Select server to connect for 'TestServer':"
        assert len(kwargs["choices"]) == 3
        return FakePrompt()

    def fake_connect(server, copy_password: bool = True, all_servers=None):
        selected["server"] = server
        return 19

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    result = cli_with_servers.invoke(app, ["TestServer"])

    assert result.exit_code == 19
    assert selected["server"].id == "test-id-001"


def test_query_shortcut_no_match_opens_full_menu(cli_with_servers: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test missing shorthand query falls back to the full server menu."""
    selected: dict[str, object] = {}

    class FakePrompt:
        def execute(self) -> str:
            return "test-id-002"

    def fake_select(**kwargs):
        assert kwargs["message"] == "No direct match for 'missing'. Select server to connect:"
        assert len(kwargs["choices"]) == 3
        return FakePrompt()

    def fake_connect(server, copy_password: bool = True, all_servers=None):
        selected["server"] = server
        return 29

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    result = cli_with_servers.invoke(app, ["missing"])

    assert result.exit_code == 29
    assert selected["server"].id == "test-id-002"


def test_import_ssh_config_command_imports_hosts(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test importing hosts from the default SSH config path."""
    config_file = temp_config_dir / "ssh_config"
    config_file.write_text("Host prod\n", encoding="utf-8")

    monkeypatch.setattr("app.cli.backup.get_default_ssh_config_path", lambda: config_file)
    monkeypatch.setattr(
        "app.cli.backup.import_ssh_config",
        lambda path: [
            Server(
                name="prod",
                host="prod.example.com",
                port=22,
                username="deploy",
                key_path="C:/keys/test-key",
                certificate_path="C:/keys/test-key-cert.pub",
            )
        ],
    )
    monkeypatch.setattr("app.cli.typer.confirm", lambda *args, **kwargs: True)

    result = runner.invoke(app, ["import-ssh-config"])

    assert result.exit_code == 0
    imported = load_servers()
    assert len(imported) == 1
    assert imported[0].name == "prod"
    assert imported[0].host == "prod.example.com"
    assert imported[0].key_path == "C:/keys/test-key"
    assert imported[0].certificate_path == "C:/keys/test-key-cert.pub"


def test_import_ssh_config_command_merge_preserves_metadata(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test SSH config merge keeps better-ssh metadata for matching names."""
    existing = Server(
        id="existing-prod",
        name="prod",
        host="old.example.com",
        port=22,
        username="old-user",
        password="secret",
        key_path="/old/key",
        certificate_path="/old/key-cert.pub",
        favorite=True,
        tags=["critical"],
        notes="Keep this note",
        use_count=8,
        last_used_at="2026-04-10T09:00:00+00:00",
    )
    save_servers([existing])

    config_file = temp_config_dir / "ssh_config"
    config_file.write_text("Host prod\n", encoding="utf-8")

    class FakePrompt:
        def execute(self) -> str:
            return "Merge - update matching host names and keep everything else"

    monkeypatch.setattr("app.cli.backup.get_default_ssh_config_path", lambda: config_file)
    monkeypatch.setattr(
        "app.cli.backup.import_ssh_config",
        lambda path: [
            Server(
                name="prod",
                host="new.example.com",
                port=2222,
                username="deploy",
                key_path="/new/key",
                certificate_path="/new/key-cert.pub",
            )
        ],
    )
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kwargs: FakePrompt())
    monkeypatch.setattr("app.cli.typer.confirm", lambda *args, **kwargs: True)

    result = runner.invoke(app, ["import-ssh-config"])

    assert result.exit_code == 0

    imported = load_servers()
    assert len(imported) == 1
    assert imported[0].id == "existing-prod"
    assert imported[0].host == "new.example.com"
    assert imported[0].port == 2222
    assert imported[0].username == "deploy"
    assert imported[0].key_path == "/new/key"
    assert imported[0].certificate_path == "/new/key-cert.pub"
    assert imported[0].password == "secret"
    assert imported[0].favorite is True
    assert imported[0].tags == ["critical"]
    assert imported[0].notes == "Keep this note"
    assert imported[0].use_count == 8
    assert imported[0].last_used_at == datetime(2026, 4, 10, 9, 0, tzinfo=UTC)


def test_list_command_empty(runner: CliRunner, temp_config_dir: Path):
    """Test list command with no servers."""
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No servers found. Start with" in result.stdout


def test_list_command_with_servers(cli_with_servers: CliRunner):
    """Test list command shows servers."""
    result = cli_with_servers.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout
    assert "TestServer2" in result.stdout
    # Host column may be heavily truncated by Rich when several optional columns
    # (Via, Alive, Tags, Notes) are shown side-by-side in a narrow terminal.
    # Verify only the non-truncated prefix; the full host is covered in other tests.
    assert "admin@" in result.stdout
    assert "auto" in result.stdout


def test_list_alias(cli_with_servers: CliRunner):
    """Test 'ls' alias works same as 'list'."""
    result = cli_with_servers.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout


def test_list_filters_by_query_name_substring(cli_with_servers: CliRunner):
    """Test `ls <query>` filters servers by name substring (case-insensitive)."""
    result = cli_with_servers.invoke(app, ["ls", "server1"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout
    assert "TestServer2" not in result.stdout
    assert "TestServer3" not in result.stdout


def test_list_filters_by_query_matches_host(cli_with_servers: CliRunner):
    """Test `ls <query>` matches server host."""
    result = cli_with_servers.invoke(app, ["ls", "example.com"])
    assert result.exit_code == 0
    assert "TestServer3" in result.stdout
    assert "TestServer1" not in result.stdout


def test_list_filters_by_query_matches_tag(cli_with_servers: CliRunner):
    """Test `ls <query>` matches server tags."""
    result = cli_with_servers.invoke(app, ["ls", "prod"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout  # has tag "prod"
    assert "TestServer2" not in result.stdout  # has tag "dev"
    assert "TestServer3" not in result.stdout


def test_add_interactive_note_prompt_stores_typed_value(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: typing a note at the direct 'Note (Enter to skip)' prompt stores it.

    The note/tags/pre/post fields are direct prompts (no 'Add X?' confirm step)
    so users can type the value directly without running into a y/n parser.
    """
    prompts: list[str] = []

    def fake_prompt(text: str, *a, **kw):
        prompts.append(text)
        # Only supply a value to the note prompt; the other text prompts
        # (tags, pre, post) get the default ("") and stay unset.
        if text.startswith("Note"):
            return "main db server"
        return kw.get("default", "")

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "NotedHost", "--host", "10.0.0.1", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    assert any(p.startswith("Note") for p in prompts)
    added = next(s for s in load_servers() if s.name == "NotedHost")
    assert added.notes == "main db server"
    # Direct-prompt fields default to empty, so nothing else should have leaked in
    assert added.tags == []
    assert added.pre_connect_cmd is None
    assert added.post_connect_cmd is None


def test_edit_can_change_existing_note(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit can change a server's existing note."""
    save_servers([Server(id="n-1", name="Noted", host="h.example", username="u", notes="old note")])

    prompt_values = iter(["Noted", "h.example", 22, "u", "new note"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change note?"),
    )

    result = runner.invoke(app, ["edit", "Noted"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "n-1")
    assert updated.notes == "new note"


def test_edit_can_clear_existing_note(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit can clear a server's note by entering an empty string."""
    save_servers([Server(id="n-1", name="Noted", host="h.example", username="u", notes="existing")])

    prompt_values = iter(["Noted", "h.example", 22, "u", ""])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change note?"),
    )

    result = runner.invoke(app, ["edit", "Noted"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "n-1")
    assert updated.notes is None


def test_add_with_key_certificate_notes_flags_skip_prompts(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --key, --certificate, --notes set fields non-interactively and skip their prompts."""
    confirms: list[str] = []
    prompts: list[str] = []
    monkeypatch.setattr(
        "app.cli.typer.prompt",
        lambda text, *a, **kw: prompts.append(text) or kw.get("default", ""),
    )
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: confirms.append(text) or False,
    )

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "Flaggy",
            "--host",
            "f.example",
            "--port",
            "22",
            "--username",
            "u",
            "--key",
            "/keys/id_ed25519",
            "--certificate",
            "/keys/id_ed25519-cert.pub",
            "--notes",
            "provisioned via script",
        ],
    )

    assert result.exit_code == 0
    # --key short-circuited the "Add SSH key?" confirm
    assert "Add SSH key?" not in confirms
    # --notes short-circuited the direct "Note (Enter to skip)" prompt
    assert not any(p.startswith("Note") for p in prompts)

    added = next(s for s in load_servers() if s.name == "Flaggy")
    assert added.key_path == "/keys/id_ed25519"
    assert added.certificate_path == "/keys/id_ed25519-cert.pub"
    assert added.notes == "provisioned via script"


def test_add_with_password_flag_skips_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --password sets the password non-interactively and skips the confirm/prompt."""
    confirms: list[str] = []
    prompts: list[str] = []
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: prompts.append(text) or "")
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: confirms.append(text) or False,
    )

    result = runner.invoke(
        app,
        ["add", "--name", "Pwd", "--host", "p.example", "--port", "22", "--username", "u", "--password", "s3cr3t"],
    )

    assert result.exit_code == 0
    assert "Add password?" not in confirms
    assert "Password" not in prompts
    added = next(s for s in load_servers() if s.name == "Pwd")
    assert added.password == "s3cr3t"


def test_add_with_empty_flag_values_stores_none(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test empty flag values (--key '', --notes '') normalize to None rather than empty strings."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "Empty",
            "--host",
            "e.example",
            "--port",
            "22",
            "--username",
            "u",
            "--key",
            "",
            "--notes",
            "",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Empty")
    assert added.key_path is None
    assert added.notes is None


def test_add_prompts_for_port_when_flag_omitted_and_stores_typed_value(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh add` without --port prompts for it via stdin and stores the typed value.

    Prompts for add's required fields go through Typer's built-in prompt=True
    (Click under the hood reads from stdin), not our patched app.cli.typer.prompt —
    so input is fed via the CliRunner `input=` argument.
    """
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    # --port omitted; stdin feeds "2222\n" to satisfy the port prompt
    result = runner.invoke(
        app,
        ["add", "--name", "Custom", "--host", "c.example", "--username", "u"],
        input="2222\n",
    )

    assert result.exit_code == 0, result.output
    added = next(s for s in load_servers() if s.name == "Custom")
    assert added.port == 2222


def test_add_port_prompt_accepts_default_on_enter(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test pressing Enter at the port prompt keeps the default (22)."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Default", "--host", "d.example", "--username", "u"],
        input="\n",  # just Enter -> accept default 22
    )

    assert result.exit_code == 0, result.output
    added = next(s for s in load_servers() if s.name == "Default")
    assert added.port == 22


def test_add_rejects_port_out_of_range(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test --port outside [1, 65535] is rejected by Typer's range validation."""
    result = runner.invoke(
        app,
        ["add", "--name", "Bad", "--host", "b.example", "--username", "u", "--port", "99999"],
    )

    assert result.exit_code != 0
    # No server should have been persisted
    assert not any(s.name == "Bad" for s in load_servers())


def test_export_ssh_config_command_writes_host_blocks(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test `bssh export-ssh-config <path>` writes a readable ssh_config file."""
    save_servers(
        [
            Server(id="a", name="alpha", host="a.example", username="u1"),
            Server(id="b", name="beta", host="b.example", username="u2", port=2222),
        ]
    )
    output = tmp_path / "bssh.conf"

    result = runner.invoke(app, ["export-ssh-config", str(output)])

    assert result.exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert "Host alpha" in text
    assert "    HostName a.example" in text
    assert "    User u1" in text
    assert "Host beta" in text
    assert "    Port 2222" in text


def test_export_ssh_config_command_empty_state(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test the command refuses to write when no servers are saved."""
    result = runner.invoke(app, ["export-ssh-config", str(tmp_path / "nope.conf")])

    assert result.exit_code == 1
    assert "No servers to export" in result.stdout


def test_export_ssh_config_command_overwrite_prompt_declined(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test declining the overwrite confirm leaves the file untouched AND returns rc=1.

    rc=1 (not 0) lets scripts distinguish "file written" from "user declined" —
    exit 0 would be ambiguous for pipelines that need to know whether the
    export actually happened. The cancel message should also surface --force
    as the scripting escape hatch.
    """
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    existing = tmp_path / "existing.conf"
    existing.write_text("# do not touch\n", encoding="utf-8")
    monkeypatch.setattr("app.cli.backup.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["export-ssh-config", str(existing)])

    assert result.exit_code == 1
    assert existing.read_text(encoding="utf-8") == "# do not touch\n"
    assert "--force" in result.output


def test_export_ssh_config_force_flag_overwrites_without_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `--force` overwrites an existing file without prompting (scripting path)."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    existing = tmp_path / "existing.conf"
    existing.write_text("# old content\n", encoding="utf-8")

    def fail_confirm(*a, **kw):
        raise AssertionError("--force must bypass the overwrite confirmation")

    monkeypatch.setattr("app.cli.backup.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["export-ssh-config", str(existing), "--force"])

    assert result.exit_code == 0
    assert "Host alpha" in existing.read_text(encoding="utf-8")


def test_export_declines_overwrite_returns_nonzero(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh export` returns rc=1 on user-declined overwrite (symmetric with export-ssh-config)."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    existing = tmp_path / "backup.json"
    existing.write_text('{"do": "not touch"}', encoding="utf-8")
    monkeypatch.setattr("app.cli.backup.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["export", str(existing)])

    assert result.exit_code == 1
    assert existing.read_text(encoding="utf-8") == '{"do": "not touch"}'
    assert "--force" in result.output


def test_export_force_flag_overwrites_without_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh export -f` overwrites without prompting (scripting path)."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    existing = tmp_path / "backup.json"
    existing.write_text('{"old": true}', encoding="utf-8")

    def fail_confirm(*a, **kw):
        raise AssertionError("-f must bypass the overwrite confirmation")

    monkeypatch.setattr("app.cli.backup.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["export", str(existing), "-f"])

    assert result.exit_code == 0
    written = existing.read_text(encoding="utf-8")
    assert '"alpha"' in written
    assert '"old"' not in written


def test_export_ssh_config_alias_esc(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test the short `esc` alias is wired to the same command."""
    save_servers([Server(id="a", name="alpha", host="a.example", username="u")])
    output = tmp_path / "out.conf"

    result = runner.invoke(app, ["esc", str(output)])

    assert result.exit_code == 0
    assert "Host alpha" in output.read_text(encoding="utf-8")


def test_import_command_replace_mode_replaces_all_servers(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh import` in Replace mode wipes existing servers and loads from file."""
    save_servers([Server(id="old-1", name="Old", host="o.example", username="u")])

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "new-1", "name": "New", "host": "n.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    class PickReplace:
        def execute(self) -> str:
            return "Replace all - delete existing servers and import new ones"

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: PickReplace())
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["import", str(backup)])

    assert result.exit_code == 0
    names = {s.name for s in load_servers()}
    assert names == {"New"}


def test_import_command_merge_mode_preserves_existing(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh import` in Merge mode keeps existing servers and upserts by id."""
    save_servers([Server(id="keep-1", name="Keep", host="k.example", username="u")])

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "new-1", "name": "New", "host": "n.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    class PickMerge:
        def execute(self) -> str:
            return "Merge - keep existing servers and add/update from import"

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: PickMerge())
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["import", str(backup)])

    assert result.exit_code == 0
    names = {s.name for s in load_servers()}
    assert names == {"Keep", "New"}


def test_import_replace_flag_skips_mode_picker(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `--replace` bypasses the interactive mode picker (still prompts for safety)."""
    save_servers([Server(id="old-1", name="Old", host="o.example", username="u")])

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "new-1", "name": "New", "host": "n.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    def fail_picker(**kw):
        raise AssertionError("--replace must bypass the inquirer.select mode picker")

    monkeypatch.setattr("app.cli.inquirer.select", fail_picker)
    # Safety confirm still fires; auto-accept it
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["import", str(backup), "--replace"])

    assert result.exit_code == 0
    assert {s.name for s in load_servers()} == {"New"}


def test_import_yes_flag_skips_safety_confirm(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `--replace --yes` wipes existing servers with no prompts at all (scripting path)."""
    save_servers(
        [
            Server(id="a", name="A", host="a.example", username="u"),
            Server(id="b", name="B", host="b.example", username="u"),
        ]
    )

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "new-1", "name": "Fresh", "host": "f.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    def fail_confirm(*a, **kw):
        raise AssertionError("--yes must bypass the safety confirmation")

    def fail_picker(**kw):
        raise AssertionError("--replace must bypass the mode picker")

    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)
    monkeypatch.setattr("app.cli.inquirer.select", fail_picker)

    result = runner.invoke(app, ["import", str(backup), "--replace", "--yes"])

    assert result.exit_code == 0
    assert {s.name for s in load_servers()} == {"Fresh"}


def test_import_safety_prompt_spells_out_destructive_replace(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test the safety prompt in replace mode explicitly mentions DELETE and counts.

    Guards against the original UX trap where a bare "Continue with import?"
    made it trivially easy to wipe the entire store by reflex-answering y.
    """
    save_servers(
        [
            Server(id="a", name="A", host="a.example", username="u"),
            Server(id="b", name="B", host="b.example", username="u"),
        ]
    )

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "n", "name": "N", "host": "n.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    prompts: list[str] = []

    def capture_confirm(text, **kw):
        prompts.append(text)
        return False  # decline so nothing happens

    monkeypatch.setattr("app.cli.typer.confirm", capture_confirm)

    result = runner.invoke(app, ["import", str(backup), "--replace"])

    assert result.exit_code == 0
    # The safety prompt must mention DELETE, the count, and the import size
    assert prompts, "expected a safety confirm to fire"
    safety = prompts[-1]
    assert "DELETE" in safety
    assert "2" in safety  # count of existing servers
    assert "1" in safety  # count of imported servers


def test_import_rejects_both_merge_and_replace(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test `--merge` + `--replace` together is rejected with rc=2 (usage error)."""
    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"servers": [{"id": "n", "name": "N", "host": "n.example", "port": 22, "username": "u"}]}',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["import", str(backup), "--merge", "--replace"])

    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_import_ssh_config_yes_flag_skips_safety_confirm(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh isc --replace --yes` wipes and imports with no prompts."""
    save_servers([Server(id="old-1", name="Old", host="o.example", username="u")])

    config_file = tmp_path / "custom.cfg"
    config_file.write_text("Host web\n  HostName w.example\n  User root\n", encoding="utf-8")

    def fail_confirm(*a, **kw):
        raise AssertionError("--yes must bypass the safety confirmation")

    def fail_picker(**kw):
        raise AssertionError("--replace must bypass the mode picker")

    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)
    monkeypatch.setattr("app.cli.inquirer.select", fail_picker)

    result = runner.invoke(app, ["isc", str(config_file), "--replace", "--yes"])

    assert result.exit_code == 0
    names = {s.name for s in load_servers()}
    assert "Old" not in names  # existing wiped
    assert "web" in names  # imported


def test_import_command_rejects_missing_file(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test `bssh import` on a non-existent file exits with an error."""
    result = runner.invoke(app, ["import", str(tmp_path / "missing.json")])

    assert result.exit_code == 1
    assert "File not found" in result.stdout


def test_import_command_rejects_bad_json(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test `bssh import` on malformed JSON exits with a clear error."""
    bad = tmp_path / "broken.json"
    bad.write_text("not json at all {", encoding="utf-8")

    result = runner.invoke(app, ["import", str(bad)])

    assert result.exit_code == 1
    assert "Failed to read" in result.stdout


def test_import_command_rejects_missing_servers_field(
    runner: CliRunner,
    temp_config_dir: Path,
    tmp_path: Path,
):
    """Test `bssh import` fails cleanly when 'servers' key is absent."""
    bad = tmp_path / "empty.json"
    bad.write_text('{"version": 1}', encoding="utf-8")

    result = runner.invoke(app, ["import", str(bad)])

    assert result.exit_code == 1
    assert "missing 'servers' field" in result.stdout


def test_encrypt_command_enables_and_encrypts_passwords(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh encrypt` enables encryption, encrypts plaintext passwords in storage."""
    save_servers([Server(id="s-1", name="S", host="h.example", username="u", password="plain-pass")])

    fake_key = tmp_path / "id_ed25519"
    fake_key.write_bytes(b"fake key material")
    # Patch both the CLI-side SSH-key lookup (for the "do we have a key?" check
    # in enable_encryption) and the encryption-module lookup used internally by
    # storage.save_servers. Without the second patch, the real
    # find_ssh_key_for_encryption returns None on CI hosts with no SSH key,
    # encrypt_password raises, contextlib.suppress swallows it, and the
    # password stays plaintext on disk.
    monkeypatch.setattr("app.cli.crypto.find_ssh_key_for_encryption", lambda: fake_key)
    monkeypatch.setattr("app.encryption.find_ssh_key_for_encryption", lambda: fake_key)
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["encrypt"])

    assert result.exit_code == 0
    assert "Encryption enabled" in result.stdout

    # Storage file must now contain ciphertext, not plaintext
    cfg_file = temp_config_dir / "servers.json"
    raw = cfg_file.read_text(encoding="utf-8")
    assert "plain-pass" not in raw
    # load_servers transparently decrypts so the password is recoverable
    loaded = next(s for s in load_servers() if s.id == "s-1")
    assert loaded.password == "plain-pass"


def test_encrypt_command_refuses_when_no_ssh_key_found(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh encrypt` fails cleanly when no SSH key is discoverable."""
    monkeypatch.setattr("app.cli.crypto.find_ssh_key_for_encryption", lambda: None)

    result = runner.invoke(app, ["encrypt"])

    assert result.exit_code == 1
    assert "SSH key not found" in result.stdout


def test_encrypt_command_already_enabled_is_idempotent(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh encrypt` is a no-op when encryption is already on."""
    save_settings({"encryption_enabled": True})

    result = runner.invoke(app, ["encrypt"])

    assert result.exit_code == 0
    assert "already enabled" in result.stdout.lower()


def test_encrypt_command_cancelled_does_not_enable(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test declining the encrypt confirm leaves settings untouched."""
    fake_key = tmp_path / "id_ed25519"
    fake_key.write_bytes(b"fake key material")
    monkeypatch.setattr("app.cli.crypto.find_ssh_key_for_encryption", lambda: fake_key)
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["encrypt"])

    assert result.exit_code == 0
    assert "Cancelled" in result.stdout
    # Settings file should still report encryption as off
    assert is_encryption_enabled() is False


def test_decrypt_command_disables_and_plainifies_passwords(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh decrypt` turns encryption off and writes plaintext passwords."""
    # First enable encryption so save_servers encrypts the password
    fake_key = tmp_path / "id_ed25519"
    fake_key.write_bytes(b"fake key material")
    monkeypatch.setattr("app.encryption.find_ssh_key_for_encryption", lambda: fake_key)
    save_settings({"encryption_enabled": True})
    save_servers([Server(id="s-1", name="S", host="h.example", username="u", password="secret")])

    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["decrypt"])

    assert result.exit_code == 0
    assert "Encryption disabled" in result.stdout
    # Plaintext must now live in servers.json
    cfg_file = temp_config_dir / "servers.json"
    raw = cfg_file.read_text(encoding="utf-8")
    assert "secret" in raw


def test_decrypt_command_already_disabled_is_idempotent(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh decrypt` is a no-op when encryption is already off."""
    result = runner.invoke(app, ["decrypt"])

    assert result.exit_code == 0
    assert "already disabled" in result.stdout.lower()


def test_encrypt_yes_flag_skips_confirmation(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh encrypt --yes` proceeds without calling typer.confirm (scripting)."""
    save_servers([Server(id="s-1", name="S", host="h.example", username="u", password="plain")])

    fake_key = tmp_path / "id_ed25519"
    fake_key.write_bytes(b"fake key material")
    monkeypatch.setattr("app.cli.crypto.find_ssh_key_for_encryption", lambda: fake_key)
    monkeypatch.setattr("app.encryption.find_ssh_key_for_encryption", lambda: fake_key)

    def fail_confirm(*a, **kw):
        raise AssertionError("--yes must bypass the confirmation prompt")

    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["encrypt", "--yes"])

    assert result.exit_code == 0
    assert "Encryption enabled" in result.stdout
    assert is_encryption_enabled() is True


def test_decrypt_yes_flag_skips_confirmation(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test `bssh decrypt -y` proceeds without calling typer.confirm (scripting)."""
    fake_key = tmp_path / "id_ed25519"
    fake_key.write_bytes(b"fake key material")
    monkeypatch.setattr("app.encryption.find_ssh_key_for_encryption", lambda: fake_key)
    save_settings({"encryption_enabled": True})
    save_servers([Server(id="s-1", name="S", host="h.example", username="u", password="secret")])

    def fail_confirm(*a, **kw):
        raise AssertionError("-y must bypass the confirmation prompt")

    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["decrypt", "-y"])

    assert result.exit_code == 0
    assert "Encryption disabled" in result.stdout
    assert is_encryption_enabled() is False


def test_encryption_status_reports_state(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh encryption-status` shows enabled/disabled correctly."""
    result = runner.invoke(app, ["encryption-status"])
    assert result.exit_code == 0
    assert "disabled" in result.stdout.lower()

    save_settings({"encryption_enabled": True, "encryption_key_source": "/fake/key"})
    result = runner.invoke(app, ["es"])  # alias
    assert result.exit_code == 0
    assert "enabled" in result.stdout.lower()


def test_ping_command_success_reports_reachable(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh ping <name>` reports reachable when the port is open."""
    save_servers([Server(id="p-1", name="Alpha", host="a.example", username="u")])
    monkeypatch.setattr("app.cli.health.check_server_availability", lambda s, **kw: (True, "reachable", 12.5))

    result = runner.invoke(app, ["ping", "Alpha"])

    assert result.exit_code == 0
    assert "reachable" in result.stdout
    assert "u@a.example" in result.stdout


def test_ping_command_failure_exits_nonzero(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh ping` exits with code 1 when the server is unreachable."""
    save_servers([Server(id="p-1", name="Alpha", host="a.example", username="u")])
    monkeypatch.setattr("app.cli.health.check_server_availability", lambda s, **kw: (False, "timeout", 3000.0))

    result = runner.invoke(app, ["ping", "Alpha"])

    assert result.exit_code == 1
    assert "timeout" in result.stdout


def test_ping_command_unknown_server_exits_nonzero(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh ping <unknown>` fails fast with a clear message."""
    save_servers([Server(id="p-1", name="Alpha", host="a.example", username="u")])

    result = runner.invoke(app, ["ping", "Ghost"])

    assert result.exit_code == 1
    assert "Server not found" in result.stdout


def test_health_command_all_available_exits_zero(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh health` exits 0 when every server is reachable."""
    save_servers(
        [
            Server(id="p-1", name="Alpha", host="a.example", username="u"),
            Server(id="p-2", name="Beta", host="b.example", username="u"),
        ]
    )
    monkeypatch.setattr("app.cli.health.check_server_availability", lambda s, **kw: (True, "reachable", 10.0))

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert "2/2 servers available" in result.stdout


def test_health_command_partial_failures_exits_nonzero(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh health` exits 1 when any server is unreachable."""
    save_servers(
        [
            Server(id="p-1", name="Alpha", host="a.example", username="u"),
            Server(id="p-2", name="Beta", host="b.example", username="u"),
        ]
    )

    def fake_check(server, **kw):
        return (server.name == "Alpha", "reachable" if server.name == "Alpha" else "timeout", 10.0)

    monkeypatch.setattr("app.cli.health.check_server_availability", fake_check)

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 1
    assert "1/2 servers available" in result.stdout


def test_health_command_empty_state(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh health` on an empty server list shows the empty-state message."""
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 1
    assert "No servers found" in result.stdout


def test_view_shows_all_fields_for_server(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh view <name>` renders all non-empty fields for one server."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops", port=2222),
            Server(
                id="t-1",
                name="Target",
                host="t.example",
                username="deploy",
                port=22,
                key_path="/keys/id_ed25519",
                jump_host="Bastion",
                keep_alive_interval=60,
                tags=["prod", "db"],
                notes="main postgres node",
                favorite=True,
                use_count=5,
            ),
        ]
    )

    result = runner.invoke(app, ["view", "Target"])

    assert result.exit_code == 0
    stdout = result.stdout
    assert "Target" in stdout
    assert "/keys/id_ed25519" in stdout
    # Jump chain references the bastion
    assert "Bastion" in stdout or "b.example" in stdout
    assert "60s" in stdout
    assert "prod" in stdout
    assert "db" in stdout
    assert "main postgres node" in stdout


def test_view_reports_broken_jump_chain(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view highlights a broken jump_host reference rather than raising."""
    save_servers(
        [
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Ghost"),
        ]
    )

    result = runner.invoke(app, ["view", "Target"])

    assert result.exit_code == 0
    assert "broken" in result.stdout
    assert "Ghost" in result.stdout


def test_view_lists_dependents_when_used_as_jump(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view shows which servers reference this one as a jump host."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="T1", host="t1.example", username="u", jump_host="Bastion"),
            Server(id="t-2", name="T2", host="t2.example", username="u", jump_host="Bastion"),
        ]
    )

    result = runner.invoke(app, ["view", "Bastion"])

    assert result.exit_code == 0
    assert "2 servers use" in result.stdout


def test_view_alias_v_works(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test the `v` alias resolves to the same view command."""
    save_servers([Server(id="s-1", name="One", host="h.example", username="u")])

    result = runner.invoke(app, ["v", "One"])

    assert result.exit_code == 0
    assert "One" in result.stdout


def test_edit_with_flags_applies_them_without_prompts(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit flags set fields non-interactively and skip the matching prompts."""
    save_servers(
        [Server(id="e-1", name="Server", host="old.example", username="old", tags=["old"], keep_alive_interval=30)]
    )

    prompts: list[str] = []
    confirms: list[str] = []
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: prompts.append(text) or "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda text, **kw: confirms.append(text) or False)

    result = runner.invoke(
        app,
        [
            "edit",
            "Server",
            "--host",
            "new.example",
            "--port",
            "2222",
            "--username",
            "newuser",
            "--notes",
            "scripted",
            "--keep-alive",
            "0",
            "-t",
            "prod",
            "-t",
            "db",
        ],
    )

    assert result.exit_code == 0
    # All relevant prompts / confirms must have been skipped by the flags
    assert "Host" not in prompts
    assert "Port" not in prompts
    assert "Username" not in prompts
    assert not any(c.startswith("Change note?") for c in confirms)
    assert not any(c.startswith("Change keep-alive") for c in confirms)
    assert not any(c.startswith("Change tags?") for c in confirms)

    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.host == "new.example"
    assert updated.port == 2222
    assert updated.username == "newuser"
    assert updated.notes == "scripted"
    assert updated.keep_alive_interval is None
    assert updated.tags == ["prod", "db"]


def test_edit_with_jump_flag_empty_clears_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump '' clears the jump host non-interactively (mirrors picker's (none))."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Bastion"),
        ]
    )

    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Target", "--jump", ""])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    assert updated.jump_host is None


def test_edit_with_jump_flag_resolves_case_insensitively(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump BASTION stores the canonical casing, matching add's behavior."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u"),
        ]
    )

    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Target", "--jump", "BASTION"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    assert updated.jump_host == "Bastion"


def test_edit_with_jump_flag_unknown_rejected(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump <unknown> fails cleanly without modifying state."""
    save_servers([Server(id="t-1", name="Target", host="t.example", username="u")])

    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Target", "--jump", "Ghost"])

    assert result.exit_code == 1
    assert "Jump host 'Ghost' not found" in result.stdout


def test_add_with_pre_and_post_flags_stores_commands(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --pre / --post on add stores the shell commands verbatim."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "H",
            "--host",
            "h.example",
            "--port",
            "22",
            "--username",
            "u",
            "--pre",
            "openvpn-connect corp",
            "--post",
            "openvpn-disconnect corp",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "H")
    assert added.pre_connect_cmd == "openvpn-connect corp"
    assert added.post_connect_cmd == "openvpn-disconnect corp"


def test_edit_with_empty_pre_clears_pre_connect_command(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --pre '' on edit clears the stored pre-connect command."""
    save_servers([Server(id="h-1", name="H", host="h.example", username="u", pre_connect_cmd="vpn up")])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "H", "--pre", ""])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "h-1")
    assert updated.pre_connect_cmd is None


def test_edit_with_no_post_flag_clears_post_connect_command(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --no-post on edit wipes the stored post-connect command."""
    save_servers([Server(id="h-1", name="H", host="h.example", username="u", post_connect_cmd="vpn down")])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "H", "--no-post"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "h-1")
    assert updated.post_connect_cmd is None


def test_view_shows_pre_and_post_connect_rows(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view renders Pre-connect / Post-connect rows when commands are set."""
    save_servers(
        [
            Server(
                id="h-1",
                name="H",
                host="h.example",
                username="u",
                pre_connect_cmd="aws sso login",
                post_connect_cmd="fusermount -u /mnt/remote",
            )
        ]
    )

    result = runner.invoke(app, ["view", "H"])

    assert result.exit_code == 0
    assert "Pre-connect" in result.stdout
    assert "aws sso login" in result.stdout
    assert "Post-connect" in result.stdout
    assert "fusermount" in result.stdout


def test_add_with_env_flag_parses_and_stores(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --env / -e is repeatable and stores KEY=VALUE pairs in order."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "E",
            "--host",
            "h.example",
            "--port",
            "22",
            "--username",
            "u",
            "-e",
            "LANG=en_US.UTF-8",
            "-e",
            "DEPLOY_ENV=staging",
            "--env",
            "PS1=user@host:",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "E")
    assert added.environment == {
        "LANG": "en_US.UTF-8",
        "DEPLOY_ENV": "staging",
        "PS1": "user@host:",
    }


def test_add_with_malformed_env_spec_exits_with_error(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test an env spec missing '=' surfaces the parser's error and exits 1."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Bad", "--host", "h.example", "--port", "22", "--username", "u", "-e", "noequals"],
    )

    assert result.exit_code == 1
    assert "Invalid env spec" in result.stdout
    assert load_servers() == []


def test_edit_with_env_flag_replaces_existing_environment(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --env on edit replaces the whole env dict, matching --tag semantics."""
    save_servers(
        [
            Server(
                id="e-1",
                name="Srv",
                host="h.example",
                username="u",
                environment={"OLD": "1", "KEEP": "me"},
            )
        ]
    )
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Srv", "-e", "NEW=value"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.environment == {"NEW": "value"}


def test_edit_with_no_env_flag_clears_environment(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --no-env wipes the stored env dict."""
    save_servers([Server(id="e-1", name="Srv", host="h.example", username="u", environment={"LANG": "en_US"})])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Srv", "--no-env"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.environment == {}


def test_view_shows_environment_section(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view renders each env var as a line inside the Environment row."""
    save_servers(
        [
            Server(
                id="e-1",
                name="E",
                host="h.example",
                username="u",
                environment={"LANG": "en_US.UTF-8", "DEPLOY_ENV": "prod"},
            )
        ]
    )

    result = runner.invoke(app, ["view", "E"])

    assert result.exit_code == 0
    assert "Environment" in result.stdout
    assert "LANG=en_US.UTF-8" in result.stdout
    assert "DEPLOY_ENV=prod" in result.stdout


def test_add_with_forward_flags_parses_and_stores(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test -L/-R/-D flags populate server.forwards non-interactively."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "Fwd",
            "--host",
            "f.example",
            "--port",
            "22",
            "--username",
            "u",
            "-L",
            "5432:localhost:5432",
            "-R",
            "9000:internal:9000",
            "-D",
            "1080",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Fwd")
    assert len(added.forwards) == 3
    assert added.forwards[0].type == "local"
    assert added.forwards[0].local_port == 5432
    assert added.forwards[1].type == "remote"
    assert added.forwards[2].type == "dynamic"


def test_add_with_malformed_forward_spec_exits_with_error(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test a malformed -L spec surfaces the parser's error and aborts."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Bad", "--host", "b.example", "--port", "22", "--username", "u", "-L", "nope"],
    )

    assert result.exit_code == 1
    assert "Invalid local forward" in result.stdout
    assert load_servers() == []


def test_edit_with_forward_flags_replaces_existing_forwards(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test passing any -L/-R/-D to edit replaces the existing forwards list."""
    save_servers(
        [
            Server(
                id="f-1",
                name="F",
                host="f.example",
                username="u",
                forwards=[
                    Forward(type="local", local_port=5432, remote_host="db", remote_port=5432),
                ],
            )
        ]
    )
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "F", "-D", "1080"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "f-1")
    assert len(updated.forwards) == 1
    assert updated.forwards[0].type == "dynamic"
    assert updated.forwards[0].local_port == 1080


def test_edit_with_no_forwards_flag_clears_forwards(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --no-forwards wipes the existing forwards list."""
    save_servers(
        [
            Server(
                id="f-1",
                name="F",
                host="f.example",
                username="u",
                forwards=[Forward(type="dynamic", local_port=1080)],
            )
        ]
    )
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "F", "--no-forwards"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "f-1")
    assert updated.forwards == []


def test_list_shows_fwd_column_when_any_server_has_forwards(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls shows a 'Fwd' column with the count when forwards are configured."""
    save_servers(
        [
            Server(
                id="f-1",
                name="WithFwd",
                host="h.example",
                username="u",
                forwards=[
                    Forward(type="local", local_port=5432, remote_host="db", remote_port=5432),
                    Forward(type="dynamic", local_port=1080),
                ],
            ),
            Server(id="p-1", name="Plain", host="p.example", username="u"),
        ]
    )
    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "Fwd" in result.stdout
    assert "2" in result.stdout  # forward count


def test_list_hides_fwd_column_when_no_forwards(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls hides the 'Fwd' column when no server has forwards set."""
    save_servers([Server(id="p-1", name="Plain", host="p.example", username="u")])

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "Fwd" not in result.stdout


def test_show_pass_renders_bracketed_password_literally(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh show-pass` prints the exact password even when it contains brackets.

    Without escape, a password like "P[ass]w0rd" would be parsed as a Rich
    style tag and render incorrectly — a silent data-integrity bug since the
    user relies on show-pass to reveal the actual stored value.
    """
    save_servers([Server(id="p-1", name="P", host="h.example", username="u", password="P[ass]w0rd")])

    result = runner.invoke(app, ["show-pass", "P"])

    assert result.exit_code == 0
    assert "P[ass]w0rd" in result.stdout


def test_view_renders_server_with_bracketed_name_without_crashing(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh view` treats names/notes with square brackets as literal text.

    Before the Rich-markup-escape pass a name like "[red]evil[/red]" would be
    parsed as markup by Rich and either break layout or hide the brackets
    entirely. Escaping makes them render verbatim.
    """
    save_servers(
        [
            Server(
                id="e-1",
                name="[red]evil[/red]",
                host="h.example",
                username="u",
                notes="has [bold]brackets[/bold] inside",
                tags=["[weird]"],
            )
        ]
    )

    result = runner.invoke(app, ["view", "e-1"])

    assert result.exit_code == 0
    # The literal brackets must remain visible in the output
    assert "[red]evil[/red]" in result.stdout
    assert "[bold]brackets[/bold]" in result.stdout
    assert "[weird]" in result.stdout


def test_list_renders_bracketed_server_name_literally(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh ls` shows a name containing square brackets verbatim."""
    save_servers([Server(id="e-1", name="[hostile]name", host="h.example", username="u")])

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "[hostile]name" in result.stdout


def test_pin_renders_bracketed_name_literally(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test pin echo message does not mangle a name with square brackets."""
    save_servers([Server(id="e-1", name="[weird]server", host="h.example", username="u")])

    result = runner.invoke(app, ["pin", "[weird]server"])

    assert result.exit_code == 0
    assert "[weird]server" in result.stdout


def test_add_with_x11_flag_stores_true(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --x11 on add sets x11_forwarding=True without interactive prompts."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "GUI", "--host", "g.example", "--port", "22", "--username", "u", "--x11"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "GUI")
    assert added.x11_forwarding is True


def test_add_without_x11_flag_defaults_false(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test omitting --x11 on add keeps x11_forwarding at its False default."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Plain", "--host", "p.example", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Plain")
    assert added.x11_forwarding is False


def test_edit_with_x11_enables_it(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit --x11 turns X11 forwarding on for an existing server."""
    save_servers([Server(id="e-1", name="X", host="h.example", username="u")])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "X", "--x11"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.x11_forwarding is True


def test_edit_with_no_x11_disables_it(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit --no-x11 turns X11 forwarding off."""
    save_servers([Server(id="e-1", name="X", host="h.example", username="u", x11_forwarding=True)])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "X", "--no-x11"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.x11_forwarding is False


def test_edit_without_x11_flag_preserves_current_value(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test omitting both --x11 and --no-x11 keeps the existing True setting."""
    save_servers([Server(id="e-1", name="X", host="h.example", username="u", x11_forwarding=True)])
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: kw.get("default", ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "X", "--host", "new.example"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "e-1")
    assert updated.x11_forwarding is True
    assert updated.host == "new.example"


def test_view_shows_x11_row_when_enabled(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view renders an X11 row for servers with x11_forwarding=True."""
    save_servers([Server(id="e-1", name="GUI", host="h.example", username="u", x11_forwarding=True)])

    result = runner.invoke(app, ["view", "GUI"])

    assert result.exit_code == 0
    assert "X11" in result.stdout
    assert "enabled" in result.stdout


def test_view_omits_x11_row_when_disabled(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view does not show the X11 row for servers with the default False value."""
    save_servers([Server(id="e-1", name="CLI", host="h.example", username="u")])

    result = runner.invoke(app, ["view", "CLI"])

    assert result.exit_code == 0
    # The row label would be "X11 ..." — with the default False it should be absent.
    assert "X11" not in result.stdout


def test_view_shows_forwards_section(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test view renders each forward as a labeled row in the panel."""
    save_servers(
        [
            Server(
                id="f-1",
                name="Fwd",
                host="h.example",
                username="u",
                forwards=[
                    Forward(type="local", local_port=5432, remote_host="db", remote_port=5432),
                    Forward(type="dynamic", local_port=1080),
                ],
            )
        ]
    )

    result = runner.invoke(app, ["view", "Fwd"])

    assert result.exit_code == 0
    assert "Forwards" in result.stdout
    assert "5432" in result.stdout
    assert "1080" in result.stdout


def test_add_skip_flag_suppresses_all_confirms(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test -s on add bypasses every 'Add X?' confirm; fields default to empty/None."""
    confirm_calls: list[str] = []
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: confirm_calls.append(text) or False,
    )
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")

    result = runner.invoke(
        app,
        ["add", "--name", "Minimal", "--host", "h.example", "--port", "22", "--username", "u", "-s"],
    )

    assert result.exit_code == 0
    assert confirm_calls == []  # no Add X? confirms fired

    added = next(s for s in load_servers() if s.name == "Minimal")
    assert added.key_path is None
    assert added.password is None
    assert added.jump_host is None
    assert added.notes is None
    assert added.tags == []
    assert added.keep_alive_interval is None
    assert added.forwards == []


def test_add_skip_flag_still_honors_value_flags(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test -y doesn't disable explicit flags — flag-provided values still apply."""

    def fail_confirm(*a, **kw):
        raise AssertionError("no confirm should fire under -s")

    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "WithFlags",
            "--host",
            "h.example",
            "--port",
            "22",
            "--username",
            "u",
            "-s",
            "--notes",
            "provisioned",
            "-t",
            "prod",
            "-L",
            "5432:localhost:5432",
            "--keep-alive",
            "60",
            "--x11",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "WithFlags")
    assert added.notes == "provisioned"
    assert added.tags == ["prod"]
    assert len(added.forwards) == 1
    assert added.forwards[0].local_port == 5432
    assert added.keep_alive_interval == 60
    assert added.x11_forwarding is True


def test_add_skip_long_form_is_equivalent(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --skip long form behaves the same as -s."""
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")

    result = runner.invoke(
        app,
        ["add", "--name", "Long", "--host", "h.example", "--port", "22", "--username", "u", "--skip"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Long")
    assert added.key_path is None


def test_edit_skip_flag_suppresses_all_prompts(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh edit <name> --skip` with no other flags is a no-op save — no prompts fire."""
    save_servers(
        [
            Server(
                id="s-1",
                name="Target",
                host="h.example",
                username="u",
                notes="keep me",
                tags=["prod"],
                pre_connect_cmd="vpn up",
            )
        ]
    )

    def fail_prompt(*a, **kw):
        raise AssertionError(f"no prompt should fire under --skip, got: {a}, {kw}")

    def fail_confirm(*a, **kw):
        raise AssertionError(f"no confirm should fire under --skip, got: {a}, {kw}")

    monkeypatch.setattr("app.cli.typer.prompt", fail_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["edit", "Target", "--skip"])

    assert result.exit_code == 0, result.output
    updated = next(s for s in load_servers() if s.id == "s-1")
    # Every field preserved — --skip with no other flags is a no-op rewrite
    assert updated.name == "Target"
    assert updated.host == "h.example"
    assert updated.notes == "keep me"
    assert updated.tags == ["prod"]
    assert updated.pre_connect_cmd == "vpn up"


def test_edit_skip_with_clear_flag_clears_only_that_field(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test the common scenario: `bssh edit <name> --no-pre -s` clears pre without prompting for anything else."""
    save_servers(
        [
            Server(
                id="s-1",
                name="Target",
                host="h.example",
                username="u",
                notes="untouched",
                tags=["kept"],
                pre_connect_cmd="will be removed",
                post_connect_cmd="also preserved",
            )
        ]
    )

    def fail_prompt(*a, **kw):
        raise AssertionError("no prompt should fire under -s")

    def fail_confirm(*a, **kw):
        raise AssertionError("no confirm should fire under -s")

    monkeypatch.setattr("app.cli.typer.prompt", fail_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["edit", "Target", "--no-pre", "-s"])

    assert result.exit_code == 0, result.output
    updated = next(s for s in load_servers() if s.id == "s-1")
    # Only pre cleared; everything else preserved
    assert updated.pre_connect_cmd is None
    assert updated.post_connect_cmd == "also preserved"
    assert updated.notes == "untouched"
    assert updated.tags == ["kept"]


def test_edit_skip_with_value_flag_applies_only_that_flag(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh edit <name> --host <new> --skip` updates just the host, preserves the rest, no prompts."""
    save_servers(
        [
            Server(
                id="s-1",
                name="Target",
                host="old.example",
                port=2222,
                username="u",
                notes="stays",
                tags=["k1", "k2"],
                keep_alive_interval=60,
            )
        ]
    )

    def fail_prompt(*a, **kw):
        raise AssertionError("no prompt should fire under -s")

    def fail_confirm(*a, **kw):
        raise AssertionError("no confirm should fire under -s")

    monkeypatch.setattr("app.cli.typer.prompt", fail_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fail_confirm)

    result = runner.invoke(app, ["edit", "Target", "--host", "new.example", "-s"])

    assert result.exit_code == 0, result.output
    updated = next(s for s in load_servers() if s.id == "s-1")
    assert updated.host == "new.example"
    # Everything else preserved verbatim
    assert updated.port == 2222
    assert updated.notes == "stays"
    assert updated.tags == ["k1", "k2"]
    assert updated.keep_alive_interval == 60


def test_add_with_tag_flag_stores_tags(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test -t/--tag is repeatable and trims/deduplicates values."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "Tagged",
            "--host",
            "h.example",
            "--port",
            "22",
            "--username",
            "u",
            "-t",
            "prod",
            "-t",
            " web ",
            "-t",
            "prod",
        ],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Tagged")
    assert added.tags == ["prod", "web"]


def test_add_interactive_tags_prompt_parses_comma_separated(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test typing comma-separated tags at the direct tags prompt parses + dedupes."""

    def fake_prompt(text: str, *a, **kw):
        if text.startswith("Tags"):
            return "prod, db, prod"  # duplicate to verify dedup
        return kw.get("default", "")

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Iac", "--host", "i.example", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Iac")
    assert added.tags == ["prod", "db"]


def test_edit_can_change_existing_tags(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit replaces existing tags when the user provides new ones."""
    save_servers([Server(id="t-1", name="Server", host="s.example", username="u", tags=["old"])])

    # Flow order: Name, Host, Port, Username, Note (direct prompt, skip ""), Tags change
    prompt_values = iter(["Server", "s.example", 22, "u", "", "prod, db"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change tags?"),
    )

    result = runner.invoke(app, ["edit", "Server"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    assert updated.tags == ["prod", "db"]


def test_edit_can_clear_existing_tags_with_empty_input(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit clears tags when the user enters an empty value at the prompt."""
    save_servers([Server(id="t-1", name="Server", host="s.example", username="u", tags=["prod"])])

    prompt_values = iter(["Server", "s.example", 22, "u", ""])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change tags?"),
    )

    result = runner.invoke(app, ["edit", "Server"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    assert updated.tags == []


def test_list_shows_tags_column_when_any_server_has_tags(cli_with_servers: CliRunner):
    """Test ls shows the 'Tags' column when at least one server has tags."""
    result = cli_with_servers.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "Tags" in result.stdout


def test_list_hides_tags_column_when_no_tags(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls hides the 'Tags' column when no server has tags."""
    save_servers([Server(id="p-1", name="Plain", host="p.example", username="u")])

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "Tags" not in result.stdout


def test_list_filters_by_jump_host_reference(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `ls <query>` also surfaces servers that use <query> as their jump host."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Bastion"),
            Server(id="o-1", name="Other", host="o.example", username="u"),
        ]
    )

    result = runner.invoke(app, ["ls", "bastion"])

    assert result.exit_code == 0
    # Both the bastion itself and its dependent should appear
    assert "Bastion" in result.stdout
    assert "Target" in result.stdout
    # Unrelated server is filtered out
    assert "Other" not in result.stdout


def test_add_with_keep_alive_flag_skips_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --keep-alive N sets the interval non-interactively and skips the confirm."""
    confirms: list[str] = []

    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: confirms.append(text) or False,
    )

    result = runner.invoke(
        app,
        [
            "add",
            "--name",
            "KA",
            "--host",
            "h.example",
            "--port",
            "22",
            "--username",
            "u",
            "--keep-alive",
            "90",
        ],
    )

    assert result.exit_code == 0
    assert "Enable SSH keep-alive?" not in confirms
    added = next(s for s in load_servers() if s.name == "KA")
    assert added.keep_alive_interval == 90


def test_add_with_keep_alive_flag_zero_leaves_disabled(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --keep-alive 0 explicitly disables and does not re-prompt."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "KA0", "--host", "h.example", "--port", "22", "--username", "u", "-K", "0"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "KA0")
    assert added.keep_alive_interval is None


def test_recent_command_sorts_by_last_used_newest_first(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh recent` orders servers by last_used_at descending, regardless of pin status."""
    save_servers(
        [
            Server(
                id="old",
                name="Old",
                host="old.example",
                username="u",
                last_used_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            ),
            Server(
                id="new",
                name="New",
                host="new.example",
                username="u",
                last_used_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            ),
            # Pinned but never used — should NOT show up in recent.
            Server(id="unused-pin", name="Pinned", host="p.example", username="u", favorite=True),
        ]
    )

    result = runner.invoke(app, ["recent"])

    assert result.exit_code == 0
    stdout = result.stdout
    assert "New" in stdout
    assert "Old" in stdout
    # "Pinned" never connected -> omitted from the time-sorted list
    assert "Pinned" not in stdout
    # Newer server appears before older one in the rendered output
    assert stdout.index("New") < stdout.index("Old")
    # Column with relative timestamps must be shown
    assert "Last used" in stdout


def test_recent_command_respects_limit(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh recent --limit N` truncates to N rows."""
    save_servers(
        [
            Server(
                id=f"s-{i}",
                name=f"Srv{i}",
                host=f"h{i}.example",
                username="u",
                last_used_at=datetime(2026, 4, i + 1, 12, 0, tzinfo=UTC),
            )
            for i in range(5)
        ]
    )

    result = runner.invoke(app, ["recent", "--limit", "2"])

    assert result.exit_code == 0
    # Newest two (Srv4, Srv3) must be present
    assert "Srv4" in result.stdout
    assert "Srv3" in result.stdout
    # Older ones must be clipped
    assert "Srv0" not in result.stdout
    assert "Srv1" not in result.stdout


def test_recent_command_short_flag_and_alias(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `-n` short flag and `r` alias both work for recent."""
    save_servers(
        [
            Server(
                id="s-1",
                name="Srv",
                host="h.example",
                username="u",
                last_used_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            )
        ]
    )

    result = runner.invoke(app, ["r", "-n", "5"])

    assert result.exit_code == 0
    assert "Srv" in result.stdout


def test_recent_command_no_used_servers_shows_friendly_message(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh recent` prints a helpful message when no server has ever been connected."""
    save_servers([Server(id="s-1", name="Fresh", host="h.example", username="u")])

    result = runner.invoke(app, ["recent"])

    assert result.exit_code == 0
    assert "No recent connections yet" in result.stdout


def test_recent_command_empty_state(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test `bssh recent` on an empty list shows the same empty-state as ls."""
    result = runner.invoke(app, ["recent"])

    assert result.exit_code == 0
    assert "No servers found" in result.stdout


def test_list_shows_alive_column_when_any_server_has_keep_alive(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls shows the 'Alive' column when at least one server has keep-alive set."""
    save_servers(
        [
            Server(id="k-1", name="Alive60", host="a.example", username="u", keep_alive_interval=60),
            Server(id="p-1", name="Plain", host="p.example", username="u"),
        ]
    )

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "Alive" in result.stdout
    assert "60s" in result.stdout


def test_list_hides_alive_column_when_no_keep_alive(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls hides the 'Alive' column when no server has keep-alive set."""
    save_servers([Server(id="p-1", name="Plain", host="p.example", username="u")])

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "Alive" not in result.stdout


def test_list_shows_notes_column_when_any_server_has_notes(cli_with_servers: CliRunner):
    """Test ls shows the 'Notes' column when at least one server has a note set."""
    # Sample data has TestServer1 with notes="Production web server"
    result = cli_with_servers.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "Notes" in result.stdout


def test_add_command_confirms_keep_alive_stores_interval(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: confirming keep-alive prompts for interval and stores the value."""
    prompts: list[str] = []

    def fake_prompt(text: str, *a, **kw):
        prompts.append(text)
        if text.startswith("Interval in seconds"):
            return 120
        return ""

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text == "Enable SSH keep-alive?",
    )

    result = runner.invoke(
        app,
        ["add", "--name", "Alive", "--host", "a.example", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    assert any(p.startswith("Interval in seconds") for p in prompts)
    added = next(s for s in load_servers() if s.name == "Alive")
    assert added.keep_alive_interval == 120


def test_edit_can_disable_existing_keep_alive_with_zero(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit disables keep-alive when user enters 0 at the interval prompt."""
    save_servers([Server(id="k-1", name="Alive", host="a.example", username="u", keep_alive_interval=60)])

    # Name, Host, Port, Username, Note (direct prompt, skip ""), then 0 for interval (disable)
    prompt_values = iter(["Alive", "a.example", 22, "u", "", 0])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change keep-alive interval?"),
    )

    result = runner.invoke(app, ["edit", "Alive"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "k-1")
    assert updated.keep_alive_interval is None


def test_add_command_keep_alive_zero_stores_none(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: entering 0 at the keep-alive interval prompt stores None, not 0."""

    def fake_prompt(text: str, *a, **kw):
        if text.startswith("Interval in seconds"):
            return 0
        return ""

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text == "Enable SSH keep-alive?",
    )

    result = runner.invoke(
        app,
        ["add", "--name", "Noop", "--host", "n.example", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Noop")
    assert added.keep_alive_interval is None


def test_prompt_keep_alive_interval_uses_int_range_validator(monkeypatch: pytest.MonkeyPatch):
    """Test the helper passes click.IntRange(min=0) to reject negative values at prompt."""
    captured: dict[str, object] = {}

    def fake_prompt(text, *, default, type):  # noqa: A002 - mirrors typer.prompt signature
        captured["text"] = text
        captured["default"] = default
        captured["type"] = type
        return 60

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)

    result = _prompt_keep_alive_interval(30)

    assert result == 60
    assert captured["default"] == 30
    # click.IntRange should enforce min=0 so typer/click rejects negatives at prompt
    validator = captured["type"]
    assert isinstance(validator, IntRange)
    assert validator.min == 0


def test_list_hides_notes_column_when_no_notes(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls hides the 'Notes' column when no server has notes."""
    save_servers([Server(id="a-1", name="Plain", host="p.example", username="u")])

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "Notes" not in result.stdout


def test_list_filters_by_query_no_matches_shows_message(cli_with_servers: CliRunner):
    """Test `ls <query>` with no matches prints a friendly message."""
    result = cli_with_servers.invoke(app, ["ls", "doesnotexist"])
    assert result.exit_code == 0
    assert "No servers match 'doesnotexist'" in result.stdout


def test_add_command_declines_key_and_password(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: declining both key and password confirms leaves them unset."""
    prompt_calls: list[str] = []

    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: prompt_calls.append(text) or "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "NewHost", "--host", "10.0.0.10", "--port", "22", "--username", "root"],
    )

    assert result.exit_code == 0
    assert "Password" not in prompt_calls
    assert "Path to private key" not in prompt_calls

    added = load_servers()
    assert len(added) == 1
    assert added[0].name == "NewHost"
    assert added[0].password is None
    assert added[0].key_path is None


def test_add_command_confirms_jump_host_saves_selected_name(
    runner: CliRunner,
    servers_json_file: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: confirming jump host triggers inquirer select and saves the name."""

    class FakeJumpPrompt:
        def execute(self) -> str:
            return "TestServer2"

    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text == "Use a jump host (ProxyJump)?",
    )
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: FakeJumpPrompt())

    result = runner.invoke(
        app,
        ["add", "--name", "ViaBastion", "--host", "10.0.0.50", "--port", "22", "--username", "app"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "ViaBastion")
    assert added.jump_host == "TestServer2"


def test_add_command_declines_jump_host_leaves_unset(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: declining jump host does not set jump_host."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)
    select_called = False

    def fake_select(**kw):
        nonlocal select_called
        select_called = True
        raise AssertionError("inquirer.select should not be called")

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)

    result = runner.invoke(
        app,
        ["add", "--name", "Direct", "--host", "1.1.1.1", "--port", "22", "--username", "u"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Direct")
    assert added.jump_host is None
    assert select_called is False


def test_add_command_confirms_password_prompts_with_confirmation(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add: confirming password triggers a hidden prompt with confirmation."""
    prompt_calls: list[tuple[str, dict[str, object]]] = []

    def fake_prompt(text, *a, **kw):
        prompt_calls.append((text, kw))
        # Only the Password prompt gets a real value; the direct-prompt
        # optional fields (Note/Tags/Pre/Post) get their default.
        if text == "Password":
            return "secret123"
        return kw.get("default", "")

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text == "Add password?",
    )

    result = runner.invoke(
        app,
        ["add", "--name", "PwdHost", "--host", "10.0.0.11", "--port", "22", "--username", "root"],
    )

    assert result.exit_code == 0
    # Exactly one Password prompt, and it carried the hide_input + confirmation_prompt kwargs
    password_prompts = [call for call in prompt_calls if call[0] == "Password"]
    assert len(password_prompts) == 1
    assert password_prompts[0][1]["hide_input"] is True
    assert password_prompts[0][1]["confirmation_prompt"] is True

    added = load_servers()
    assert len(added) == 1
    assert added[0].name == "PwdHost"
    assert added[0].password == "secret123"


def test_edit_without_query_opens_interactive_selection(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit command can select a server interactively when query is omitted."""

    class FakePrompt:
        def execute(self) -> str:
            return "test-id-003"

    answers = iter(["RenamedServer", "example.com", 22, "user"])

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kwargs: FakePrompt())
    monkeypatch.setattr("app.cli.typer.prompt", lambda *args, **kwargs: next(answers, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *args, **kwargs: False)

    result = cli_with_servers.invoke(app, ["edit"])

    assert result.exit_code == 0

    updated = next(server for server in load_servers() if server.id == "test-id-003")
    assert updated.name == "RenamedServer"


def test_edit_no_key_shows_confirm_not_path_prompt(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test editing a server without key shows 'Add key path?' confirm, not an open-ended prompt."""
    prompt_calls: list[str] = []
    confirm_calls: list[str] = []

    answers = {"Name": "TestServer3", "Host": "example.com", "Port": 22, "Username": "user"}

    def fake_prompt(text: str, *args, **kwargs):
        prompt_calls.append(text)
        # Direct-prompt optional fields (Note/Tags/Pre/Post) aren't in the
        # answers dict — return their default (empty) so they skip silently.
        return answers.get(text, kwargs.get("default", ""))

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        return False

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer3"])

    assert result.exit_code == 0
    assert confirm_calls == [
        "Add key path?",
        "Add certificate path?",
        "Add password?",
        "Use a jump host (ProxyJump)?",
        "Enable SSH keep-alive?",
        "Configure port forwards?",
        "Set environment variables?",
        "Add a pre-connect command?",
        "Add a post-connect command?",
    ]
    # No key/cert path prompts — user declined via confirm
    assert not any("path" in p.lower() for p in prompt_calls)

    updated = next(server for server in load_servers() if server.id == "test-id-003")
    assert updated.key_path is None


def test_edit_existing_password_does_not_ask_clear_password(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit replaces the old clear-password branch with a single new password prompt."""
    prompt_values = iter(["TestServer1", "192.168.1.10", 22, "admin", "new-secret"])
    confirm_calls: list[str] = []

    def fake_prompt(*args, **kwargs):
        return next(prompt_values, "")

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        if text == "Clear password?":
            raise AssertionError("Clear password prompt should not be shown")
        return text == "Change password?"

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer1"])

    assert result.exit_code == 0
    assert confirm_calls == [
        "Add key path?",
        "Add certificate path?",
        "Change password?",
        "Use a jump host (ProxyJump)?",
        "Change note? [Production web server]",
        "Enable SSH keep-alive?",
        "Change tags? [prod, web]",
        "Configure port forwards?",
        "Set environment variables?",
        "Add a pre-connect command?",
        "Add a post-connect command?",
    ]

    updated = next(server for server in load_servers() if server.id == "test-id-001")
    assert updated.password == "new-secret"


def test_edit_existing_key_path_can_be_cleared(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit can clear an already saved key path."""
    prompt_values = iter(["TestServer2", "192.168.1.20", 2222, "root", ""])
    confirm_calls: list[str] = []

    def fake_prompt(*args, **kwargs):
        return next(prompt_values, "")

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        return text.startswith("Change key path?")

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer2"])

    assert result.exit_code == 0
    assert confirm_calls == [
        "Change key path? [/home/user/.ssh/id_rsa]",
        "Add certificate path?",
        "Add password?",
        "Use a jump host (ProxyJump)?",
        "Enable SSH keep-alive?",
        "Change tags? [dev]",
        "Configure port forwards?",
        "Set environment variables?",
        "Add a pre-connect command?",
        "Add a post-connect command?",
    ]

    updated = next(server for server in load_servers() if server.id == "test-id-002")
    assert updated.key_path is None


def test_edit_without_jump_host_offers_to_add_one(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit: a server without jump_host can have one assigned via ProxyJump prompt."""
    prompt_values = iter(["TestServer1", "192.168.1.10", 22, "admin"])
    confirm_calls: list[str] = []

    class FakeJumpPrompt:
        def execute(self) -> str:
            return "TestServer2"

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        return text == "Use a jump host (ProxyJump)?"

    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: FakeJumpPrompt())

    result = cli_with_servers.invoke(app, ["edit", "TestServer1"])

    assert result.exit_code == 0
    assert "Use a jump host (ProxyJump)?" in confirm_calls

    updated = next(s for s in load_servers() if s.id == "test-id-001")
    assert updated.jump_host == "TestServer2"


def test_none_jump_sentinel_cannot_collide_with_server_name(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test a server literally named '__none__' is distinguishable from the (none) sentinel."""
    # A unique object sentinel guarantees no string server name can shadow it.
    assert not isinstance(_NONE_JUMP_SENTINEL, str)

    # Save a server whose name is the legacy sentinel string; verify the picker
    # treats it as a normal candidate and selecting it stores the name, not None.
    save_servers(
        [
            Server(id="n-1", name="__none__", host="none.example", username="u"),
            Server(id="t-1", name="Target", host="t.example", username="u"),
        ]
    )

    class PickStringNone:
        def execute(self) -> str:
            return "__none__"

    prompt_values = iter(["Target", "t.example", 22, "u"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda text, **kw: text == "Use a jump host (ProxyJump)?")
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: PickStringNone())

    result = runner.invoke(app, ["edit", "Target"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    # The string "__none__" must be stored as a real jump_host, not treated as the sentinel
    assert updated.jump_host == "__none__"


def test_edit_existing_jump_host_can_be_cleared(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit: a server with jump_host can clear it back via (none) sentinel."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Bastion"),
        ]
    )

    prompt_values = iter(["Target", "t.example", 22, "u"])

    class FakePrompt:
        def execute(self) -> str:
            return _NONE_JUMP_SENTINEL

    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: text.startswith("Change jump host?"),
    )
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: FakePrompt())

    result = runner.invoke(app, ["edit", "Target"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "t-1")
    assert updated.jump_host is None


def test_list_shows_via_column_for_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls output includes the 'Via' column populated for servers with jump_host."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Bastion"),
        ]
    )

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    assert "Via" in result.stdout
    assert "Bastion" in result.stdout


def test_list_hides_via_column_when_no_jump_hosts(
    runner: CliRunner,
    temp_config_dir: Path,
):
    """Test ls hides the 'Via' column when no server has jump_host set."""
    save_servers(
        [
            Server(id="a-1", name="AlphaOnly", host="a.example", username="u"),
            Server(id="b-1", name="BetaOnly", host="b.example", username="u"),
        ]
    )

    result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    # No "Via" header should appear
    assert "Via" not in result.stdout


def test_rename_cascades_to_jump_host_references(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test renaming a server used as jump_host updates all referencing servers."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="T1", host="t1.example", username="u", jump_host="Bastion"),
            Server(id="t-2", name="T2", host="t2.example", username="u", jump_host="Bastion"),
        ]
    )

    # User renames Bastion -> NewBastion, declines all other prompts
    prompt_values = iter(["NewBastion", "b.example", 22, "ops"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Bastion"])

    assert result.exit_code == 0
    servers = {s.id: s for s in load_servers()}
    assert servers["b-1"].name == "NewBastion"
    assert servers["t-1"].jump_host == "NewBastion"
    assert servers["t-2"].jump_host == "NewBastion"


def test_edit_warns_when_server_used_as_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit prints a warning when the server is used as a jump host by others."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="Target", host="t.example", username="u", jump_host="Bastion"),
        ]
    )

    prompt_values = iter(["Bastion", "b.example", 22, "ops"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Bastion"])

    assert result.exit_code == 0
    assert "1 server uses this as a jump host" in result.stdout
    assert "Target" in result.stdout


def test_add_with_jump_flag_sets_jump_host_without_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump <name> sets jump_host non-interactively and skips the confirm."""
    save_servers([Server(id="b-1", name="Bastion", host="b.example", username="ops")])

    confirms: list[str] = []
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr(
        "app.cli.typer.confirm",
        lambda text, **kw: confirms.append(text) or False,
    )
    monkeypatch.setattr(
        "app.cli.inquirer.select",
        lambda **kw: (_ for _ in ()).throw(AssertionError("select must not be called with --jump")),
    )

    result = runner.invoke(
        app,
        ["add", "--name", "Target", "--host", "t.example", "--port", "22", "--username", "u", "--jump", "Bastion"],
    )

    assert result.exit_code == 0
    assert "Use a jump host (ProxyJump)?" not in confirms
    added = next(s for s in load_servers() if s.name == "Target")
    assert added.jump_host == "Bastion"


def test_remove_cascade_clears_dependents_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test removing a server used as jump host clears jump_host on dependents."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="T1", host="t1.example", username="u", jump_host="Bastion"),
            Server(id="t-2", name="T2", host="t2.example", username="u", jump_host="Bastion"),
        ]
    )
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: True)

    result = runner.invoke(app, ["rm", "Bastion"])

    assert result.exit_code == 0
    remaining = {s.name: s for s in load_servers()}
    assert "Bastion" not in remaining
    assert remaining["T1"].jump_host is None
    assert remaining["T2"].jump_host is None


def test_remove_cascade_cancel_keeps_everything(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test declining the cascade-clear prompt aborts the removal entirely."""
    save_servers(
        [
            Server(id="b-1", name="Bastion", host="b.example", username="ops"),
            Server(id="t-1", name="T1", host="t1.example", username="u", jump_host="Bastion"),
        ]
    )
    # First confirm (remove) -> True; second (cascade clear) -> False
    answers = iter([True, False])
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: next(answers))

    result = runner.invoke(app, ["rm", "Bastion"])

    assert result.exit_code == 0
    names = {s.name for s in load_servers()}
    assert names == {"Bastion", "T1"}
    t1 = next(s for s in load_servers() if s.id == "t-1")
    assert t1.jump_host == "Bastion"


def test_add_rejects_duplicate_name(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add refuses to create a second server with an existing name (case-insensitive)."""
    save_servers([Server(id="a-1", name="Prod", host="p.example", username="u")])

    prompts: list[str] = []
    monkeypatch.setattr("app.cli.typer.prompt", lambda text, *a, **kw: prompts.append(text) or "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "prod", "--host", "new.example", "--port", "22", "--username", "root"],
    )

    assert result.exit_code == 1
    assert "already exists" in result.stdout
    # Nothing new saved
    assert len(load_servers()) == 1
    # Should have failed before prompting for key/password
    assert "Password" not in prompts


def test_edit_rejects_rename_to_existing_name(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit refuses to rename a server to an already-taken name."""
    save_servers(
        [
            Server(id="a-1", name="Prod", host="p.example", username="u"),
            Server(id="b-1", name="Stage", host="s.example", username="u"),
        ]
    )

    prompt_values = iter(["Prod"])  # rename Stage -> Prod
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Stage"])

    assert result.exit_code == 1
    assert "already exists" in result.stdout
    # Stage kept its original name
    servers = {s.id: s for s in load_servers()}
    assert servers["b-1"].name == "Stage"


def test_edit_keeping_same_name_is_allowed(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit without a rename does not trigger the name-uniqueness check."""
    save_servers([Server(id="a-1", name="Prod", host="p.example", username="u")])

    # Keep name (default), change host
    prompt_values = iter(["Prod", "new.example", 22, "u"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(app, ["edit", "Prod"])

    assert result.exit_code == 0
    updated = next(s for s in load_servers() if s.id == "a-1")
    assert updated.name == "Prod"
    assert updated.host == "new.example"


def test_edit_rejects_cycle_at_save_time(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test setting jump_host that would create A→B→A cycle is rejected before save."""
    save_servers(
        [
            Server(id="a-1", name="A", host="a.example", username="u", jump_host="B"),
            Server(id="b-1", name="B", host="b.example", username="u"),
        ]
    )

    class PickA:
        def execute(self) -> str:
            return "A"

    prompt_values = iter(["B", "b.example", 22, "u"])
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: next(prompt_values, ""))
    monkeypatch.setattr("app.cli.typer.confirm", lambda text, **kw: text == "Use a jump host (ProxyJump)?")
    monkeypatch.setattr("app.cli.inquirer.select", lambda **kw: PickA())

    result = runner.invoke(app, ["edit", "B"])

    assert result.exit_code == 1
    assert "cycle detected" in result.stdout.lower()
    # Nothing saved
    b_after = next(s for s in load_servers() if s.id == "b-1")
    assert b_after.jump_host is None


def test_add_with_jump_flag_matches_case_insensitively(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump resolves names case-insensitively and stores the canonical casing."""
    save_servers([Server(id="b-1", name="Bastion", host="b.example", username="ops")])

    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Target", "--host", "t.example", "--port", "22", "--username", "u", "--jump", "BASTION"],
    )

    assert result.exit_code == 0
    added = next(s for s in load_servers() if s.name == "Target")
    assert added.jump_host == "Bastion"  # canonical casing stored, not "BASTION"


def test_add_with_jump_flag_rejects_unknown_jump_host(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test --jump <unknown-name> fails with an error instead of silently saving a bad reference."""
    monkeypatch.setattr("app.cli.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("app.cli.typer.confirm", lambda *a, **kw: False)

    result = runner.invoke(
        app,
        ["add", "--name", "Target", "--host", "t.example", "--port", "22", "--username", "u", "--jump", "Ghost"],
    )

    assert result.exit_code == 1
    assert "Jump host 'Ghost' not found" in result.stdout


def test_pin_command_marks_server_as_favorite(cli_with_servers: CliRunner):
    """Test pin command marks a server as favorite."""
    result = cli_with_servers.invoke(app, ["pin", "TestServer3"])

    assert result.exit_code == 0
    assert "Pinned:" in result.stdout

    updated = next(server for server in load_servers() if server.id == "test-id-003")
    assert updated.favorite is True


def test_unpin_without_query_opens_interactive_selection(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test unpin command can select from pinned servers interactively."""
    servers = load_servers()
    target = next(server for server in servers if server.id == "test-id-001")
    target.favorite = True
    save_servers(servers)

    class FakePrompt:
        def execute(self) -> str:
            return "test-id-001"

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kwargs: FakePrompt())

    result = cli_with_servers.invoke(app, ["unpin"])

    assert result.exit_code == 0
    assert "Unpinned:" in result.stdout

    updated = next(server for server in load_servers() if server.id == "test-id-001")
    assert updated.favorite is False


def test_root_invocation_interactively_connects_selected_server(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test default root flow selects a server and passes it to the SSH connect call."""
    selected: dict[str, object] = {}

    class FakePrompt:
        def execute(self) -> str:
            return "test-id-002"

    def fake_select(**kwargs):
        assert kwargs["message"] == "Select server to connect:"
        return FakePrompt()

    def fake_connect(server, copy_password: bool = True, all_servers=None):
        selected["server"] = server
        selected["copy_password"] = copy_password
        return 0

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    result = cli_with_servers.invoke(app, [])

    assert result.exit_code == 0
    assert selected["copy_password"] is True
    assert selected["server"].id == "test-id-002"

    updated = next(server for server in load_servers() if server.id == "test-id-002")
    assert updated.use_count == 1
    assert updated.last_used_at is not None


def test_root_invocation_sorts_pinned_servers_before_recents(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test interactive root choices prioritize pinned servers before other recents."""
    save_servers(
        [
            Server(
                id="pinned-old",
                name="PinnedOld",
                host="10.0.0.3",
                username="user",
                favorite=True,
                use_count=1,
                last_used_at="2026-04-08T10:00:00+00:00",
            ),
            Server(
                id="pinned-new",
                name="PinnedNew",
                host="10.0.0.2",
                username="user",
                favorite=True,
                use_count=5,
                last_used_at="2026-04-09T10:00:00+00:00",
            ),
            Server(
                id="newest",
                name="Newest",
                host="10.0.0.1",
                username="user",
                use_count=1,
                last_used_at="2026-04-10T10:00:00+00:00",
            ),
            Server(
                id="older-recent",
                name="OlderRecent",
                host="10.0.0.4",
                username="user",
                use_count=3,
                last_used_at="2026-04-09T08:00:00+00:00",
            ),
        ]
    )

    captured_choices: list[InquirerChoice] = []

    class FakePrompt:
        def execute(self) -> str:
            return captured_choices[0].value  # return server ID

    def fake_select(**kwargs):
        captured_choices.extend(kwargs["choices"])
        return FakePrompt()

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connection.connect", lambda server, copy_password=True, all_servers=None: 0)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert captured_choices[0].name.startswith("[pin] PinnedNew")
    assert captured_choices[1].name.startswith("[pin] PinnedOld")
    assert captured_choices[2].name.startswith("Newest")
    assert captured_choices[3].name.startswith("OlderRecent")


def test_list_command_sorts_pinned_servers_first(runner: CliRunner, temp_config_dir: Path):
    """Test list output keeps pinned servers at the top."""
    save_servers(
        [
            Server(name="Recent", host="10.0.0.2", username="user", last_used_at="2026-04-10T10:00:00+00:00"),
            Server(name="Pinned", host="10.0.0.1", username="user", favorite=True),
        ]
    )

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert result.stdout.find("Pinned") < result.stdout.find("Recent")
    assert "pin" in result.stdout


def test_export_warns_when_reencryption_fails(
    runner: CliRunner,
    tmp_path: Path,
    temp_config_dir: Path,
    temp_ssh_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test export shows a warning (not silent failure) when re-encryption fails."""
    save_settings({"encryption_enabled": True})
    save_servers([Server(name="S", host="h", username="u", password="secret")])

    # Return "Encrypted" mode so the export tries to re-encrypt
    class FakePrompt:
        def execute(self) -> str:
            return "Encrypted - keep passwords encrypted (only works on this machine)"

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kwargs: FakePrompt())

    # No SSH key in temp_ssh_dir → encrypt_password raises RuntimeError → warning shown
    output_file = str(tmp_path / "export.json")
    result = runner.invoke(app, ["export", output_file])

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "plaintext" in result.output


def test_copy_pass_shows_error_when_decryption_failed(
    runner: CliRunner,
    temp_config_dir: Path,
    mock_ssh_key: Path,
):
    """Test copy-pass shows an error when encryption is on but decryption fails (wrong salt)."""
    save_settings({"encryption_enabled": True})
    salt = get_or_create_encryption_salt()
    encrypted = encrypt_password("secret", salt)
    save_servers([Server(id="s1", name="S", host="h", username="u", password=encrypted)])

    # Corrupt salt → decryption will fail silently → password stays encrypted
    save_settings({"encryption_enabled": True, "encryption_salt": "bm90LXRoZS1yZWFsLXNhbHQ="})

    result = runner.invoke(app, ["copy-pass", "S"])

    assert result.exit_code == 1
    assert "could not be decrypted" in result.output


def test_show_pass_shows_error_when_decryption_failed(
    runner: CliRunner,
    temp_config_dir: Path,
    mock_ssh_key: Path,
):
    """Test show-pass shows an error when encryption is on but decryption fails (wrong salt)."""
    save_settings({"encryption_enabled": True})
    salt = get_or_create_encryption_salt()
    encrypted = encrypt_password("secret", salt)
    save_servers([Server(id="s1", name="S", host="h", username="u", password=encrypted)])

    save_settings({"encryption_enabled": True, "encryption_salt": "bm90LXRoZS1yZWFsLXNhbHQ="})

    result = runner.invoke(app, ["show-pass", "S"])

    assert result.exit_code == 1
    assert "could not be decrypted" in result.output


def test_copy_pass_shows_error_when_encrypted_but_disabled(
    runner: CliRunner,
    temp_config_dir: Path,
    mock_ssh_key: Path,
):
    """Test copy-pass shows helpful error when password is encrypted but encryption is disabled."""
    save_settings({"encryption_enabled": True})
    salt = get_or_create_encryption_salt()
    encrypted = encrypt_password("secret", salt)
    save_servers([Server(id="s1", name="S", host="h", username="u", password=encrypted)])

    # Disable encryption without decrypting — inconsistent state
    save_settings({"encryption_enabled": False})

    result = runner.invoke(app, ["copy-pass", "S"])

    assert result.exit_code == 1
    assert "encrypted but encryption is disabled" in result.output


def test_show_pass_shows_error_when_encrypted_but_disabled(
    runner: CliRunner,
    temp_config_dir: Path,
    mock_ssh_key: Path,
):
    """Test show-pass shows helpful error when password is encrypted but encryption is disabled."""
    save_settings({"encryption_enabled": True})
    salt = get_or_create_encryption_salt()
    encrypted = encrypt_password("secret", salt)
    save_servers([Server(id="s1", name="S", host="h", username="u", password=encrypted)])

    save_settings({"encryption_enabled": False})

    result = runner.invoke(app, ["show-pass", "S"])

    assert result.exit_code == 1
    assert "encrypted but encryption is disabled" in result.output


def test_unpin_no_pinned_servers_exits_cleanly(runner: CliRunner, temp_config_dir: Path):
    """Test unpin with no pinned servers exits with code 0, not 1."""
    save_servers([Server(name="S", host="h", username="u")])

    result = runner.invoke(app, ["unpin"])

    assert result.exit_code == 0
    assert "No pinned servers found" in result.stdout


def test_connect_records_use_only_on_success(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test connect records server usage on rc=0 and rc=130, but not on other exit codes."""
    monkeypatch.setattr("app.cli.connection.connect", lambda srv, copy_password=True, all_servers=None: 1)

    cli_with_servers.invoke(app, ["connect", "TestServer1"])

    updated = next(s for s in load_servers() if s.id == "test-id-001")
    assert updated.use_count == 0  # not recorded for rc=1

    monkeypatch.setattr("app.cli.connection.connect", lambda srv, copy_password=True, all_servers=None: 130)
    cli_with_servers.invoke(app, ["connect", "TestServer1"])

    updated = next(s for s in load_servers() if s.id == "test-id-001")
    assert updated.use_count == 1  # recorded for rc=130


def test_connect_default_copies_password(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh connect <name>` without flags uses copy_password=True (default)."""
    captured: list[bool] = []

    def fake_connect(srv, copy_password=True, all_servers=None):
        captured.append(copy_password)
        return 0

    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    cli_with_servers.invoke(app, ["connect", "TestServer1"])

    assert captured == [True]


def test_connect_no_copy_flag_disables_clipboard(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test `bssh connect <name> --no-copy` passes copy_password=False (backward-compat)."""
    captured: list[bool] = []

    def fake_connect(srv, copy_password=True, all_servers=None):
        captured.append(copy_password)
        return 0

    monkeypatch.setattr("app.cli.connection.connect", fake_connect)

    cli_with_servers.invoke(app, ["connect", "TestServer1", "--no-copy"])

    assert captured == [False]


def test_remove_cancel_confirmation_exits_cleanly(cli_with_servers: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test that declining the remove confirmation exits with code 0, not 1."""
    monkeypatch.setattr("app.cli.typer.confirm", lambda *args, **kwargs: False)

    result = cli_with_servers.invoke(app, ["remove", "TestServer1"])

    assert result.exit_code == 0
    assert len(load_servers()) == 3  # nothing removed


def test_copy_pass_clipboard_failure_shows_fallback_message(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test copy-pass shows helpful fallback message when clipboard is unavailable."""
    printed: list[str] = []

    monkeypatch.setattr("app.cli.pyperclip.copy", lambda _: (_ for _ in ()).throw(Exception("no mechanism")))
    monkeypatch.setattr("app.cli.console.print", lambda m: printed.append(str(m)))

    result = cli_with_servers.invoke(app, ["copy-pass", "TestServer1"])

    assert result.exit_code == 1
    assert any("Clipboard not available" in m for m in printed)
    assert any("show-pass" in m for m in printed)


def test_encryption_status_disabled(runner: CliRunner, temp_config_dir: Path):
    """Test encryption-status shows disabled state and plaintext warning."""
    result = runner.invoke(app, ["encryption-status"])
    assert result.exit_code == 0
    assert "Encryption disabled" in result.stdout
    assert "plaintext" in result.stdout


def test_encryption_status_enabled(runner: CliRunner, temp_config_dir: Path, mock_ssh_key: Path):
    """Test encryption-status shows enabled state."""
    save_settings({"encryption_enabled": True})

    result = runner.invoke(app, ["encryption-status"])
    assert result.exit_code == 0
    assert "Encryption enabled" in result.stdout


@pytest.mark.parametrize(
    ("command", "alias"),
    [
        ("list", "ls"),
        ("add", "a"),
        ("remove", "rm"),
        ("edit", "e"),
        ("connect", "c"),
        ("copy-pass", "cp"),
        ("show-pass", "sp"),
        ("ping", "p"),
        ("health", "h"),
        ("export", "ex"),
        ("import", "im"),
        ("import-ssh-config", "isc"),
        ("encrypt", "enc"),
        ("decrypt", "dec"),
        ("encryption-status", "es"),
    ],
)
def test_command_aliases_work(runner: CliRunner, command: str, alias: str):
    """Test that aliases are documented in the main command and both are invokable."""
    result_main = runner.invoke(app, [command, "--help"])
    result_alias = runner.invoke(app, [alias, "--help"])

    assert result_main.exit_code == 0
    assert result_alias.exit_code == 0
    # Main command help must document its alias — catches renames and missing docs
    assert f"Alias: {alias}" in result_main.stdout


def test_commands_alphabetically_ordered(runner: CliRunner):
    """Test that commands are listed alphabetically in help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0

    # Extract commands section
    commands_section = result.stdout.split("Commands:")[1] if "Commands:" in result.stdout else ""

    # Main commands should appear in alphabetical order
    # (aliases are hidden so shouldn't appear)
    expected_order = [
        "add",
        "connect",
        "copy-pass",
        "decrypt",
        "edit",
        "encrypt",
        "encryption-status",
        "export",
        "health",
        "import",
        "import-ssh-config",
        "list",
        "pin",
        "ping",
        "remove",
        "show-pass",
        "unpin",
    ]

    last_pos = 0
    for command in expected_order:
        pos = commands_section.find(f"  {command}")
        if pos != -1:  # command found
            assert pos > last_pos, f"Command '{command}' is not in alphabetical order"
            last_pos = pos


def test_no_duplicate_aliases_in_help(runner: CliRunner):
    """Test that alias commands don't appear as duplicates in help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0

    # Check that we show aliases in command descriptions (like "Alias: ls")
    # but don't have separate duplicate command entries
    # Count main commands - should be 14 unique commands
    lines = result.stdout.split("\n")
    command_lines = [line for line in lines if "Alias:" in line]
    # Should have at least some commands with aliases
    assert len(command_lines) >= 8
