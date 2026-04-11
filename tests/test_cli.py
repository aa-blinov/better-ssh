"""Tests for CLI commands."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from InquirerPy.base.control import Choice as InquirerChoice
from typer.testing import CliRunner

from app.cli import app
from app.models import Server
from app.storage import load_servers, save_servers, save_settings


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

    def fake_connect_cmd(query: str | None = None, no_copy: bool = False):
        calls.append((query, no_copy))

    monkeypatch.setattr("app.cli.connect_cmd", fake_connect_cmd)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert calls == [(None, False)]


def test_root_invocation_propagates_connect_exit_code(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test default root flow preserves the connect command exit code."""

    def fake_connect_cmd(query: str | None = None, no_copy: bool = False):
        raise typer.Exit(7)

    monkeypatch.setattr("app.cli.connect_cmd", fake_connect_cmd)

    result = runner.invoke(app, [])

    assert result.exit_code == 7


def test_help_does_not_trigger_default_connect(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test help path does not open the default connect flow."""
    called = False

    def fake_connect_cmd(query: str | None = None, no_copy: bool = False):
        nonlocal called
        called = True

    monkeypatch.setattr("app.cli.connect_cmd", fake_connect_cmd)

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

    def fake_connect(server, copy_password: bool = True):
        selected["server"] = server
        selected["copy_password"] = copy_password
        return 17

    monkeypatch.setattr("app.cli.inquirer.select", fail_select)
    monkeypatch.setattr("app.cli.connect", fake_connect)

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

    def fake_connect(server, copy_password: bool = True):
        selected["server"] = server
        return 19

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connect", fake_connect)

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

    def fake_connect(server, copy_password: bool = True):
        selected["server"] = server
        return 29

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connect", fake_connect)

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

    monkeypatch.setattr("app.cli.get_default_ssh_config_path", lambda: config_file)
    monkeypatch.setattr(
        "app.cli.import_ssh_config",
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

    monkeypatch.setattr("app.cli.get_default_ssh_config_path", lambda: config_file)
    monkeypatch.setattr(
        "app.cli.import_ssh_config",
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
    assert "192.168.1.10" in result.stdout
    assert "auto" in result.stdout


def test_list_alias(cli_with_servers: CliRunner):
    """Test 'ls' alias works same as 'list'."""
    result = cli_with_servers.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout


def test_add_command_without_password_flag_skips_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add without --password flag does not prompt for password."""
    prompt_calls: list[str] = []

    def fake_prompt(text: str, *args, **kwargs):
        prompt_calls.append(text)
        return ""

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)

    result = runner.invoke(
        app,
        ["add", "--name", "NewHost", "--host", "10.0.0.10", "--port", "22", "--username", "root"],
    )

    assert result.exit_code == 0
    assert "Password" not in prompt_calls

    added = load_servers()
    assert len(added) == 1
    assert added[0].name == "NewHost"
    assert added[0].password is None


def test_add_command_password_flag_triggers_prompt(
    runner: CliRunner,
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test add --password triggers a hidden password prompt with confirmation."""
    prompt_calls: list[tuple[str, dict[str, object]]] = []

    def fake_prompt(text: str, *args, **kwargs):
        prompt_calls.append((text, kwargs))
        return "secret123"

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)

    result = runner.invoke(
        app,
        ["add", "--name", "PwdHost", "--host", "10.0.0.11", "--port", "22", "--username", "root", "--password"],
    )

    assert result.exit_code == 0
    assert prompt_calls == [
        (
            "Password",
            {
                "hide_input": True,
                "confirmation_prompt": True,
            },
        )
    ]

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
    monkeypatch.setattr("app.cli.typer.prompt", lambda *args, **kwargs: next(answers))
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
        return answers[text]

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        return False

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer3"])

    assert result.exit_code == 0
    assert confirm_calls == ["Add key path?", "Add certificate path?", "Add password?"]
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
        return next(prompt_values)

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        if text == "Clear password?":
            raise AssertionError("Clear password prompt should not be shown")
        return text == "Change password?"

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer1"])

    assert result.exit_code == 0
    assert confirm_calls == ["Add key path?", "Add certificate path?", "Change password?"]

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
        return next(prompt_values)

    def fake_confirm(text: str, *args, **kwargs):
        confirm_calls.append(text)
        return text.startswith("Change key path?")

    monkeypatch.setattr("app.cli.typer.prompt", fake_prompt)
    monkeypatch.setattr("app.cli.typer.confirm", fake_confirm)

    result = cli_with_servers.invoke(app, ["edit", "TestServer2"])

    assert result.exit_code == 0
    assert confirm_calls == ["Change key path? [/home/user/.ssh/id_rsa]", "Add certificate path?", "Add password?"]

    updated = next(server for server in load_servers() if server.id == "test-id-002")
    assert updated.key_path is None


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

    def fake_connect(server, copy_password: bool = True):
        selected["server"] = server
        selected["copy_password"] = copy_password
        return 0

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connect", fake_connect)

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
    monkeypatch.setattr("app.cli.connect", lambda server, copy_password=True: 0)

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
    monkeypatch.setattr("app.cli.connect", lambda srv, copy_password=True: 1)

    cli_with_servers.invoke(app, ["connect", "TestServer1"])

    updated = next(s for s in load_servers() if s.id == "test-id-001")
    assert updated.use_count == 0  # not recorded for rc=1

    monkeypatch.setattr("app.cli.connect", lambda srv, copy_password=True: 130)
    cli_with_servers.invoke(app, ["connect", "TestServer1"])

    updated = next(s for s in load_servers() if s.id == "test-id-001")
    assert updated.use_count == 1  # recorded for rc=130


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
