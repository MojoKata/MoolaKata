"""Dependents by age (requirements S8.14.5; the filed tax years walk, decision 3): every age
about the lines the credits and a qualifying child draw (13, 17, 19, 24), student or not, a
child or grandchild or not, held to the rules as IRS Pub. 501 and 503 state them; and a child
both separate books claimed copied once into the joint book after them.
"""

import itertools

import pytest
from test_last_year import couple  # noqa: F401

from moolakata.taxes import dependents


@pytest.mark.parametrize(
    ("age", "student", "descendant", "claimed_as"),
    list(
        itertools.product(
            range(11, 26), (False, True), (False, True), ("qualifying child", "qualifying relative")
        )
    ),
)
def test_a_dependents_age_against_the_lines(age, student, descendant, claimed_as):
    # IRS Pub. 501: a qualifying child is a descendant under 19 at the year's end, or under 24
    # and a full-time student; the child tax credit wants under 17, the childcare credit under
    # 13 (Pub. 503).
    child = descendant and (age < 19 or (student and age < 24))
    assert dependents.suggest(descendant, age, student) == (
        "qualifying child" if child else "qualifying relative"
    )
    want = {str(n) for n in (13, 17) if age == n}
    if claimed_as == "qualifying child":
        want |= {"19"} if age == 19 and not student else set()
        want |= {"24"} if age == 24 else set()
    flags = dependents.ages_out(age, claimed_as, student)
    assert {f.split(":")[0].split()[-1] for f in flags} == want, flags
    assert (age < dependents.CREDIT_AGE, age < dependents.CARE_AGE) == (age < 17, age < 13)


def test_a_child_both_separate_books_claimed_is_copied_once_into_the_joint_book(couple):  # noqa: F811
    w = couple
    alice = w.c["alice"]
    from edits import make

    kid = make(alice, "Persn", name="Emma Griffin", sex="female", birthYear=2015).json()["id"]
    a = w.book(2025, "alice", ())
    b = w.book(2025, "bob", ())
    for owner, book in (("alice", a), ("bob", b)):
        r = make(w.c[owner], "TxDep", bookId=book["id"], personId=kid,
                 claimedAs="qualifying child", months=12)  # fmt: skip
        assert r.status_code == 200, r.text
    joint = w.book(2026, "alice", ("bob",), switch=True)
    d = alice.get(f"/ui/api/tax-books/{joint['id']}").json()
    assert [x["personId"] for x in d["dependents"]] == [kid]


def test_the_joint_book_copies_from_each_filers_book_whoever_accepts_last(couple):  # noqa: F811
    # S8.14.4: the copy is from both of last year's books, though the filer who accepts last
    # never could see the other's.
    w = couple
    alice = w.c["alice"]
    from edits import make

    kid = make(alice, "Persn", name="Emma Griffin", sex="female", birthYear=2015).json()["id"]
    a = w.book(2025, "alice", ())
    w.book(2025, "bob", ())
    r = make(alice, "TxDep", bookId=a["id"], personId=kid, claimedAs="qualifying child",
             months=12)  # fmt: skip
    assert r.status_code == 200, r.text
    joint = w.book(2026, "alice", ("bob",), switch=True)
    d = alice.get(f"/ui/api/tax-books/{joint['id']}").json()
    assert [x["personId"] for x in d["dependents"]] == [kid]
