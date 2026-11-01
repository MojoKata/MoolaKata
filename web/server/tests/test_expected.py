"""Statements expected (requirements S1.11.7): the interval by type, learned from what arrives,
and when the next statement is overdue."""

import datetime as dt
from types import SimpleNamespace as NS

from edits import edit, saved

from moolakata.ledger import expected


def acct(type_="checking", kept='["file"]', every=None, dismissed=None):
    return NS(
        type=type_, keptBy=kept, statementInterval=every, statementIntervalDismissed=dismissed
    )


def imp(*ends):
    return [NS(coveredTo=e, format="statement") for e in ends]


def test_the_default_follows_the_type():
    d = expected.default_interval
    assert d("checking", ["file"]) == "monthly"
    assert d("credit-card", ["file"]) == "monthly"
    assert d("roth-ira", ["file"]) == "monthly"
    assert d("401k", ["file"]) == "quarterly"
    assert d("529", ["file"]) == "quarterly"
    assert d("checking", ["manual"]) == "none"
    assert d("crypto-wallet", ["bitcoin"]) == "none"
    assert d("real-estate", ["file"]) == "none"
    assert expected.interval(acct(every="yearly")) == "yearly"


def test_overdue_after_the_interval_and_its_grace():
    a = acct()
    ends = imp(dt.date(2026, 7, 31), dt.date(2026, 8, 31))
    assert expected.overdue(a, ends, dt.date(2026, 10, 14)) is None
    late = expected.overdue(a, ends, dt.date(2026, 10, 15))
    assert (late.periodStart, late.periodEnd, late.due) == (
        dt.date(2026, 9, 1),
        dt.date(2026, 9, 30),
        dt.date(2026, 10, 15),
    )
    assert late.name == "the September statement"
    q = expected.overdue(acct("401k"), imp(dt.date(2026, 6, 30)), dt.date(2026, 10, 30))
    assert (q.periodEnd, q.due, q.name) == (
        dt.date(2026, 9, 30),
        dt.date(2026, 10, 30),
        "the July–September statement",
    )
    y = expected.overdue(acct(every="yearly"), imp(dt.date(2025, 12, 31)), dt.date(2027, 3, 1))
    assert (y.due, y.name) == (dt.date(2027, 3, 1), "the 2026 statement")
    assert expected.overdue(acct(every="none"), ends, dt.date(2030, 1, 1)) is None
    assert expected.overdue(a, [], dt.date(2030, 1, 1)) is None


def test_the_interval_is_learned_from_three_and_a_dismissed_one_isnt_proposed_again():
    quarters = imp(dt.date(2026, 3, 31), dt.date(2026, 6, 30), dt.date(2026, 9, 30))
    assert expected.learned(quarters[:2]) is None
    assert expected.learned(quarters) == "quarterly"
    a = acct()
    assert expected.proposal(a, quarters) == "quarterly"
    assert expected.proposal(acct(every="quarterly"), quarters) is None
    assert expected.proposal(acct(dismissed="quarterly"), quarters) is None
    weekly = imp(*(dt.date(2026, 9, d) for d in (1, 8, 15, 22)))
    assert expected.learned(weekly) is None


def test_the_account_sets_its_interval_and_answers_the_proposal(server):
    from conftest import make_user, sign_in
    from test_accounts import new_account

    from moolakata import ids
    from moolakata.store.entities.accounts import Import

    alice = make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, keptBy=["file"])
    assert (a["statementInterval"], a["statementIntervalDefault"]) == (None, "monthly")
    with server.db.tx(unscoped="test") as s:
        for end in (dt.date(2026, 3, 31), dt.date(2026, 6, 30), dt.date(2026, 9, 30)):
            s.add(
                Import(
                    id=ids.new_id("Imprt"),
                    accountId=a["id"],
                    userId=alice.id,
                    format="statement",
                    fileName=f"{end}.pdf",
                    fileHash=str(end),
                    coveredFrom=end.replace(day=1),
                    coveredTo=end,
                )
            )
    d = c.get(f"/ui/api/accounts/{a['id']}").json()
    assert d["statementIntervalProposal"] == "quarterly"
    path = f"/ui/api/accounts/{a['id']}"
    r = edit(c, "Acct", path, statementIntervalDismissed="quarterly")
    assert saved(r)["statementIntervalProposal"] is None
    r = edit(c, "Acct", path, statementInterval="weekly")
    assert r.json()["errors"][0]["code"] == "statement-interval-invalid"
    assert saved(edit(c, "Acct", path, statementInterval="yearly"))["statementInterval"] == "yearly"
    out = saved(edit(c, "Acct", path, statementInterval=None))
    assert out["statementInterval"] is None, "back to the type's"
