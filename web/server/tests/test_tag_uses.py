"""A tag's uses (requirements S12.18.12): how many records the caller sees carry it, so a tag
box lists the most used first. Records deleted, and records the caller no longer sees, don't
count."""

from conftest import make_user, sign_in
from edits import change, make, remove, share, tag
from test_accounts import add, new_account


def uses(c) -> dict[str, int]:
    return {t["name"]: t["uses"] for t in c.get("/ui/api/tags").json()["items"]}


def test_a_tag_counts_the_records_the_caller_sees_carrying_it(server):
    u = {n: make_user(server, n) for n in ("alice", "bob")}
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    own = new_account(alice)
    make(alice, "Txn", accountId=own["id"], date="2026-09-01", amount="-4.00", tags=["work"])
    make(alice, "Txn", accountId=own["id"], date="2026-09-02", amount="-5.00",
         tags=["work", "coffee"])  # fmt: skip
    gone = make(alice, "Txn", accountId=own["id"], date="2026-09-03", amount="-6.00",
                tags=["work"])  # fmt: skip
    make(alice, "Rule", payeeMatch="blue bottle", tags=["coffee"])
    assert uses(alice) == {"coffee": 2, "work": 3}

    # A deleted transaction no longer counts.
    assert remove(alice, "Txn", gone.json()).status_code == 200
    assert uses(alice) == {"coffee": 2, "work": 2}

    # Alice's tag on Bob's shared account counts while she sees it, and not once she doesn't.
    theirs = new_account(bob, name="Joint")
    assert share(bob, "account", theirs["id"], users={u["alice"].id: "write"}).status_code == 200
    add(alice, theirs["id"], "-7.00", payee="Lunch")
    t = next(x for x in alice.get("/ui/api/transactions").json()["items"] if x["payee"] == "Lunch")
    r = change(alice, "Txn", t, tagIds={"add": [tag(alice, "work")], "remove": []})
    assert r.status_code == 200, r.text
    assert uses(alice)["work"] == 3
    assert share(bob, "account", theirs["id"], users={u["alice"].id: "none"}).status_code == 200
    assert uses(alice)["work"] == 2
    # Bob's tags are his own: Alice's don't show for him at all.
    assert uses(bob) == {}
