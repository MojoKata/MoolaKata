"""The small modules at their edges: what each gives back when there is nothing there to work
with, and the few refusals they make on their own."""

import datetime as dt
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moolakata import errors, exactjson, figures, ids, money, ratelimit, tokens
from moolakata.app import Server
from moolakata.errors import Problem


def test_a_locked_server_answers_its_defaults_with_no_store(config):
    """S13.6: before the unlock, what the middleware asks of the server needs no store: no
    badges, no session, the upload limits as configured, every address allowed, and the
    longest session's age."""
    srv = Server(config=config)
    assert srv.badges(SimpleNamespace(id="User_a", admin=True)) == {}
    assert srv.session_user("a token") is None
    assert srv.import_cap() == srv.upload_limit == srv.upload_cap()
    assert srv.network_ranges() == {}
    assert srv.session_max_age() == 30 * 86400


def test_an_error_no_route_expected_is_a_500_named_by_its_logged_id(caplog):
    """S13.8.3, S13.7.8: an unhandled error answers a problem with an error id, the same as in
    the log, and nothing of the error itself."""
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("account Shaw Checking at /data/moolakata.db")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    body = r.json()
    assert (r.status_code, body["code"]) == (500, "server-error")
    assert body["detail"] == (
        "Something went wrong. An admin can find it in the log by its error id."
    )
    assert "Shaw" not in r.text and "/data" not in r.text
    assert f"unhandled error {body['errorId']} on GET /boom" in caplog.text


def test_ids_made_faster_than_the_counter_runs_stay_in_order(monkeypatch):
    """schema.md §2: past 4,096 ids in one millisecond the next is the next millisecond's, so
    ids still sort by when they were made."""
    monkeypatch.setattr(ids, "_last", (10**12, 0xFFF))
    monkeypatch.setattr(ids.time, "time_ns", lambda: 10**12 * 1_000_000)
    u = ids.uuid7()
    assert u.int >> 80 == 10**12 + 1 and (u.int >> 64) & 0xFFF == 0
    assert ids.decode(ids.encode(u)) == u


@pytest.mark.parametrize("prefix", ["acct", "Account", "A1", "", "Acc_t"])
def test_a_prefix_not_of_the_schemas_form_makes_no_id(prefix):
    with pytest.raises(ValueError, match="bad prefix"):
        ids.new_id(prefix)


def test_an_ids_prefix_is_what_comes_before_its_underscore():
    assert ids.prefix_of("Acct_01m87csva1frytapg0xjcvx7cw") == "Acct"
    assert ids.prefix_of("nothing") == "nothing"


def test_no_quantity_is_written_as_none():
    assert money.quantity_str(None) is None
    assert money.quantity_str(Decimal("-0.000")) == "0"


def test_exact_json_refuses_what_isnt_json_unless_told_how():
    with pytest.raises(TypeError, match="set is not JSON"):
        exactjson.dumps({"a": {1}})
    assert exactjson.dumps({"a": {1}, "b": Decimal("1.50")}, default=sorted) == (
        '{"a": [1], "b": 1.50}'
    )


def test_a_range_from_the_start_begins_at_the_earliest_day_or_today():
    today = dt.date(2026, 10, 13)
    assert figures.first_day("All", today, dt.date(2019, 3, 1)) == dt.date(2019, 3, 1)
    assert figures.first_day("All", today, None) == today


def test_a_sign_in_failure_past_its_window_no_longer_slows_the_username():
    """S13.7.5.1: a failure older than the window no longer counts toward the slowing."""
    now = [0.0]
    g = ratelimit.SignInGuard(clock=lambda: now[0])
    for at in (0.0, 1.0, 2.0, 3.0, 400.0):
        now[0] = at
        g.failed("jane", "10.0.0.5")
    now[0] = 402.0
    assert g.delay("jane", "10.0.0.6") > 0, "five failures: slowed"
    now[0] = g.WINDOW + 3.0
    assert g.delay("jane", "10.0.0.6") == 0, "the first four lapsed: one left"


def test_a_token_whose_owner_has_no_email_is_told_nobody(unscoped):
    s, _ = unscoped
    sent = []
    svc = SimpleNamespace(mailer=SimpleNamespace(send=lambda *a: sent.append(a)))
    tokens.tell_made(s, svc, SimpleNamespace(email=None), SimpleNamespace(name="Claude"))
    assert sent == []


def test_a_chosen_items_token_ignores_an_item_of_no_kind_it_reads():
    t = SimpleNamespace(
        items=json.dumps([{"kind": "account", "id": "Acct_1"}, {"kind": "budget", "id": "Bdgt_1"}])
    )
    assert tokens.chosen(t) == {"account": {"Acct_1"}, "portfolio": set()}


def test_no_accounts_no_instruments_or_nothing_owed_finds_nothing(unscoped):
    from moolakata import reimbursements, valuation

    s, owner = unscoped
    assert reimbursements.marked(s, []) == []
    paid = reimbursements.Awaiting("Txn_1", None, "Acct_1", dt.date(2026, 1, 2), "Air",
                                   None, None, Decimal("50"), Decimal("50"))  # fmt: skip
    assert reimbursements.offers(s, paid, ["Acct_1"]) == []
    owed = reimbursements.Awaiting("Txn_1", None, "Acct_1", dt.date(2026, 1, 2), "Air",
                                   None, None, Decimal("50"), Decimal("0"))  # fmt: skip
    assert reimbursements.offers(s, owed, []) == []
    assert valuation._tiers(s, [], dt.date(2026, 1, 1), dt.date(2026, 2, 1), owner) == {}


def test_an_option_value_for_what_isnt_an_option_is_none(unscoped):
    from moolakata import valuation

    s, owner = unscoped
    assert valuation.intrinsic(s, "Instr_not_an_option", dt.date(2026, 1, 2), owner) is None


@pytest.mark.parametrize("kind", ["receipt", "transaction", ""])
def test_a_kind_that_isnt_shared_is_not_found(unscoped, kind):
    from moolakata import sharing

    s, _ = unscoped
    for find in (lambda: sharing.share_entity(kind), lambda: sharing.item(s, kind, "x")):
        with pytest.raises(Problem) as e:
            find()
        assert (e.value.status, e.value.code) == (404, "not-found")


def test_a_shared_item_gone_or_never_made_is_not_found(unscoped):
    from moolakata import sharing

    s, _ = unscoped
    with pytest.raises(Problem) as e:
        sharing.item(s, "budget", "Bdgt_never")
    assert (e.value.status, e.value.code) == (404, "not-found")
