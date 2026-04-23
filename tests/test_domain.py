"""Unit tests for pure domain helpers (currently housed in app.cli).

These functions contain no I/O, no Typer, no Rich — they're plain logic over
Server objects. Testing them directly avoids the overhead of CliRunner and
pins down the contract before these helpers are extracted into app.domain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import (
    check_jump_cycle,
    format_relative_time,
    jump_host_usage_map,
    name_conflict,
    parse_env_spec,
    parse_forward_spec,
    parse_tags,
    servers_matching_query,
    sort_servers,
)
from app.models import Server

# Keep original underscore-prefixed aliases so existing test bodies stay readable
# with their original call sites (these mirror the pre-refactor internal names).
_check_jump_cycle = check_jump_cycle
_jump_host_usage_map = jump_host_usage_map
_name_conflict = name_conflict
_parse_tags = parse_tags
_servers_matching_query = servers_matching_query
_sort_servers = sort_servers

# ---------------------------------------------------------------------------
# _parse_tags
# ---------------------------------------------------------------------------


def test_parse_tags_trims_whitespace_and_skips_empty():
    assert _parse_tags("  prod ,  ,  db  ") == ["prod", "db"]


def test_parse_tags_deduplicates_case_insensitively_keeping_first_casing():
    assert _parse_tags("Prod, PROD, prod, DB") == ["Prod", "DB"]


def test_parse_tags_empty_string_yields_empty_list():
    assert _parse_tags("") == []
    assert _parse_tags(",,,") == []


# ---------------------------------------------------------------------------
# _name_conflict
# ---------------------------------------------------------------------------


def test_name_conflict_is_case_insensitive():
    servers = [Server(id="a", name="Prod", host="h", username="u")]
    conflict = _name_conflict("prod", servers)
    assert conflict is not None
    assert conflict.id == "a"


def test_name_conflict_excludes_given_id():
    servers = [Server(id="a", name="Prod", host="h", username="u")]
    # When editing "a" itself, its own name should not register as conflict
    assert _name_conflict("Prod", servers, exclude_id="a") is None


def test_name_conflict_ignores_whitespace_only_input():
    servers = [Server(id="a", name="Prod", host="h", username="u")]
    assert _name_conflict("   ", servers) is None


def test_name_conflict_returns_none_when_unique():
    servers = [Server(id="a", name="Prod", host="h", username="u")]
    assert _name_conflict("Stage", servers) is None


# ---------------------------------------------------------------------------
# _check_jump_cycle
# ---------------------------------------------------------------------------


def test_check_jump_cycle_no_jump_is_none():
    srv = Server(id="a", name="A", host="h", username="u")
    assert _check_jump_cycle([srv], srv) is None


def test_check_jump_cycle_valid_single_hop_is_none():
    b = Server(id="b", name="B", host="h", username="u")
    a = Server(id="a", name="A", host="h", username="u", jump_host="B")
    assert _check_jump_cycle([a, b], a) is None


def test_check_jump_cycle_two_way_cycle_detected():
    a = Server(id="a", name="A", host="h", username="u", jump_host="B")
    b = Server(id="b", name="B", host="h", username="u", jump_host="A")
    err = _check_jump_cycle([a, b], a)
    assert err is not None
    assert "cycle" in err.lower()


def test_check_jump_cycle_self_reference_detected():
    a = Server(id="a", name="A", host="h", username="u", jump_host="A")
    err = _check_jump_cycle([a], a)
    assert err is not None
    assert "cycle" in err.lower()


def test_check_jump_cycle_missing_reference_reported():
    a = Server(id="a", name="A", host="h", username="u", jump_host="Ghost")
    err = _check_jump_cycle([a], a)
    assert err is not None
    assert "not found" in err.lower()


# ---------------------------------------------------------------------------
# _jump_host_usage_map
# ---------------------------------------------------------------------------


def test_jump_host_usage_map_counts_references():
    servers = [
        Server(id="b", name="Bastion", host="h", username="u"),
        Server(id="t1", name="T1", host="h", username="u", jump_host="Bastion"),
        Server(id="t2", name="T2", host="h", username="u", jump_host="Bastion"),
        Server(id="t3", name="T3", host="h", username="u"),
    ]
    usage = _jump_host_usage_map(servers)
    assert usage == {"Bastion": 2}


def test_jump_host_usage_map_empty_when_no_jumps():
    servers = [Server(id="a", name="A", host="h", username="u")]
    assert _jump_host_usage_map(servers) == {}


# ---------------------------------------------------------------------------
# _servers_matching_query
# ---------------------------------------------------------------------------


def test_servers_matching_query_by_name_substring():
    servers = [
        Server(id="a", name="prod-web", host="h1", username="u"),
        Server(id="b", name="dev-web", host="h2", username="u"),
    ]
    match = _servers_matching_query(servers, "prod")
    assert [s.name for s in match] == ["prod-web"]


def test_servers_matching_query_by_tag():
    servers = [
        Server(id="a", name="A", host="h", username="u", tags=["prod", "db"]),
        Server(id="b", name="B", host="h", username="u", tags=["dev"]),
    ]
    match = _servers_matching_query(servers, "prod")
    assert [s.name for s in match] == ["A"]


def test_servers_matching_query_by_jump_host():
    servers = [
        Server(id="b", name="Bastion", host="h", username="u"),
        Server(id="t", name="Target", host="h", username="u", jump_host="Bastion"),
        Server(id="o", name="Other", host="h", username="u"),
    ]
    match = _servers_matching_query(servers, "bastion")
    names = {s.name for s in match}
    # Both the bastion itself and anyone referencing it must surface
    assert names == {"Bastion", "Target"}


def test_servers_matching_query_by_id_prefix():
    servers = [
        Server(id="abc-123", name="A", host="h", username="u"),
        Server(id="def-456", name="B", host="h", username="u"),
    ]
    match = _servers_matching_query(servers, "abc")
    assert [s.name for s in match] == ["A"]


def test_servers_matching_query_no_match_is_empty():
    servers = [Server(id="a", name="A", host="h", username="u")]
    assert _servers_matching_query(servers, "zzz") == []


# ---------------------------------------------------------------------------
# _sort_servers
# ---------------------------------------------------------------------------


def test_sort_servers_pinned_first():
    servers = [
        Server(id="a", name="Alpha", host="h", username="u", favorite=False),
        Server(id="b", name="Beta", host="h", username="u", favorite=True),
    ]
    ordered = _sort_servers(servers)
    assert [s.name for s in ordered] == ["Beta", "Alpha"]


def test_sort_servers_within_pinned_by_use_count():
    servers = [
        Server(id="a", name="Alpha", host="h", username="u", favorite=True, use_count=1),
        Server(id="b", name="Beta", host="h", username="u", favorite=True, use_count=10),
    ]
    ordered = _sort_servers(servers)
    assert [s.name for s in ordered] == ["Beta", "Alpha"]


def test_sort_servers_stable_fallback_to_name():
    servers = [
        Server(id="a", name="Charlie", host="h", username="u"),
        Server(id="b", name="Alpha", host="h", username="u"),
        Server(id="c", name="Bravo", host="h", username="u"),
    ]
    ordered = _sort_servers(servers)
    assert [s.name for s in ordered] == ["Alpha", "Bravo", "Charlie"]


# ---------------------------------------------------------------------------
# parse_forward_spec
# ---------------------------------------------------------------------------


def test_parse_forward_local_without_bind():
    f = parse_forward_spec("5432:localhost:5432", "local")
    assert f.type == "local"
    assert f.bind_host is None
    assert f.local_port == 5432
    assert f.remote_host == "localhost"
    assert f.remote_port == 5432


def test_parse_forward_local_with_bind():
    f = parse_forward_spec("127.0.0.1:8080:web:80", "local")
    assert f.type == "local"
    assert f.bind_host == "127.0.0.1"
    assert f.local_port == 8080
    assert f.remote_host == "web"
    assert f.remote_port == 80


def test_parse_forward_remote_mirrors_local_syntax():
    f = parse_forward_spec("9000:internal:9000", "remote")
    assert f.type == "remote"
    assert f.local_port == 9000


def test_parse_forward_dynamic_port_only():
    f = parse_forward_spec("1080", "dynamic")
    assert f.type == "dynamic"
    assert f.bind_host is None
    assert f.local_port == 1080
    assert f.remote_host is None


def test_parse_forward_dynamic_with_bind():
    f = parse_forward_spec("127.0.0.1:1080", "dynamic")
    assert f.type == "dynamic"
    assert f.bind_host == "127.0.0.1"
    assert f.local_port == 1080


def test_parse_forward_roundtrip_via_to_ssh_spec():
    for spec, kind in [
        ("5432:localhost:5432", "local"),
        ("127.0.0.1:8080:web:80", "local"),
        ("9000:internal:9000", "remote"),
        ("1080", "dynamic"),
        ("127.0.0.1:1080", "dynamic"),
    ]:
        f = parse_forward_spec(spec, kind)
        assert f.to_ssh_spec() == spec


def test_parse_forward_rejects_empty_string():
    with pytest.raises(ValueError, match="Empty"):
        parse_forward_spec("", "local")


def test_parse_forward_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unknown forward kind"):
        parse_forward_spec("5432:localhost:5432", "lateral")


def test_parse_forward_rejects_malformed_local():
    with pytest.raises(ValueError, match="Invalid local forward"):
        parse_forward_spec("5432:localhost", "local")
    with pytest.raises(ValueError, match="Invalid local forward"):
        parse_forward_spec("a:b:c:d:e", "local")


def test_parse_forward_rejects_malformed_dynamic():
    with pytest.raises(ValueError, match="Invalid dynamic forward"):
        parse_forward_spec("a:b:c", "dynamic")


def test_parse_forward_rejects_non_integer_port():
    with pytest.raises(ValueError, match="Invalid port"):
        parse_forward_spec("notaport:localhost:5432", "local")
    with pytest.raises(ValueError, match="Invalid port"):
        parse_forward_spec("notaport", "dynamic")


def test_parse_forward_rejects_empty_remote_host():
    with pytest.raises(ValueError, match="remote host is empty"):
        parse_forward_spec("5432::5432", "local")


# ---------------------------------------------------------------------------
# format_relative_time
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)


def test_format_relative_time_seconds_ago_is_just_now():
    assert format_relative_time(_NOW - timedelta(seconds=30), now=_NOW) == "just now"


def test_format_relative_time_minutes_ago():
    assert format_relative_time(_NOW - timedelta(minutes=5), now=_NOW) == "5m ago"
    assert format_relative_time(_NOW - timedelta(minutes=59), now=_NOW) == "59m ago"


def test_format_relative_time_hours_ago():
    assert format_relative_time(_NOW - timedelta(hours=1), now=_NOW) == "1h ago"
    assert format_relative_time(_NOW - timedelta(hours=23), now=_NOW) == "23h ago"


def test_format_relative_time_days_ago():
    assert format_relative_time(_NOW - timedelta(days=1), now=_NOW) == "1d ago"
    assert format_relative_time(_NOW - timedelta(days=29), now=_NOW) == "29d ago"


def test_format_relative_time_older_than_month_falls_back_to_iso_date():
    result = format_relative_time(_NOW - timedelta(days=60), now=_NOW)
    # Should be an ISO date (YYYY-MM-DD), not "Xd ago"
    assert result.startswith("20")
    assert len(result) == 10  # YYYY-MM-DD


def test_format_relative_time_accepts_naive_datetime_as_utc():
    # A naive datetime should not crash; we treat it as UTC.
    naive = (_NOW - timedelta(minutes=10)).replace(tzinfo=None)
    assert format_relative_time(naive, now=_NOW) == "10m ago"


# ---------------------------------------------------------------------------
# parse_env_spec
# ---------------------------------------------------------------------------


def test_parse_env_spec_basic():
    assert parse_env_spec("LANG=en_US.UTF-8") == ("LANG", "en_US.UTF-8")


def test_parse_env_spec_empty_value_allowed():
    assert parse_env_spec("FOO=") == ("FOO", "")


def test_parse_env_spec_value_can_contain_equals():
    # Partitions on the first '=' so values with extra '=' survive verbatim
    assert parse_env_spec("PS1=user@host:") == ("PS1", "user@host:")
    assert parse_env_spec("EQ=a=b=c") == ("EQ", "a=b=c")


def test_parse_env_spec_trims_key_whitespace():
    assert parse_env_spec("  LANG  =en_US") == ("LANG", "en_US")


def test_parse_env_spec_missing_equals_rejected():
    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        parse_env_spec("JUSTTEXT")


def test_parse_env_spec_empty_key_rejected():
    with pytest.raises(ValueError, match="empty key"):
        parse_env_spec("=value")


def test_parse_env_spec_whitespace_in_key_rejected():
    with pytest.raises(ValueError, match="whitespace"):
        parse_env_spec("BAD KEY=value")
