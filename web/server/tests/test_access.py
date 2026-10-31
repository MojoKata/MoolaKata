"""The access views (docs/schema.md §7): every table declared, every view made, its queries
searched by index, and, while the Python rules remain, the views agreeing with them for every
user and record of a household built to reach every rule."""

import hashlib

import pytest
from sqlalchemy import select, text

from moolakata import access, clock, ids
from moolakata.app import Server
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store import access_views, views
from moolakata.store.maintenance import open_store
from moolakata.store.tables import metadata

# ---- The household ----


@pytest.fixture(scope="module")
def household(tmp_path_factory):
    """The dev seed (admin, alice, bob, the Household group, a linked server), and what it
    doesn't reach: an inactive user, a member of an active and of an inactive group, a filer
    who hasn't accepted, a gift plan for bob shared with him, a receipt kept with a gift and
    with transactions on both sides of a share, and a linked server's user with and without
    *Include receipts*."""
    from moolakata.dev import seed
    from moolakata.store.repos.ledger import ensure_categories

    tmp = tmp_path_factory.mktemp("access")
    config = Config(
        name="test",
        mode="proxy",
        data_dir=tmp / "data",
        backup_dir=tmp / "backups",
        socket_path=tmp / "run" / "sock",
    )
    key = b"\x07" * 16
    master.create_keyring(config, key)
    store = open_store(config, key)
    srv = Server(config=config, store=store, ready=True)
    with srv.db.tx(unscoped="test") as s:
        ensure_categories(s)
    seed.seed(srv)
    with srv.db.tx(unscoped="test") as s:
        names = edge_cases(s)
    yield srv, names
    store.db.dispose()


def edge_cases(s) -> dict[str, str]:
    from moolakata.links.manage import apply_directory
    from moolakata.people import make as make_person
    from moolakata.store.entities.accounts import Account, Transaction
    from moolakata.store.entities.budgets import Budget
    from moolakata.store.entities.education import Gift, GiftPerson, GiftPlan
    from moolakata.store.entities.links import Link
    from moolakata.store.entities.receipts import Receipt, ReceiptLink
    from moolakata.store.entities.sharing import Share
    from moolakata.store.entities.taxes import TaxBook, TaxBookFiler
    from moolakata.store.entities.users import Group, User, UserGroup

    now = clock.now()
    users = {u.username: u for u in s.scalars(select(User).where(User.linkId.is_(None)))}
    alice, bob = users["alice"], users["bob"]

    def user(name: str, active: bool = True) -> User:
        p = make_person(s, name.title(), "female")
        u = User(
            id=ids.new_id("User"),
            personId=p.id,
            username=name,
            displayName=name.title(),
            email=f"{name}@griffin.home",
            active=active,
        )
        s.add(u)
        s.flush()
        return u

    def group(name: str, active: bool, *members: User) -> Group:
        g = Group(id=ids.new_id("Group"), name=name, active=active)
        s.add(g)
        s.flush()
        for m in members:
            s.add(UserGroup(userId=m.id, groupId=g.id, createdAt=now))
        return g

    def share(kind, item_id, level, user=None, grp=None, receipts=False):
        s.add(
            Share(
                id=ids.new_id("Share"),
                kind=kind,
                itemId=item_id,
                userId=user.id if user else None,
                groupId=grp.id if grp else None,
                level=level,
                createdById=alice.id,
                includeReceipts=receipts,
            )
        )

    def alices(entity, **where):
        q = select(entity).where(entity.ownerId == alice.id, entity.deleted.is_(False))
        for k, v in where.items():
            q = q.where(getattr(entity, k) == v)
        return s.scalars(q.order_by(entity.id)).first()

    accounts = list(
        s.scalars(select(Account).where(Account.ownerId == alice.id).order_by(Account.name))
    )
    shared = next(a for a in accounts if a.name == "Everyday checking")
    unshared = next(
        a
        for a in accounts
        if not s.scalars(select(Share).where(Share.itemId == a.id)).first()
        and s.scalars(select(Transaction).where(Transaction.accountId == a.id)).first()
    )

    carol = user("carol", active=False)
    s.add(Account(id=ids.new_id("Acct"), ownerId=carol.id, name="Carol's", type="checking"))
    share("account", shared.id, "read", user=carol)

    dave = user("dave")
    helpers = group("Helpers", True, dave)
    former = group("Former helpers", False, dave)
    book = alices(TaxBook)
    budget = alices(Budget)
    share("tax-book", book.id, "read", grp=helpers)
    share("budget", budget.id, "write", grp=former)

    erin = user("erin")
    s.add(TaxBookFiler(bookId=book.id, userId=erin.id, createdAt=now))

    household = s.scalars(select(Group).where(Group.name == "Household")).one()
    plan = alices(GiftPlan, personId=bob.personId)
    if plan is None:
        plan = GiftPlan(id=ids.new_id("GfPln"), ownerId=alice.id, personId=bob.personId)
        s.add(plan)
        s.flush()
    share("gift-plan", plan.id, "read", grp=household)
    surprise = Gift(id=ids.new_id("Gift"), ownerId=alice.id, description="A watch")
    s.add(surprise)
    s.flush()
    s.add(GiftPerson(giftId=surprise.id, personId=bob.personId, createdAt=now))

    def txn(account):
        return s.scalars(
            select(Transaction)
            .where(Transaction.accountId == account.id, Transaction.deleted.is_(False))
            .order_by(Transaction.id)
        ).first()

    receipt = Receipt(
        id=ids.new_id("Rcpt"),
        ownerId=alice.id,
        fileName="jeweller.pdf",
        mediaType="application/pdf",
        size=1,
        sha256=hashlib.sha256(b"x").hexdigest(),
        fileId="0" * 32,
    )
    s.add(receipt)
    s.flush()
    for kind, item in (
        ("transaction", txn(shared).id),
        ("transaction", txn(unshared).id),
        ("gift", surprise.id),
    ):
        s.add(ReceiptLink(receiptId=receipt.id, kind=kind, itemId=item, linkedById=alice.id))

    link = s.scalars(select(Link).order_by(Link.id)).first()
    apply_directory(
        s,
        link,
        {
            "users": [
                {"id": "r-tom", "username": "tom", "displayName": "Tom", "sex": "male"},
                {"id": "r-ann", "username": "ann", "displayName": "Ann", "sex": "female"},
            ]
        },
    )
    remote = {u.remoteId: u for u in s.scalars(select(User).where(User.linkId == link.id))}
    share("account", shared.id, "read", user=remote["r-tom"])
    share("account", shared.id, "read", user=remote["r-ann"], receipts=True)
    s.flush()
    return {
        "carol": carol.id,
        "dave": dave.id,
        "erin": erin.id,
        "tom": remote["r-tom"].id,
        "ann": remote["r-ann"].id,
        "receipt": receipt.id,
        "gift": surprise.id,
        "plan": plan.id,
        "book": book.id,
        "budget": budget.id,
        "unshared": unshared.id,
        "alice": alice.id,
        "bob": bob.id,
    }


def rows(s, table: str) -> dict[tuple[str, str], tuple[int, int, int, int]]:
    return {
        (r[0], r[1]): tuple(int(x) for x in r[2:])
        for r in s.execute(
            text(
                f'SELECT "targetId", "userId", writable, deletable, shareable, configurable '
                f'FROM "{access_views.access_name(table)}"'
            )
        )
    }


# ---- Declarations and views ----


def test_every_view_has_one_row_per_record_and_user(household):
    srv, _ = household
    with srv.db.read(unscoped="test") as s:
        for t in metadata.sorted_tables:
            if not access_views.has_view(t):
                continue
            name = access_views.access_name(t.name)
            dup = s.execute(
                text(
                    f'SELECT count(*) FROM (SELECT 1 FROM "{name}" '
                    'GROUP BY "targetId", "userId" HAVING count(*) > 1)'
                )
            ).scalar()
            assert dup == 0, name
            broken = s.execute(
                text(
                    f'SELECT count(*) FROM "{name}" WHERE '
                    "(deletable OR shareable OR configurable) AND NOT writable"
                )
            ).scalar()
            assert broken == 0, f"{name}: a permission without writable"


def test_a_child_is_searched_by_its_index_never_scanned(household):
    """Joined as a caller joins it, a child's view adds no scan of the child table to a query
    by its id or its parent's key (decision 2.4)."""
    srv, _ = household

    def scans(s, t, sql):
        plan = [r[3] for r in s.execute(text("EXPLAIN QUERY PLAN " + sql), {"x": "x", "u": "u"})]
        return [p for p in plan if p in ("SCAN c", f"SCAN {t.name}")], plan

    with srv.db.read(unscoped="test") as s:
        for t in metadata.sorted_tables:
            how = access_views.seen(t)
            if how.how != "child":
                continue
            name = access_views.access_name(t.name)
            for where in ("c.id = :x", f'c."{how.key}" = :x'):
                bare = f'SELECT c.id FROM "{t.name}" AS c WHERE {where}'
                joined = (
                    f'{bare} AND EXISTS (SELECT 1 FROM "{name}" AS a '
                    'WHERE a."targetId" = c.id AND a."userId" = :u)'
                )
                before, _ = scans(s, t, bare)
                after, plan = scans(s, t, joined)
                assert len(after) <= len(before), f"{t.name} ({where}): {plan}"


# ---- The views against the Python rules (decision 7.2, until step 5) ----

ROOTS = {
    "account": "Account",
    "portfolio": "Portfolio",
    "budget": "Budget",
    "gift-plan": "GiftPlan",
    "giving-plan": "GivingPlan",
    "tax-book": "TaxBook",
    "projection": "Projection",
}


def everyone(s) -> list[str]:
    from moolakata.store.entities.users import User

    return [u.id for u in s.scalars(select(User).where(User.deleted.is_(False)))]


def derived(row) -> str | None:
    """The level a root's view gives, as the API names it (decision 6.4)."""
    if row is None:
        return None
    if all(row):
        return "owner"
    return "write" if row[0] else "read"


def old_root(s, kind: str, item, user_id: str) -> str | None:
    from moolakata.taxes import books

    if kind == "tax-book":
        return books.level(s, user_id, item)
    if kind == "gift-plan":  # as gifts.plan_by_id had it: while its person is there
        from moolakata.store.entities.education import Person

        person = s.get(Person, item.personId)
        if person is None or person.deleted:
            return None
    return access.level_of(s, user_id, kind, item.ownerId, item.id, item.deleted)


def expected_difference(kind: str, item_id: str, user_id: str, names, s) -> str | None:
    """Why a view deliberately parts from the Python rule, by decision; None when it
    doesn't."""
    from moolakata.store.entities.users import User

    u = s.get(User, user_id)
    if not u.active:
        return "4.1"
    if kind == "gift-plan" and u.linkId is not None:
        return "4.5"
    return None


def test_roots_agree_with_the_python_rules(household):
    srv, names = household
    from moolakata.store import entities  # noqa: F401
    from moolakata.store.entities.accounts import Account
    from moolakata.store.entities.budgets import Budget
    from moolakata.store.entities.education import GiftPlan
    from moolakata.store.entities.giving import GivingPlan
    from moolakata.store.entities.projections import Projection
    from moolakata.store.entities.sharing import Portfolio
    from moolakata.store.entities.taxes import TaxBook

    entity = {
        "account": Account,
        "portfolio": Portfolio,
        "budget": Budget,
        "gift-plan": GiftPlan,
        "giving-plan": GivingPlan,
        "tax-book": TaxBook,
        "projection": Projection,
    }
    wrong = []
    with srv.db.read(unscoped="test") as s:
        users = everyone(s)
        for kind, table in ROOTS.items():
            view = rows(s, table)
            for item in s.scalars(select(entity[kind]).where(entity[kind].deleted.is_(False))):
                for u in users:
                    old = old_root(s, kind, item, u)
                    new = derived(view.get((item.id, u)))
                    if old != new:
                        why = expected_difference(kind, item.id, u, names, s)
                        if why is None or new is not None:
                            wrong.append((kind, item.id, u, old, new))
    assert not wrong, wrong[:20]


def test_children_agree_with_their_roots(household):
    """Each child is seen exactly as the root its keys lead to is, by the Python rule."""
    srv, names = household
    wrong = []
    with srv.db.read(unscoped="test") as s:
        users = everyone(s)
        old_cache: dict[tuple[str, str, str], str | None] = {}
        for t in metadata.sorted_tables:
            if access_views.seen(t).how != "child":
                continue
            chain, cur = [], t
            while access_views.seen(cur).how == "child":
                key = access_views.seen(cur).key
                parent = next(f for f in cur.foreign_keys if f.parent.name == key).column.table
                chain.append((cur, key, parent))
                cur = parent
            root = cur
            kind = access_views.seen(root).share
            if kind is None:
                continue
            # Every live child's root, through the Effective views.
            sql = f'SELECT c0.id, c{len(chain) - 1}."{chain[-1][1]}" FROM '
            joins = []
            for i, (tab, _, _) in enumerate(chain):
                src = (
                    f'"{views.view_name(tab.name)}" AS c{i}'
                    if tab.info.get("softDelete")
                    else f'"{tab.name}" AS c{i}'
                )
                live = f'NOT c{i}."effectiveDeleted"' if tab.info.get("softDelete") else "1"
                if i == 0:
                    joins.append(f"{src}")
                    where = [live]
                else:
                    joins.append(f'JOIN {src} ON c{i}.id = c{i - 1}."{chain[i - 1][1]}"')
                    where.append(live)
            sql += "\n".join(joins) + " WHERE " + " AND ".join(where)
            view = rows(s, t.name)
            ent = {r.local_table.name: r.class_ for r in _mappers()}[root.name]
            for child_id, root_id in s.execute(text(sql)):
                item = s.get(ent, root_id)
                for u in users:
                    k = (kind, root_id, u)
                    if k not in old_cache:
                        old_cache[k] = old_root(s, kind, item, u) if item else None
                    old = old_cache[k]
                    row = view.get((child_id, u))
                    got = None if row is None else ("write" if row[0] else "read")
                    want = (
                        None if old is None else ("write" if old in ("owner", "write") else "read")
                    )
                    if got != want and expected_difference(kind, root_id, u, names, s) is None:
                        wrong.append((t.name, child_id, u, want, got))
    assert not wrong, wrong[:20]


def _mappers():
    from moolakata.store.mapping import mapper_registry

    return list(mapper_registry.mappers)


def test_people_receipts_and_gifts_agree_with_the_python_rules(household):
    srv, names = household
    from moolakata import gifts, people, receipts
    from moolakata.store.entities.education import Gift, Person
    from moolakata.store.entities.receipts import Receipt

    wrong = []
    with srv.db.read(unscoped="test") as s:
        users = everyone(s)
        person = rows(s, "Person")
        for p in s.scalars(select(Person).where(Person.deleted.is_(False))):
            for u in users:
                old = people.level(s, u, p)
                row = person.get((p.id, u))
                new = None if row is None else ("owner" if row[0] else "read")
                if old != new and expected_difference("person", p.id, u, names, s) is None:
                    wrong.append(("person", p.name, u, old, new))
        receipt = rows(s, "Receipt")
        for r in s.scalars(select(Receipt).where(Receipt.deleted.is_(False))):
            for u in users:
                old = receipts.level(s, u, r)
                row = receipt.get((r.id, u))
                new = (
                    None if row is None else ("owner" if row[1] else "write" if row[0] else "read")
                )
                why = expected_difference("receipt", r.id, u, names, s)
                if r.id == names["receipt"] and u == names["bob"]:
                    why = "1d.3"  # through the gift for him: never; through the joint account
                if r.id == names["receipt"] and u == names["tom"]:
                    why = "4.4"  # without Include receipts
                if old != new and why is None:
                    wrong.append(("receipt", r.fileName, u, old, new))
        gift = rows(s, "Gift")
        for u in users:
            seen = {g.id for g, _ in gifts.visible_gifts(s, u)}
            for g in s.scalars(select(Gift).where(Gift.deleted.is_(False))):
                ps = gifts.people_of_gifts(s, [g.id])[g.id]
                old = gifts.level_on_gift(s, u, g, ps) if g.id in seen else None
                row = gift.get((g.id, u))
                new = (
                    None
                    if row is None
                    else ("owner" if g.ownerId == u else "write" if row[0] else "read")
                )
                if old != new and expected_difference("gift", g.id, u, names, s) is None:
                    wrong.append(("gift", g.description, u, old, new))
    assert not wrong, wrong[:20]


def test_the_household_reaches_every_rule(household):
    """What the edge cases are for, each as the decisions say."""
    srv, n = household
    with srv.db.read(unscoped="test") as s:
        account, receipt = rows(s, "Account"), rows(s, "Receipt")
        link, gift = rows(s, "ReceiptLink"), rows(s, "Gift")
        book, budget = rows(s, "TaxBook"), rows(s, "Budget")
        assert not [k for k in account if k[1] == n["carol"]]  # 4.1
        assert (n["book"], n["dave"]) in book  # an active group's share
        assert (n["budget"], n["dave"]) not in budget  # an inactive group's: nothing
        assert (n["book"], n["erin"]) not in book  # a filer who hasn't accepted
        assert book[(n["book"], n["alice"])] == (1, 1, 1, 1)
        assert (n["gift"], n["bob"]) not in gift  # the person it is for (1d.3)
        assert (n["receipt"], n["bob"]) in receipt  # through the shared account
        mine = s.execute(
            text('SELECT id FROM "ReceiptLink" WHERE "receiptId" = :r'), {"r": n["receipt"]}
        ).scalars()
        bobs = [x for x in mine if (x, n["bob"]) in link]
        assert len(bobs) == 1  # CR3-47: only the joint account's link
        assert (n["receipt"], n["tom"]) not in receipt  # 4.4: without Include receipts
        assert (n["receipt"], n["ann"]) in receipt  # with it
        assert not [k for k in account if k[1] == n["tom"] and account[k][0]]  # read only


def test_activity_agrees_with_the_python_rule(household):
    """S10.8's entries, as the Activity screen's query chooses them."""
    srv, _ = household
    from moolakata.auth.users import admin_ids
    from moolakata.store.entities.core import Activity

    class C:
        def __init__(self, uid, admin):
            self.id, self.admin = uid, admin

    def _visible(s, c):
        """The rule as the Python code had it (ui/activity.py), until step 5."""
        from sqlalchemy import and_, func, or_

        from moolakata.store.entities.budgets import Budget
        from moolakata.store.entities.sharing import Portfolio
        from moolakata.taxes import books

        r = access.reach(s, c.id)

        def readable(entity, kind):
            return [
                x.id
                for x in s.scalars(select(entity).where(entity.deleted.is_(False)))
                if access.level_of(s, c.id, kind, x.ownerId, x.id, x.deleted, r)
            ]

        from moolakata.store.entities.accounts import Account

        accounts = readable(Account, "account")
        portfolios = readable(Portfolio, "portfolio")
        budgets = readable(Budget, "budget")
        shared: dict[str, set[str]] = {}
        for kind, item in r.levels:
            shared.setdefault(kind, set()).add(item)
        from moolakata.store.entities.taxes import TaxBook

        shared.setdefault("tax-book", set()).update(
            b.id
            for b in s.scalars(select(TaxBook).where(TaxBook.deleted.is_(False)))
            if books.level(s, c.id, b) is not None
        )
        groups = access.groups_of(s, c.id)
        grantee = func.json_extract(Activity.detail, "$.granteeId")
        conds = [
            Activity.actorId == c.id,
            Activity.ownerId == c.id,
            and_(Activity.subjectKind == "account", Activity.subjectId.in_(accounts)),
            and_(Activity.subjectKind == "portfolio", Activity.subjectId.in_(portfolios)),
            and_(Activity.subjectKind == "budget", Activity.subjectId.in_(budgets)),
            *(
                and_(Activity.subjectKind == kind, Activity.subjectId.in_(sorted(items)))
                for kind, items in shared.items()
                if kind not in ("account", "portfolio", "budget")
            ),
            and_(Activity.kind == "share.removed", or_(grantee == c.id, grantee.in_(groups))),
        ]
        if c.admin:
            conds.append(
                and_(
                    Activity.forAdmins,
                    or_(
                        Activity.subjectKind.is_(None),
                        Activity.subjectKind.in_(("user", "group", "link")),
                    ),
                )
            )
        return or_(*conds)

    with srv.db.read(unscoped="test") as s:
        view = rows(s, "Activity")
        admins = admin_ids(s)
        from moolakata.store.entities.users import User

        for u in s.scalars(select(User).where(User.linkId.is_(None), User.active)):
            old = set(s.scalars(select(Activity.id).where(_visible(s, C(u.id, u.id in admins)))))
            new = {k[0] for k in view if k[1] == u.id}
            extra = {
                i
                for i in new - old
                if s.get(Activity, i).subjectKind == "person"  # 1f.5: through PersonAccess
            }
            assert old == new - extra, (u.username, old ^ new)


# ---- Scoped sessions (decision 5) ----


def test_a_users_session_reads_only_what_their_views_give(household):
    """Lists, a get, a joined table and an alias are all scoped; the same statement, cached,
    gives each user their own; the server's session reads everything."""
    from sqlalchemy.orm import aliased

    from moolakata.store.entities.accounts import Account, Transaction

    srv, n = household

    def ids_of(user=None, unscoped=None):
        with srv.db.read(user=user, unscoped=unscoped) as s:
            accounts = set(s.scalars(select(Account.id)))
            joined = set(
                s.scalars(select(Transaction.id).join(Account, Account.id == Transaction.accountId))
            )
            a = aliased(Account)
            aliased_ids = set(s.scalars(select(a.id)))
            got = s.get(Account, n["unshared"])
            return accounts, joined, aliased_ids, got

    every, all_txns, _, unshared = ids_of(unscoped="test: every account")
    assert unshared is not None
    for user in ("alice", "bob", "tom", "carol"):
        with srv.db.read(unscoped="test: the view") as s:
            view = rows(s, "Account")
            txns = rows(s, "Transaction")
        accounts, joined, aliased_ids, got = ids_of(user=n[user])
        assert accounts == {k[0] for k in view if k[1] == n[user]}, user
        assert aliased_ids == accounts, user
        assert joined == {k[0] for k in txns if k[1] == n[user]} & all_txns, user
        assert (got is not None) == ((n["unshared"], n[user]) in view), user
    assert accounts < every


def test_need_answers_404_unread_and_403_without_the_permission(household):
    from moolakata.errors import Problem
    from moolakata.store.entities.accounts import Account

    srv, n = household
    with srv.db.read(user=n["bob"]) as s:
        shared = s.scalars(select(Account).where(Account.name == "Everyday checking")).one()
        got, p = access.need(s, Account, shared.id, n["bob"])
        assert got.id == shared.id and p.level() == "read"
        with pytest.raises(Problem) as e:
            access.need(s, Account, shared.id, n["bob"], "writable", "account")
        assert e.value.status == 403
        with pytest.raises(Problem) as e:
            access.need(s, Account, n["unshared"], n["bob"])
        assert e.value.status == 404
        listed = access.listing(s, Account, n["bob"], order_by=Account.name)
        assert {a.id for a, _ in listed} == {k[0] for k in rows(s, "Account") if k[1] == n["bob"]}
    with srv.db.read(unscoped="test: holders") as s:
        held = access.holders_of(s, Account, shared.id)
        assert held[n["alice"]].level() == "owner" and n["bob"] in held
