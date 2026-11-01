"""What this server sends a linked server (requirements S11.3, S11.4, S11.5): each item shared
with that server's people, worked out here as each of them would see it, with the code its own
screens use, and only what changed since the last exchange.

An item travels as its row in its list (path "") and the documents its screens read, each the
answer this server's API gives the person it names, kept by path. The receiving server shows
these and never works anything out again (S11.3.1)."""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import delete, false, select

from .. import clock, exactjson
from ..errors import Problem
from ..store.entities.links import Link, LinkSent
from ..store.entities.sharing import Share
from ..store.entities.users import User
from . import changes, keys

# The eight shareable kinds (S10.3), each of which may go to named people on a linked server.
KINDS = (
    "account",
    "portfolio",
    "budget",
    "gift-plan",
    "giving-plan",
    "tax-book",
    "projection",
    "person",
)


@dataclass
class Item:
    id: str
    kind: str
    name: str
    ownerName: str
    sharedAt: str
    viewers: set[str] = field(default_factory=set)  # the peer's user ids
    includeReceipts: bool = False


def _req(srv):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(server=srv)))


def _dump(x):
    if isinstance(x, list):
        return [_dump(i) for i in x]
    if isinstance(x, dict):
        return {k: _dump(v) for k, v in x.items()}
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


def _document(x):
    """A route's answer as the linked window reads it: a list as every list answers, a page
    (S13.8.5), since the route was called directly rather than through its paging."""
    from ..ui.conventions import everything

    out = _dump(x)
    return everything().page(out) if isinstance(out, list) else out


def shared_items(srv, link_id: str) -> tuple[dict[str, Item], dict[str, User]]:
    """The items shared with this link's people, and those people (here, remote users)."""
    from .. import sharing
    from ..store.entities.education import GiftPlan

    with srv.db.read(unscoped="links.serve: shared items") as s:
        people = {
            u.id: u
            for u in s.scalars(
                select(User).where(User.linkId == link_id, User.deleted == false(), User.active)
            )
        }
        out: dict[str, Item] = {}
        if not people:
            return out, people
        for g in s.scalars(
            select(Share).where(
                Share.userId.in_(list(people)), Share.deleted == false(), Share.level == "read"
            )
        ):
            try:
                obj = sharing.item(s, g.kind, g.itemId)
            except Problem:
                continue
            if getattr(obj, "deleted", False):
                continue
            if g.kind not in KINDS:
                continue
            # Gifts for a user of that server never cross (S7.8.5).
            if isinstance(obj, GiftPlan) and obj.personId in {u.personId for u in people.values()}:
                continue
            name = getattr(obj, "name", None) or str(getattr(obj, "year", ""))
            if isinstance(obj, GiftPlan):
                from ..store.entities.education import Person

                name = s.get(Person, obj.personId).name
            owner = s.get(User, obj.ownerId) if obj.ownerId else None
            it = out.setdefault(
                g.itemId,
                Item(
                    g.itemId,
                    g.kind,
                    name,
                    owner.displayName if owner else "?",
                    g.createdAt.isoformat(),
                ),
            )
            it.viewers.add(people[g.userId].remoteId)
            it.includeReceipts = it.includeReceipts or g.includeReceipts
        return out, people


def _paths(srv, it: Item) -> list[tuple[str, callable]]:
    """Each document an item's screens read: its API path and how this server answers it."""
    from ..ui import accounts, budgets, gifts, giving, portfolios, projections, taxes, taxpanels
    from ..ui import transactions as txns
    from ..ui.conventions import Paging

    r, i = _req(srv), it.id
    if it.kind == "account":
        out = [
            (f"/accounts/{i}", lambda c: accounts.get_account(i, r, c)),
            (f"/accounts/{i}/series?range=All", lambda c: accounts.account_series(i, r, c, "All")),
            (f"/accounts/{i}/holdings", lambda c: accounts.account_holdings(i, r, c)),
            (
                f"/transactions?account={i}",
                # The whole history: a long one travels in parts by date (S11.4).
                lambda c: txns.list_transactions(
                    r,
                    c,
                    Paging(offset=0, limit=ALL),
                    [i],
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "-date",
                ),
            ),
        ]
        return out
    if it.kind == "portfolio":
        return [
            (f"/portfolios/{i}", lambda c: portfolios.get_portfolio(i, r, c)),
            (f"/portfolios/{i}/holdings", lambda c: portfolios.portfolio_holdings(i, r, c)),
            (f"/portfolios/{i}/returns", lambda c: portfolios.portfolio_returns(i, r, c)),
            (
                f"/portfolios/{i}/series?range=All",
                lambda c: portfolios.portfolio_series(i, r, c, "value", "All"),
            ),
        ]
    if it.kind == "budget":
        return [
            (f"/budgets/{i}/month", lambda c: budgets.budget_month(i, r, c, None)),
            (f"/budgets/{i}/trends", lambda c: budgets.budget_trends(i, r, c, None, None, 12)),
            (f"/budgets/{i}/cash-flow", lambda c: budgets.budget_cash_flow(i, r, c, None)),
            (f"/budgets/{i}/recurring", lambda c: budgets.budget_recurring(i, r, c)),
        ]
    if it.kind == "tax-book":
        return [
            (f"/tax-books/{i}", lambda c: taxes.get_book(i, r, c)),
            (f"/tax-books/{i}/panels", lambda c: taxpanels.get_panels(i, r, c)),
        ]
    if it.kind == "projection":
        return [(f"/projections/{i}", lambda c: projections.get_projection(i, r, c))]
    if it.kind == "giving-plan":
        year = int(it.name) if it.name.isdigit() else None
        return [
            (f"/giving?year={year}", lambda c: giving.get_giving(r, year, c)),
            (f"/giving/donations?year={year}", lambda c: giving.list_donations(r, year, c)),
        ]
    if it.kind == "person":
        # A private person: their name and birthday (the row) and their relationships, to
        # those the viewer may see (S10.3, S10.10.2).
        from ..ui import people as people_ui

        return [(f"/persons/{i}/relations", lambda c: people_ui.person_relations(i, r, None, c))]
    if it.kind == "gift-plan":
        from ..store.entities.education import GiftPlan

        with srv.db.read(unscoped="links.serve: paths") as s:
            person = s.get(GiftPlan, i).personId
        return [(f"/gifts?person={i}", lambda c: gifts.list_gifts(r, None, person, c))]
    return []


ROWS = {
    "account": "/accounts",
    "portfolio": "/portfolios",
    "budget": "/budgets",
    "tax-book": "/tax-books",
    "projection": "/projections",
    "gift-plan": "/people",
    "person": "/persons",
}


def _rows(srv, kind: str, c) -> dict[str, dict]:
    from ..ui import accounts, budgets, gifts, portfolios, projections, taxes
    from ..ui import people as people_ui

    r = _req(srv)
    fn = {
        "account": lambda: accounts.list_accounts(r, c),
        "portfolio": lambda: portfolios.list_portfolios(r, c),
        "budget": lambda: budgets.list_budgets(r, c),
        "tax-book": lambda: taxes.list_books(r, c),
        "projection": lambda: projections.list_projections(r, c),
        "gift-plan": lambda: gifts.list_people(r, c),
        "person": lambda: people_ui.list_persons(r, c),
    }.get(kind)
    if fn is None:
        return {}
    key = "planId" if kind == "gift-plan" else "id"
    return {row[key]: row for row in _dump(fn()) if isinstance(row, dict) and key in row}


def work_out(srv, link_id: str) -> tuple[dict[str, Item], dict[tuple[str, str, str], object]]:
    """Every item and document this link's people should have, as they would see it here."""
    from ..ui.deps import Caller

    items, people = shared_items(srv, link_id)
    docs: dict[tuple[str, str, str], object] = {}
    by_viewer: dict[str, list[Item]] = defaultdict(list)
    for it in items.values():
        for v in it.viewers:
            by_viewer[v].append(it)
    remote = {u.remoteId: u for u in people.values()}
    for viewer, its in by_viewer.items():
        c = Caller(remote[viewer], None, False)
        rows: dict[str, dict[str, dict]] = {}
        for it in its:
            if it.kind not in rows:
                try:
                    rows[it.kind] = _rows(srv, it.kind, c)
                except Problem:
                    rows[it.kind] = {}
            if it.id in rows[it.kind]:
                docs[(it.id, "", viewer)] = rows[it.kind][it.id]
            for path, fn in _paths(srv, it):
                try:
                    doc = _document(fn(c))
                except Problem:
                    continue  # this person can't read this part: it isn't sent
                if it.kind == "gift-plan" and not it.includeReceipts:
                    doc = _without_documents(doc)
                docs[(it.id, path, viewer)] = doc
    for it in items.values():
        if it.kind == "account" and it.includeReceipts:
            for f in receipt_files(srv, it.id):
                docs[(it.id, f"file:{f['id']}", "")] = f
    return items, docs


def _without_documents(doc):
    """A gift's documents (their names, notes and links) stay home without Include receipts
    (S11.5.1)."""
    if isinstance(doc, dict) and isinstance(doc.get("items"), list):
        return {**doc, "items": [{**g, "documents": []} for g in doc["items"]]}
    return doc


def receipt_files(srv, account_id: str) -> list[dict]:
    """An account's receipts as they cross (S11.5.1): their dates, amounts, payees and the text
    read from them, with the length and hash of the file, which is fetched on its own."""
    import base64

    from sqlalchemy import or_

    from ..store.entities.accounts import Transaction
    from ..store.entities.receipts import Receipt, ReceiptLink

    with srv.db.read(unscoped="links.serve: receipt files") as s:
        txns = list(
            s.scalars(
                select(Transaction.id).where(
                    Transaction.accountId == account_id, Transaction.deleted == false()
                )
            )
        )
        links = s.scalars(
            select(ReceiptLink).where(
                ReceiptLink.deleted == false(),
                or_(
                    (ReceiptLink.kind == "transaction") & ReceiptLink.itemId.in_(txns),
                    (ReceiptLink.kind == "account") & (ReceiptLink.itemId == account_id),
                ),
            )
        ).all()
        out = {}
        for ln in links:
            r = s.get(Receipt, ln.receiptId)
            # A file the source prunes leaves the copy at its next pull (S14.10.6).
            if r is None or r.deleted or r.filePrunedAt is not None or r.id in out:
                continue
            out[r.id] = {
                "id": r.id,
                "itemId": account_id,
                "contentType": r.mediaType,
                "length": r.size,
                "sha256": r.sha256,
                "thumbnail": (
                    "data:image/jpeg;base64," + base64.b64encode(r.thumbnail).decode()
                    if r.thumbnail
                    else None
                ),
                "meta": {
                    "date": r.date.isoformat() if r.date else None,
                    "amount": str(r.amount) if r.amount is not None else None,
                    "payee": r.payee,
                    "text": r.text,
                    "transactionId": ln.itemId if ln.kind == "transaction" else None,
                },
            }
        return list(out.values())


def allowed_file(srv, link_id: str, receipt_id: str) -> bool:
    """Whether this link's people may have this receipt: one of an account shared with them
    with Include receipts ticked."""
    items, _ = shared_items(srv, link_id)
    return any(
        it.kind == "account"
        and it.includeReceipts
        and any(f["id"] == receipt_id for f in receipt_files(srv, it.id))
        for it in items.values()
    )


def _hash(body) -> str:
    return hashlib.sha256(
        exactjson.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def change_for(srv, link_id: str, have: int, full: bool) -> list[dict]:
    """The signed changes that bring the peer from its `have` up to now: everything when it
    asks, or when its sequence isn't the one last sent; else only what changed. Empty when
    nothing has; more than one when it is large, oldest first (S11.4)."""
    items, docs = work_out(srv, link_id)
    with srv.db.tx(unscoped="links.serve: change for") as s:
        link = s.get(Link, link_id)
        full = full or have != link.sentSeq
        sent = {
            (r.itemId, r.path, r.viewer): r.hash
            for r in s.scalars(select(LinkSent).where(LinkSent.linkId == link_id))
        }
        if full:
            sent = {}
        hashes = {k: _hash(v) for k, v in docs.items()}
        sent_items = {k[0] for k in sent}
        change: dict = {"asOf": clock.now().isoformat(), "full": full}
        changed_all = [k for k, h in hashes.items() if sent.get(k) != h]
        gone_all = [k for k in sent if k not in hashes and k[0] in items]
        is_file = lambda k: k[1].startswith("file:")  # noqa: E731
        changed_docs = [k for k in changed_all if not is_file(k)]
        gone_docs = [k for k in gone_all if not is_file(k)]
        changed_files = [k for k in changed_all if is_file(k)]
        gone_files = [k for k in gone_all if is_file(k)]
        gone_items = sorted(sent_items - set(items))
        touched = {k[0] for k in changed_all} | {k[0] for k in gone_all}
        new_items = [i for i in items if i not in sent_items]
        item_rows = [items[i] for i in sorted(set(new_items) | touched) if i in items]
        if not full and not changed_all and not gone_all and not gone_items and not item_rows:
            return []
        change["items"] = [
            {
                "id": it.id,
                "kind": it.kind,
                "name": it.name,
                "ownerName": it.ownerName,
                "sharedAt": it.sharedAt,
                "viewers": sorted(it.viewers),
                "includeReceipts": it.includeReceipts,
                "version": link.sentSeq + 1,
            }
            for it in (items.values() if full else item_rows)
        ]
        change["removed"] = gone_items
        change["docs"] = [
            {"itemId": k[0], "path": k[1], "viewer": k[2], "body": docs[k]}
            for k in (docs if full else changed_docs)
            if not is_file(k)
        ]
        change["files"] = [docs[k] for k in (docs if full else changed_files) if is_file(k)]
        change["filesRemoved"] = [k[1][5:] for k in gone_files]
        change["docsRemoved"] = [{"itemId": k[0], "path": k[1], "viewer": k[2]} for k in gone_docs]
        parts = split(change)
        for part in parts:
            link.sentSeq += 1
            part["seq"] = link.sentSeq
        s.execute(delete(LinkSent).where(LinkSent.linkId == link_id))
        for (item_id, path, viewer), h in hashes.items():
            s.add(LinkSent(linkId=link_id, itemId=item_id, path=path, viewer=viewer, hash=h))
        own = keys.private_key(s, srv.keys.secrets)
        # Sealed to the peer's copy key, so only its copy reads what it holds (S11.9.6); with
        # no copy key yet, only the registry travels.
        copy_key = keys.unb64(link.peerCopyKey) if link.peerCopyKey else None
        way = keys.direction(
            keys.fingerprint(keys.raw_public(own.public_key())),
            keys.fingerprint(keys.unb64(link.peerKey)),
        )
    return [changes.sign(own, changes.seal_part(part, copy_key, way)) for part in parts]


def sealed_receipt(srv, link_id: str, receipt_id: str):
    """One receipt sealed to the peer's copy key, written aside so its sealed bytes can be
    hashed and signed before they are sent; the caller removes the file once it is sent. The
    receipt is read through this server's own decryption and is never on disk in the clear.
    Returns the path and the sealed bytes' SHA-256."""
    import secrets

    from .. import receipts
    from ..store.entities.receipts import Receipt
    from . import sealed

    with srv.db.read(unscoped="links.serve: sealed receipt") as s:
        link = s.get(Link, link_id)
        r = s.get(Receipt, receipt_id)
        own = keys.public_of(s, srv.keys.secrets)
        copy_key = keys.unb64(link.peerCopyKey) if link.peerCopyKey else None
        peer = keys.unb64(link.peerKey)
    if copy_key is None or r is None:
        raise changes.ChangeError("the peer's copy has no access key yet")
    out = srv.config.data_dir / "links-out"
    out.mkdir(mode=0o700, exist_ok=True)
    path = out / (secrets.token_hex(12) + ".mkr")
    way = keys.direction(keys.fingerprint(own), keys.fingerprint(peer))
    sealed.write(
        path, sealed.seal(copy_key, sealed.RECEIPT, way, receipt_id, receipts.read_file(srv, r))
    )
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return path, h.hexdigest()


def stream_file(path):
    """A sealed file's bytes, then the file gone."""
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 16):
                yield chunk
    finally:
        path.unlink(missing_ok=True)


PART_BYTES = 4 * 1024 * 1024  # a change larger than this travels in parts
ALL = 10**9  # every record of a list document
DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})")


def _newest(entry) -> str:
    """The newest date an entry holds, for sending the oldest first."""
    found = DAY.findall(exactjson.dumps(entry))
    return max(found) if found else ""


def _size(entry) -> int:
    return len(exactjson.dumps(entry))


def _records(doc: dict) -> list[dict]:
    """A long list document (an account's transactions, newest first) as pieces of whole
    records up to a date, oldest first: the first replaces the document, each after it adds
    its records ahead of those before (`append`). Any other document is one piece."""
    body = doc.get("body")
    rows = body.get("items") if isinstance(body, dict) else None
    if not isinstance(rows, list) or _size(doc) <= PART_BYTES // 4:
        return [doc]
    pieces: list[list] = []
    end = len(rows)
    while end > 0:
        start, size = end, 0
        while start > 0 and (size < PART_BYTES // 4 or start == end):
            start -= 1
            size += _size(rows[start])
        # Whole records up to a date: one day's records stay in one piece.
        while start > 0 and _newest(rows[start - 1]) == _newest(rows[start]):
            start -= 1
        pieces.append(rows[start:end])
        end = start
    return [
        {**doc, "body": {**body, "items": rows_}, **({"append": True} if i else {})}
        for i, rows_ in enumerate(pieces)
    ]


def split(change: dict) -> list[dict]:
    """A large change as parts that travel oldest to newest (S11.4): the first carries the
    items and what was removed, then the documents and files, each by the newest date it
    holds, a long document in pieces of whole records up to a date, so the copy fills from
    its earliest records and is usable up to a date while the rest arrives. Each part says
    how far it reaches and how much of the whole has come."""
    entries = [("docs", d) for d in change.get("docs") or []] + [
        ("files", f) for f in change.get("files") or []
    ]
    total = sum(_size(e) for _, e in entries) or 1
    if total <= PART_BYTES:
        return [change]
    entries = [("docs", p) for kind, d in entries if kind == "docs" for p in _records(d)] + [
        (kind, f) for kind, f in entries if kind == "files"
    ]
    total = sum(_size(e) for _, e in entries)
    # Stable: a document's pieces keep their order where their dates tie with another's.
    entries.sort(key=lambda e: _newest(e[1]))
    head = {k: v for k, v in change.items() if k not in ("docs", "files")}
    parts: list[dict] = []
    cur: dict = {**head, "docs": [], "files": []}
    size = sent = 0
    through = ""
    for kind, e in entries:
        n = _size(e)
        if (cur["docs"] or cur["files"]) and size + n > PART_BYTES:
            cur["progress"] = {"through": through or None, "bytes": sent, "total": total}
            parts.append(cur)
            cur = {
                "asOf": change["asOf"],
                "full": False,
                "items": [],
                "removed": [],
                "docsRemoved": [],
                "filesRemoved": [],
                "docs": [],
                "files": [],
            }
            size = 0
        cur[kind].append(e)
        size += n
        sent += n
        through = max(through, _newest(e))
    cur["progress"] = {"through": through or None, "bytes": sent, "total": total}
    parts.append(cur)
    return parts
