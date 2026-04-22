"""Unit tests for pure domain helpers (currently housed in app.cli).

These functions contain no I/O, no Typer, no Rich — they're plain logic over
Server objects. Testing them directly avoids the overhead of CliRunner and
pins down the contract before these helpers are extracted into app.domain.
"""

from __future__ import annotations

from app.cli import (
    _check_jump_cycle,
    _jump_host_usage_map,
    _name_conflict,
    _parse_tags,
    _servers_matching_query,
    _sort_servers,
)
from app.models import Server

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
