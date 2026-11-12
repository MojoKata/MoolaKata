"""The household's categories (requirements S7.2): who adds one, who changes its name, parent,
kind, tax tag and receipts' keeping, who deletes one, what counts as in use, and the Activity
every change leaves for every user (S7.2.3, S10.8)."""

import pytest
from conftest import make_user, sign_in
from edits import change, make, remove, saved
from sqlalchemy import select, text
from test_accounts import add, new_account

from moolakata import ids
from moolakata.categories import SERVER_KEYS
from moolakata.store.entities.accounts import Category

FIELDS = ("name", "parentId", "kind", "taxTag", "keepReceiptsYears")


def rows(c) -> dict[str, dict]:
    return {x["path"]: x for x in c.get("/ui/api/categories").json()["items"]}


def row(c, cat_id: str) -> dict:
    return next(x for x in c.get("/ui/api/categories").json()["items"] if x["id"] == cat_id)


def new(c, name, kind="expense", **kw) -> dict:
    r = make(c, "Cat", name=name, kind=kind, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def error(r) -> tuple[int, str | None, str]:
    e = r.json()["errors"][0]
    return r.status_code, e.get("field"), e["code"]


@pytest.fixture
def people(server, admin_client):
    a, b = make_user(server, "alice"), make_user(server, "bob")
    return {
        "admin": admin_client,
        "alice": sign_in(server, "alice"),
        "bob": sign_in(server, "bob"),
        "ids": {"alice": a.id, "bob": b.id},
    }


def test_anyone_adds_a_category_at_either_level_with_any_tax_tag(people):
    alice, bob = people["alice"], people["bob"]
    pets = new(alice, "Pets")
    vet = new(alice, "Vet", parentId=pets["id"], taxTag="medical")
    church = new(bob, "Church", parentId=rows(bob)["Giving"]["id"], taxTag="charitable")
    seen = rows(bob)
    assert seen["Pets › Vet"]["taxTag"] == "medical" and seen["Pets"]["createdById"]
    assert not seen["Pets"]["shipped"] and seen["Giving › Church"]["id"] == church["id"]
    # The maker may still change its parent, kind and tax tag; others may only rename it.
    assert seen["Pets › Vet"]["allowed"] == {
        "rename": True,
        "change": False,
        "delete": False,
        "merge": False,
    }
    assert row(alice, vet["id"])["allowed"] == {
        "rename": True,
        "change": True,
        "delete": True,
        "merge": False,
    }


NAMES = [
    ("", "name-invalid"),
    ("   ", "name-invalid"),
    ("x" * 61, "name-invalid"),
    ("Pets › Vet", "name-invalid"),
    ("food", "name-taken"),  # a top-level Food ships; names match in any case
    ("  Food  ", "name-taken"),  # trimmed first
]


@pytest.mark.parametrize("name,code", NAMES)
def test_a_name_is_refused(people, name, code):
    r = make(people["alice"], "Cat", name=name, kind="expense")
    assert error(r) == (422, "name", code)


def test_a_name_is_trimmed_and_may_repeat_under_another_parent(people):
    alice = people["alice"]
    one = new(alice, "x" * 60)
    assert one["name"] == "x" * 60 and new(alice, " Pets ")["name"] == "Pets"
    # Insurance ships under Housing; another parent may have one too.
    health = rows(alice)["Health"]["id"]
    assert new(alice, "Insurance ", parentId=health)["path"] == "Health › Insurance"
    r = make(alice, "Cat", name="INSURANCE", kind="expense", parentId=health)
    assert error(r) == (422, "name", "name-taken")


def test_a_kind_parent_and_tax_tag_are_checked(people, server):
    alice = people["alice"]
    have = rows(alice)
    gone = new(alice, "Gone")
    saved(remove(alice, "Cat", gone))
    cases = [
        ({"kind": "spending"}, ("kind", "kind-invalid")),
        ({"parentId": have["Food › Groceries"]["id"]}, ("parentId", "parent-invalid")),
        ({"parentId": gone["id"]}, ("parentId", "parent-invalid")),
        ({"parentId": ids.new_id("Cat")}, ("parentId", "parent-invalid")),
        ({"taxTag": "hobby"}, ("taxTag", "tax-tag-invalid")),
    ]
    for fields, (field, code) in cases:
        body = {"name": "Odd", "kind": "expense", **fields}
        assert error(make(alice, "Cat", **body))[1:] == (field, code), fields
    for kind in ("expense", "income", "savings", "transfer"):
        assert new(alice, f"A {kind}", kind=kind)["kind"] == kind
    for tag in (
        "medical",
        "charitable",
        "business",
        "childcare",
        "education",
        "loan-interest",
        "property-tax",
        "retirement",
    ):
        assert new(alice, f"Tagged {tag}", taxTag=tag)["taxTag"] == tag


def _origin(people, origin: str) -> dict:
    alice = people["alice"]
    if origin == "shipped":
        return rows(alice)["Entertainment"]
    return new(alice, "Hobbies")


def _use(people, cat_id: str) -> None:
    alice = people["alice"]
    acct = new_account(alice)
    add(alice, acct["id"], "-12.00", payee="Toy shop", categoryId=cat_id)


def _value(people, field: str, cat: dict):
    return {
        "name": "Fun and games",
        "parentId": rows(people["alice"])["Personal"]["id"],
        "kind": "income",
        "taxTag": "business",
        "keepReceiptsYears": 3,
    }[field]


def _allowed(caller: str, origin: str, used: bool, field: str) -> bool:
    """S7.2.3 written out: the name is anyone's; parent, kind and tax tag the maker's while
    nothing uses it, else an admin's; receipts' keeping an admin's."""
    if field == "name":
        return True
    if field == "keepReceiptsYears":
        return caller == "admin"
    return caller == "admin" or (caller == "alice" and origin == "alice's" and not used)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("used", [False, True], ids=["unused", "in use"])
@pytest.mark.parametrize("origin", ["shipped", "alice's"])
@pytest.mark.parametrize("caller", ["admin", "alice", "bob"])
def test_who_changes_what(people, caller, origin, used, field):
    cat = _origin(people, origin)
    if used:
        _use(people, cat["id"])
    c = people[caller]
    before = row(c, cat["id"])
    assert before["inUse"] is used
    r = change(c, "Cat", before, **{field: _value(people, field, cat)})
    if _allowed(caller, origin, used, field):
        assert r.status_code == 200, r.text
        assert saved(r)[field] == _value(people, field, cat)
    else:
        assert error(r) == (403, field, "admins-only")
    if field in ("parentId", "kind", "taxTag"):
        assert before["allowed"]["change"] is _allowed(caller, origin, used, field)


USES = ["transaction", "split", "rule", "plan line", "move", "loan", "child"]


def _put_to_use(c, cat_id: str, how: str) -> None:
    acct = new_account(c, name=f"For {how}", mask="9999")
    if how == "transaction":
        add(c, acct["id"], "-5.00", categoryId=cat_id)
    elif how == "split":
        other = row(c, cat_id)
        add(
            c,
            acct["id"],
            "-5.00",
            splits=[
                {"categoryId": other["id"], "amount": "-2.00"},
                {"categoryId": None, "amount": "-3.00"},
            ],
        )
    elif how == "rule":
        saved_rule = make(c, "Rule", payeeMatch="toys", categoryId=cat_id)
        assert saved_rule.status_code == 200, saved_rule.text
    elif how in ("plan line", "move"):
        from test_budgets import save_plan

        b = make(c, "Bdgt", name=f"B {how}", accountIds=[acct["id"]], method="envelope").json()
        if how == "plan line":
            assert (
                save_plan(
                    c, b, "2026-10-01", [{"categoryId": cat_id, "amount": "10.00"}]
                ).status_code
                == 200
            )
        else:
            food = rows(c)["Food"]["id"]
            r = make(
                c,
                "BdgMv",
                budgetId=b["id"],
                month="2026-10-01",
                fromCategoryId=food,
                toCategoryId=cat_id,
                amount="1.00",
            )
            assert r.status_code == 200, r.text
    elif how == "loan":
        loan = new_account(c, name="Car loan", type="auto-loan", mask="7777")
        from edits import terms

        r = terms(
            c,
            loan["id"],
            principal="9000.00",
            rate="5",
            termMonths=48,
            startDate="2026-11-01",
            budgetCounting="whole",
            budgetCategoryId=cat_id,
        )
        assert r.status_code == 200, r.text
    else:
        new(c, "Inside", parentId=cat_id)


@pytest.mark.parametrize("how", USES)
def test_each_use_makes_a_category_in_use(people, how):
    alice = people["alice"]
    mine = new(alice, "Hobbies")
    assert not row(alice, mine["id"])["inUse"]
    _put_to_use(alice, mine["id"], how)
    now = row(alice, mine["id"])
    assert now["inUse"] and not now["allowed"]["change"] and not now["allowed"]["delete"]
    # A use the maker can't see counts too: the admin's view says the same.
    assert row(people["bob"], mine["id"])["inUse"]
    assert error(change(alice, "Cat", now, kind="income")) == (403, "kind", "admins-only")
    assert error(remove(alice, "Cat", now))[2] == "category-in-use"
    assert error(remove(people["admin"], "Cat", now))[2] == "category-in-use"


def test_a_parent_is_checked_when_it_changes(people):
    admin = people["admin"]
    have = rows(admin)
    food = have["Food"]
    pets = new(admin, "Pets")
    # One with children stays at the top: the tree has two levels.
    r = change(admin, "Cat", food, parentId=pets["id"])
    assert error(r) == (422, "parentId", "parent-invalid")
    r = change(admin, "Cat", pets, parentId=pets["id"])
    assert error(r) == (422, "parentId", "parent-invalid")
    r = change(admin, "Cat", pets, parentId=have["Food › Groceries"]["id"])
    assert error(r) == (422, "parentId", "parent-invalid")
    # Moving under a parent with a child of the same name is refused at the name.
    dining = new(admin, "Dining out")
    r = change(admin, "Cat", dining, parentId=food["id"])
    assert error(r) == (422, "name", "name-taken")
    vet = saved(change(admin, "Cat", new(admin, "Vet"), parentId=pets["id"]))
    assert vet["path"] == "Pets › Vet"
    top = saved(change(admin, "Cat", vet, parentId=None))
    assert top["path"] == "Vet" and top["parentId"] is None
    # A rename that changes only the case is no clash with itself.
    assert saved(change(admin, "Cat", top, name="VET"))["name"] == "VET"


def test_what_the_server_counts_in_keeps_its_kind_and_stays(people):
    admin = people["admin"]
    have = {x["id"]: x for x in admin.get("/ui/api/categories").json()["items"]}
    named = [x for x in have.values() if x["serverNamed"]]
    with_key = {x["path"] for x in named}
    assert {"Gifts", "Giving", "Cash", "Fees and charges", "Loan payments"} <= with_key
    for x in named:
        assert (
            error(
                change(admin, "Cat", x, kind="transfer" if x["kind"] != "transfer" else "expense")
            )[2]
            == "category-kept"
        )
        assert error(remove(admin, "Cat", x))[2] == "category-kept"
        assert not x["allowed"]["delete"] and not x["allowed"]["merge"]
    gifts = next(x for x in named if x["path"] == "Gifts")
    renamed = saved(change(admin, "Cat", gifts, name="Presents", taxTag="business"))
    assert renamed["name"] == "Presents" and renamed["taxTag"] == "business"


def test_every_key_the_server_names_is_kept(server):
    """A key the server's code looks a category up by is one of SERVER_KEYS: a source test,
    so a new one can't be merged away unnoticed."""
    import pathlib
    import re

    import moolakata

    root = pathlib.Path(moolakata.__file__).parent
    found = set()
    pattern = re.compile(r'(?:\.key\(|builtIn == )"([a-z.-]+)"')
    for path in root.rglob("*.py"):
        if "dev" in path.relative_to(root).parts or "alembic" in path.parts:
            continue
        found |= set(pattern.findall(path.read_text()))
    found.discard("admins")  # the Admins group's key, not a category's
    assert found and found <= SERVER_KEYS, found - SERVER_KEYS


DELETES = [
    # (caller, origin, allowed)
    ("admin", "shipped", True),
    ("alice", "shipped", False),
    ("admin", "alice's", True),
    ("alice", "alice's", True),
    ("bob", "alice's", False),
]


@pytest.mark.parametrize("caller,origin,allowed", DELETES)
def test_who_deletes_a_category_nothing_uses(people, caller, origin, allowed):
    cat = _origin(people, origin)
    c = people[caller]
    current = row(c, cat["id"])
    assert current["allowed"]["delete"] is allowed
    r = remove(c, "Cat", current)
    if allowed:
        assert r.status_code == 200, r.text
        assert cat["id"] not in {x["id"] for x in c.get("/ui/api/categories").json()["items"]}
    else:
        assert error(r) == (403, None, "admins-only")


def _texts(c) -> list[str]:
    return [a["text"] for a in c.get("/ui/api/activity").json()["items"]]


def test_every_change_goes_to_activity_for_every_user(people, server):
    admin, alice, bob = people["admin"], people["alice"], people["bob"]
    pets = new(alice, "Pets")
    vet = new(alice, "Vet")
    vet = saved(change(alice, "Cat", vet, parentId=pets["id"]))
    vet = saved(change(alice, "Cat", vet, name="Vets"))
    vet = saved(change(alice, "Cat", vet, taxTag="medical"))
    vet = saved(change(alice, "Cat", vet, kind="income"))
    vet = saved(change(admin, "Cat", vet, keepReceiptsYears=7))
    saved(remove(alice, "Cat", row(alice, vet["id"])))
    want = [
        "Alice deleted the category Pets › Vets",
        "Ada Admin set how long Pets › Vets's receipts are kept to 7 years"
        " (it was its parent's, or for ever)",
        "Alice made Pets › Vets a income category (it was expense)",
        "Alice changed Pets › Vets's tax tag from none to medical",
        "Alice renamed the category Pets › Vet to Pets › Vets",
        "Alice moved the category Vet from the top level to Pets",
        "Alice added the category Vet",
        "Alice added the category Pets",
    ]
    for c in (admin, alice, bob):
        got = [t for t in _texts(c) if "categor" in t or "Vet" in t]
        assert got == want, got
    # Never to a linked server's user, who reads only what is shared with them (S10.3.3).
    with server.db.tx(unscoped="test") as s:
        from moolakata.links.manage import apply_directory
        from moolakata.store.entities.links import Link
        from moolakata.store.entities.users import User

        link = Link(id=ids.new_id("Link"), state="active", role="inviter")
        s.add(link)
        s.flush()
        apply_directory(
            s,
            link,
            {"users": [{"id": "r-tom", "username": "tom", "displayName": "Tom", "sex": "male"}]},
        )
        tom = s.scalars(select(User).where(User.linkId == link.id)).one()
        s.flush()
        seen = s.execute(
            text(
                'SELECT COUNT(*) FROM "ActivityAccess" AS v '
                'JOIN "Activity" AS e ON e.id = v."targetId" '
                'WHERE v."userId" = :u AND e."subjectKind" = \'category\''
            ),
            {"u": tom.id},
        ).scalar()
        assert seen == 0
        bobs = s.execute(
            text(
                'SELECT COUNT(*) FROM "ActivityAccess" AS v '
                'JOIN "Activity" AS e ON e.id = v."targetId" '
                'JOIN "User" AS u ON u.id = v."userId" '
                "WHERE u.username = 'bob' AND e.\"subjectKind\" = 'category'"
            ),
        ).scalar()
        assert bobs == len(want)


def test_a_category_changed_by_another_page_is_stale(people):
    alice = people["alice"]
    pets = new(alice, "Pets")
    saved(change(alice, "Cat", pets, name="Pet"))
    assert change(alice, "Cat", pets, name="Animals").status_code == 412


def test_a_shipped_categorys_key_stays_when_renamed(people, server):
    admin = people["admin"]
    food = rows(admin)["Food"]
    saved(change(admin, "Cat", food, name="Groceries and dining"))
    with server.db.read(unscoped="test") as s:
        got = s.scalars(select(Category).where(Category.builtIn == "food")).one()
        assert got.name == "Groceries and dining"


def test_a_category_made_in_a_dialogs_draft_is_made_before_what_names_it(people):
    """New category… in a transaction's dialog (S12.15.7): the category comes after the
    transaction in the draft, and the save makes it first, so the transaction finds it; a
    refusal of either saves neither."""
    from edits import new_id

    alice = people["alice"]
    acct = new_account(alice)
    txn, cat = new_id("Txn"), new_id("Cat")

    def ops(name):
        return [
            {
                "op": "create",
                "entity": "Txn",
                "id": txn,
                "fields": {
                    "accountId": acct["id"],
                    "date": "2026-10-02",
                    "amount": "-9.00",
                    "kind": "withdrawal",
                    "payee": "Vet",
                    "categoryId": cat,
                },
            },
            {
                "op": "create",
                "entity": "Cat",
                "id": cat,
                "fields": {
                    "name": name,
                    "kind": "expense",
                    "parentId": None,
                    "taxTag": None,
                    "keepReceiptsYears": None,
                },
            },
        ]

    r = alice.post("/ui/api/save", json={"ops": ops("")})
    assert r.status_code == 422 and cat in {e["id"] for e in r.json()["errors"]}
    assert "Vet bills" not in rows(alice)
    r = alice.post("/ui/api/save", json={"ops": ops("Vet bills")})
    assert r.status_code == 200, r.text
    got = alice.get(f"/ui/api/transactions/{txn}").json()
    assert got["categoryId"] == cat == rows(alice)["Vet bills"]["id"]


# ---------- each refusal's whole answer: what the dialog shows ----------


def answer(r) -> tuple:
    e = r.json()["errors"][0]
    return r.status_code, e.get("field"), e["code"], e["message"]


TOP_TAKEN = "There is a category with this name at the top level already."
NAME_WORDS = "Enter a name of up to 60 characters, without ›."
TWO_LEVELS = "Categories have two levels: choose a top-level one."
YEARS = "A whole number of years from 1."


def test_what_a_new_category_is_refused_says(people):
    admin, alice = people["admin"], people["alice"]
    food = rows(alice)["Food"]["id"]

    def made(c, **fields):
        return answer(make(c, "Cat", **{"name": "Odd", "kind": "expense", **fields}))

    assert made(alice, name=" ") == (422, "name", "name-invalid", NAME_WORDS)
    assert made(alice, name="FOOD") == (422, "name", "name-taken", TOP_TAKEN)
    assert made(alice, name="groceries", parentId=food) == (
        422,
        "name",
        "name-taken",
        "There is a category with this name beside it already.",
    )
    assert made(alice, kind="spending") == (
        422,
        "kind",
        "kind-invalid",
        "Expense, income, savings or transfer.",
    )
    assert made(alice, parentId=rows(alice)["Food › Groceries"]["id"]) == (
        422,
        "parentId",
        "parent-invalid",
        TWO_LEVELS,
    )
    assert made(alice, taxTag="hobby") == (
        422,
        "taxTag",
        "tax-tag-invalid",
        "Choose one of the tax tags, or none.",
    )
    assert made(alice, keepReceiptsYears=5) == (
        403,
        "keepReceiptsYears",
        "admins-only",
        "Only admins can do this.",
    )
    assert made(admin, keepReceiptsYears=0) == (422, "keepReceiptsYears", "years-invalid", YEARS)
    assert new(admin, "Kept five", keepReceiptsYears=5)["keepReceiptsYears"] == 5


@pytest.mark.parametrize("years,ok", [(0, False), (1, True), (100, True), (101, False)])
def test_how_long_receipts_are_kept_is_from_1_to_100_years(people, years, ok):
    admin = people["admin"]
    cat = new(admin, f"Kept {years}")
    r = change(admin, "Cat", cat, keepReceiptsYears=years)
    if ok:
        assert saved(r)["keepReceiptsYears"] == years
        # Emptied again: for ever, or as its parent says.
        assert (
            saved(change(admin, "Cat", row(admin, cat["id"]), keepReceiptsYears=None))[
                "keepReceiptsYears"
            ]
            is None
        )
    else:
        assert answer(r) == (422, "keepReceiptsYears", "years-invalid", YEARS)


def test_what_a_change_refused_says(people):
    admin, alice, bob = people["admin"], people["alice"], people["bob"]
    have = rows(admin)
    mine = new(alice, "Mine")
    _use(people, mine["id"])
    cases = [
        (
            bob,
            have["Entertainment"],
            {"kind": "income"},
            (
                403,
                "kind",
                "admins-only",
                "Only admins change a shipped category's parent, kind or tax tag.",
            ),
        ),
        (
            bob,
            row(bob, mine["id"]),
            {"taxTag": "medical"},
            (
                403,
                "taxTag",
                "admins-only",
                "Only admins change another user's category's parent, kind or tax tag.",
            ),
        ),
        (
            alice,
            row(alice, mine["id"]),
            {"parentId": have["Food"]["id"]},
            (
                403,
                "parentId",
                "admins-only",
                "It's in use now: only admins change its parent, kind or tax tag.",
            ),
        ),
        (
            admin,
            have["Gifts"],
            {"kind": "income"},
            (
                422,
                "kind",
                "category-kept",
                "MoolaKata counts in this category by its own rules: its kind stays.",
            ),
        ),
        (
            admin,
            have["Food"],
            {"parentId": have["Health"]["id"]},
            (
                422,
                "parentId",
                "parent-invalid",
                "It has categories of its own, and categories have two levels: it stays at the"
                " top.",
            ),
        ),
        (
            admin,
            have["Travel"],
            {"taxTag": "hobby"},
            (422, "taxTag", "tax-tag-invalid", "Choose one of the tax tags, or none."),
        ),
        (
            admin,
            have["Travel"],
            {"keepReceiptsYears": 0},
            (422, "keepReceiptsYears", "years-invalid", YEARS),
        ),
        (admin, have["Travel"], {"name": "food"}, (422, "name", "name-taken", TOP_TAKEN)),
    ]
    for c, cat, fields, want in cases:
        assert answer(change(c, "Cat", cat, **fields)) == want, fields


def test_what_a_delete_refused_says(people):
    admin, alice, bob = people["admin"], people["alice"], people["bob"]
    have = rows(admin)
    used = new(alice, "Used")
    _use(people, used["id"])
    mine = new(alice, "Spare")
    cases = [
        (
            admin,
            have["Gifts"],
            (
                422,
                None,
                "category-kept",
                "MoolaKata counts in this category by its own rules: it stays.",
            ),
        ),
        (
            admin,
            row(admin, used["id"]),
            (
                422,
                None,
                "category-in-use",
                "It's in use: 1 use you can't see. An admin can merge it into another category.",
            ),
        ),
        (
            alice,
            have["Travel"],
            (403, None, "admins-only", "Only admins delete a shipped category."),
        ),
        (
            bob,
            row(bob, mine["id"]),
            (403, None, "admins-only", "Only admins delete another user's category."),
        ),
    ]
    for c, cat, want in cases:
        assert answer(remove(c, "Cat", cat)) == want, cat["path"]


def test_a_deleted_category_is_not_found_and_its_name_is_free_again(people, server):
    alice = people["alice"]
    gone = new(alice, "Gone soon")
    saved(remove(alice, "Cat", gone))
    with server.db.read(unscoped="test") as s:
        got = s.get(Category, gone["id"])
        assert got.deleted and got.deletedById == got.createdById  # Alice, who deleted it
    for r in (change(alice, "Cat", gone, name="Back"), remove(alice, "Cat", gone)):
        assert answer(r) == (404, None, "not-found", "Not found")
    assert new(alice, "Gone soon")["id"] != gone["id"]


def test_a_row_names_its_maker_and_the_save_answers_with_the_row(people):
    admin, alice = people["admin"], people["alice"]
    mine = new(alice, "Named")
    assert row(admin, mine["id"])["createdByName"] == "Alice"
    assert rows(admin)["Food"]["createdByName"] is None and rows(admin)["Food"]["shipped"]
    _use(people, mine["id"])
    renamed = saved(change(admin, "Cat", row(admin, mine["id"]), name="Named again"))
    assert renamed["inUse"] is True and renamed["createdByName"] == "Alice"
    assert saved(change(admin, "Cat", rows(admin)["Travel"], name="Trips"))["inUse"] is False


def test_each_change_names_its_category_and_tells_every_page(people, server, monkeypatch):
    admin, alice = people["admin"], people["alice"]
    told = []
    monkeypatch.setattr(server.events, "publish", lambda kind, data=None, **kw: told.append(kind))
    pets = new(alice, "Pets")
    vet = new(alice, "Vet", parentId=pets["id"])
    vet = saved(change(alice, "Cat", vet, parentId=rows(alice)["Health"]["id"]))
    vet = saved(change(admin, "Cat", vet, keepReceiptsYears=7))
    saved(change(admin, "Cat", row(admin, vet["id"]), keepReceiptsYears=3))
    saved(change(admin, "Cat", row(admin, vet["id"]), keepReceiptsYears=1))
    saved(change(alice, "Cat", row(alice, pets["id"]), taxTag="medical"))
    saved(change(alice, "Cat", row(alice, pets["id"]), taxTag=None))
    assert told.count("category") == 8
    items = admin.get("/ui/api/activity").json()["items"]
    cats = [a for a in items if a["kind"].startswith("category.")]
    assert {a["subjectKind"] for a in cats} == {"category"}
    assert {a["subjectId"] for a in cats} == {pets["id"], vet["id"]}
    texts = [a["text"] for a in cats]
    assert "Alice moved the category Vet from Pets to Health" in texts
    assert (
        "Ada Admin set how long Health › Vet's receipts are kept to 1 year (it was 3 years)"
        in texts
    )
    assert "Alice changed Pets's tax tag from medical to none" in texts
    assert "Alice changed Pets's tax tag from none to medical" in texts
    assert (
        "Ada Admin set how long Health › Vet's receipts are kept to 3 years (it was 7 years)"
        in texts
    )
    assert (
        "Ada Admin set how long Health › Vet's receipts are kept to 7 years"
        " (it was its parent's, or for ever)" in texts
    )


def test_two_new_categories_naming_each_other_are_refused_not_lost(people):
    """The save puts a create another names first; two that name each other can't both go
    first, and are refused as any parent that isn't there yet is."""
    from edits import new_id

    alice = people["alice"]
    a, b = new_id("Cat"), new_id("Cat")
    ops = [
        {
            "op": "create",
            "entity": "Cat",
            "id": a,
            "fields": {
                "name": "A",
                "kind": "expense",
                "parentId": b,
                "taxTag": None,
                "keepReceiptsYears": None,
            },
        },
        {
            "op": "create",
            "entity": "Cat",
            "id": b,
            "fields": {
                "name": "B",
                "kind": "expense",
                "parentId": a,
                "taxTag": None,
                "keepReceiptsYears": None,
            },
        },
    ]
    r = alice.post("/ui/api/save", json={"ops": ops})
    assert r.status_code == 422, r.text
    assert {e["code"] for e in r.json()["errors"]} == {"parent-invalid"}


def test_a_save_that_changes_nothing_records_nothing(people, server):
    from moolakata.categories import used

    alice = people["alice"]
    pets = new(alice, "Pets")
    before = len(alice.get("/ui/api/activity").json()["items"])
    assert saved(change(alice, "Cat", pets, name="Pets"))["version"] == pets["version"]
    assert len(alice.get("/ui/api/activity").json()["items"]) == before
    with server.db.read(unscoped="test") as s:
        assert used(s, []) == set()


# ---------- its uses (S12.2.6, S12.17.6) ----------


def uses(c, cat_id: str) -> dict:
    r = c.get(f"/ui/api/categories/{cat_id}/uses")
    assert r.status_code == 200, r.text
    return r.json()


KIND = {
    "transaction": "transactions",
    "split": "transactions",
    "rule": "rules",
    "plan line": "planLines",
    "move": "moves",
    "loan": "loans",
    "child": "categories",
}
# Who else sees each kind of use, as made in an account or budget of the maker's own: a child
# category is the household's; the rest are the maker's until shared (S10.3).
EVERYONE_SEES = {"child"}


def _listed(u: dict, kind: str) -> int:
    v = u[KIND[kind]]
    return v if kind in ("transaction", "split") else len(v)


@pytest.mark.parametrize("how", USES)
def test_each_use_is_listed_for_its_maker_and_counted_for_others(people, how):
    alice, bob = people["alice"], people["bob"]
    mine = new(alice, "Hobbies")
    empty = uses(alice, mine["id"])
    assert empty == {
        "gone": False,
        "seen": 0,
        "unseen": 0,
        "transactions": 0,
        "rules": [],
        "planLines": [],
        "moves": [],
        "loans": [],
        "categories": [],
    }
    _put_to_use(alice, mine["id"], how)
    u = uses(alice, mine["id"])
    assert (u["seen"], u["unseen"], _listed(u, how)) == (1, 0, 1)
    assert all(_listed(u, k) == 0 for k in USES if KIND[k] != KIND[how])
    other = uses(bob, mine["id"])
    if how in EVERYONE_SEES:
        assert (other["seen"], other["unseen"], _listed(other, how)) == (1, 0, 1)
    else:
        assert (other["seen"], other["unseen"], _listed(other, how)) == (0, 1, 0)


def test_what_each_use_says(people):
    alice = people["alice"]
    pets = new(alice, "Pets")
    for how in USES:
        _put_to_use(alice, pets["id"], how)
    u = uses(alice, pets["id"])
    assert (u["seen"], u["unseen"], u["transactions"]) == (7, 0, 2)
    assert u["rules"] == [{"id": u["rules"][0]["id"], "payeeMatch": "toys", "position": 0}]
    assert [(x["budgetName"], x["month"]) for x in u["planLines"]] == [
        ("B plan line", "2026-10-01")
    ]
    assert [(x["budgetName"], x["month"]) for x in u["moves"]] == [("B move", "2026-10-01")]
    assert [x["name"] for x in u["loans"]] == ["Car loan"]
    assert [x["name"] for x in u["categories"]] == ["Inside"]
    budgets = {b["name"]: b["id"] for b in alice.get("/ui/api/budgets").json()["items"]}
    assert u["planLines"][0]["budgetId"] == budgets["B plan line"]
    assert u["moves"][0]["budgetId"] == budgets["B move"]


def test_a_transaction_counts_once_whatever_its_parts(people):
    alice = people["alice"]
    pets = new(alice, "Pets")
    acct = new_account(alice)
    split = [
        {"categoryId": pets["id"], "amount": "-2.00"},
        {"categoryId": pets["id"], "amount": "-3.00"},
    ]
    add(alice, acct["id"], "-5.00", splits=split)
    add(alice, acct["id"], "-4.00", categoryId=pets["id"])
    u = uses(alice, pets["id"])
    assert (u["transactions"], u["seen"]) == (2, 2)
    # As the Transactions page filtered to it counts them.
    listed = alice.get("/ui/api/transactions", params={"category": pets["id"]}).json()
    assert listed["total"] == 2


def test_a_shared_account_shows_its_uses(people):
    from edits import share

    alice, bob = people["alice"], people["bob"]
    pets = new(alice, "Pets")
    acct = new_account(alice)
    for amount in ("-1.00", "-2.00", "-3.00"):
        add(alice, acct["id"], amount, categoryId=pets["id"])
    hidden = new_account(alice, name="Mine alone", mask="4242")
    add(alice, hidden["id"], "-9.00", categoryId=pets["id"])
    assert (uses(bob, pets["id"])["seen"], uses(bob, pets["id"])["unseen"]) == (0, 4)
    share(alice, "account", acct["id"], users={people["ids"]["bob"]: "read"})
    u = uses(bob, pets["id"])
    assert (u["seen"], u["unseen"], u["transactions"]) == (3, 1, 3)


def test_deleted_uses_count_for_nothing(people):
    alice = people["alice"]
    pets = new(alice, "Pets")
    acct = new_account(alice)
    whole = add(alice, acct["id"], "-4.00", categoryId=pets["id"])
    parts = [{"categoryId": pets["id"], "amount": "-2.00"}, {"categoryId": None, "amount": "-3.00"}]
    split = add(alice, acct["id"], "-5.00", splits=parts)
    assert uses(alice, pets["id"])["seen"] == 2
    for t in (whole, split):
        saved(remove(alice, "Txn", t))
    # A deleted transaction's parts name nothing either: the category may go.
    u = uses(alice, pets["id"])
    assert (u["seen"], u["unseen"], u["transactions"]) == (0, 0, 0)
    assert not row(alice, pets["id"])["inUse"]


def test_the_uses_of_no_category(people):
    alice = people["alice"]
    assert alice.get("/ui/api/categories/Cat_nothing/uses").status_code == 404
    gone = new(alice, "Gone")
    assert remove(alice, "Cat", row(alice, gone["id"])).status_code == 200
    # One deleted says so, for a tour open on it.
    assert uses(alice, gone["id"]) == {
        "gone": True,
        "seen": 0,
        "unseen": 0,
        "transactions": 0,
        "rules": [],
        "planLines": [],
        "moves": [],
        "loans": [],
        "categories": [],
    }


@pytest.mark.parametrize(
    "seen,unseen,words",
    [
        (1, 0, "1 use you can see"),
        (2, 0, "2 uses you can see"),
        (0, 1, "1 use you can't see"),
        (0, 3, "3 uses you can't see"),
        (1, 1, "1 use you can see, and 1 you can't"),
        (47, 22, "47 uses you can see, and 22 you can't"),
    ],
)
def test_how_uses_are_counted_in_words(seen, unseen, words):
    from moolakata.ui.categories import uses_words

    assert uses_words(seen, unseen) == words


def test_a_refused_delete_counts_both(people):
    alice, bob = people["alice"], people["bob"]
    pets = new(alice, "Pets")
    _put_to_use(alice, pets["id"], "transaction")
    new(bob, "Inside", parentId=pets["id"])
    r = remove(people["admin"], "Cat", row(people["admin"], pets["id"]))
    assert r.json()["errors"][0]["message"] == (
        "It's in use: 1 use you can see, and 1 you can't."
        " An admin can merge it into another category."
    )
    r = remove(bob, "Cat", row(bob, pets["id"]))
    assert r.json()["errors"][0]["message"].startswith("It's in use: 1 use you can see, and 1")


def test_a_save_tells_the_savers_own_pages(people, server, monkeypatch):
    """S12.6: a save, a bulk categorise and rules applied each tell the pages of the user who
    made them, so a tour's counts follow (S12.17.4); nothing at all, or nothing changed, tells
    no one."""
    alice = people["alice"]
    told = []
    monkeypatch.setattr(
        server.events,
        "publish",
        lambda kind, data=None, users=None, **kw: told.append((kind, data, users)),
    )
    me = [people["ids"]["alice"]]
    acct = new_account(alice)
    t = add(alice, acct["id"], "-3.00", payee="Toy shop")
    assert ("saved", None, me) in told
    told.clear()
    pets = new(alice, "Pets")
    told.clear()
    r = alice.post(
        "/ui/api/transactions/categorise", json={"ids": [t["id"]], "categoryId": pets["id"]}
    )
    assert r.json() == {"changed": 1} and told == [("saved", None, me)]
    told.clear()
    alice.post("/ui/api/transactions/categorise", json={"ids": [t["id"]], "categoryId": pets["id"]})
    assert told == [], "nothing changed"
    make(alice, "Rule", payeeMatch="toy", categoryId=pets["id"])
    add(alice, acct["id"], "-4.00", payee="Toy barn")
    told.clear()
    assert alice.post("/ui/api/rules/apply", json={}).json() == {"changed": 1}
    assert told == [("saved", None, me)]
    told.clear()
    assert alice.post("/ui/api/rules/apply", json={}).json() == {"changed": 0}
    assert told == []
    r = alice.post("/ui/api/save", json={"ops": [], "confirm": []})
    assert r.status_code == 200 and told == []


def test_a_categorys_uses_are_its_own_live_ones_in_order(people):
    """Only what names this category, not another's; nothing deleted (a rule, a plan line, a
    move, a loan, a part taken out of a live transaction); each kind in its order: rules as the
    list, plan lines and moves by budget then month, categories by name in any case."""
    from edits import terms
    from test_budgets import save_plan

    alice = people["alice"]
    mine, other = new(alice, "Mine"), new(alice, "Other")
    acct = new_account(alice)
    # Transactions: its own, one through a part, and another category's of each sort.
    add(alice, acct["id"], "-1.00", categoryId=mine["id"])
    add(alice, acct["id"], "-2.00", categoryId=other["id"])
    parts = [
        {"categoryId": other["id"], "amount": "-1.00"},
        {"categoryId": None, "amount": "-1.00"},
    ]
    add(alice, acct["id"], "-2.00", splits=parts)
    gone_part = add(
        alice,
        acct["id"],
        "-3.00",
        splits=[
            {"categoryId": mine["id"], "amount": "-1.00"},
            {"categoryId": None, "amount": "-2.00"},
        ],
    )
    live = alice.get(f"/ui/api/transactions/{gone_part['id']}").json()
    part = next(x for x in live["splits"] if x["categoryId"] == mine["id"])
    saved(change(alice, "Split", part, categoryId=other["id"]))
    # Rules: two of its own, out of the order they were made in once moved; one deleted; one
    # of another category.
    first = make(alice, "Rule", payeeMatch="zzz", categoryId=mine["id"]).json()
    second = make(alice, "Rule", payeeMatch="aaa", categoryId=mine["id"]).json()
    make(alice, "Rule", payeeMatch="other", categoryId=other["id"]).json()
    dropped = make(alice, "Rule", payeeMatch="dropped", categoryId=mine["id"]).json()
    saved(remove(alice, "Rule", dropped))
    have = {r["id"]: r for r in alice.get("/ui/api/rules").json()["items"]}
    saved(change(alice, "Rule", have[second["id"]], position=0))
    # Plan lines and moves in two budgets, the later budget's earlier, each month made late.
    b1 = make(alice, "Bdgt", name="B one", accountIds=[acct["id"]], method="envelope").json()
    b2 = make(alice, "Bdgt", name="B two", accountIds=[acct["id"]], method="envelope").json()
    line = lambda c: {"categoryId": c, "amount": "5.00"}  # noqa: E731
    for b, months in ((b1, ("2026-09-01", "2026-07-01")), (b2, ("2026-05-01",))):
        for m in months:
            assert save_plan(alice, b, m, [line(mine["id"]), line(other["id"])]).status_code == 200
    assert save_plan(alice, b2, "2026-06-01", [line(other["id"])]).status_code == 200
    food = rows(alice)["Food"]["id"]
    move = lambda b, m, a, z: make(  # noqa: E731
        alice, "BdgMv", budgetId=b["id"], month=m, fromCategoryId=a, toCategoryId=z, amount="1.00"
    ).json()
    move(b1, "2026-09-01", food, mine["id"])
    move(b1, "2026-07-01", mine["id"], food)
    move(b2, "2026-05-01", food, other["id"])
    gone = move(b2, "2026-04-01", food, mine["id"])
    saved(remove(alice, "BdgMv", gone))
    # Loans: one counting in it, one in another, one whose terms went.
    for name, cat in (("Loan mine", mine), ("Loan other", other), ("Loan gone", mine)):
        loan = new_account(alice, name=name, type="auto-loan", mask="7777")
        made_terms = terms(
            alice,
            loan["id"],
            principal="9000.00",
            rate="5",
            termMonths=48,
            startDate="2026-11-01",
            budgetCounting="whole",
            budgetCategoryId=cat["id"],
        )
        assert made_terms.status_code == 200, made_terms.text
        if name == "Loan gone":  # its terms go with its account
            saved(remove(alice, "Acct", alice.get(f"/ui/api/accounts/{loan['id']}").json()))
    # Categories under it, named in either case.
    for name in ("beta", "Alpha", "a_b", "aZ"):
        new(alice, name, parentId=mine["id"])
    new(alice, "Elsewhere", parentId=other["id"])

    u = uses(alice, mine["id"])
    assert u["transactions"] == 1
    assert [r["payeeMatch"] for r in u["rules"]] == ["aaa", "zzz"]
    assert [r["position"] for r in u["rules"]] == sorted(r["position"] for r in u["rules"])
    assert [(x["budgetName"], x["month"]) for x in u["planLines"]] == [
        ("B one", "2026-07-01"),
        ("B one", "2026-09-01"),
        ("B two", "2026-05-01"),
        ("B two", "2026-06-01"),  # where the plan takes it out: a line that names it too
    ]
    assert [(x["budgetName"], x["month"]) for x in u["moves"]] == [
        ("B one", "2026-07-01"),
        ("B one", "2026-09-01"),
    ]
    assert [x["name"] for x in u["loans"]] == ["Loan mine"]
    assert [x["name"] for x in u["categories"]] == ["a_b", "Alpha", "aZ", "beta"]
    # A deleted account's loan is no use the reader sees, but still one: restored, it would
    # name the category again (as `used` holds it, keeping the category from deletion).
    assert u["seen"] == 1 + 2 + 4 + 2 + 1 + 4 and u["unseen"] == 1
    assert first["id"] in {r["id"] for r in u["rules"]}


def test_a_deleted_move_leaves_its_category_unused(people):
    """`used` reads moves as the count does: a deleted one names nothing."""
    alice = people["alice"]
    spare = new(alice, "Spare")
    acct = new_account(alice)
    b = make(alice, "Bdgt", name="B", accountIds=[acct["id"]], method="envelope").json()
    food = rows(alice)["Food"]["id"]
    for a, z in ((spare["id"], food), (food, spare["id"])):
        m = make(
            alice,
            "BdgMv",
            budgetId=b["id"],
            month="2026-10-01",
            fromCategoryId=a,
            toCategoryId=z,
            amount="1.00",
        ).json()
        assert row(alice, spare["id"])["inUse"]
        saved(remove(alice, "BdgMv", m))
        assert not row(alice, spare["id"])["inUse"]
