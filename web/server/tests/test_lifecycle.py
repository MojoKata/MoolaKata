"""A link's lifecycle (links/lifecycle.py; requirements S11.6, S11.7; link-protocol.md §4.6):
every state × broken mark × event, against the table the protocol writes, with no server; the
protocol's tables held to the module's; nothing else in `links/` writing a link's state; and
the sequences two servers live through, linking again among them (CR3-50)."""

import itertools
import re
from pathlib import Path

import pytest
from linkpair import linked
from test_links import admins, links_of, pair  # noqa: F401

from moolakata.links import keys, lifecycle, signing
from moolakata.links.client import LinkError
from moolakata.store.entities.links import Link

ROOT = Path(__file__).resolve().parents[3]
LIVE = ("pending", "active", "paused")

# What the protocol says, written from link-protocol.md §4.6 by reading it: each event, the
# states it moves a link from, and where to; any other state refuses it.
EXPECTED = {
    "invite": {None: "invited"},
    "join-here": {None: "pending"},
    "join-arrives": {"invited": "requested"},
    "approve": {"requested": "active"},
    "peer-active": {"pending": "active", "active": "active"},
    "pause": {"active": "paused"},
    "resume": {"paused": "active"},
    "end-here": dict.fromkeys(("invited", "requested", "pending", "active", "paused"), "ended"),
    "link-ended": dict.fromkeys(("requested", "pending", "active", "paused", "ended"), "ended"),
    "not-linked": {s: s for s in LIVE},
    "good-call": {s: s for s in lifecycle.STATES},
    "link-again": {"ended": "ended"},  # and a broken live one, below
}


def cases():
    for state, broken, event in itertools.product(
        (None, *lifecycle.STATES), (False, True), lifecycle.EVENTS
    ):
        if broken and state not in LIVE:
            continue  # only a pending, active or paused link is ever marked broken
        yield state, broken, event


@pytest.mark.parametrize(("state", "broken", "event"), list(cases()))
def test_every_state_and_event(state, broken, event):
    allowed = EXPECTED[event]
    if event == "link-again" and broken:
        allowed = {state: "ended"}
    if state not in allowed:
        with pytest.raises(LinkError) as e:
            lifecycle.step(state, broken, event)
        assert e.value.code in ("state-invalid", "not-requested", "already-linked")
        if event == "link-again":
            assert e.value.code == "already-linked", "the link the two already have"
        return
    got = lifecycle.step(state, broken, event)
    assert got.state == allowed[state]
    assert got.ended == (got.state == "ended" and state != "ended")
    assert got.retired == (event == "link-again")
    if event == "not-linked":
        assert got.broken
    elif event in ("good-call", "end-here", "link-ended", "link-again"):
        assert not got.broken
    else:
        assert got.broken == broken, "the mark stays until a good call"


def table(text: str, heading: str) -> list[list[str]]:
    """The rows of the first table after a heading, as cells."""
    after = text[text.index(heading) :]
    rows = []
    for line in after.splitlines()[1:]:
        if line.startswith("|") and not set(line) <= set("|- "):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows and not line.startswith("|"):
            break
    return rows[1:]


def test_the_protocols_tables_are_the_modules():
    text = (ROOT / "docs" / "link-protocol.md").read_text()
    moves = {}
    for event, frm, to in table(text, "### 4.6 A link's states"):
        name = re.match(r"`([a-z-]+)`", event).group(1)
        moves[name] = (frm, to)
    assert set(moves) == set(lifecycle.EVENTS)
    for event, (frm, to) in moves.items():
        states = set(re.findall(r"\b(" + "|".join(lifecycle.STATES) + r")\b", frm))
        if frm == "—":
            states = {None}
        if frm == "any":
            states = set(lifecycle.STATES)
        assert states == set(lifecycle.MOVES[event]), event
        if to not in ("the same",) and not to.startswith("ended"):
            assert set(lifecycle.MOVES[event].values()) == {to}, event
    calls = {}
    for path, _signed, states, _what in table(text, "## 4. Calls"):
        name = re.search(r"/link/v1/([a-z]+)", path).group(1)
        calls[name] = set(re.findall(r"\b(" + "|".join(lifecycle.STATES) + r")\b", states))
    for name, states in lifecycle.CALLS.items():
        assert calls[name] == set(states), name


def test_nothing_else_in_links_writes_a_links_state():
    src = ROOT / "web" / "server" / "src" / "moolakata" / "links"
    for f in src.glob("*.py"):
        if f.name == "lifecycle.py":
            continue
        text = f.read_text()
        assert not re.search(r"\b(link|row|old)\.state\s*=[^=]", text), f.name
        assert not re.search(r"\bstate\s*=\s*\"(" + "|".join(lifecycle.STATES) + ')"', text), f
        assert not re.search(r"\.brokenAt\s*=[^=]", text), f.name


# ---------- two servers through the sequences


def the_link(srv, link_id):
    with srv.db.read() as s:
        return s.get(Link, link_id)


def live_links(srv):
    with srv.db.read() as s:
        return s.query(Link).filter(Link.deleted.is_(False)).all()


def test_an_ended_link_is_linked_again_from_either_side(admins):  # noqa: F811
    a, b, ca, cb, _ = admins
    a_id, b_id = linked(ca, cb)
    assert ca.post(f"/ui/api/settings/links/{a_id}/end").status_code == 200
    assert the_link(b, b_id).state == "ended", "the other side learned at once"
    # B invites this time; A joins.
    on_b, on_a = linked(cb, ca)
    assert the_link(a, a_id).deleted and the_link(b, b_id).deleted, "put aside for the new link"
    assert [x["id"] for x in links_of(ca)["links"]] == [on_a]
    assert the_link(a, on_a).state == "active" and the_link(b, on_b).state == "active"


def test_a_broken_link_is_ended_and_replaced_by_linking_again(admins):  # noqa: F811
    a, b, ca, cb, _ = admins
    a_id, b_id = linked(ca, cb)
    other = keys.b64(keys.raw_public(signing.Ed25519PrivateKey.generate().public_key()))
    with b.db.tx() as s:  # B restored from before the link: it has none with A's key
        s.query(Link).filter(Link.id == b_id).update({Link.peerKey: other})
    ca.post(f"/ui/api/settings/links/{a_id}/pull")
    assert the_link(a, a_id).brokenAt is not None
    new_a, _ = linked(ca, cb)
    old = the_link(a, a_id)
    assert old.deleted and old.state == "ended" and old.endedAt is not None
    assert [link.id for link in live_links(a)] == [new_a]
    assert the_link(a, new_a).brokenAt is None


def test_a_link_neither_ended_nor_broken_isnt_linked_twice(admins):  # noqa: F811
    _a, _b, ca, cb, _ = admins
    linked(ca, cb)
    code = ca.post("/ui/api/settings/links/invitations").json()["code"]
    r = cb.post("/ui/api/settings/links/join", json={"code": code})
    assert r.status_code >= 400 and r.json()["code"] == "already-linked"


def test_a_request_ended_before_its_approval_ends_on_both_sides(admins):  # noqa: F811
    a, b, ca, cb, _ = admins
    code = ca.post("/ui/api/settings/links/invitations").json()["code"]
    b_id = cb.post("/ui/api/settings/links/join", json={"code": code}).json()["id"]
    a_id = next(x["id"] for x in links_of(ca)["links"] if x["state"] == "requested")
    assert ca.post(f"/ui/api/settings/links/{a_id}/end").status_code == 200
    assert the_link(a, a_id).state == "ended"
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # B learns at its next call (S11.6)
    assert the_link(b, b_id).state == "ended"


def test_a_paused_link_ended_ends_on_both_sides(admins):  # noqa: F811
    a, b, ca, cb, _ = admins
    a_id, b_id = linked(ca, cb)
    r = ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": "1d"})
    assert r.status_code == 200, r.text
    assert ca.post(f"/ui/api/settings/links/{a_id}/end").status_code == 200
    assert the_link(a, a_id).state == "ended" and the_link(b, b_id).state == "ended"


def test_a_stranger_is_never_marked_broken():
    """`not-linked` from a peer whose link here is ended or not yet made changes nothing."""
    for state in ("invited", "requested", "ended"):
        with pytest.raises(LinkError):
            lifecycle.step(state, False, "not-linked")
