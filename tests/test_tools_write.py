"""Write-tool behavior: dry-run default, forced flags, duplicate gate."""

from fakes import ACCT_CARD, CAT_COFFEE, PAYEE_STARBUCKS, FakeYnab, call, make_server


def test_create_dry_run_default_writes_nothing():
    fake = FakeYnab()
    out = call(
        make_server(fake, allow_writes=True),
        "create_transaction",
        {
            "account": "Credit Card",
            "date": "2026-09-19",
            "amount": "-9.99",
            "payee": "Starbucks",
            "category": "Coffee",
        },
    )
    assert out["dry_run"] is True
    assert out["would_create"]["amount"] == "-9.99"
    assert out["would_create"]["account"]["name"] == "Credit Card"
    assert out["would_create"]["payee"]["name"] == "Starbucks"
    assert out["would_create"]["approved"] is False
    assert out["would_create"]["cleared"] == "uncleared"
    assert fake.created == []


def test_create_real_forces_unapproved_and_uncleared():
    fake = FakeYnab()
    out = call(
        make_server(fake, allow_writes=True),
        "create_transaction",
        {
            "account": "Credit Card",
            "date": "2026-09-19",
            "amount": "-9.99",
            "payee": "Starbucks",
            "category": "Coffee",
            "dry_run": False,
        },
    )
    assert out["dry_run"] is False
    assert out["created"]["id"]
    sent = fake.created[0]
    assert sent["approved"] is False
    assert sent["cleared"] == "uncleared"
    assert sent["amount"] == -9990
    assert sent["account_id"] == ACCT_CARD
    assert sent["payee_id"] == PAYEE_STARBUCKS
    assert sent["category_id"] == CAT_COFFEE


def test_new_payee_name_passes_through():
    fake = FakeYnab()
    out = call(
        make_server(fake, allow_writes=True),
        "create_transaction",
        {
            "account": "Credit Card",
            "date": "2026-09-19",
            "amount": "-5.00",
            "payee": "Brand New Coffee Shop",
            "dry_run": False,
        },
    )
    assert out["dry_run"] is False
    sent = fake.created[0]
    assert sent["payee_name"] == "Brand New Coffee Shop"
    assert "payee_id" not in sent


def test_duplicate_refused_then_override():
    fake = FakeYnab()
    server = make_server(fake, allow_writes=True)
    payload = {
        "account": "Credit Card",
        "date": "2026-09-18",
        "amount": "-7.45",
        "dry_run": False,
    }
    out = call(server, "create_transaction", payload)
    assert out["error"] == "possible_duplicate"
    assert out["matches"][0]["id"] == "t-1"
    assert fake.created == []
    out2 = call(server, "create_transaction", {**payload, "allow_duplicate": True})
    assert out2["dry_run"] is False
    assert len(fake.created) == 1


def test_ambiguous_account_refused_with_candidates():
    out = call(
        make_server(FakeYnab(), allow_writes=True),
        "create_transaction",
        {"account": "e", "date": "2026-09-19", "amount": "-1.00"},
    )
    assert out["error"] == "account_not_resolved"
    assert out["failure"] == "ambiguous"
    assert len(out["candidates"]) >= 2


def test_validation_errors():
    server = make_server(FakeYnab(), allow_writes=True)
    out = call(
        server,
        "create_transaction",
        {
            "account": "Credit Card",
            "date": "2026-09-19",
            "amount": "-1.00",
            "flag_color": "chartreuse",
        },
    )
    assert out["error"] == "invalid_input"
    assert "flag_color" in out["message"]
    out2 = call(
        server,
        "create_transaction",
        {"account": "Credit Card", "date": "09/19/2026", "amount": "-1.00"},
    )
    assert out2["error"] == "invalid_input"
    out3 = call(
        server,
        "create_transaction",
        {"account": "Credit Card", "date": "2026-09-19", "amount": "1.2345"},
    )
    assert out3["error"] == "invalid_input"


def test_bulk_dry_run_then_create():
    fake = FakeYnab()
    server = make_server(fake, allow_writes=True)
    items = [
        {"account": "Credit Card", "date": "2026-09-19", "amount": "-4.50", "payee": "Starbucks"},
        {"account": "Checking", "date": "2026-09-19", "amount": "-12.00", "payee": "Brand New Shop"},
    ]
    out = call(server, "create_transactions", {"transactions": items})
    assert out["dry_run"] is True
    assert out["count"] == 2
    assert fake.created == []
    out2 = call(server, "create_transactions", {"transactions": items, "dry_run": False})
    assert out2["dry_run"] is False
    assert out2["created_count"] == 2
    assert len(fake.created) == 2
    assert all(c["approved"] is False for c in fake.created)


def test_bulk_validation_is_all_or_nothing():
    fake = FakeYnab()
    out = call(
        make_server(fake, allow_writes=True),
        "create_transactions",
        {
            "transactions": [
                {"account": "Credit Card", "date": "2026-09-19", "amount": "-4.50"},
                {"account": "Credit Card", "date": "nope", "amount": "-1.00"},
            ],
            "dry_run": False,
        },
    )
    assert out["error"] == "validation_failed"
    assert out["items"][0]["index"] == 1
    assert fake.created == []


def test_bulk_duplicate_refusal():
    fake = FakeYnab()
    out = call(
        make_server(fake, allow_writes=True),
        "create_transactions",
        {
            "transactions": [{"account": "Credit Card", "date": "2026-09-18", "amount": "-7.45"}],
            "dry_run": False,
        },
    )
    assert out["error"] == "possible_duplicate"
    assert out["duplicates"][0]["index"] == 0
    assert fake.created == []
