"""A tag's uses (requirements S12.18.12): how many records the caller sees carry it, so a tag
box lists the most used first. Records deleted, and records the caller no longer sees, don't
count."""

from conftest import make_user, sign_in
from edits import change, make, remove, share, tag
from test_accounts import add, new_account


def uses(c) -> dict[str, int]:
    return {t["name"]: t["uses"] for t in c.get("/ui/api/tags").json()["items"]}


def test_a_tag_counts_the_records_the_caller_sees_carrying_it(server):
    u = {n: make_user(server, n) for n in ("jane", "john")}
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    own = new_account(jane)
    make(jane, "Txn", accountId=own["id"], date="2026-09-01", amount="-4.00", tags=["work"])
    make(jane, "Txn", accountId=own["id"], date="2026-09-02", amount="-5.00",
         tags=["work", "coffee"])  # fmt: skip
    gone = make(jane, "Txn", accountId=own["id"], date="2026-09-03", amount="-6.00",
                tags=["work"])  # fmt: skip
    make(jane, "Rule", payeeMatch="blue bottle", tags=["coffee"])
    assert uses(jane) == {"coffee": 2, "work": 3}

    # A deleted transaction no longer counts.
    assert remove(jane, "Txn", gone.json()).status_code == 200
    assert uses(jane) == {"coffee": 2, "work": 2}

    # Jane's tag on John's shared account counts while she sees it, and not once she doesn't.
    theirs = new_account(john, name="Joint")
    assert share(john, "account", theirs["id"], users={u["jane"].id: "write"}).status_code == 200
    add(jane, theirs["id"], "-7.00", payee="Lunch")
    t = next(x for x in jane.get("/ui/api/transactions").json()["items"] if x["payee"] == "Lunch")
    r = change(jane, "Txn", t, tagIds={"add": [tag(jane, "work")], "remove": []})
    assert r.status_code == 200, r.text
    assert uses(jane)["work"] == 3
    assert share(john, "account", theirs["id"], users={u["jane"].id: "none"}).status_code == 200
    assert uses(jane)["work"] == 2
    # John's tags are his own: Jane's don't show for him at all.
    assert uses(john) == {}
