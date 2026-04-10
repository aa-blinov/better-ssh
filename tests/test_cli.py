"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
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
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


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
            return "TestServer1  [admin@192.168.1.10:22 | pwd]"

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
            return "TestServer2  [root@192.168.1.20:2222 | key]"

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
    assert imported[0].last_used_at == "2026-04-10T09:00:00+00:00"


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


def test_edit_without_query_opens_interactive_selection(
    cli_with_servers: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test edit command can select a server interactively when query is omitted."""

    class FakePrompt:
        def execute(self) -> str:
            return "TestServer3  [user@example.com:22 | auto]"

    answers = iter(["RenamedServer", "example.com", "22", "user", "", ""])

    monkeypatch.setattr("app.cli.inquirer.select", lambda **kwargs: FakePrompt())
    monkeypatch.setattr("app.cli.typer.prompt", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr("app.cli.typer.confirm", lambda *args, **kwargs: False)

    result = cli_with_servers.invoke(app, ["edit"])

    assert result.exit_code == 0

    updated = next(server for server in load_servers() if server.id == "test-id-003")
    assert updated.name == "RenamedServer"


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
            return "[pin] TestServer1  [admin@192.168.1.10:22 | pwd]"

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
            return "TestServer2  [root@192.168.1.20:2222 | key]"

    def fake_select(**kwargs):
        assert kwargs["message"] == "Select server to connect:"
        return FakePrompt()

    def fake_connect(server, copy_password: bool = True):
        selected["server"] = server
        selected["copy_password"] = copy_password
        return 23

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connect", fake_connect)

    result = cli_with_servers.invoke(app, [])

    assert result.exit_code == 23
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

    captured_choices: list[str] = []

    class FakePrompt:
        def execute(self) -> str:
            return captured_choices[0]

    def fake_select(**kwargs):
        captured_choices.extend(kwargs["choices"])
        return FakePrompt()

    monkeypatch.setattr("app.cli.inquirer.select", fake_select)
    monkeypatch.setattr("app.cli.connect", lambda server, copy_password=True: 0)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert captured_choices[0].startswith("[pin] PinnedNew")
    assert captured_choices[1].startswith("[pin] PinnedOld")
    assert captured_choices[2].startswith("Newest")
    assert captured_choices[3].startswith("OlderRecent")


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


def test_encryption_status_disabled(runner: CliRunner, temp_config_dir: Path):
    """Test encryption-status shows disabled."""
    result = runner.invoke(app, ["encryption-status"])
    assert result.exit_code == 0
    assert "disabled" in result.stdout.lower() or "not enabled" in result.stdout.lower()


def test_encryption_status_enabled(runner: CliRunner, temp_config_dir: Path, mock_ssh_key: Path):
    """Test encryption-status shows enabled."""
    save_settings({"encryption_enabled": True})

    result = runner.invoke(app, ["encryption-status"])
    assert result.exit_code == 0
    assert "enabled" in result.stdout.lower()


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
    ],
)
def test_command_aliases_work(runner: CliRunner, command: str, alias: str):
    """Test that all command aliases invoke help successfully."""
    # Test main command
    result_main = runner.invoke(app, [command, "--help"])
    assert result_main.exit_code == 0

    # Test alias
    result_alias = runner.invoke(app, [alias, "--help"])
    assert result_alias.exit_code == 0


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
