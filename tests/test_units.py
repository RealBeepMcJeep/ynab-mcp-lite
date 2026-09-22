"""Unit tests for the pure helpers: money, dates, name resolution, dedupe."""

from datetime import date

import pytest

from ynab_mcp_lite.ynab import (
    ResolveError,
    amount_to_milliunits,
    find_amount_matches,
    flatten_categories,
    milliunits_to_amount,
    parse_amount,
    parse_date,
    resolve_one,
)


def mu(text: str | float) -> int:
    return amount_to_milliunits(parse_amount(text))


class TestMoney:
    def test_strings(self):
        assert mu("12.34") == 12340
        assert mu("-7.45") == -7450
        assert mu("0") == 0
        assert mu("12.345") == 12345

    def test_numbers(self):
        assert mu(12.34) == 12340
        assert mu(-5) == -5000

    def test_rejects_junk(self):
        for bad in ["abc", "1.2345", "1,000", "", None, "1e3"]:
            with pytest.raises(ValueError):
                parse_amount(bad)
        with pytest.raises(TypeError):
            parse_amount(True)

    def test_milliunits_output(self):
        assert milliunits_to_amount(12340) == "12.34"
        assert milliunits_to_amount(-7450) == "-7.45"
        assert milliunits_to_amount(0) == "0"
        assert milliunits_to_amount(500) == "0.5"
        assert milliunits_to_amount(1000) == "1"
        assert milliunits_to_amount(-1005) == "-1.005"


class TestDates:
    def test_ok(self):
        assert parse_date("2026-09-01") == date(2026, 9, 1)

    def test_rejects(self):
        for bad in ["09/01/2026", "2026-9-1", "2026-13-01", "", "20260901"]:
            with pytest.raises(ValueError):
                parse_date(bad)


ACCOUNTS = [
    {"id": "a-1", "name": "Checking", "deleted": False},
    {"id": "a-2", "name": "Credit Card", "deleted": False},
    {"id": "a-3", "name": "Checking Plus", "deleted": False},
    {"id": "a-4", "name": "Gone", "deleted": True},
]


class TestResolve:
    def test_exact_id(self):
        assert resolve_one("account", ACCOUNTS, "a-2")["name"] == "Credit Card"

    def test_case_insensitive_name(self):
        assert resolve_one("account", ACCOUNTS, "credit card")["id"] == "a-2"

    def test_unique_substring(self):
        assert resolve_one("account", ACCOUNTS, "Plus")["id"] == "a-3"

    def test_ambiguous_substring(self):
        with pytest.raises(ResolveError) as ei:
            resolve_one("account", ACCOUNTS, "check")
        assert ei.value.failure == "ambiguous"
        assert len(ei.value.candidates) == 2

    def test_not_found(self):
        with pytest.raises(ResolveError) as ei:
            resolve_one("account", ACCOUNTS, "savings")
        assert ei.value.failure == "not_found"

    def test_unknown_uuid_is_invalid_id(self):
        with pytest.raises(ResolveError) as ei:
            resolve_one("account", ACCOUNTS, "99999999-9999-9999-9999-999999999999")
        assert ei.value.failure == "invalid_id"

    def test_deleted_skipped(self):
        with pytest.raises(ResolveError):
            resolve_one("account", ACCOUNTS, "Gone")


class TestDedupe:
    def test_window(self):
        txs = [
            {"id": "x", "date": "2026-09-18", "amount": -7450},
            {"id": "y", "date": "2026-09-05", "amount": -7450},
            {"id": "z", "date": "2026-09-18", "amount": -1000},
        ]
        hits = find_amount_matches(txs, -7450, date(2026, 9, 16), 10)
        assert [h["id"] for h in hits] == ["x"]

    def test_exact_boundary_included(self):
        txs = [{"id": "x", "date": "2026-09-06", "amount": -100}]
        assert find_amount_matches(txs, -100, date(2026, 9, 16), 10)

    def test_deleted_and_garbage_skipped(self):
        txs = [
            {"id": "d", "date": "2026-09-18", "amount": -100, "deleted": True},
            {"id": "g", "date": "junk", "amount": -100},
        ]
        assert find_amount_matches(txs, -100, date(2026, 9, 18), 5) == []


class TestFlattenCategories:
    def test_flat_shape(self):
        plan = {
            "categories": [
                {"id": "c1", "name": "A", "category_group_name": "G", "deleted": False},
                {"id": "c2", "name": "B", "deleted": True},
            ],
            "category_groups": [],
        }
        cats = flatten_categories(plan)
        assert [c["id"] for c in cats] == ["c1"]
        assert cats[0]["_group"] == "G"

    def test_nested_shape_and_group_lookup(self):
        plan = {
            "categories": [{"id": "c1", "name": "A", "category_group_id": "g1", "deleted": False}],
            "category_groups": [
                {
                    "id": "g1",
                    "name": "Group",
                    "deleted": False,
                    "categories": [{"id": "c1", "name": "A", "deleted": False}],
                }
            ],
        }
        cats = flatten_categories(plan)
        assert cats[0]["_group"] == "Group"
