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
    jane = w.c["jane"]
    from edits import make

    kid = make(jane, "Persn", name="Lisa Doe", sex="female", birthYear=2015).json()["id"]
    a = w.book(2025, "jane", ())
    b = w.book(2025, "john", ())
    for owner, book in (("jane", a), ("john", b)):
        r = make(w.c[owner], "TxDep", bookId=book["id"], personId=kid,
                 claimedAs="qualifying child", months=12)  # fmt: skip
        assert r.status_code == 200, r.text
    joint = w.book(2026, "jane", ("john",), switch=True)
    d = jane.get(f"/ui/api/tax-books/{joint['id']}").json()
    assert [x["personId"] for x in d["dependents"]] == [kid]


def test_the_joint_book_copies_from_each_filers_book_whoever_accepts_last(couple):  # noqa: F811
    # S8.14.4: the copy is from both of last year's books, though the filer who accepts last
    # never could see the other's.
    w = couple
    jane = w.c["jane"]
    from edits import make

    kid = make(jane, "Persn", name="Lisa Doe", sex="female", birthYear=2015).json()["id"]
    a = w.book(2025, "jane", ())
    w.book(2025, "john", ())
    r = make(jane, "TxDep", bookId=a["id"], personId=kid, claimedAs="qualifying child",
             months=12)  # fmt: skip
    assert r.status_code == 200, r.text
    joint = w.book(2026, "jane", ("john",), switch=True)
    d = jane.get(f"/ui/api/tax-books/{joint['id']}").json()
    assert [x["personId"] for x in d["dependents"]] == [kid]
