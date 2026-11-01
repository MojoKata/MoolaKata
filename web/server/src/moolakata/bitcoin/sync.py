"""Keeping wallets current (requirements S1.6.2): every hour, and when asked, each wallet's
addresses are read from the explorer or node; the addresses found used extend the derivation
to keep the gap limit; and each transaction with 6 confirmations is recorded once (by its txid)
as bitcoin received (a transfer in, its basis to be entered) or sent (a transfer out, with its
network fee as a sale of its own). A recorded one that leaves the chain is marked, never
deleted. Nothing is sent to the explorer or node but the addresses or the public keys."""

import datetime as dt
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import false, select

from .. import clock, ids, settings, timezones
from ..store.entities.accounts import Account, Instrument, Transaction, WalletAddress
from ..store.entities.prices import Price
from ..store.repos import ledger as repo
from ..store.repos import secrets as secret_repo
from . import sources, wallet
from .sources import SAT, Config, SourceError

log = logging.getLogger("moolakata.bitcoin")
PASSWORD = ("Setting", "bitcoin", "password")
ROUNDS = 10  # derivation rounds a sync extends the gap by, at most


def config(s, secrets_key: bytes | None) -> Config:
    get = lambda k: settings.get(s, k)  # noqa: E731
    pw = secret_repo.use(s, secrets_key, *PASSWORD) if secrets_key else None
    return Config(
        kind=get("bitcoinSource"),
        esploraUrl=get("bitcoinEsploraUrl") or sources.DEFAULT_ESPLORA,
        host=get("bitcoinNodeHost"),
        port=get("bitcoinNodePort"),
        tls=get("bitcoinNodeTls"),
        rpcUser=get("bitcoinRpcUser"),
        password=pw,
        certSha256=get("bitcoinNodeCert"),
    )


def chosen(server, s) -> bool:
    """Whether wallets may be read: no wallet is read until an admin saves Settings › Bitcoin,
    so nothing is asked of a public explorer before then (S16.7, R3.5). Dev mode's stub
    source too waits for it; a seeded dev server saves the stub (S17.7)."""
    return settings.saved(s, "bitcoinSource")


def source(server, s):
    """With dev mode's stubs, nothing outside is read: the stub answers whatever is saved."""
    if server.config.stubs:
        from .stub import Stub

        return Stub()
    cfg = config(s, server.keys.secrets)
    if cfg.kind == "stub":
        raise SourceError("The stub source is dev mode's: choose an explorer or a node.")
    return sources.make(cfg, server.guard)


def hosts(s) -> tuple[list[str], list[str]]:
    """The explorer's or node's host, for the egress guard, once a wallet exists."""
    has_wallet = s.scalars(
        select(Account.id).where(Account.type == "crypto-wallet", Account.deleted == false())
    ).first()
    return config(s, None).hosts() if has_wallet else ([], [])


def _scan(src, account_id: str, s) -> tuple[list[sources.Tx], set[str]]:
    rows = wallet.addresses_of(s, account_id)
    if isinstance(src, sources.Core):
        wanted = []
        for k in wallet.keys_of(s, account_id):
            top = max((r.idx for r in rows if r.keyId == k.id and r.idx is not None), default=None)
            wanted += sources.descriptors(k, top)
        name = f"moolakata-{account_id}"
        src.wallet(name, wanted)
        txs, used = src.history_of(name)
        return txs, used | {a for t in txs for a in t.addresses}
    txs = src.history([r.address for r in rows])
    return txs, {a for t in txs for a in t.addresses}


def sync_account(server, account_id: str) -> int:
    """Read one wallet now; returns the transactions recorded. Raises SourceError."""
    with server.db.read(unscoped="bitcoin.sync: sync account") as s:
        if not chosen(server, s):
            raise SourceError("no wallet is read until an admin saves Settings › Bitcoin")
        src = source(server, s)
    txs: dict[str, sources.Tx] = {}
    for _ in range(ROUNDS):
        with server.db.read(unscoped="bitcoin.sync: sync account") as s:
            found, used = _scan(src, account_id, s)
        txs.update({t.txid: t for t in found})
        with server.db.tx(unscoped="bitcoin.sync: sync account") as s:
            now = clock.now()
            counts: dict[str, int] = {}
            for t in txs.values():
                for a in t.addresses:
                    counts[a] = counts.get(a, 0) + 1
            for r in s.scalars(select(WalletAddress).where(WalletAddress.accountId == account_id)):
                r.used = r.used or r.address in used
                r.txCount = counts.get(r.address, 0)
                r.checkedAt = now
            s.flush()
            added = sum(wallet.extend(s, k) for k in wallet.keys_of(s, account_id))
        if not added:
            break
    with server.db.tx(unscoped="bitcoin.sync: sync account") as s:
        made = record(s, account_id, list(txs.values()))
        mark_gone(s, account_id, list(txs.values()))
        a = s.get(Account, account_id)
        from ..bitcoin import transfers as btcmatch

        btcmatch.propose(s, a.ownerId)
        unpriced = (
            made
            and not s.scalars(
                select(Price.instrumentId)
                .join(Instrument, Instrument.id == Price.instrumentId)
                .where(Instrument.symbol == "BTC", Instrument.instrumentClass == "crypto")
            ).first()
        )
    if unpriced:
        server.tasks.run_now("prices")  # the first coins held: their price history (S4.4)
    return made


CONFIRMATIONS = 6  # recorded once this deep, about an hour (S1.6.2.6)


def _price(s, btc_id: str, day: dt.date) -> Decimal | None:
    from .. import valuation

    p = valuation.prices(s, [btc_id], day).get(btc_id)
    return p.price if p is not None else None


def _fee(s, a, btc, out: Transaction, fee_sats: int, txid: str) -> None:
    """A network fee paid in bitcoin disposes of its sats (S8.19): a sale of them at the day's
    price, taken from the lots like any sale, beside a fee of the same amount, so the cash is
    unchanged. Without a price yet, both wait at 0 for the next sync to value them."""
    qty = Decimal(fee_sats) / SAT
    price = _price(s, btc.id, out.date)
    value = (qty * price).quantize(Decimal("0.01")) if price is not None else Decimal(0)
    for fit, kind, amount, payee in (
        (f"btcfee:{txid}", "sell", value, "Network fee: its sats sold"),
        (f"btcfeecash:{txid}", "fee", -value, "Bitcoin network fee"),
    ):
        s.add(
            Transaction(
                id=ids.new_id("Txn"),
                accountId=a.id,
                date=out.date,
                kind=kind,
                amount=amount,
                payee=payee,
                instrumentId=btc.id if kind == "sell" else None,
                quantity=qty if kind == "sell" else None,
                price=price if kind == "sell" else None,
                lotMethod=a.lotMethod if kind == "sell" else None,
                optionTransactionId=out.id,
                fitId=fit,
            )
        )


def revalue_fees(s, account_id: str) -> int:
    """Fees recorded before bitcoin had a price, valued now that it has one."""
    done = 0
    rows = s.scalars(
        select(Transaction).where(
            Transaction.accountId == account_id,
            Transaction.fitId.like("btcfee:%"),
            Transaction.amount == 0,
            Transaction.deleted == false(),
        )
    ).all()
    for t in rows:
        price = _price(s, t.instrumentId, t.date)
        if price is None:
            continue
        value = (t.quantity * price).quantize(Decimal("0.01"))
        t.amount, t.price = value, price
        cash = s.scalars(
            select(Transaction).where(Transaction.fitId == "btcfeecash:" + t.fitId[7:])
        ).first()
        if cash is not None:
            cash.amount = -value
        done += 1
    return done


def record(s, account_id: str, txs: list[sources.Tx]) -> int:
    a = s.get(Account, account_id)
    have = set(
        s.scalars(
            select(Transaction.fitId).where(
                Transaction.accountId == account_id, Transaction.fitId.like("btc:%")
            )
        )
    )
    zone = ZoneInfo(timezones.host_zone())
    btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
    made = 0
    for t in sorted(txs, key=lambda x: x.confirmedAt or dt.datetime.max.replace(tzinfo=dt.UTC)):
        if t.confirmedAt is None or not t.net or f"btc:{t.txid}" in have:
            continue
        if t.confirmations is not None and t.confirmations < CONFIRMATIONS:
            continue  # waits until it is deep enough
        sent = t.net < 0
        # Sent: what left for others; the fee is a sale of its own (S8.19). In a transaction
        # others put inputs into too (a coinjoin), the wallet's share of the fee is at most
        # what it put in net, never the whole transaction's (S1.6.2.6).
        fee = min(t.fee, -t.net) if sent else 0
        sats = abs(t.net) - fee
        share = " (this wallet's share)" if fee < t.fee else ""
        row = Transaction(
            id=ids.new_id("Txn"),
            accountId=a.id,
            date=t.confirmedAt.astimezone(zone).date(),
            kind="transfer-out" if sent else "transfer-in",
            amount=Decimal(0),
            payee=("Sent bitcoin" if sats else "Network fee") if sent else "Received bitcoin",
            memo=f"txid {t.txid}" + (f" · network fee {fee:,} sats{share}" if fee else ""),
            instrumentId=btc.id,
            quantity=Decimal(sats) / SAT,
            lotMethod=a.lotMethod if sent else None,
            fitId=f"btc:{t.txid}",
        )
        s.add(row)
        s.flush()
        if fee:
            _fee(s, a, btc, row, fee, t.txid)
        made += 1
    s.flush()
    revalue_fees(s, account_id)
    return made


def mark_gone(s, account_id: str, txs: list[sources.Tx]) -> int:
    """A recorded transaction the explorer or node no longer has, after a whole history was
    read, is marked *no longer on the chain* once two reads in a row miss it, never deleted
    (S1.6.2.7); one back on it is unmarked, and one its owner kept stays kept."""
    seen = {f"btc:{t.txid}" for t in txs}
    now = clock.now()
    marked = 0
    for r in s.scalars(
        select(Transaction).where(
            Transaction.accountId == account_id,
            Transaction.fitId.like("btc:%"),
            Transaction.deleted == false(),
        )
    ):
        if r.fitId in seen:
            r.offChainAt = r.offChainMissedAt = None
        elif r.offChainKeptAt is not None or r.offChainAt is not None:
            continue
        elif r.offChainMissedAt is None:
            r.offChainMissedAt = now  # one miss: a node catching up, or a reorganisation
        else:
            r.offChainAt = now
            marked += 1
    return marked


def sync_all(server, ctx=None) -> str | None:
    """Every wallet, for the hourly task; returns the first error, if any. Nothing until
    Settings › Bitcoin is saved."""
    with server.db.read(unscoped="bitcoin.sync: sync all") as s:
        if not chosen(server, s):
            return None
        wallets = list(
            s.scalars(
                select(Account.id).where(
                    Account.type == "crypto-wallet",
                    Account.deleted == false(),
                    Account.active.is_(True),
                )
            )
        )
    error = None
    for account_id in wallets:
        if ctx is not None and ctx.stop.is_set():
            break
        try:
            sync_account(server, account_id)
        except sources.CertificateChanged as e:
            # Kept for an admin to confirm, and alerted (S1.6.2.4).
            with server.db.tx(unscoped="bitcoin.sync: sync all") as s:
                settings.put(s, "bitcoinNodeCertOffered", e.sha256, None)
            error = error or str(e)
            log.warning("bitcoin: %s", e)
        except SourceError as e:
            error = error or str(e)
            log.warning("bitcoin: %s", e)
        except Exception:
            # One wallet's failure is its own: the others are still read.
            log.exception("bitcoin: reading wallet %s failed", account_id)
            error = error or "a wallet couldn't be read; the server's log says why"
    if error:
        raise SourceError(error)
    return None
