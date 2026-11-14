"""The generated mockup's build (requirements S12.9): crawled in parts, the parts' records are
joined as one crawl would have kept them, by `Book.keep`'s rule (a GET's answer from the latest
job, a computed POST's from the earliest); and each long data: URL is kept in the page once."""

import base64
import importlib.util
from pathlib import Path

import pytest

from moolakata import exactjson
from moolakata.dev import seed
from moolakata.ui.profile import AVATAR, AVATAR_MAX

BUILD = Path(__file__).resolve().parents[2] / "ui" / "mockup" / "build.py"
spec = importlib.util.spec_from_file_location("mockup_build", BUILD)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def part(tmp_path: Path, k: int, answers: dict) -> Path:
    path = tmp_path / f"MoolaKata-app.part{k}.json"
    record = {
        "answers": {"jane": answers},
        "hellos": {"jane": {"part": k}},
        "users": [{"username": "jane", "name": "Jane Doe"}],
    }
    path.write_text(exactjson.dumps(record))
    return path


def test_the_parts_are_kept_as_one_crawl_would_keep_them(tmp_path):
    one = part(
        tmp_path,
        1,
        {
            "GET /ui/api/session": [-1, {"body": "signed in"}],  # every part's first recorder
            "GET /ui/api/accounts": [2, {"body": "job 2"}],
            "POST /ui/api/projections/run": [1, {"body": "job 1"}],
            "GET /ui/api/only-one": [0, {"body": "part 1 alone"}],
        },
    )
    two = part(
        tmp_path,
        2,
        {
            "GET /ui/api/session": [-1, {"body": "signed in"}],
            "GET /ui/api/accounts": [5, {"body": "job 5"}],
            "POST /ui/api/projections/run": [3, {"body": "job 3"}],
            "GET /ui/api/budget": [7, {"body": "part 2 alone"}],
        },
    )
    answers, hellos, users = build.join([one, two])
    assert answers == {
        "jane": {
            "GET /ui/api/accounts": {"body": "job 5"},  # a GET: the latest job's
            "GET /ui/api/budget": {"body": "part 2 alone"},
            "GET /ui/api/only-one": {"body": "part 1 alone"},
            "GET /ui/api/session": {"body": "signed in"},
            "POST /ui/api/projections/run": {"body": "job 1"},  # a computed POST: the earliest's
        }
    }
    assert hellos == {"jane": {"part": 1}} and users == [{"username": "jane", "name": "Jane Doe"}]
    # The order the parts come in doesn't matter.
    assert build.join([two, one])[0] == answers


def test_a_part_is_one_of_its_n(capsys):
    for bad in ("0/2", "3/2"):
        with pytest.raises(SystemExit):
            build.main(["--part", bad])
    assert "K is from 1 to N" in capsys.readouterr().err


def test_a_long_data_url_is_kept_once_and_named_where_it_was():
    avatar = "data:image/png;base64," + "A" * 2000
    short = "data:image/png;base64,AAAA"  # too short to be worth keeping apart
    answers = {
        "jane": {
            "GET /ui/api/session": {"body": {"user": {"avatar": avatar}, "logo": short}},
            "GET /ui/api/activity": {"body": {"items": [{"actorAvatar": avatar}, {"n": 1.5}]}},
        }
    }
    blobs = {}
    stored = build.stored_once(answers, blobs)
    assert list(blobs) == [avatar]
    assert stored["jane"]["GET /ui/api/session"]["body"] == {
        "user": {"avatar": "mk-blob:0"},
        "logo": short,
    }
    assert stored["jane"]["GET /ui/api/activity"]["body"]["items"] == [
        {"actorAvatar": "mk-blob:0"},
        {"n": 1.5},
    ]


def test_the_seeds_avatars_are_ones_profile_would_take():
    for name in ("jane", "john"):
        png = (seed.AVATARS / f"{name}.png").read_bytes()
        url = "data:image/png;base64," + base64.b64encode(png).decode()
        assert AVATAR.match(url) and len(url) <= AVATAR_MAX, name
