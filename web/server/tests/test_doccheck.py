"""How the documents cite issues (requirements README, how the requirements are organised)."""

import pytest

from moolakata.dev import doccheck

URL = "https://github.com/MojoKata/MoolaKata/issues/"


@pytest.mark.parametrize(
    ("line", "found"),
    [
        (f"a gap ([G#581]({URL}581)).", []),
        (f"later work ([F#560]({URL}560)).", []),
        (f"an issue ([#7]({URL}7)).", []),
        (f"out of scope ([NO#585]({URL}585)).", []),
        ("[NO#585] alone", ["[NO#585] links to no issue"]),
        (f"[N#585]({URL}585)", ["[N#585]: the prefix is G, F, NO or none"]),
        ("the form `[G#n]` is an example, not a citation", []),
        ("[G#581] alone", ["[G#581] links to no issue"]),
        ("[#7] alone", ["[#7] links to no issue"]),
        (f"[F#560]({URL}561)", [f"[F#560] links to {URL}561, not issue 560"]),
        (
            "[G#5](https://github.com/other/repo/issues/5)",
            ["[G#5] links to https://github.com/other/repo/issues/5, not issue 5"],
        ),
        ("[G#5](gaps.md)", ["[G#5] links to gaps.md, not issue 5"]),
        (
            f"two: [G#1]({URL}1) and [F#2]({URL}3)",
            [f"[F#2] links to {URL}3, not issue 2"],
        ),
    ],
)
def test_an_issue_is_cited_by_a_link_to_that_issue(line, found):
    assert doccheck.issue_link_problems(line) == found


@pytest.mark.parametrize(
    ("line", "cited"),
    [
        ("as G25 says", ["G25"]),
        ("(L14) and (G8)", ["L14", "G8"]),
        (f"[G#581]({URL}581)", []),
        ("a G-code, L-shaped, AG12, L1x, 4G5", []),
        ("Q8 is a question", []),
    ],
)
def test_a_retired_gap_or_later_id_is_found(line, cited):
    assert [m.group(0) for m in doccheck.RETIRED.finditer(line)] == cited
