"""Categorisation and payee rules (requirements S2.7)."""

import io
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved, tag
from PIL import Image
from test_accounts import FIX, add, new_account, upload
from test_receipts import upload as upload_receipt

from moolakata.ledger import rules as match


def cats(c) -> dict[str, str]:
    return {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


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


NO_BACKTRACKING = "RE2 has no look-arounds or back-references."
NO_ATOMIC = "RE2 has no atomic groups, possessive repeats or conditionals."
FLAGS = "RE2's inline flags are i, m, s and U."


@pytest.mark.parametrize(
    ("pattern", "said"),
    [
        # Every form of Python's syntax that RE2 hasn't: look-arounds,
        (r"re:(?=AMZN)", NO_BACKTRACKING),
        (r"re:(?!AMZN)", NO_BACKTRACKING),
        (r"re:(?<=SQ )x", NO_BACKTRACKING),
        (r"re:(?<!SQ )x", NO_BACKTRACKING),
        # back-references, by number and by name, in each spelling,
        (r"re:(a)\1", NO_BACKTRACKING),
        (r"re:(a)(b)(c)(d)(e)(f)(g)(h)(i)\9", NO_BACKTRACKING),
        (r"re:(a)\g<1>", NO_BACKTRACKING),
        (r"re:(?P<n>a)(?P=n)", NO_BACKTRACKING),
        (r"re:(?<n>a)\k<n>", NO_BACKTRACKING),
        # atomic groups, possessive repeats and conditionals,
        (r"re:(?>a+)b", NO_ATOMIC),
        (r"re:a++", NO_ATOMIC),
        (r"re:a*+", NO_ATOMIC),
        (r"re:a?+", NO_ATOMIC),
        (r"re:a{2}+", NO_ATOMIC),
        (r"re:(a)?(?(1)b|c)", NO_ATOMIC),
        # and the inline flags RE2 hasn't.
        (r"re:(?x) a", FLAGS),
        (r"re:(?a)a", FLAGS),
        (r"re:(?L)a", FLAGS),
        (r"re:(?u)a", FLAGS),
        (r"re:(?-x)a", FLAGS),
    ],
)
def test_what_python_has_and_re2_hasnt_is_refused_in_plain_words(pattern, said):
    """RE2's syntax (S2.7.1): what Python's has and RE2's hasn't is named, not RE2's text."""
    with pytest.raises(match.Invalid) as e:
        match.compile_pattern(pattern)
    assert str(e.value) == said


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
        # RE2's own inline flags: (?i) changes nothing; (?-i) turns case on, as the user asks.
        (r"re:(?i)amzn", "AMZN MKTP", True),
        (r"re:(?-i)AMZN", "amzn mktp", False),
        (r"re:(?-i)AMZN", "AMZN MKTP", True),
        (r"re:(?-i:AMZN) mktp", "AMZN MKTP", True),
        (r"re:(?s)a.b", "A\nB", True),
        # \10 is no back-reference in RE2: it is the character with octal code 10.
        (r"re:(a)\10", "A\x08", True),
        (r"re:(a)\10", "AA", False),
    ],
)
def test_re2_patterns_match_as_written(pattern, payee, hit):
    assert match.matches(m(payeeMatch=pattern), payee, D("-1"), "A") is hit


@pytest.mark.parametrize(
    "pattern", [r"re:((a+))+$", r"re:(?:(a+))+$", r"re:((ab)+)+$", r"re:(a|aa)+$", "re:a.*a.*a.*b"]
)
def test_no_pattern_holds_the_server(pattern):
    """Each of these backtracked for ever in Python's re on a payee that nearly matches; RE2 reads
    the 500 characters once. The bound is generous: a backtracking engine takes days here, RE2
    microseconds."""
    import time

    r = m(payeeMatch=pattern)
    t = time.perf_counter()
    for payee in ("a" * 600 + "!", "ab" * 300 + "!", "a" * 499 + "c"):
        match.matches(r, payee, D("-1"), "A")
    assert time.perf_counter() - t < 2.0


# ---- through the API ----


def test_rules_are_kept_in_order_and_first_match_wins(jane):
    c = cats(jane)
    r = make(jane, "Rule", payeeMatch="re:(?=a)", categoryId=c["Food › Groceries"])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "payeeMatch"
    assert r.json()["errors"][0]["message"] == "RE2 has no look-arounds or back-references."
    r = make(jane, "Rule", payeeMatch="kroger")
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"
    make(jane, "Rule", payeeMatch="kroger", categoryId=c["Food › Groceries"])
    r = make(
        jane, "Rule", payeeMatch="re:^KROGER #1", categoryId=c["Food › Dining out"], payee="Kroger"
    )
    assert r.status_code == 200, r.text
    first, second = jane.get("/ui/api/rules").json()["items"]
    assert (first["position"], second["position"]) == (0, 1)
    # Moved up, through the save: the other closes up behind it.
    assert saved(change(jane, "Rule", second, position=0))["position"] == 0
    assert [x["id"] for x in jane.get("/ui/api/rules").json()["items"]] == [
        second["id"],
        first["id"],
    ]
    a = new_account(jane)
    job = upload(jane, a["id"], "bank.ofx", (FIX / "bank.ofx").read_bytes())
    assert job["result"]["categorised"] == 1, job
    items = jane.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    kroger = next(t for t in items if t["payeeRaw"] == "KROGER #123")
    assert kroger["categoryId"] == c["Food › Dining out"] and kroger["payee"] == "Kroger"
    feed = jane.get("/ui/api/activity").json()["items"]
    assert any("reordered their categorisation rules" in x["text"] for x in feed)


def test_applied_on_demand_to_the_uncategorised_only(jane):
    c = cats(jane)
    a = new_account(jane)
    add(jane, a["id"], "-42.00", "2026-10-01", payee="WHOLE FOODS #77")
    add(
        jane,
        a["id"],
        "-18.00",
        "2026-10-02",
        payee="WHOLE FOODS #77",
        categoryId=c["Food › Dining out"],
    )
    r = make(
        jane, "Rule", payeeMatch="whole foods", categoryId=c["Food › Groceries"], tags=["Food"]
    )
    assert r.status_code == 200, r.text
    assert jane.get("/ui/api/rules").json()["uncategorised"] == 1
    assert jane.post("/ui/api/rules/apply").json()["changed"] == 1
    items = jane.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    got = sorted((t["amount"], t["categoryId"], t["tags"]) for t in items)
    assert got == [
        ("-42.00", c["Food › Groceries"], ["food"]),
        ("-18.00", c["Food › Dining out"], []),
    ]
    assert jane.post("/ui/api/rules/apply").json()["changed"] == 0
    feed = jane.get("/ui/api/activity").json()["items"]
    assert any("rules set 1 transaction" in x["text"] for x in feed)


def test_a_rule_is_its_owners_alone_and_can_be_deleted(server, jane):
    make_user(server, "john")
    john = sign_in(server, "john")
    c = cats(jane)
    r = make(jane, "Rule", payeeMatch="acme", categoryId=c["Income › Salary"]).json()
    assert john.get("/ui/api/rules").json()["items"] == []
    assert remove(john, "Rule", r).status_code == 404
    assert remove(jane, "Rule", r).status_code == 200
    assert jane.get("/ui/api/rules").json()["items"] == []


def test_a_rule_changed_keeps_its_place_and_sets_what_it_says(server, jane):
    c = cats(jane)
    for payee in ("acme", "shop"):
        make(jane, "Rule", payeeMatch=payee, categoryId=c["Income › Salary"])
    first, second = jane.get("/ui/api/rules").json()["items"]
    work = tag(jane, "Work")
    r = change(jane, "Rule", first, payee="Acme Corp", tagIds={"add": [work], "remove": []})
    assert r.status_code == 200, r.text
    items = jane.get("/ui/api/rules").json()["items"]
    assert [x["id"] for x in items] == [first["id"], second["id"]]
    assert (items[0]["payee"], items[0]["tags"]) == ("Acme Corp", ["work"])
    r = change(jane, "Rule", items[1], categoryId=None)
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"


def test_a_receipts_merchant_is_renamed_by_the_rules(server, jane):
    from moolakata.receipts.reading import save_reading
    from moolakata.store.entities.receipts import Receipt

    make(jane, "Rule", payeeMatch="re:blue ?bottle", payee="Blue Bottle")
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    rid = upload_receipt(jane, buf.getvalue()).json()["id"]
    with server.db.tx(unscoped="test") as s:
        save_reading(s, s.get(Receipt, rid), ["BLUEBOTTLE CAFE", "TOTAL 5.75"], "text", "test")
    assert jane.get(f"/ui/api/receipts/{rid}").json()["payee"] == "Blue Bottle"


def test_user_text_reaches_a_regular_expression_only_through_a_rule():
    """Every case of one kind of bug: a pattern a user typed, run by a backtracking engine. Python's
    `re` is called only with patterns written in the code; the rest are named here with what they
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


AMOUNT = "The amount without its sign: 0 or more."


@pytest.mark.parametrize(
    ("fields", "refused"),
    [
        ({"payeeMatch": "re:(?=a)"},
         ("payeeMatch", "pattern-invalid", "RE2 has no look-arounds or back-references.")),
        ({"direction": "sideways"},
         ("direction", "direction-invalid", "Money in, out, or either.")),
        ({"amountMin": "-0.01"}, ("amountMin", "amount-invalid", AMOUNT)),
        ({"amountMax": "-0.01"}, ("amountMax", "amount-invalid", AMOUNT)),
        ({"amountMin": "10", "amountMax": "9.99"},
         ("amountMax", "range-invalid", "At least the amount it starts from.")),
        ({"accountId": "theirs"},
         ("accountId", "account-unknown", "One of the accounts you can change.")),
        ({"categoryId": "gone"}, ("categoryId", "category-unknown", "Choose a category.")),
        ({"payee": "x" * 201}, ("payee", "payee-too-long", "At most 200 characters.")),
        ({"tags": 11}, ("tagIds", "tags-invalid", "Up to 10 tags.")),
        ({"payee": "   ", "categoryId": None},
         ("categoryId", "rule-sets-nothing", "A category, a payee or a tag to set.")),
        # Each bound's own side is kept, and an account of the caller's own.
        ({"direction": "in"}, None),
        ({"amountMin": "0", "amountMax": "0"}, None),
        ({"payee": " " + "x" * 200 + " "}, None),
        ({"tags": 10}, None),
        ({"tags": 1, "categoryId": None}, None),
        ({"accountId": "mine"}, None),
    ],
)  # fmt: skip
def test_each_part_of_a_rule_is_refused_on_its_own_field(server, jane, fields, refused):
    """S2.7: what a rule matches and sets is checked field by field, each refusal saying what
    the field takes (R3.11)."""
    fields = {"payeeMatch": "acme", **fields}
    fields.setdefault("categoryId", cats(jane)["Food › Groceries"])
    if fields.get("accountId") == "theirs":
        make_user(server, "john")
        fields["accountId"] = new_account(sign_in(server, "john"), name="John's")["id"]
    if fields.get("accountId") == "mine":
        fields["accountId"] = new_account(jane, name="Mine")["id"]
    if fields.get("categoryId") == "gone":
        fields["categoryId"] = new_id("Cat")
    if "tags" in fields:
        fields["tagIds"] = [tag(jane, f"t{i}") for i in range(fields.pop("tags"))]
    r = make(jane, "Rule", **fields)
    if refused is None:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 422, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"], e["message"]) == refused


# ---- the list, its records and what each change leaves (S2.7) ----


def rule(c, **fields) -> dict:
    r = make(c, "Rule", **fields)
    assert r.status_code == 200, r.text
    return r.json()


def feed(c):
    me = c.get("/ui/api/session").json()["user"]["id"]
    items = c.get("/ui/api/activity").json()["items"]
    return me, [x for x in items if x["kind"].startswith("rule")]


def test_a_rule_lists_what_it_matches_and_sets_with_the_names_it_shows(server, jane):
    """S2.7: each rule as listed: its bounds, its account by name, its category by its path,
    what it renames to and its tags; a rule of none of these lists none, and a rule goes with
    the account it names."""
    c = cats(jane)
    a = new_account(jane, name="Joint")
    full = rule(
        jane,
        payeeMatch=" acme ",
        amountMin="5.00",
        amountMax="50.00",
        direction="out",
        accountId=a["id"],
        categoryId=c["Food › Groceries"],
        payee=" Acme ",
        tagIds=[tag(jane, "Work")],
    )
    bare = rule(jane, payeeMatch="shop", payee="Shop")
    got = {r["id"]: r for r in jane.get("/ui/api/rules").json()["items"]}
    f, b = got[full["id"]], got[bare["id"]]
    assert {
        k: f[k]
        for k in (
            "payeeMatch",
            "amountMin",
            "amountMax",
            "direction",
            "accountId",
            "accountName",
            "categoryId",
            "categoryPath",
            "categoryDeleted",
            "payee",
            "tags",
        )
    } == {
        "payeeMatch": "acme",
        "amountMin": "5.00",
        "amountMax": "50.00",
        "direction": "out",
        "accountId": a["id"],
        "accountName": "Joint",
        "categoryId": c["Food › Groceries"],
        "categoryPath": "Food › Groceries",
        "categoryDeleted": False,
        "payee": "Acme",
        "tags": ["work"],
    }
    assert (b["accountId"], b["accountName"]) == (None, None)
    assert (b["categoryId"], b["categoryPath"], b["categoryDeleted"]) == (None, None, False)
    assert (b["amountMin"], b["amountMax"], b["tags"]) == (None, None, [])
    saved(remove(jane, "Acct", jane.get(f"/ui/api/accounts/{a['id']}").json(), confirm=True))
    assert [r["id"] for r in jane.get("/ui/api/rules").json()["items"]] == [bare["id"]]


def test_each_change_to_a_rule_is_the_owners_activity_and_only_what_happened(server, jane):
    """S2.7, S12.11: made, moved, changed and deleted are each recorded once, by the owner,
    about themselves; a move alone is no change, and a change in place no move; applying
    says how many changed."""
    c = cats(jane)
    first = rule(jane, payeeMatch="acme", categoryId=c["Food › Groceries"])
    rule(jane, payeeMatch="shop", categoryId=c["Food › Groceries"])
    me, items = feed(jane)
    assert [x["kind"] for x in items] == ["rule.created", "rule.created"]
    assert {(x["actorId"], x["subjectKind"], x["subjectId"]) for x in items} == {(me, "user", me)}
    first = saved(change(jane, "Rule", first, position=1))
    assert next(x["kind"] for x in feed(jane)[1]) == "rule.moved"
    first = saved(change(jane, "Rule", first, payee="Acme"))
    assert [x["kind"] for x in feed(jane)[1]][:2] == ["rule.updated", "rule.moved"]
    saved(remove(jane, "Rule", first))
    assert next(x["kind"] for x in feed(jane)[1]) == "rule.deleted"
    a = new_account(jane, name="Joint")
    for payee in ("ACME 1", "ACME 2"):
        add(jane, a["id"], "-5.00", payee=payee)
    rule(jane, payeeMatch="acme", categoryId=c["Food › Groceries"])
    assert jane.post("/ui/api/rules/apply").json()["changed"] == 2
    applied = feed(jane)[1][0]
    assert applied["kind"] == "rules.applied" and "2" in applied["text"], applied


def test_a_rule_deleted_closes_the_list_up_and_its_tags_taken_off_say_by_whom(server, jane):
    """S2.7, S2.6: the rules after a deleted one move up; a tag taken off a rule goes, marked
    as taken off by its owner; a deleted rule, or another's, is not found."""
    from moolakata.store.entities.accounts import RuleTag

    c = cats(jane)
    rules = [rule(jane, payeeMatch=p, categoryId=c["Food › Groceries"]) for p in ("a", "b", "c")]
    saved(remove(jane, "Rule", rules[0]))
    listed = jane.get("/ui/api/rules").json()["items"]
    assert [(r["payeeMatch"], r["position"]) for r in listed] == [("b", 0), ("c", 1)]
    work = tag(jane, "Work")
    b = saved(change(jane, "Rule", listed[0], tagIds={"add": [work], "remove": []}))
    b = saved(change(jane, "Rule", b, tagIds={"add": [], "remove": [work]}))
    assert b["tags"] == []
    me = jane.get("/ui/api/session").json()["user"]["id"]
    with server.db.read(unscoped="test") as s:
        (link,) = s.query(RuleTag).filter_by(ruleId=b["id"]).all()
        assert link.deletedById == me
    r = change(jane, "Rule", rules[0], payee="x")
    assert (r.status_code, r.json()["errors"][0]["code"]) == (404, "not-found"), r.text
    assert r.json()["errors"][0]["message"] == "No such rule."
    make_user(server, "john")
    r = change(sign_in(server, "john"), "Rule", b, payee="x")
    assert (r.status_code, r.json()["errors"][0]["message"]) == (404, "No such rule."), r.text


def test_a_rule_names_an_account_of_the_callers_own_when_changed_too(server, jane):
    c = cats(jane)
    r = rule(jane, payeeMatch="acme", categoryId=c["Food › Groceries"])
    a = new_account(jane, name="Mine")
    assert saved(change(jane, "Rule", r, accountId=a["id"]))["accountId"] == a["id"]


def test_five_hundred_rules_and_no_more(server, jane):
    """S2.7: a user keeps at most 500 rules: the 500th is made, the 501st refused."""
    from moolakata import ids
    from moolakata.store.entities.accounts import Rule

    me = jane.get("/ui/api/session").json()["user"]["id"]
    with server.db.tx(unscoped="test: 499 rules") as s:
        for i in range(499):
            s.add(
                Rule(id=ids.new_id("Rule"), ownerId=me, position=i, payeeMatch=f"p{i}", payee="x")
            )
    rule(jane, payeeMatch="last", payee="x")
    r = make(jane, "Rule", payeeMatch="over", payee="x")
    assert r.status_code == 422, r.text
    e = r.json()["errors"][0]
    assert (e["code"], e["message"]) == ("too-many-rules", "At most 500 rules.")


def test_uncategorised_counts_what_a_rule_would_set_in_the_callers_accounts_alone(server, jane):
    """S2.7.4: the count is of live, uncategorised transactions that are neither trades nor a
    transfer's half, in accounts the caller can change, that a rule matches by the bank's words
    and the account the rule names."""
    from moolakata.store.entities.accounts import Transaction

    c = cats(jane)
    a = new_account(jane, name="Joint")
    b = new_account(jane, name="Other", mask="9999")
    brk = new_account(jane, name="Brokerage", type="brokerage")
    counted = add(jane, a["id"], "-5.00", payee="Acme")
    add(jane, b["id"], "-5.00", payee="Acme")  # another account than the rule names
    gone = add(jane, a["id"], "-6.00", payee="Acme")
    saved(remove(jane, "Txn", gone))
    add(
        jane,
        brk["id"],
        "-50.00",
        kind="buy",
        symbol="VTI",
        quantity="1",
        price="50",
        fees="0",
        payee="Acme",
    )
    out = add(jane, a["id"], "-500.00", "2026-09-15", payee="Acme")
    add(jane, b["id"], "500.00", "2026-09-16", kind="deposit", payee="Acme")  # its pair
    make_user(server, "john")
    john = sign_in(server, "john")
    add(john, new_account(john, name="John's")["id"], "-5.00", payee="Acme")
    with server.db.tx(unscoped="test: the bank's words, renamed") as s:
        t = s.get(Transaction, counted["id"])
        t.payeeRaw, t.payee = "ACME STORE 1", "Corner shop"
    rule(jane, payeeMatch="acme store", accountId=a["id"], categoryId=c["Food › Groceries"])
    assert jane.get(f"/ui/api/transactions/{out['id']}").json()["transferId"]
    assert jane.get("/ui/api/rules").json()["uncategorised"] == 1
