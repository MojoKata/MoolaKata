"""A self-custody wallet's keys and addresses (requirements S1.6.1, S1.6.3): public data only.
The form's text is checked for anything that looks like a private key or seed phrase before
anything else, and a refusal never repeats or logs it."""

import datetime as dt

from fastapi import APIRouter, Depends, Request

from .. import access, activity
from ..bitcoin import keys as bk
from ..bitcoin import wallet
from ..errors import Problem, refuse
from ..store.entities.accounts import WalletKey
from .conventions import ExactRoute, Model, if_match, version_of
from .deps import Caller, caller, server
from .prices import apply_egress

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["wallets"])
SHOWN = 10  # unused addresses shown a chain


class WalletKeyOut(Model):
    id: str
    kind: str  # xpub or address
    value: str
    script: str
    gapLimit: int
    addresses: int
    used: int


class WalletAddressOut(Model):
    address: str
    keyId: str
    chain: int | None  # 0 receive, 1 change, null typed
    index: int | None
    used: bool
    txCount: int
    balanceSats: int
    checkedAt: dt.datetime | None


class WalletView(Model):
    keys: list[WalletKeyOut]
    addresses: list[WalletAddressOut]
    watched: int  # every address watched
    used: int
    balanceSats: int
    checkedAt: dt.datetime | None
    version: int  # its keys together


MAX_TEXT = 200_000  # characters: well over a thousand addresses
MAX_ENTRIES = 1000  # keys, descriptors and addresses


def _wallet_account(s, c: Caller, account_id: str, level: str):
    a, lv = access.account(s, c.id, account_id, level)
    if a.type != "crypto-wallet":
        raise refuse(None, "not-a-wallet", "Only a self-custody wallet holds keys and addresses.")
    return a, lv


def _held_sats(s, account_id: str) -> int:
    """What the wallet holds, from its ledger, in whole sats (S1.6.4)."""
    from sqlalchemy import select

    from ..store.entities.accounts import Account, Instrument
    from ..store.repos import ledger as repo

    btc = s.scalars(
        select(Instrument.id).where(
            Instrument.symbol == "BTC", Instrument.instrumentClass == "crypto"
        )
    ).first()
    if btc is None:
        return 0
    qty = repo.load(s, s.get(Account, account_id)).replay().quantity(btc)
    return int(qty * 100_000_000)


def _view(s, account_id: str) -> WalletView:
    keys = wallet.keys_of(s, account_id)
    rows = wallet.addresses_of(s, account_id)
    shown = []
    for k in keys:
        mine = [r for r in rows if r.keyId == k.id]
        for chain in (None, 0, 1):
            on = [r for r in mine if r.chain == chain]
            last = max((r.idx for r in on if r.used and r.idx is not None), default=-1)
            shown += [r for r in on if r.used or r.chain is None or (r.idx or 0) <= last + SHOWN]
    return WalletView(
        version=version_of(s, WalletKey, WalletKey.accountId == account_id),
        keys=[
            WalletKeyOut(
                id=k.id,
                kind=k.kind,
                value=k.value,
                script=k.script,
                gapLimit=k.gapLimit,
                addresses=sum(1 for r in rows if r.keyId == k.id),
                used=sum(1 for r in rows if r.keyId == k.id and r.used),
            )
            for k in keys
        ],
        addresses=[
            WalletAddressOut(
                address=r.address,
                keyId=r.keyId,
                chain=r.chain,
                index=r.idx,
                used=r.used,
                txCount=r.txCount,
                balanceSats=r.balanceSats,
                checkedAt=r.checkedAt,
            )
            for r in shown
        ],
        watched=len(rows),
        used=sum(1 for r in rows if r.used),
        balanceSats=_held_sats(s, account_id),
        checkedAt=max((r.checkedAt for r in rows if r.checkedAt), default=None),
    )


@router.get("/accounts/{account_id}/wallet", response_model=WalletView)
def get_wallet(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        _wallet_account(s, c, account_id, "read")
        return _view(s, account_id)


def checked(text: str, gap_limit: int) -> list:
    """The keys and addresses typed for a wallet, refused at once when anything looks like a
    private key or seed phrase; the refusal never repeats it."""
    if len(text) > MAX_TEXT:
        raise refuse("walletKeys", "too-long", "At most 200,000 characters of keys and addresses.")
    what = bk.secret_kind(text)
    if what:
        raise refuse("walletKeys", "secret-refused", bk.REFUSAL.format(what=what))
    try:
        entries = bk.parse(text)
    except bk.Refused as e:
        raise refuse("walletKeys", e.code, e.message) from None
    if len(entries) > MAX_ENTRIES:
        raise refuse(
            "walletKeys", "too-many", f"At most {MAX_ENTRIES:,} keys and addresses a wallet."
        )
    if not 1 <= gap_limit <= 200:
        raise refuse("gapLimit", "gap-invalid", "From 1 to 200 unused addresses: 20 is usual.")
    return entries


def replace(ctx, a, text: str | None, gap_limit: int) -> None:
    """A wallet's keys and addresses, replaced whole as its account's draft saves them."""
    if a.type != "crypto-wallet":
        raise refuse(
            "walletKeys", "not-a-wallet", "Only a self-custody wallet holds keys and addresses."
        )
    entries = checked(text or "", gap_limit)
    wallet.replace(ctx.s, a.id, entries, gap_limit, ctx.caller.id)
    activity.record(ctx.s, "wallet.changed", actor=ctx.caller.id, subject_kind="account",
                    subject_id=a.id, owner=a.ownerId)  # fmt: skip
    srv = server(ctx.request)
    ctx.after("egress", lambda: apply_egress(srv))


def current(s, a) -> dict:
    """The wallet's keys, one a line, and its gap limit, as its account's draft holds them."""
    keys = wallet.keys_of(s, a.id) if a.type == "crypto-wallet" else []
    return {"walletKeys": "\n".join(k.value for k in keys) or None,
            "gapLimit": keys[0].gapLimit if keys else 20}  # fmt: skip


class SyncOut(Model):
    recorded: int  # transactions added
    wallet: WalletView


@router.post("/accounts/{account_id}/wallet/sync", response_model=SyncOut)
def sync_wallet(account_id: str, request: Request, c: Caller = Depends(caller)):
    """Read the wallet from the explorer or node now (S1.6.2)."""
    from ..bitcoin import sync
    from ..bitcoin.sources import SourceError

    srv = server(request)
    with srv.db.read(user=c.id) as s:
        a, _ = _wallet_account(s, c, account_id, "write")
        if not sync.chosen(srv, s):
            raise refuse(
                None,
                "bitcoin-not-set",
                "No wallet is read until an admin saves Settings › Bitcoin.",
                409,
            )
    try:
        made = sync.sync_account(srv, a.id)
    except SourceError as e:
        raise Problem(502, "source-failed", str(e)) from None
    with srv.db.read(user=c.id) as s:
        return SyncOut(recorded=made, wallet=_view(s, a.id))


# ---- Bitcoin moved between the owner's accounts (S1.7.1) ----


class TransferPair(Model):
    id: str
    fromAccount: str
    toAccount: str
    fromDate: dt.date
    toDate: dt.date
    sats: int
    version: int


@router.get("/transfers/bitcoin", response_model=list[TransferPair])
def bitcoin_transfers(request: Request, c: Caller = Depends(caller)):
    """The pairs proposed for the caller's own accounts, to confirm or reject."""
    from ..bitcoin import transfers as btcmatch

    with server(request).db.read(user=c.id) as s:
        return [TransferPair(**btcmatch.describe(s, m)) for m in btcmatch.pending(s, c.id)]


class TransferAnswer(Model):
    confirm: bool


@router.post("/transfers/bitcoin/{match_id}", response_model=list[TransferPair])
def answer_transfer(
    match_id: str,
    body: TransferAnswer,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    """Confirmed, the coins arrive with the lots they left with; rejected, the pair isn't
    proposed again."""
    from .. import washes
    from ..bitcoin import transfers as btcmatch
    from ..store.entities.accounts import TransferMatch
    from .conventions import check

    with server(request).db.tx(user=c.id) as s:
        m = s.get(TransferMatch, match_id)
        if m is None or m.deleted or m.ownerId != c.id or m.state != "proposed":
            raise Problem(404, "not-found", "Not found")
        check(m, version, {"id": m.id, "version": m.version})
        if body.confirm:
            btcmatch.confirm(s, c.id, m)
            washes.recompute(s, c.id)
        else:
            btcmatch.reject(s, m)
        s.flush()
        return [TransferPair(**btcmatch.describe(s, x)) for x in btcmatch.pending(s, c.id)]
