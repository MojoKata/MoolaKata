"""Screenshots in a pull request's conversation (web/dev.sh pr-screenshots): the fork named by
its remote, and a comment showing each image inline at the commit that holds it."""

import pytest

from moolakata.dev import prshots


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:donclaudio777/MoolaKata.git",
        "https://github.com/donclaudio777/MoolaKata.git",
        "https://github.com/donclaudio777/MoolaKata",
    ],
)
def test_the_fork_is_named_by_its_remote(url):
    assert prshots.fork_of(url) == "donclaudio777/MoolaKata"


def test_a_remote_elsewhere_is_refused():
    with pytest.raises(SystemExit, match="isn't a GitHub repository"):
        prshots.fork_of("https://gitlab.com/someone/thing.git")


def test_the_comment_shows_each_image_at_its_commit():
    sha = "0123456789abcdef0123456789abcdef01234567"
    text = prshots.body(65, "donclaudio777/MoolaKata", sha, ["nav-tall.png", "nav-short.png"],
                        "The sidebar, tall and short.")  # fmt: skip
    raw = f"https://raw.githubusercontent.com/donclaudio777/MoolaKata/{sha}/pr-65"
    assert text.startswith("The sidebar, tall and short.\n\n")
    assert "Screenshots for review (2), from `donclaudio777/MoolaKata@01234567`:" in text
    assert f"![nav-tall.png]({raw}/nav-tall.png)" in text
    assert f"![nav-short.png]({raw}/nav-short.png)" in text
    assert text.index("nav-tall.png") < text.index("nav-short.png")
    assert prshots.body(1, "a/b", sha, ["x.png"]).startswith("Screenshots for review (1)")
