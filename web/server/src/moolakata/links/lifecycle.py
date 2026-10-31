"""A link's lifecycle (requirements S11.6, S11.7; link-protocol.md §4.6): its states, what
moves a link from one to another, and which calls each state allows, in one place. Nothing
else in `links/` writes a link's state or its broken mark: `manage` moves a link only through
`step`, and the routes take their states from `CALLS`.

*Broken* is a mark on a link that still has its state, never a state of its own: the peer
answered that it has no link with this one (restored from an older backup, say). A good call
clears it; an admin ends the link, or links again, which ends it and puts a new link in its
place."""

from dataclasses import dataclass

from .. import clock
from .client import LinkError

STATES = ("invited", "requested", "pending", "active", "paused", "ended")

# Each event, and the state it moves a link from to the state it moves it to.
MOVES: dict[str, dict[str | None, str]] = {
    # An admin makes a link code here: a link waiting for the other server.
    "invite": {None: "invited"},
    # An admin enters the other server's code here: a link waiting for its admin.
    "join-here": {None: "pending"},
    # The other server answers this one's code: a request for this side's admin.
    "join-arrives": {"invited": "requested"},
    "approve": {"requested": "active"},
    # The other side approved: its answer to an exchange, or its exchange, says so.
    "peer-active": {"pending": "active", "active": "active"},
    "pause": {"active": "paused"},
    # An admin resumes it, or the pause runs out.
    "resume": {"paused": "active"},
    "end-here": {s: "ended" for s in ("invited", "requested", "pending", "active", "paused")},
    # The peer's signed `link-ended`, its answer or its call.
    "link-ended": {s: "ended" for s in ("requested", "pending", "active", "paused", "ended")},
    # The peer answers `not-linked`: marked broken, its state kept.
    "not-linked": {s: s for s in ("pending", "active", "paused")},
    # A call the peer answered: the broken mark goes.
    "good-call": {s: s for s in STATES},
    # A new link is made with this link's peer (S11.6): an ended link is put aside for it, and
    # a broken one ended first; any other is the link the two already have.
    "link-again": {"ended": "ended", **{s: "ended" for s in ("pending", "active", "paused")}},
}
EVENTS = tuple(MOVES)

REFUSED = {
    "approve": ("not-requested", "Only a request can be approved."),
    "link-again": ("already-linked", "These two servers are already linked."),
}

# Which calls the peer may make in each state (link-protocol.md §4): the routes' finders.
CALLS: dict[str, tuple[str, ...]] = {
    "ping": ("requested", "pending", "active", "paused"),
    "exchange": ("pending", "active"),
    "next": ("active",),
    "deliver": ("active",),
    "file": ("active",),
    "certificate": ("active", "paused"),
    "end": ("requested", "pending", "active", "paused"),
}


@dataclass(frozen=True)
class Step:
    """Where an event leaves a link: its state, its broken mark, whether the event ended it
    (its copy, shares and remote users go), and whether it is put aside for a new link."""

    state: str
    broken: bool
    ended: bool = False
    retired: bool = False


def step(state: str | None, broken: bool, event: str) -> Step:
    """The link after `event`, or LinkError when its state doesn't allow it."""
    moves = MOVES[event]
    if state not in moves or (event == "link-again" and state != "ended" and not broken):
        code, message = REFUSED.get(
            event, ("state-invalid", f"A link that is {state or 'not made'} can't take {event}.")
        )
        raise LinkError(code, message)
    to = moves[state]
    if event == "not-linked":
        marked = True
    elif event in ("good-call", "end-here", "link-ended", "link-again"):
        marked = False
    else:
        marked = broken
    return Step(to, marked, ended=to == "ended" and state != "ended", retired=event == "link-again")


def start(event: str) -> str:
    """The state a new link starts in: `invite` or `join-here`."""
    return step(None, False, event).state


def apply(link, event: str, by: str | None = None) -> Step:
    """Move a link row by `event`: its state, its broken mark, when it ended, and, put aside
    for a new link, its row soft-deleted (by `by`). The caller does what an end means beyond
    the row."""
    got = step(link.state, link.brokenAt is not None, event)
    link.state = got.state
    if got.broken and link.brokenAt is None:
        link.brokenAt = clock.now()
    elif not got.broken:
        link.brokenAt = None
    if got.ended:
        link.endedAt = clock.now()
    if got.retired:
        link.mark_deleted(by)
    return got
