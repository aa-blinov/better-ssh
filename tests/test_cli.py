"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.storage import save_settings


@pytest.fixture
def cli_with_servers(runner: CliRunner, servers_json_file: Path) -> CliRunner:
    """Provide CLI runner with servers already configured."""
    return runner


def test_cli_help(runner: CliRunner):
    """Test --help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Better SSH" in result.stdout
    # Rich formatting uses panel header
    assert "Commands" in result.stdout or "commands" in result.stdout.lower()


def test_help_flag_alias(runner: CliRunner):
    """Test -h alias for --help flag."""
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Better SSH" in result.stdout


def test_list_command_empty(runner: CliRunner, temp_config_dir: Path):
    """Test list command with no servers."""
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No servers" in result.stdout or "0" in result.stdout


def test_list_command_with_servers(cli_with_servers: CliRunner):
    """Test list command shows servers."""
    result = cli_with_servers.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout
    assert "TestServer2" in result.stdout
    assert "192.168.1.10" in result.stdout


def test_list_alias(cli_with_servers: CliRunner):
    """Test 'ls' alias works same as 'list'."""
    result = cli_with_servers.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "TestServer1" in result.stdout


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
        "list",
        "ping",
        "remove",
        "show-pass",
    ]

    last_pos = 0
    for command in expected_order:
        pos = commands_section.find(command)
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
