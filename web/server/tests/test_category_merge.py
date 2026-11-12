"""Merging a category into another (requirements S7.2.4): the plan lines of the two, month by month
(`merge_lines`, a function of two histories), what a merge checks, everything that named the
category moving, its children mapped, the budgets the reader sees, and one in a large
household."""

import datetime as dt
import time
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, make, saved
from sqlalchemy import select
from test_accounts import add, new_account
from test_budgets import save_plan
from test_categories import new, rows

from moolakata import clock, ids
from moolakata.categories import Line, merge_lines, per
from moolakata.store.entities.accounts import Category, Loan, Rule, Split, Transaction
from moolakata.store.entities.budgets import BudgetLine, BudgetMove

M = [dt.date(2026, m, 1) for m in range(1, 13)]


def L(month: int, amount: str, **kw) -> Line:
    return Line(fromMonth=M[month - 1], amount=D(amount), **kw)


# ---------- the plan lines, month by month ----------


def test_per_converts_between_a_month_and_a_year():
    assert per(D("1200.00"), "year", "month") == D("100.00")
    assert per(D("1000.00"), "year", "month") == D("83.33")
    assert per(D("0.06"), "year", "month") == D("0.00")  # half a cent rounds to even
    assert per(D("0.18"), "year", "month") == D("0.02")  # 1.5 cents, to even
    assert per(D("100.00"), "month", "year") == D("1200.00")
    assert per(D("5.00"), "month", "month") == D("5.00")
    assert per(D("5.00"), "year", "year") == D("5.00")


LINES = [
    # (what it shows, target's lines, source's lines, the merged lines)
    ("only the target plans", [L(1, "100")], [], [L(1, "100")]),
    ("only the source plans", [], [L(3, "40", rollover=True)], [L(3, "40", rollover=True)]),
    ("both, from one month", [L(1, "100")], [L(1, "40")], [L(1, "140")]),
    (
        "histories that interleave",
        [L(1, "100"), L(4, "120")],
        [L(2, "40"), L(6, "50")],
        [L(1, "100"), L(2, "140"), L(4, "160"), L(6, "170")],
    ),
    (
        "a yearly source on a monthly target",
        [L(1, "100")],
        [L(1, "1200", cadence="year")],
        [L(1, "200")],
    ),
    (
        "a monthly source on a yearly target",
        [L(1, "2400", cadence="year")],
        [L(1, "50")],
        [L(1, "3000", cadence="year")],
    ),
    (
        "both yearly",
        [L(1, "2400", cadence="year")],
        [L(1, "600", cadence="year")],
        [L(1, "3000", cadence="year")],
    ),
    (
        "the source out of the plan from a month",
        [L(1, "100")],
        [L(1, "40"), L(5, "0", out=True)],
        [L(1, "140"), L(5, "100")],
    ),
    (
        "both out of the plan from a month",
        [L(1, "100"), L(5, "0", out=True)],
        [L(1, "40"), L(5, "0", out=True)],
        [L(1, "140"), L(5, "0", out=True)],
    ),
    (
        "the target out, the source still in",
        [L(1, "100"), L(3, "0", out=True)],
        [L(1, "40", rollover=True)],
        [L(1, "140", rollover=True), L(3, "40", rollover=True)],
    ),
    (
        "a source that changes nothing adds no line",
        [L(1, "100"), L(2, "100")],
        [L(1, "0"), L(2, "0")],
        [L(1, "100")],
    ),
    (
        "the target's reserve, the source without one",
        [L(1, "100", target=D("1200"), heldInId="Acct_t")],
        [L(1, "40")],
        [L(1, "140", target=D("1200"), heldInId="Acct_t")],
    ),
    (
        "the target's terms win",
        [L(1, "100", overspend="next", projectionId="Prjct_a")],
        [L(1, "40", overspend="carry", projectionId="Prjct_b")],
        [L(1, "140", overspend="next", projectionId="Prjct_a")],
    ),
    (
        "what the target leaves unset the source gives",
        [L(1, "100")],
        [L(1, "40", rollover=True, projectionId="Prjct_b", target=D("500"), heldInId="Acct_s")],
        [L(1, "140", rollover=True, projectionId="Prjct_b", target=D("500"), heldInId="Acct_s")],
    ),
    (
        "two reserves: the targets add up, the target's account",
        [L(1, "100", target=D("1200"), heldInId="Acct_t")],
        [L(1, "50", target=D("600"), heldInId="Acct_s")],
        [L(1, "150", target=D("1800"), heldInId="Acct_t")],
    ),
    ("nothing planned", [], [], []),
    (
        "out lines before anything was planned are dropped",
        [L(1, "0", out=True)],
        [L(1, "0", out=True), L(2, "30")],
        [L(2, "30")],
    ),
]


@pytest.mark.parametrize("what,target,source,want", LINES, ids=[x[0] for x in LINES])
def test_merge_lines(what, target, source, want):
    assert merge_lines(target, source) == want


def test_merge_lines_reads_the_lines_in_any_order():
    target = [L(4, "120"), L(1, "100")]
    source = [L(6, "50"), L(2, "40")]
    assert merge_lines(target, source) == merge_lines(
        sorted(target, key=lambda x: x.fromMonth), sorted(source, key=lambda x: x.fromMonth)
    )


# ---------- the merge ----------


T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def people(server, admin_client, frozen):
    make_user(server, "alice")
    make_user(server, "bob")
    return {"admin": admin_client, "alice": sign_in(server, "alice"), "bob": sign_in(server, "bob")}


def merge(c, source: dict, into: str, children: dict | None = None, version=None):
    return c.post(
        f"/ui/api/categories/{source['id']}/merge",
        json={"into": into, "children": children or {}},
        headers={"If-Match": str(source["version"] if version is None else version)},
    )


def preview(c, source: dict, into: str, children: dict | None = None):
    return c.post(
        f"/ui/api/categories/{source['id']}/merge-preview",
        json={"into": into, "children": children or {}},
    )


def error(r):
    e = r.json()["errors"][0]
    return r.status_code, e.get("field"), e["code"]


def answer(r):
    """A refusal as the dialog shows it: its status, field, code and words."""
    e = r.json()["errors"][0]
    return r.status_code, e.get("field"), e["code"], e["message"]


def test_a_merge_moves_everything_that_named_the_category(people, server):
    admin, alice = people["admin"], people["alice"]
    pet = new(alice, "Pet")
    pets = new(alice, "Pets")
    acct = new_account(alice)
    t = add(alice, acct["id"], "-20.00", "2026-10-02", payee="Vet", categoryId=pet["id"])
    split = add(
        alice,
        acct["id"],
        "-9.00",
        "2026-10-03",
        payee="Store",
        splits=[
            {"categoryId": pet["id"], "amount": "-4.00"},
            {"categoryId": None, "amount": "-5.00"},
        ],
    )
    rule = make(alice, "Rule", payeeMatch="petco", categoryId=pet["id"]).json()
    b = make(alice, "Bdgt", name="Home", accountIds=[acct["id"]], method="envelope").json()
    assert (
        save_plan(
            alice,
            b,
            "2026-09-01",
            [
                {"categoryId": pet["id"], "amount": "40.00"},
                {"categoryId": pets["id"], "amount": "60.00"},
            ],
        ).status_code
        == 200
    )
    food = rows(alice)["Food"]["id"]
    across = make(
        alice,
        "BdgMv",
        budgetId=b["id"],
        month="2026-10-01",
        fromCategoryId=food,
        toCategoryId=pet["id"],
        amount="5.00",
    ).json()
    between = make(
        alice,
        "BdgMv",
        budgetId=b["id"],
        month="2026-10-01",
        fromCategoryId=pets["id"],
        toCategoryId=pet["id"],
        amount="3.00",
    ).json()
    loan_acct = new_account(alice, name="Loan", type="auto-loan", mask="3333")
    from edits import terms

    assert (
        terms(
            alice,
            loan_acct["id"],
            principal="9000.00",
            rate="5",
            termMonths=48,
            startDate="2026-11-01",
            budgetCounting="whole",
            budgetCategoryId=pet["id"],
        ).status_code
        == 200
    )
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert preview(admin, source, pets["id"]).json() == {"budgets": []}  # not shared with the admin
    assert preview(alice, source, pets["id"]).status_code == 403
    r = merge(admin, source, pets["id"])
    assert r.status_code == 200, r.text
    assert r.json()["into"]["id"] == pets["id"]
    with server.db.read(unscoped="test") as s:
        assert s.get(Category, pet["id"]).deleted
        assert s.get(Transaction, t["id"]).categoryId == pets["id"]
        assert s.get(Transaction, t["id"]).version == t["version"] + 1
        parts = s.scalars(select(Split).where(Split.transactionId == split["id"])).all()
        assert {p.categoryId for p in parts} == {pets["id"], None}
        assert s.get(Rule, rule["id"]).categoryId == pets["id"]
        assert s.get(BudgetMove, across["id"]).toCategoryId == pets["id"]
        assert s.get(BudgetMove, between["id"]).deleted, "a move within one category moves nothing"
        loan = s.scalars(select(Loan).where(Loan.accountId == loan_acct["id"])).one()
        assert loan.budgetCategoryId == pets["id"]
        lines = s.scalars(
            select(BudgetLine).where(BudgetLine.budgetId == b["id"], BudgetLine.deleted.is_(False))
        ).all()
        assert [(x.categoryId, x.amount) for x in lines] == [(pets["id"], D("100.00"))]
    texts = [a["text"] for a in people["bob"].get("/ui/api/activity").json()["items"]]
    assert [x for x in texts if "merged" in x] == ["Ada Admin merged the category Pet into Pets"]
    assert pet["id"] not in {x["id"] for x in alice.get("/ui/api/categories").json()["items"]}


def test_the_preview_names_the_budgets_the_reader_sees(people):
    admin, alice = people["admin"], people["alice"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    for c, name in ((admin, "Admin's"), (alice, "Alice's")):
        acct = new_account(c, name=f"{name} checking")
        b = make(c, "Bdgt", name=name, accountIds=[acct["id"]]).json()
        assert (
            save_plan(c, b, "2026-10-01", [{"categoryId": pet["id"], "amount": "1.00"}]).status_code
            == 200
        )
    unplanned = make(
        admin, "Bdgt", name="Unplanned", accountIds=[new_account(admin, name="X")["id"]]
    )
    assert unplanned.status_code == 200
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert preview(admin, source, pets["id"]).json() == {"budgets": ["Admin's"]}


def test_a_parents_children_go_where_the_merge_says(people, server):
    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    dog, cat = new(admin, "dog", parentId=pet["id"]), new(admin, "cat", parentId=pet["id"])
    theirs = {n: new(admin, n, parentId=pets["id"]) for n in ("Cats", "Dogs", "Birds")}
    acct = new_account(admin)
    t = add(admin, acct["id"], "-8.00", payee="Kibble", categoryId=dog["id"])
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    r = merge(admin, source, pets["id"], {dog["id"]: theirs["Dogs"]["id"], cat["id"]: cat["id"]})
    assert r.status_code == 200, r.text
    now = rows(admin)
    assert "Pets › cat" in now and "Pets › dog" not in now and "Pet" not in now
    assert sorted(k for k in now if k.startswith("Pets")) == [
        "Pets",
        "Pets › Birds",
        "Pets › Cats",
        "Pets › Dogs",
        "Pets › cat",
    ]
    with server.db.read(unscoped="test") as s:
        assert s.get(Transaction, t["id"]).categoryId == theirs["Dogs"]["id"]
        assert s.get(Category, cat["id"]).parentId == pets["id"]
    texts = [a["text"] for a in admin.get("/ui/api/activity").json()["items"]]
    assert [x for x in texts if "merged" in x] == [
        "Ada Admin merged the category Pet into Pets (dog into Pets › Dogs; cat moved)"
    ]


def _refusal_world(admin):
    w = {
        "pet": new(admin, "Pet"),
        "pets": new(admin, "Pets"),
        "wage": new(admin, "Wage", kind="income"),
    }
    w["dog"] = new(admin, "Dog", parentId=w["pet"]["id"])
    w["toy"] = new(admin, "Toy", kind="savings", parentId=w["pet"]["id"])
    w["dogs"] = new(admin, "Dogs", parentId=w["pets"]["id"])
    w["Dog"] = new(admin, "dog", parentId=w["pets"]["id"])
    w["lonely"] = new(admin, "Lonely")
    gone = new(admin, "Gone")
    from edits import remove

    saved(remove(admin, "Cat", gone))
    w["gone"] = gone
    w["food"] = rows(admin)["Food"]
    w["groceries"] = rows(admin)["Food › Groceries"]
    w["gifts"] = rows(admin)["Gifts"]
    w["loans"] = rows(admin)["Loan payments"]
    w["housing"] = rows(admin)["Housing"]
    return w


REFUSALS = [
    # (what, source, into, children (names → names or "self"), (status, field, code, message))
    (
        "into itself",
        "lonely",
        "lonely",
        {},
        (422, "into", "merge-itself", "Choose another category to merge it into."),
    ),
    (
        "into one deleted",
        "lonely",
        "gone",
        {},
        (422, "into", "category-unknown", "Choose a category."),
    ),
    (
        "into another kind",
        "lonely",
        "wage",
        {},
        (422, "into", "merge-kind", "Choose another expense category."),
    ),
    (
        "a parent into a child",
        "pet",
        "groceries",
        None,
        (422, "into", "merge-level", "Categories have two levels: merge it into a top-level one."),
    ),
    (
        "a child left out",
        "pet",
        "pets",
        {"dog": "dogs"},
        (422, "children", "merge-children", "Say where each of its categories goes."),
    ),
    (
        "a child not its own",
        "lonely",
        "pets",
        {"dog": "dogs"},
        (422, "children", "merge-children", "Say where each of its categories goes."),
    ),
    (
        "into a child outside the target",
        "pet",
        "pets",
        {"dog": "groceries", "toy": "self"},
        (422, "children.dog", "merge-children", "Choose one of Pets's categories."),
    ),
    (
        "a child into another kind",
        "pet",
        "pets",
        {"dog": "dogs", "toy": "dogs"},
        (422, "children.toy", "merge-kind", "Choose another savings category."),
    ),
    (
        "a child kept beside its namesake",
        "pet",
        "pets",
        {"dog": "self", "toy": "self"},
        (422, "children.dog", "name-taken", "Pets has a Dog already: merge Dog into it."),
    ),
    (
        "a category the server counts in",
        "gifts",
        "food",
        {},
        (
            422,
            None,
            "category-kept",
            "MoolaKata counts in this category by its own rules: it stays.",
        ),
    ),
]


@pytest.mark.parametrize("what,src,into,kids,want", REFUSALS, ids=[x[0] for x in REFUSALS])
def test_a_merge_is_checked(people, what, src, into, kids, want):
    admin = people["admin"]
    w = _refusal_world(admin)
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == w[src]["id"]
    )
    if kids is None:
        kids = {"dog": "self", "toy": "self"}
    children = {w[k]["id"]: (w[k]["id"] if v == "self" else w[v]["id"]) for k, v in kids.items()}
    status, field, code, message = want
    if field and field.startswith("children."):
        field = f"children.{w[field.removeprefix('children.')]['id']}"
    want = (status, field, code, message)
    assert answer(merge(admin, source, w[into]["id"], children)) == want
    assert answer(preview(admin, source, w[into]["id"], children)) == want


def test_a_child_the_server_counts_in_moves_but_is_never_merged_away(people):
    admin = people["admin"]
    w = _refusal_world(admin)
    other = new(admin, "Home")
    homes = new(admin, "Tax", parentId=other["id"])
    housing = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == w["housing"]["id"]
    )
    kids = {
        x["id"]: x["id"]
        for x in admin.get("/ui/api/categories").json()["items"]
        if x["parentId"] == housing["id"]
    }
    tax = rows(admin)["Housing › Property tax"]["id"]
    assert answer(merge(admin, housing, other["id"], {**kids, tax: homes["id"]})) == (
        422,
        f"children.{tax}",
        "category-kept",
        "MoolaKata counts in Property tax by its own rules: it moves, as it is.",
    )
    r = merge(admin, housing, other["id"], kids)
    assert r.status_code == 200, r.text
    assert "Home › Property tax" in rows(admin)


def test_only_an_admin_merges_and_a_stale_one_is_refused(people):
    admin, alice = people["admin"], people["alice"]
    pet, pets = new(alice, "Pet"), new(alice, "Pets")
    source = next(
        x for x in alice.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert not source["allowed"]["merge"]
    assert answer(merge(alice, source, pets["id"])) == (
        403,
        None,
        "admins-only",
        "Only admins merge categories.",
    )
    assert next(x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"])[
        "allowed"
    ]["merge"]
    saved(change(alice, "Cat", source, name="Pet!"))
    assert merge(admin, source, pets["id"]).status_code == 412
    r = merge(admin, {"id": ids.new_id("Cat"), "version": 1}, pets["id"])
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (404, "not-found", "Not found")


def test_a_merge_in_a_large_household_takes_moments(people, server):
    """Round 9 of the categories walk: a merge runs in the request, in one transaction, which
    holds only while a large household's merge stays quick."""
    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    acct = new_account(admin)
    n = 50_000
    with server.db.tx(unscoped="test") as s:
        rows_ = [
            {
                "id": ids.new_id("Txn"),
                "accountId": acct["id"],
                "date": dt.date(2025, 1, 1) + dt.timedelta(days=i % 600),
                "kind": "withdrawal",
                "amount": D("-1.00"),
                "categoryId": pet["id"] if i % 2 else pets["id"],
                "createdAt": T0,
                "updatedAt": T0,
            }
            for i in range(n)
        ]
        s.execute(Transaction.__table__.insert(), rows_)
    budgets = []
    for i in range(10):
        b = make(admin, "Bdgt", name=f"B{i}", accountIds=[acct["id"]]).json()
        assert (
            save_plan(
                admin,
                b,
                "2026-01-01",
                [
                    {"categoryId": pet["id"], "amount": "10.00"},
                    {"categoryId": pets["id"], "amount": "5.00"},
                ],
            ).status_code
            == 200
        )
        budgets.append(b)
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    start = time.monotonic()
    r = merge(admin, source, pets["id"])
    took = time.monotonic() - start
    assert r.status_code == 200, r.text
    assert took < 5, f"a merge of {n:,} transactions took {took:.1f} s"
    with server.db.read(unscoped="test") as s:
        left = s.scalars(select(Transaction.id).where(Transaction.categoryId == pet["id"])).first()
        assert left is None


T1 = dt.datetime(2026, 10, 21, 9, 30, tzinfo=dt.UTC)


def test_a_merge_marks_each_record_it_moves_and_leaves_the_rest(people, server):
    """Every record that named the category, deleted ones too, names the other, its version
    up by one and its time the merge's; a move between the two that was already deleted stays
    as it was; other categories' records, lines and moves are left as they are."""
    from edits import remove, terms

    admin, alice = people["admin"], people["alice"]
    pet, pets = new(alice, "Pet"), new(alice, "Pets")
    food = rows(alice)["Food"]["id"]
    fun = rows(alice)["Entertainment"]["id"]
    acct = new_account(alice)
    t = add(alice, acct["id"], "-20.00", "2026-10-02", payee="Vet", categoryId=pet["id"])
    gone = add(alice, acct["id"], "-5.00", "2026-10-03", payee="Old", categoryId=pet["id"])
    saved(remove(alice, "Txn", gone))
    other = add(alice, acct["id"], "-7.00", "2026-10-04", payee="Shop", categoryId=food)
    split = add(
        alice,
        acct["id"],
        "-9.00",
        "2026-10-05",
        payee="Mixed",
        splits=[
            {"categoryId": pet["id"], "amount": "-4.00"},
            {"categoryId": food, "amount": "-5.00"},
        ],
    )
    rule = make(alice, "Rule", payeeMatch="petco", categoryId=pet["id"]).json()
    b = make(alice, "Bdgt", name="Home", accountIds=[acct["id"]], method="envelope").json()
    assert (
        save_plan(
            alice,
            b,
            "2026-09-01",
            [
                {"categoryId": pet["id"], "amount": "40.00"},
                {"categoryId": food, "amount": "300.00"},
            ],
        ).status_code
        == 200
    )

    def mv(f, to):
        return make(
            alice,
            "BdgMv",
            budgetId=b["id"],
            month="2026-10-01",
            fromCategoryId=f,
            toCategoryId=to,
            amount="1.00",
        ).json()

    across, untouched = mv(food, pet["id"]), mv(food, fun)
    live_between, from_target = mv(pets["id"], pet["id"]), mv(pets["id"], food)
    old_between = mv(pets["id"], pet["id"])
    saved(remove(alice, "BdgMv", old_between))
    loan_acct = new_account(alice, name="Loan", type="auto-loan", mask="3333")
    assert (
        terms(
            alice,
            loan_acct["id"],
            principal="9000.00",
            rate="5",
            termMonths=48,
            startDate="2026-11-01",
            budgetCounting="whole",
            budgetCategoryId=pet["id"],
        ).status_code
        == 200
    )
    with server.db.read(unscoped="test") as s:
        before = {
            "txn": s.get(Transaction, t["id"]).version,
            "gone": s.get(Transaction, gone["id"]).version,
            "other": s.get(Transaction, other["id"]).version,
            "split": {
                p.categoryId: p.version
                for p in s.scalars(select(Split).where(Split.transactionId == split["id"]))
            },
            "rule": s.get(Rule, rule["id"]).version,
            "across": s.get(BudgetMove, across["id"]).version,
            "untouched": s.get(BudgetMove, untouched["id"]).version,
            "live": s.get(BudgetMove, live_between["id"]).version,
            "from_target": s.get(BudgetMove, from_target["id"]).version,
            "between": (
                s.get(BudgetMove, old_between["id"]).version,
                s.get(BudgetMove, old_between["id"]).deletedAt,
            ),
            "loan": s.scalars(select(Loan).where(Loan.accountId == loan_acct["id"])).one().version,
        }
        admin_id = s.scalars(select(Category.createdById).where(Category.id == pet["id"])).one()
    clock.fix(T1)
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert merge(admin, source, pets["id"]).status_code == 200
    with server.db.read(unscoped="test") as s:
        ada = s.get(Category, pet["id"]).deletedById
        assert ada and ada != admin_id, "deleted by the admin who merged, not its maker"
        for key, row_ in (
            ("txn", s.get(Transaction, t["id"])),
            ("gone", s.get(Transaction, gone["id"])),
        ):
            assert (row_.categoryId, row_.version, row_.updatedAt) == (
                pets["id"],
                before[key] + 1,
                T1,
            )
        assert s.get(Transaction, gone["id"]).deleted, "repointed, still deleted"
        assert s.get(Transaction, other["id"]).version == before["other"]
        parts = {
            p.categoryId: p
            for p in s.scalars(select(Split).where(Split.transactionId == split["id"]))
        }
        assert (parts[pets["id"]].version, parts[pets["id"]].updatedAt) == (
            before["split"][pet["id"]] + 1,
            T1,
        )
        assert parts[food].version == before["split"][food]
        r_ = s.get(Rule, rule["id"])
        assert (r_.categoryId, r_.version, r_.updatedAt) == (pets["id"], before["rule"] + 1, T1)
        m = s.get(BudgetMove, across["id"])
        assert (m.toCategoryId, m.fromCategoryId, m.version, m.updatedAt) == (
            pets["id"],
            food,
            before["across"] + 1,
            T1,
        )
        assert s.get(BudgetMove, untouched["id"]).version == before["untouched"]
        now_within = s.get(BudgetMove, live_between["id"])
        assert (now_within.deleted, now_within.deletedById, now_within.deletedAt) == (True, ada, T1)
        # Moved onto Pets (+1), then deleted as a move within it (+1).
        assert (now_within.version, now_within.updatedAt) == (before["live"] + 2, T1)
        kept = s.get(BudgetMove, from_target["id"])
        assert (kept.deleted, kept.version) == (False, before["from_target"])
        old = s.get(BudgetMove, old_between["id"])
        assert old.deletedAt == before["between"][1], "already deleted: when it was is kept"
        assert old.version == before["between"][0] + 1 and old.fromCategoryId == pets["id"]
        loan = s.scalars(select(Loan).where(Loan.accountId == loan_acct["id"])).one()
        assert (loan.budgetCategoryId, loan.version, loan.updatedAt) == (
            pets["id"],
            before["loan"] + 1,
            T1,
        )
        lines = s.scalars(select(BudgetLine).where(BudgetLine.budgetId == b["id"])).all()
        live = sorted((x.categoryId, x.amount) for x in lines if not x.deleted)
        assert live == sorted([(pets["id"], D("40.00")), (food, D("300.00"))])
        dead = [x for x in lines if x.deleted]
        assert [x.categoryId for x in dead] == [pet["id"]] and dead[0].deletedById == ada


def test_merged_lines_carry_every_term(people, server):
    """A budget that plans only the source has its line moved with every term; one that
    plans only the target is left alone; one that plans both has one line from each month."""
    admin = people["admin"]
    pet, pets = new(admin, "Pet", kind="savings"), new(admin, "Pets", kind="savings")
    acct = new_account(admin)
    saving = new_account(admin, name="Savings box", type="savings", mask="8888")
    ids_ = [acct["id"], saving["id"]]
    only_target = make(admin, "Bdgt", name="A target only", accountIds=ids_).json()
    only_source = make(
        admin, "Bdgt", name="B source only", accountIds=ids_, method="envelope", reserves=True
    ).json()
    assert (
        save_plan(
            admin, only_target, "2026-09-01", [{"categoryId": pets["id"], "amount": "10.00"}]
        ).status_code
        == 200
    )
    terms_ = {
        "amount": "50.00",
        "rollover": True,
        "overspend": "next",
        "target": "600.00",
        "heldInId": saving["id"],
    }
    r = save_plan(admin, only_source, "2026-09-01", [{"categoryId": pet["id"], **terms_}])
    assert r.status_code == 200, r.text
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert merge(admin, source, pets["id"]).status_code == 200
    with server.db.read(unscoped="test") as s:

        def live(b):
            alive = (BudgetLine.budgetId == b["id"], BudgetLine.deleted.is_(False))
            return s.scalars(select(BudgetLine).where(*alive)).all()

        (kept,) = live(only_target)
        assert (kept.categoryId, kept.amount, kept.deleted) == (pets["id"], D("10.00"), False)
        assert not s.scalars(
            select(BudgetLine).where(
                BudgetLine.budgetId == only_target["id"], BudgetLine.deleted.is_(True)
            )
        ).all()
        (moved,) = live(only_source)
        got = (
            moved.categoryId,
            moved.fromMonth,
            moved.amount,
            moved.out,
            moved.cadence,
            moved.rollover,
            moved.overspend,
            moved.target,
            moved.heldInId,
        )
        assert got == (
            pets["id"],
            dt.date(2026, 9, 1),
            D("50.00"),
            False,
            "month",
            True,
            "next",
            D("600.00"),
            saving["id"],
        )


def test_a_yearly_line_and_a_projection_carry_too(people, server):
    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    acct = new_account(admin)
    b = make(admin, "Bdgt", name="Yearly", accountIds=[acct["id"]]).json()
    assert (
        save_plan(
            admin,
            b,
            "2026-09-01",
            [
                {"categoryId": pet["id"], "amount": "1200.00", "cadence": "year"},
            ],
        ).status_code
        == 200
    )
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    assert merge(admin, source, pets["id"]).status_code == 200
    with server.db.read(unscoped="test") as s:
        (moved,) = s.scalars(
            select(BudgetLine).where(BudgetLine.budgetId == b["id"], BudgetLine.deleted.is_(False))
        ).all()
        assert (moved.cadence, moved.amount, moved.categoryId) == ("year", D("1200.00"), pets["id"])


def test_a_deleted_child_needs_no_place(people):
    from edits import remove

    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    saved(remove(admin, "Cat", new(admin, "Old", parentId=pet["id"])))
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    # With no children left it may go into a child, as any childless one may.
    child = new(admin, "Kid", parentId=pets["id"])
    assert merge(admin, source, child["id"]).status_code == 200


def test_the_preview_leaves_out_deleted_budgets_and_sorts_by_name(people):
    from edits import remove

    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    made = {}
    for name in ("Beta", "alpha", "Gone"):
        acct = new_account(admin, name=f"{name} checking")
        made[name] = make(admin, "Bdgt", name=name, accountIds=[acct["id"]]).json()
        assert (
            save_plan(
                admin, made[name], "2026-10-01", [{"categoryId": pet["id"], "amount": "1.00"}]
            ).status_code
            == 200
        )
    saved(remove(admin, "Bdgt", admin.get(f"/ui/api/budgets/{made['Gone']['id']}").json()))
    source = next(
        x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"]
    )
    # By name, whatever its case: alpha before Beta.
    assert preview(admin, source, pets["id"]).json() == {"budgets": ["alpha", "Beta"]}


def test_a_refused_merge_reads_as_its_parts():
    from moolakata.categories import Refused

    e = Refused("into", "merge-kind", "Choose another expense category.")
    assert (e.field, e.code, e.message) == (
        "into",
        "merge-kind",
        "Choose another expense category.",
    )
    assert e.args == ("into", "merge-kind", "Choose another expense category.")


def test_a_second_merge_reads_only_the_live_lines(people, server):
    """Pet into Pets, then Pets into Animals: the first merge's lines, deleted, play no part."""
    admin = people["admin"]
    pet, pets, animals = new(admin, "Pet"), new(admin, "Pets"), new(admin, "Animals")
    acct = new_account(admin)
    b = make(admin, "Bdgt", name="Twice", accountIds=[acct["id"]]).json()
    assert (
        save_plan(
            admin,
            b,
            "2026-09-01",
            [
                {"categoryId": pet["id"], "amount": "10.00"},
                {"categoryId": pets["id"], "amount": "20.00"},
            ],
        ).status_code
        == 200
    )

    def merged(src, into):
        row_ = next(x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == src)
        assert merge(admin, row_, into).status_code == 200

    merged(pet["id"], pets["id"])
    merged(pets["id"], animals["id"])
    with server.db.read(unscoped="test") as s:
        alive = (BudgetLine.budgetId == b["id"], BudgetLine.deleted.is_(False))
        got = [(x.categoryId, x.amount) for x in s.scalars(select(BudgetLine).where(*alive))]
        assert got == [(animals["id"], D("30.00"))]


def test_a_line_taken_out_of_the_plan_stays_out_when_moved(people, server):
    admin = people["admin"]
    pet, pets = new(admin, "Pet"), new(admin, "Pets")
    acct = new_account(admin)
    b = make(admin, "Bdgt", name="Out", accountIds=[acct["id"]]).json()
    assert (
        save_plan(
            admin, b, "2026-08-01", [{"categoryId": pet["id"], "amount": "10.00"}]
        ).status_code
        == 200
    )
    assert save_plan(admin, b, "2026-10-01", []).status_code == 200  # taken out from October
    row_ = next(x for x in admin.get("/ui/api/categories").json()["items"] if x["id"] == pet["id"])
    assert merge(admin, row_, pets["id"]).status_code == 200
    with server.db.read(unscoped="test") as s:
        alive = (BudgetLine.budgetId == b["id"], BudgetLine.deleted.is_(False))
        got = sorted(
            (x.fromMonth, x.out, x.categoryId) for x in s.scalars(select(BudgetLine).where(*alive))
        )
        assert got == [
            (dt.date(2026, 8, 1), False, pets["id"]),
            (dt.date(2026, 10, 1), True, pets["id"]),
        ]
