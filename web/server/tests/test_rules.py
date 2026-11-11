"""Categorisation and payee rules (requirements S2.7)."""

import io
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, make, remove, saved, tag
from PIL import Image
from test_accounts import FIX, add, new_account, upload
from test_receipts import upload as upload_receipt

from moolakata.ledger import rules as match


def cats(c) -> dict[str, str]:
    return {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


# ---- matching ----


def m(**kw):
    rule = type(
        "R", (), {"amountMin": None, "amountMax": None, "direction": "any", "accountId": None} | kw
    )
    return match.matcher(rule)


def test_text_matches_anywhere_case_aside_and_re_by_its_pattern():
    assert match.matches(m(payeeMatch="whole foods"), "WHOLE FOODS #123", D("-40"), "A")
    assert not match.matches(m(payeeMatch="whole foods"), "WHOLEFOODS", D("-40"), "A")
    assert match.matches(m(payeeMatch="re:^amzn"), "AMZN Mktp US", D("-12"), "A")
    assert not match.matches(m(payeeMatch="re:^amzn"), "PAYPAL *AMZN", D("-12"), "A")


def test_amount_direction_and_account_narrow_a_rule():
    r = m(payeeMatch="sq *", amountMax=D(20), direction="out", accountId="A")
    assert match.matches(r, "SQ *BLUE BOTTLE", D("-5.75"), "A")
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("-25.00"), "A")  # over the range
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("5.75"), "A")  # money in
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("-5.75"), "B")  # another account


@pytest.mark.parametrize("bad", ["", "re:", "re:(unclosed", "re:a{2,1}", "re:a++", "x" * 201])
def test_patterns_that_cant_be_kept_are_refused(bad):
    with pytest.raises(match.Invalid):
        match.compile_pattern(bad)


@pytest.mark.parametrize(
    "pattern", [r"re:(?=AMZN)", r"re:(?!AMZN)", r"re:(?<=SQ )x", r"re:(?<!SQ )x", r"re:(a)\1"]
)
def test_what_needs_backtracking_is_refused_in_plain_words(pattern):
    """RE2's syntax (S2.7.1): what Python's has and RE2's hasn't is named, not RE2's text."""
    with pytest.raises(match.Invalid) as e:
        match.compile_pattern(pattern)
    assert str(e.value) == "RE2 has no look-arounds or back-references."


def test_any_other_refusal_gives_re2s_reason():
    with pytest.raises(match.Invalid) as e:
        match.compile_pattern("re:(")
    assert str(e.value) == "Not a regular expression: missing ): (."


@pytest.mark.parametrize(
    ("pattern", "payee", "hit"),
    [
        (r"re:^whole ?foods", "WHOLE FOODS #12", True),
        (r"re:[[:digit:]]{4}$", "CHECK 1042", True),
        (r"re:\bfuel\b", "KROGER FUEL #3", True),
        (r"re:\bfuel\b", "KROGERFUELS", False),
        (r"re:(?P<store>kroger|aldi) #\d+", "ALDI #77", True),
        (r"re:^(sq|tst)\s*\*", "TST* BLUE BOTTLE", True),
        (r"re:café$", "CAFÉ", True),  # case aside beyond ASCII too
        (r"re:\z", "anything", True),
    ],
)
def test_re2_patterns_match_as_written(pattern, payee, hit):
    assert match.matches(m(payeeMatch=pattern), payee, D("-1"), "A") is hit


@pytest.mark.parametrize(
    "pattern", [r"re:((a+))+$", r"re:(?:(a+))+$", r"re:((ab)+)+$", r"re:(a|aa)+$", "re:a.*a.*a.*b"]
)
def test_no_pattern_holds_the_server(pattern):
    """CR3-25: each of these backtracked for ever in Python's re on a payee that nearly
    matches; RE2 reads the 500 characters once. The bound is generous: a backtracking engine
    takes days here, RE2 microseconds."""
    import time

    r = m(payeeMatch=pattern)
    t = time.perf_counter()
    for payee in ("a" * 600 + "!", "ab" * 300 + "!", "a" * 499 + "c"):
        match.matches(r, payee, D("-1"), "A")
    assert time.perf_counter() - t < 2.0


# ---- through the API ----


def test_rules_are_kept_in_order_and_first_match_wins(alice):
    c = cats(alice)
    r = make(alice, "Rule", payeeMatch="re:(?=a)", categoryId=c["Food › Groceries"])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "payeeMatch"
    assert r.json()["errors"][0]["message"] == "RE2 has no look-arounds or back-references."
    r = make(alice, "Rule", payeeMatch="kroger")
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"
    make(alice, "Rule", payeeMatch="kroger", categoryId=c["Food › Groceries"])
    r = make(
        alice, "Rule", payeeMatch="re:^KROGER #1", categoryId=c["Food › Dining out"], payee="Kroger"
    )
    assert r.status_code == 200, r.text
    first, second = alice.get("/ui/api/rules").json()["items"]
    assert (first["position"], second["position"]) == (0, 1)
    # Moved up, through the save: the other closes up behind it.
    assert saved(change(alice, "Rule", second, position=0))["position"] == 0
    assert [x["id"] for x in alice.get("/ui/api/rules").json()["items"]] == [
        second["id"],
        first["id"],
    ]
    a = new_account(alice)
    job = upload(alice, a["id"], "bank.ofx", (FIX / "bank.ofx").read_bytes())
    assert job["result"]["categorised"] == 1, job
    items = alice.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    kroger = next(t for t in items if t["payeeRaw"] == "KROGER #123")
    assert kroger["categoryId"] == c["Food › Dining out"] and kroger["payee"] == "Kroger"
    feed = alice.get("/ui/api/activity").json()["items"]
    assert any("reordered their categorisation rules" in x["text"] for x in feed)


def test_applied_on_demand_to_the_uncategorised_only(alice):
    c = cats(alice)
    a = new_account(alice)
    add(alice, a["id"], "-42.00", "2026-10-01", payee="WHOLE FOODS #77")
    add(
        alice,
        a["id"],
        "-18.00",
        "2026-10-02",
        payee="WHOLE FOODS #77",
        categoryId=c["Food › Dining out"],
    )
    r = make(
        alice, "Rule", payeeMatch="whole foods", categoryId=c["Food › Groceries"], tags=["Food"]
    )
    assert r.status_code == 200, r.text
    assert alice.get("/ui/api/rules").json()["uncategorised"] == 1
    assert alice.post("/ui/api/rules/apply").json()["changed"] == 1
    items = alice.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    got = sorted((t["amount"], t["categoryId"], t["tags"]) for t in items)
    assert got == [
        ("-42.00", c["Food › Groceries"], ["food"]),
        ("-18.00", c["Food › Dining out"], []),
    ]
    assert alice.post("/ui/api/rules/apply").json()["changed"] == 0
    feed = alice.get("/ui/api/activity").json()["items"]
    assert any("rules set 1 transaction" in x["text"] for x in feed)


def test_a_rule_is_its_owners_alone_and_can_be_deleted(server, alice):
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    c = cats(alice)
    r = make(alice, "Rule", payeeMatch="acme", categoryId=c["Income › Salary"]).json()
    assert bob.get("/ui/api/rules").json()["items"] == []
    assert remove(bob, "Rule", r).status_code == 404
    assert remove(alice, "Rule", r).status_code == 200
    assert alice.get("/ui/api/rules").json()["items"] == []


def test_a_rule_changed_keeps_its_place_and_sets_what_it_says(server, alice):
    c = cats(alice)
    for payee in ("acme", "shop"):
        make(alice, "Rule", payeeMatch=payee, categoryId=c["Income › Salary"])
    first, second = alice.get("/ui/api/rules").json()["items"]
    work = tag(alice, "Work")
    r = change(alice, "Rule", first, payee="Acme Corp", tagIds={"add": [work], "remove": []})
    assert r.status_code == 200, r.text
    items = alice.get("/ui/api/rules").json()["items"]
    assert [x["id"] for x in items] == [first["id"], second["id"]]
    assert (items[0]["payee"], items[0]["tags"]) == ("Acme Corp", ["work"])
    r = change(alice, "Rule", items[1], categoryId=None)
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"


def test_a_receipts_merchant_is_renamed_by_the_rules(server, alice):
    from moolakata.receipts.reading import save_reading
    from moolakata.store.entities.receipts import Receipt

    make(alice, "Rule", payeeMatch="re:blue ?bottle", payee="Blue Bottle")
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    rid = upload_receipt(alice, buf.getvalue()).json()["id"]
    with server.db.tx(unscoped="test") as s:
        save_reading(s, s.get(Receipt, rid), ["BLUEBOTTLE CAFE", "TOTAL 5.75"], "text", "test")
    assert alice.get(f"/ui/api/receipts/{rid}").json()["payee"] == "Blue Bottle"


def test_user_text_reaches_a_regular_expression_only_through_a_rule():
    """CR3-25's category: a pattern a user typed, run by a backtracking engine. Python's `re`
    is called only with patterns written in the code; the rest are named here with what they
    are built from, never a user's text. A user's pattern goes through `compile_pattern`."""
    import ast
    from pathlib import Path

    import moolakata

    built = {
        "exactjson.py": "its own marker pattern, as bytes",
        "mcp.py": "the patterns its tools declare for their arguments",
        "middleware.py": "the API's route paths",
        "dev/mutate.py": "the module names a developer passes",
    }
    calls = {"compile", "search", "match", "fullmatch", "sub", "subn", "split", "findall"}
    calls.add("finditer")
    root = Path(moolakata.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr in calls
            ):
                continue
            given = (k.value for k in node.keywords if k.arg == "pattern")
            arg = node.args[0] if node.args else next(given, None)
            if not isinstance(arg, ast.Constant):
                found.add(path.relative_to(root).as_posix())
    assert found == set(built)


@pytest.mark.parametrize(
    ("args", "said"),
    [
        ((b"missing ): (",), "Not a regular expression: missing ): (."),
        (("as text",), "Not a regular expression: as text."),
        ((b"bad \xff byte",), "Not a regular expression: bad � byte."),
        ((), "Not a regular expression: ."),
        ((b"invalid perl operator: (?<=",), "RE2 has no look-arounds or back-references."),
        ((b"invalid escape sequence: \\9",), "RE2 has no look-arounds or back-references."),
    ],
)
def test_re2s_reason_is_read_whatever_form_it_comes_in(args, said):
    """RE2 gives its reason as bytes; text, a byte that isn't UTF-8 and none at all read too."""
    import re2

    assert match._refusal(re2.error(*args)) == said
