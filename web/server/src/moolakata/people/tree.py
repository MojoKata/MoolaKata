"""The family tree (requirements S10.10.5), worked out from the stored *child*, *spouse* and
*couple* relationships as of a day, never stored. Each relation is said in the word for the
other person's sex: mother or father, niece or nephew."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..store.entities.education import Person, Relationship
from . import holds_on, order

# The relations that are a person's children, listed oldest first.
CHILDREN = ("child", "grandchild", "step-child")

WORDS = {
    # key: (female, male)
    "parent": ("mother", "father"),
    "child": ("daughter", "son"),
    "sibling": ("sister", "brother"),
    "half-sibling": ("half-sister", "half-brother"),
    "grandparent": ("grandmother", "grandfather"),
    "grandchild": ("granddaughter", "grandson"),
    "aunt-uncle": ("aunt", "uncle"),
    "niece-nephew": ("niece", "nephew"),
    "cousin": ("cousin", "cousin"),
    "step-parent": ("stepmother", "stepfather"),
    "step-child": ("stepdaughter", "stepson"),
    "step-sibling": ("stepsister", "stepbrother"),
    "parent-in-law": ("mother-in-law", "father-in-law"),
    "child-in-law": ("daughter-in-law", "son-in-law"),
    "sibling-in-law": ("sister-in-law", "brother-in-law"),
    "spouse": ("wife", "husband"),
    "ex-spouse": ("ex-wife", "ex-husband"),
    "widowed": ("widow", "widower"),
    "couple": ("couple", "couple"),
    "friend": ("friend", "friend"),
    "colleague": ("colleague", "colleague"),
    "family": ("family", "family"),
    "relative": ("relative", "relative"),
}


def word(key: str, sex: str, depth: int = 0) -> str:
    """The word for a relation; `depth` adds great- for ancestors and descendants past the
    grandparents."""
    w = WORDS[key][0 if sex == "female" else 1]
    return "great-" * depth + w


@dataclass
class Relation:
    personId: str
    key: str  # parent, sibling, step-parent… or a stored friend, colleague, family
    word: str  # in the other person's sex: mother, brother-in-law
    stored: bool  # entered, or worked out
    label: str | None = None  # family's label


class Graph:
    """The household's relationships as of a day."""

    def __init__(self, people: dict[str, Person], rels: list[Relationship], day: dt.date):
        self.people = people
        self.day = day
        deaths = {p.id: p.diedOn for p in people.values() if p.diedOn}
        self.parents: dict[str, set[str]] = {}
        self.children: dict[str, set[str]] = {}
        self.spouses: dict[str, set[str]] = {}  # married on the day
        self.couples: dict[str, set[str]] = {}
        self.exes: dict[str, set[str]] = {}  # divorced by the day
        self.widowed: dict[str, set[str]] = {}  # married until one of them died
        self.stored: list[Relationship] = []
        for r in rels:
            a, b = r.person1Id, r.person2Id
            if a not in people or b not in people:
                continue
            if r.relation == "child":
                if r.fromDate is None or r.fromDate <= day:
                    self.parents.setdefault(b, set()).add(a)
                    self.children.setdefault(a, set()).add(b)
            elif r.relation in ("spouse", "couple"):
                if r.fromDate and day < r.fromDate:
                    continue
                if holds_on(None, r, day, deaths):
                    into = self.spouses if r.relation == "spouse" else self.couples
                    into.setdefault(a, set()).add(b)
                    into.setdefault(b, set()).add(a)
                elif r.relation == "spouse":
                    died = [deaths[i] for i in (a, b) if i in deaths and deaths[i] <= day]
                    by_death = died and (r.toDate is None or min(died) <= r.toDate)
                    into = self.widowed if by_death else self.exes
                    into.setdefault(a, set()).add(b)
                    into.setdefault(b, set()).add(a)
            else:
                if (r.fromDate is None or r.fromDate <= day) and (
                    r.toDate is None or day < r.toDate
                ):
                    self.stored.append(r)

    def _p(self, x: str) -> set[str]:
        return self.parents.get(x, set())

    def _c(self, x: str) -> set[str]:
        return self.children.get(x, set())

    def _sp(self, x: str) -> set[str]:
        return self.spouses.get(x, set())

    def _wed(self, x: str) -> set[str]:
        """Spouses on the day and those a death parted: the in-laws and step-family through a
        marriage last past a death, and end only with a divorce (S10.10.5)."""
        return self.spouses.get(x, set()) | self.widowed.get(x, set())

    def siblings(self, x: str) -> tuple[set[str], set[str]]:
        """Full siblings (both parents shared) and half-siblings (one shared)."""
        full, half = set(), set()
        mine = self._p(x)
        for p in mine:
            for sib in self._c(p):
                if sib == x:
                    continue
                if self._p(sib) == mine:
                    full.add(sib)
                else:
                    half.add(sib)
        return full, half - full

    def relations(self, ego: str) -> list[Relation]:
        found: dict[str, tuple[int, str, int]] = {}  # person → (rank, key, depth)

        def put(pid: str, rank: int, key: str, depth: int = 0) -> None:
            if pid == ego or pid not in self.people:
                return
            if pid not in found or rank < found[pid][0]:
                found[pid] = (rank, key, depth)

        for x in self._sp(ego):
            put(x, 0, "spouse")
        for x in self.couples.get(ego, set()):
            put(x, 0, "couple")
        for x in self._p(ego):
            put(x, 1, "parent")
        for x in self._c(ego):
            put(x, 1, "child")
        full, half = self.siblings(ego)
        for x in full:
            put(x, 2, "sibling")
        for x in half:
            put(x, 3, "half-sibling")
        # Ancestors and descendants past the first: grandparents, then great-.
        level, depth = set(self._p(ego)), 0
        while level:
            level = {g for p in level for g in self._p(p)}
            for g in level:
                put(g, 4 + depth, "grandparent", depth)
            depth += 1
        level, depth = set(self._c(ego)), 0
        while level:
            level = {g for c in level for g in self._c(c)}
            for g in level:
                put(g, 4 + depth, "grandchild", depth)
            depth += 1
        for p in self._p(ego):
            pf, ph = self.siblings(p)
            for au in pf | ph:
                put(au, 6, "aunt-uncle")
                for cousin in self._c(au):
                    put(cousin, 8, "cousin")
        for sib in full | half:
            for n in self._c(sib):
                put(n, 6, "niece-nephew")
        # Step-family: a parent's spouse who isn't a parent, and their children.
        for p in self._p(ego):
            for sp in self._wed(p):
                if sp not in self._p(ego):
                    put(sp, 5, "step-parent")
                    for sc in self._c(sp):
                        if sc not in full | half:
                            put(sc, 7, "step-sibling")
        for sp in self._wed(ego):
            for sc in self._c(sp):
                if sc not in self._c(ego):
                    put(sc, 5, "step-child")
        # In-laws: through a spouse, or a child's or sibling's spouse.
        for sp in self._wed(ego):
            for p in self._p(sp):
                put(p, 5, "parent-in-law")
            sf, sh = self.siblings(sp)
            for x in sf | sh:
                put(x, 7, "sibling-in-law")
        for c in self._c(ego):
            for x in self._wed(c):
                put(x, 5, "child-in-law")
        for sib in full | half:
            for x in self._wed(sib):
                put(x, 7, "sibling-in-law")
        for x in self.exes.get(ego, set()):
            put(x, 9, "ex-spouse")
        for x in self.widowed.get(ego, set()):
            p = self.people[x]
            # The one who died is still the husband or wife; the survivor is the widow(er).
            ego_died = self.people[ego].diedOn
            put(x, 0, "widowed" if ego_died and (not p.diedOn or ego_died < p.diedOn) else "spouse")
        # Anyone else joined through the tree is a relative.
        for x in self._joined(ego):
            put(x, 10, "relative")

        def in_order(r: Relation) -> tuple:
            # Nearest first; a person's children oldest first, anyone else by name (S10.10.7).
            rank, key, _ = found.get(r.personId, (99, "", 0))
            p = self.people[r.personId]
            near = (
                order.oldest_first_key(p)
                if key in CHILDREN
                else (False, 0, 0, 0, p.name.casefold())
            )
            return (rank, key, near)

        out = [
            Relation(pid, key, word(key, self.people[pid].sex, depth), False)
            for pid, (_, key, depth) in found.items()
        ]
        known = set(found)
        for r in self.stored:
            if ego not in (r.person1Id, r.person2Id):
                continue
            pid = r.person2Id if r.person1Id == ego else r.person1Id
            if pid in known:
                continue
            known.add(pid)
            text = (r.label or "family") if r.relation == "family" else r.relation
            out.append(Relation(pid, r.relation, text, True, r.label))
        stored_pairs = {(r.person1Id, r.person2Id) for r in self.stored}
        for rel in out:
            if (
                rel.key in ("parent", "child", "spouse", "couple")
                or (ego, rel.personId) in stored_pairs
                or (rel.personId, ego) in stored_pairs
            ):
                rel.stored = True
        return sorted(out, key=in_order)

    def _joined(self, ego: str) -> set[str]:
        """Everyone reached through parents, children and marriages, those a death parted
        among them."""
        seen, todo = {ego}, [ego]
        while todo:
            x = todo.pop()
            for y in self._p(x) | self._c(x) | self._wed(x) | self.couples.get(x, set()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        return seen - {ego}


def graph(s: Session, day: dt.date | None = None) -> Graph:
    from .. import clock

    people = {p.id: p for p in s.scalars(select(Person).where(Person.deleted == false()))}
    rels = list(s.scalars(select(Relationship).where(Relationship.deleted == false())))
    return Graph(people, rels, day or clock.today())


def relations(s: Session, person_id: str, day: dt.date | None = None) -> list[Relation]:
    """Who a person is related to as of a day, stored and worked out (S10.10.5)."""
    return graph(s, day).relations(person_id)


def relation_to(s: Session, viewer_person: str, day: dt.date | None = None) -> dict[str, Relation]:
    """Each person's relation to the viewer: *Lisa, your granddaughter*."""
    return {r.personId: r for r in relations(s, viewer_person, day)}
