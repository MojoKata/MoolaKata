"""A 529's plan, contributions and qualified expenses at their edges (requirements S1.8): each
refusal at its field with its code and words, the plan changed through its save, and who a
contribution names."""

import pytest
from conftest import make_user, sign_in
from edits import _save, change, make, new_id, plan529, remove, saved, share
from test_accounts import add, new_account
from test_education import T0, plan

from moolakata import clock


@pytest.fixture
def jane(server):
    clock.fix(T0)
    make_user(server, "jane")
    yield sign_in(server, "jane")
    clock.fix(None)


def refused(r, field, code, words, status=422):
    assert r.status_code == status, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == (field, code, words)


def made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _john(server):
    make_user(server, "john")
    john = sign_in(server, "john")
    return john, john.get("/ui/api/session").json()["user"]["id"]


def _private_person(c, name="Ann Smith"):
    r = make(c, "Persn", name=name, sex="female", private=True)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_529s_plan_is_changed_through_its_save_and_stays_with_its_account(server, jane):
    """S1.8.1: the plan is set on the 529's Settings: changed in place, never a second one,
    never moved to another account or deleted alone; what it holds is refused at its field."""
    acct, lisa, p = plan(jane)
    p = saved(plan529(jane, acct["id"], planName="my529 Plus", stateDeduction="0"))
    assert (p["planName"], p["stateDeduction"], p["beneficiary"]["id"]) == (
        "my529 Plus",
        "0.00",
        lisa["id"],
    )
    assert jane.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["version"] == p["version"]
    second = {"op": "create", "entity": "EdPln", "id": new_id("EdPln"),
              "fields": {"accountId": acct["id"]}}  # fmt: skip
    refused(_save(jane, second, False), "accountId", "plan-exists",
            "This 529 has its plan; change it.", 409)  # fmt: skip
    other = new_account(jane, name="Max's 529", type="529", institution="my529")
    refused(change(jane, "EdPln", p, accountId=other["id"]), "accountId", "plan-fixed",
            "A plan stays with its account.")  # fmt: skip
    refused(remove(jane, "EdPln", p), None, "plan-delete",
            "A 529 keeps its plan; delete the account instead.")  # fmt: skip
    refused(change(jane, "EdPln", p, stateDeduction="-1"), "stateDeduction", "amount-invalid",
            "Zero or more.")  # fmt: skip
    refused(change(jane, "EdPln", p, openedOn="2026-10-14"), "openedOn", "date-ahead",
            "Not after today.")  # fmt: skip
    assert saved(change(jane, "EdPln", p, openedOn="2026-10-13"))["openedOn"] == "2026-10-13"


def test_a_529s_beneficiary_is_one_of_the_household_the_owner_sees(server, jane):
    """S1.8.1, S10.10.2: a private person of someone else's is no one's beneficiary but theirs."""
    acct, _lisa, p = plan(jane)
    john, _ = _john(server)
    hidden = _private_person(john)
    refused(change(jane, "EdPln", p, beneficiaryId=hidden["id"]), "beneficiaryId",
            "beneficiary-invalid", "One of the household's people.")  # fmt: skip
    cleared = saved(change(jane, "EdPln", p, beneficiaryId=None))
    assert cleared["beneficiary"] is None and cleared["beneficiaryId"] is None
    assert jane.get(f"/ui/api/accounts/{acct['id']}/goal").json() == {
        "beneficiary": None,
        "projection": None,
        "others": 0,
    }


def test_a_529s_plan_is_changed_by_its_writers_only(server, jane):
    """S10.3: shared to read, John sees the plan and changes nothing of it."""
    acct, _, p = plan(jane)
    john, john_id = _john(server)
    share(jane, "account", acct["id"], users={john_id: "read"})
    seen = john.get(f"/ui/api/accounts/{acct['id']}/plan529").json()
    assert seen["planName"] == "my529" and not seen["access"]["writable"]
    r = change(john, "EdPln", p, planName="his")
    assert r.status_code == 403, r.text
    assert r.json()["errors"][0]["code"] == "share-read-only"
    share(jane, "account", acct["id"], users={john_id: "write"})
    assert saved(change(john, "EdPln", p, planName="theirs"))["planName"] == "theirs"


def test_only_a_529_has_a_plan(jane):
    bank = new_account(jane, name="Checking")
    r = jane.get(f"/ui/api/accounts/{bank['id']}/plan529")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        409,
        "not-a-529",
        "This account isn't a 529 plan.",
    )
    op = {"op": "create", "entity": "EdPln", "id": new_id("EdPln"),
          "fields": {"accountId": bank["id"]}}  # fmt: skip
    refused(_save(jane, op, False), None, "not-a-529", "This account isn't a 529 plan.", 409)


def test_a_contribution_names_the_owner_a_person_or_a_users_person(server, jane):
    """S1.8.2: who made a deposit is the owner, a person of the household, or a user (their
    own person); anyone else, or a person the owner can't see, is refused."""
    acct, lisa, _ = plan(jane)
    john, john_id = _john(server)
    john_person = john.get("/ui/api/profile").json()["personId"]
    by_user = made(make(jane, "Cntrb", accountId=acct["id"], date="2026-02-01", amount="100",
                         contributor=f"user:{john_id}"))  # fmt: skip
    assert by_user["contributor"] == f"person:{john_person}" and by_user["name"] == "John"
    by_person = made(make(jane, "Cntrb", accountId=acct["id"], date="2026-02-02",
                           amount="200", contributor=f"person:{lisa['id']}"))  # fmt: skip
    assert by_person["name"] == "Lisa Doe"
    hidden = _private_person(john)
    for who in (f"person:{hidden['id']}", "user:Usr_nobody", "pet:Rex", "Lisa"):
        refused(make(jane, "Cntrb", accountId=acct["id"], date="2026-02-03", amount="1",
                     contributor=who), "contributor", "contributor-invalid",
                "The owner or a person.")  # fmt: skip
    refused(change(jane, "Cntrb", by_person, contributor="pet:Rex"), "contributor",
            "contributor-invalid", "The owner or a person.")  # fmt: skip


def test_a_contribution_is_a_deposit_in_its_529_tagged_once(jane):
    """S1.8.2: a new deposit is more than zero on a day; an existing one is a deposit into
    this 529, tagged once."""
    acct, _, _ = plan(jane)
    base = {"accountId": acct["id"], "date": "2026-02-01"}
    refused(make(jane, "Cntrb", **base, amount="0"), "amount", "amount-invalid",
            "More than zero.")  # fmt: skip
    refused(make(jane, "Cntrb", accountId=acct["id"], amount="5"), "date", "date-missing",
            "The day it was paid in.")  # fmt: skip
    bank = new_account(jane, name="Checking")
    out = add(jane, acct["id"], "-50.00", "2026-03-01")
    elsewhere = add(jane, bank["id"], "50.00", "2026-03-01")
    for t in (out, elsewhere):
        refused(make(jane, "Cntrb", accountId=acct["id"], transactionId=t["id"]),
                "transactionId", "not-found", "No such contribution.")  # fmt: skip
    gone = add(jane, acct["id"], "70.00", "2026-03-01")
    assert remove(jane, "Txn", gone).status_code == 200
    for missing in (gone["id"], new_id("Txn")):
        refused(make(jane, "Cntrb", accountId=acct["id"], transactionId=missing), None,
                "not-found", "Not found", 404)  # fmt: skip
    dep = add(jane, acct["id"], "80.00", "2026-03-02")
    made(make(jane, "Cntrb", accountId=acct["id"], transactionId=dep["id"]))
    refused(make(jane, "Cntrb", accountId=acct["id"], transactionId=dep["id"]),
            "transactionId", "tagged", "It is tagged: change its tag.", 409)  # fmt: skip


def test_a_qualified_expense_is_changed_and_stays_with_its_529(jane):
    """S1.8.3: an expense is changed in place, its kind one of the qualified ones and its
    amount more than zero; it never moves to another 529."""
    acct, _, _ = plan(jane)
    e = made(make(jane, "QExpn", accountId=acct["id"], date="2026-08-15", kind="tuition",
                   description="Fall tuition", amount="4000"))  # fmt: skip
    e = saved(change(jane, "QExpn", e, amount="4200", year=2027, description="  "))
    assert (e["amount"], e["year"], e["description"]) == ("4200.00", 2027, None)
    listed = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"]
    assert [(x["id"], x["amount"]) for x in listed] == [(e["id"], "4200.00")]
    other = new_account(jane, name="Max's 529", type="529", institution="my529")
    refused(change(jane, "QExpn", e, accountId=other["id"]), "accountId", "expense-fixed",
            "An expense stays with its 529.")  # fmt: skip
    refused(change(jane, "QExpn", e, kind="car"), "kind", "kind-invalid",
            "One of the qualified expenses.")  # fmt: skip
    refused(change(jane, "QExpn", e, amount="0"), "amount", "amount-invalid", "More than zero.")
    assert remove(jane, "QExpn", e).status_code == 200
    refused(change(jane, "QExpn", e, amount="1"), None, "not-found", "No such expense.", 404)


def test_a_529_opened_on_29_february_rolls_over_fifteen_years_on_28_february(jane):
    """S1.8.4: fifteen years after a leap day is the 28th, in a year without one."""
    _, _, p = plan(jane, opened="2024-02-29")
    assert p["rollover"]["possibleFrom"] == "2039-02-28"


def _hidden_529(server, jane):
    """John's 529 for Max, his private person, with Max's contribution, shared with Jane to
    write: the account, Max and John's client."""
    john, _ = _john(server)
    jane_id = jane.get("/ui/api/session").json()["user"]["id"]
    hidden = made(make(john, "Persn", name="Max Smith", sex="male", birthYear=2015,
                       private=True))  # fmt: skip
    acct = new_account(john, name="Max's 529", type="529", institution="my529")
    saved(plan529(john, acct["id"], beneficiaryId=hidden["id"]))
    made(make(john, "Cntrb", accountId=acct["id"], date="2026-06-01", amount="300",
              contributor=f"person:{hidden['id']}"))  # fmt: skip
    share(john, "account", acct["id"], users={jane_id: "write"})
    return acct, hidden, john


def test_a_beneficiary_or_contributor_the_reader_cant_see_is_named_and_no_more(server, jane):
    """R3.14, S10.10.2: John's 529 for his private person, shared with Jane, names Max to
    her, and no more of him (his birth year, his relation to John). An education projection
    is for someone she sees, so it starts no goal; to John it names his person whole."""
    acct, hidden, john = _hidden_529(server, jane)
    mine = john.get(f"/ui/api/accounts/{acct['id']}/plan529").json()
    assert (mine["beneficiary"]["id"], mine["beneficiary"]["birthYear"]) == (hidden["id"], 2015)
    seen = jane.get(f"/ui/api/accounts/{acct['id']}/plan529").json()
    assert seen["beneficiary"] == {
        "kind": "person",
        "id": hidden["id"],
        "name": "Max Smith",
        "birthYear": None,
        "deleted": False,
    }
    r = jane.get(f"/ui/api/accounts/{acct['id']}/contributions")
    assert r.status_code == 200, r.text
    [row] = r.json()["rows"]
    assert (row["name"], row["relationship"]) == ("Max Smith", None)
    assert jane.get(f"/ui/api/accounts/{acct['id']}/goal").json()["beneficiary"] is None
    r = jane.post(f"/ui/api/accounts/{acct['id']}/goal")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        409,
        "no-beneficiary",
        "Choose the beneficiary in Settings first.",
    )


def test_the_goal_tab_finds_a_projection_for_the_beneficiary_as_a_user(server, jane):
    """S1.8.5: an education projection made for a user is for their person, so the 529 for
    that person shows it; one for someone else, or with another goal, isn't its goal."""
    john, john_id = _john(server)
    john_person = john.get("/ui/api/profile").json()["personId"]
    acct = new_account(jane, name="John's 529", type="529", institution="my529")
    saved(plan529(jane, acct["id"], beneficiaryId=john_person))
    _, lisa, _ = plan(jane)
    typed = {"kind": "typed", "amount": 1000}
    for name, goal, who in (
        ("Retire", "retirement", None),
        ("Lisa's school", "education", {"kind": "person", "id": lisa["id"]}),
        ("John's school", "education", {"kind": "user", "id": john_id}),
    ):
        inputs = {"beneficiary": who} if who else {}
        made(make(jane, "Prjct", name=name, goal=goal, builtOn=typed, inputs=inputs))
    v = jane.get(f"/ui/api/accounts/{acct['id']}/goal").json()
    assert v["beneficiary"]["id"] == john_person and v["others"] == 0
    assert v["projection"]["name"] == "John's school"


def test_a_plan_or_contribution_no_longer_there_is_not_found(jane):
    acct, _, p = plan(jane)
    c = made(make(jane, "Cntrb", accountId=acct["id"], date="2026-02-01", amount="100"))
    assert remove(jane, "Cntrb", c).status_code == 200
    refused(change(jane, "Cntrb", c, fiveYear=True), None, "not-found",
            "No such contribution.", 404)  # fmt: skip
    ghost = {**p, "id": new_id("EdPln")}
    refused(change(jane, "EdPln", ghost, planName="x"), None, "not-found", "Not found", 404)
