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
    make_user(server, "alice")
    make_user(server, "bob")
    return {"admin": admin_client, "alice": sign_in(server, "alice"), "bob": sign_in(server, "bob")}


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
