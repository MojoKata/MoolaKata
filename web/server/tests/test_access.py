"""The access views (docs/schema.md §7): every table declared, every view made, its queries
searched by index, and, while the Python rules remain, the views agreeing with them for every
user and record of a household built to reach every rule."""

import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from moolakata import access, clock, ids
from moolakata.app import Server
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store import access_views
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
    from moolakata.store.entities.accounts import (
        Account,
        Reimbursement,
        Transaction,
        TransferMatch,
        WashSale,
    )
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
        from moolakata.auth import passwords
        from moolakata.dev.seed import PASSWORD

        p = make_person(s, name.title(), "female")
        u = User(
            id=ids.new_id("User"),
            personId=p.id,
            username=name,
            displayName=name.title(),
            email=f"{name}@griffin.home",
            active=active,
            passwordHash=passwords.hash_password(PASSWORD),
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
    carols = Account(id=ids.new_id("Acct"), ownerId=carol.id, name="Carol's", type="checking")
    s.add(carols)
    share("account", shared.id, "read", user=carol)

    dave = user("dave")
    helpers = group("Helpers", True, dave)
    former = group("Former helpers", False, dave)
    book = alices(TaxBook)
    budget = alices(Budget)
    share("tax-book", book.id, "read", grp=helpers)
    share("budget", budget.id, "write", grp=former)

    erin = user("erin")
    invitation = TaxBookFiler(bookId=book.id, userId=erin.id, createdAt=now)
    s.add(invitation)

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
    links = {}
    for name, kind, item in (
        ("shared link", "transaction", txn(shared).id),
        ("unshared link", "transaction", txn(unshared).id),
        ("gift link", "gift", surprise.id),
    ):
        ln = ReceiptLink(receiptId=receipt.id, kind=kind, itemId=item, linkedById=alice.id)
        s.add(ln)
        links[name] = ln.id

    # The rows joining two transactions, one on each side of the share (1e).
    # A trade in an account of hers no one else reads, as a wash sale's sale and a transfer's
    # side are; and the joint account's first transaction.
    unshared_ids = [
        a.id for a in accounts if not s.scalars(select(Share).where(Share.itemId == a.id)).first()
    ]
    mine = s.scalars(
        select(Transaction)
        .where(
            Transaction.accountId.in_(unshared_ids),
            Transaction.instrumentId.is_not(None),
            Transaction.quantity.is_not(None),
            Transaction.deleted.is_(False),
        )
        .order_by(Transaction.id)
    ).first()
    ours = txn(shared)
    reimbursement = Reimbursement(
        id=ids.new_id("Rmbrs"), spendingId=mine.id, paybackId=ours.id, amount=Decimal("1.00")
    )
    match = TransferMatch(id=ids.new_id("XfrMt"), ownerId=alice.id, outId=mine.id, inId=ours.id)
    wash = WashSale(
        id=ids.new_id("WashS"),
        ownerId=alice.id,
        saleId=mine.id,
        replacementId=ours.id,
        quantity=Decimal(1),
        disallowed=Decimal("1.00"),
        heldFrom=mine.date,
        createdAt=now,
    )
    s.add_all([reimbursement, match, wash])

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
    admin = s.scalars(select(User).where(User.username == "admin")).one()
    return {
        **links,
        "shared": shared.id,
        "carols": carols.id,
        "erins invitation": invitation.id,
        "reimbursement": reimbursement.id,
        "match": match.id,
        "wash": wash.id,
        "bobs person": bob.personId,
        "admin": admin.id,
        "former": former.id,
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


# ---- Who holds what, written out (decision 7.2: the parity test's household, kept) ----

R, W, D, S, C = "read", "writable", "deletable", "shareable", "configurable"
EVERY = (W, D, S, C)

# (table, record, user, what they hold: None when they don't read it).
HOLDS = [
    ("Account", "unshared", "alice", EVERY),
    ("Account", "unshared", "bob", None),
    ("Account", "shared", "bob", (R,)),  # through the Household group
    ("Account", "shared", "carol", None),  # inactive (4.1)
    ("Account", "shared", "tom", (R,)),  # a linked server's user reads, never more (4.3)
    ("Account", "carols", "carol", None),  # an inactive user holds nothing, not even theirs
    ("TaxBook", "book", "alice", EVERY),
    ("TaxBook", "book", "dave", (R,)),  # an active group's share
    ("TaxBook", "book", "erin", None),  # a filer who hasn't accepted
    ("TaxBookFiler", "erins invitation", "erin", (W,)),  # answered before accepting
    ("Budget", "budget", "dave", None),  # an inactive group's share gives nothing
    ("GiftPlan", "plan", "bob", (R,)),
    ("Gift", "gift", "alice", (W, D)),
    ("Gift", "gift", "bob", None),  # the person it is for (1d.3)
    ("Receipt", "receipt", "alice", (W, D)),
    ("Receipt", "receipt", "bob", (R,)),  # through the shared account
    ("Receipt", "receipt", "tom", None),  # without Include receipts (4.4)
    ("Receipt", "receipt", "ann", (R,)),  # with it
    ("ReceiptLink", "shared link", "bob", (R,)),
    ("ReceiptLink", "unshared link", "bob", None),  # CR3-47: never the other account's
    ("ReceiptLink", "gift link", "bob", None),
    ("ReceiptLink", "unshared link", "alice", (W, D)),
    ("Reimbursement", "reimbursement", "alice", (W, D)),
    ("Reimbursement", "reimbursement", "bob", (R,)),  # from the side he reads (1e.3)
    ("TransferMatch", "match", "alice", (W, D)),
    ("TransferMatch", "match", "bob", None),  # its owner's alone (1e.4)
    ("WashSale", "wash", "alice", (R,)),  # a cache: read with its sale, never changed
    ("WashSale", "wash", "bob", None),
    ("Person", "bobs person", "erin", (R,)),  # every local user, as he is not private
    ("Person", "bobs person", "bob", EVERY),
    ("Person", "bobs person", "admin", EVERY),  # admins hold every person (1b.3)
    ("User", "carol", "admin", (W, D)),  # admins read inactive users too
    ("User", "carol", "bob", None),
    ("User", "tom", "tom", (R,)),  # one's own row; changed only by a local user
    ("Group", "former", "dave", None),  # an inactive group
    ("Group", "former", "admin", (W, D)),
]


def test_who_holds_what(household):
    """Each rule as the decisions say, on the household built to reach them."""
    srv, n = household
    wrong = []
    with srv.db.read(unscoped="test") as s:
        for table, record, user, want in HOLDS:
            row = rows(s, table).get((n[record], n[user]))
            got = (
                None
                if row is None
                else (R, *(p for p, x in zip((W, D, S, C), row, strict=True) if x))
            )
            expected = None if want is None else tuple(dict.fromkeys((R, *want)))
            if got != expected:
                wrong.append((table, record, user, expected, got))
    assert not wrong, wrong


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


# ---- The write check at flush (decision 5.4) ----


def test_a_users_session_writes_only_what_their_views_allow(household):
    """Past the routes: a change needs writable, a setting configurable, a delete deletable,
    a new record writable on itself; each refusal undoes the whole transaction."""
    from moolakata.errors import Problem
    from moolakata.store.entities.accounts import Account, Transaction

    srv, n = household

    def first(s, name):
        a = s.scalars(select(Account).where(Account.name == name)).one()
        t = s.scalars(
            select(Transaction).where(Transaction.accountId == a.id).order_by(Transaction.id)
        ).first()
        return a, t

    def refused(change):
        with pytest.raises(Problem) as e, srv.db.tx(user=n["bob"]) as s:
            change(s)
        assert e.value.status == 403 and e.value.code == "write-refused"

    # Everyday checking: read through the Household group; Emergency savings: write.
    refused(lambda s: setattr(first(s, "Everyday checking")[1], "memo", "mine now"))
    refused(lambda s: setattr(first(s, "Emergency savings")[0], "name", "renamed"))
    refused(lambda s: first(s, "Emergency savings")[0].mark_deleted(n["bob"]))

    def add_to_read_only(s):
        a, t = first(s, "Everyday checking")
        s.add(Transaction(id=ids.new_id("Txn"), accountId=a.id, date=t.date, kind=t.kind,
                          amount=t.amount))  # fmt: skip

    refused(add_to_read_only)
    with srv.db.tx(user=n["bob"]) as s:
        _, t = first(s, "Emergency savings")
        was, t.memo = t.memo, "allowed"
    with srv.db.tx(user=n["bob"]) as s:
        first(s, "Emergency savings")[1].memo = was
