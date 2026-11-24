"""Where a wallet's history comes from (requirements S1.6.2): a public explorer or the
household's own node, set by an admin in Settings › Bitcoin.

1. **Esplora** (mempool.space by default, Blockstream, or the household's own mempool or
   Esplora instance) over HTTPS: each address's transactions, with every input's prevout.
2. **An Electrum server** (Fulcrum, electrs) over TCP, TLS by default: each address's history
   by its script hash, and the raw transactions, read here.
3. **Bitcoin Core** over JSON-RPC, with a watch-only descriptor wallet MoolaKata makes for each
   wallet account: its keys imported as descriptors over the derived range, then its
   transactions listed.

Each answers the same question: the confirmed and unconfirmed transactions touching a set of
addresses, each with its net effect on them."""

import base64
import datetime as dt
import hashlib
import io
import json
import socket
import ssl
from dataclasses import dataclass, field
from decimal import Decimal

from .. import net
from ..tasks import TaskError
from . import keys as bk

SAT = 100_000_000
DEFAULT_ESPLORA = "https://mempool.space/api"
PUBLIC_EXPLORERS = ("mempool.space", "blockstream.info")
KINDS = ("esplora", "electrum", "core")


class SourceError(TaskError):
    """The explorer or node couldn't answer: the message says what to fix, and never names an
    address or an amount."""


class CertificateChanged(SourceError):
    """An Electrum server presented a certificate other than the one trusted (S1.6.2.4), or
    none is trusted yet: refused until an admin confirms the one it shows."""

    def __init__(self, message: str, sha256: str):
        super().__init__(message)
        self.sha256 = sha256


@dataclass
class Tx:
    txid: str
    confirmedAt: dt.datetime | None  # None while unconfirmed
    net: int = 0  # sats, + into the addresses, − out of them
    fee: int = 0  # sats, when the addresses paid it
    addresses: set[str] = field(default_factory=set)  # ours it touched
    confirmations: int | None = None  # None: not known, so taken as deep enough


@dataclass
class Config:
    kind: str = "esplora"
    esploraUrl: str = DEFAULT_ESPLORA
    host: str | None = None
    port: int = 50002
    tls: bool = True
    rpcUser: str | None = None
    password: str | None = None
    certSha256: str | None = None  # an Electrum server's certificate, trusted on first use

    def hosts(self) -> tuple[list[str], list[str]]:
        """The hosts to reach, and those named by an admin (a node on the LAN, S13.5)."""
        if self.kind == "esplora":
            host = (net.httpx.URL(self.esploraUrl).host or "").lower()
            if not host:
                return [], []
            public = any(host == p or host.endswith("." + p) for p in PUBLIC_EXPLORERS)
            return [host], [] if public else [host]
        return ([self.host], [self.host]) if self.host else ([], [])


# ---------- Esplora


class Esplora:
    def __init__(self, cfg: Config, guard: net.Guard):
        self.base = cfg.esploraUrl.rstrip("/")
        self.client = net.Client(guard, use="bitcoin")

    def _get(self, path: str):
        try:
            r = self.client.get(self.base + path)
        except net.httpx.HTTPError as e:
            # The error's type only: its text may carry the URL, which names an address.
            raise SourceError(f"{self.base} didn't answer ({type(e).__name__}).") from None
        if r.status_code == 429:
            raise SourceError(f"{self.base} asked to slow down (429); it is tried again later.")
        if r.status_code >= 400:
            raise SourceError(f"{self.base} answered {r.status_code}.")
        if "json" in r.headers.get("content-type", ""):
            return json.loads(r.text, parse_float=Decimal)
        return r.text

    def test(self) -> str:
        return f"Esplora answered: block {int(self._get('/blocks/tip/height')):,}"

    def history(self, addresses: list[str]) -> list[Tx]:
        mine = set(addresses)
        seen: dict[str, Tx] = {}
        tip = int(self._get("/blocks/tip/height")) if addresses else 0
        for a in addresses:
            page = self._get(f"/address/{a}/txs")
            while True:
                for t in page:
                    if t["txid"] not in seen:
                        seen[t["txid"]] = _esplora_tx(t, mine, tip)
                confirmed = [t for t in page if t.get("status", {}).get("confirmed")]
                if len(confirmed) < 25:
                    break
                page = self._get(f"/address/{a}/txs/chain/{confirmed[-1]['txid']}")
        return list(seen.values())


def _esplora_tx(t: dict, mine: set[str], tip: int = 0) -> Tx:
    st = t.get("status") or {}
    when = (
        dt.datetime.fromtimestamp(st["block_time"], dt.UTC)
        if st.get("confirmed") and st.get("block_time")
        else None
    )
    out = Tx(t["txid"], when)
    if st.get("block_height") and tip:
        out.confirmations = tip - int(st["block_height"]) + 1
    paid = False
    for i in t.get("vin", []):
        p = i.get("prevout") or {}
        if p.get("scriptpubkey_address") in mine:
            out.net -= int(p["value"])
            out.addresses.add(p["scriptpubkey_address"])
            paid = True
    for o in t.get("vout", []):
        if o.get("scriptpubkey_address") in mine:
            out.net += int(o["value"])
            out.addresses.add(o["scriptpubkey_address"])
    if paid:
        out.fee = int(t.get("fee") or 0)
    return out


# ---------- Electrum


def _varint(f) -> int:
    n = f.read(1)[0]
    if n < 0xFD:
        return n
    return int.from_bytes(f.read({0xFD: 2, 0xFE: 4, 0xFF: 8}[n]), "little")


def parse_tx(raw: bytes) -> tuple[list[tuple[str, int]], list[tuple[bytes, int]]]:
    """A raw transaction's inputs (prevout txid, index) and outputs (script, sats)."""
    f = io.BytesIO(raw)
    f.read(4)
    segwit = raw[4:6] == b"\x00\x01"
    if segwit:
        f.read(2)
    ins = []
    for _ in range(_varint(f)):
        txid = f.read(32)[::-1].hex()
        idx = int.from_bytes(f.read(4), "little")
        f.read(_varint(f))
        f.read(4)
        ins.append((txid, idx))
    outs = []
    for _ in range(_varint(f)):
        value = int.from_bytes(f.read(8), "little")
        outs.append((f.read(_varint(f)), value))
    return ins, outs


class Electrum:
    def __init__(self, cfg: Config, guard: net.Guard):
        if not cfg.host:
            raise SourceError("Name the Electrum server's host first.")
        self.cfg = cfg
        self.guard = guard
        self.sock = None
        self.buf = b""
        self.n = 0
        self.raw: dict[str, bytes] = {}
        self.seen: str | None = None  # the certificate's SHA-256, once connected
        self.testing = False

    def _connect(self):
        try:
            # To the address the guard checked, never a second lookup (S13.5).
            address = self.guard.check(self.cfg.host, self.cfg.port, "bitcoin")
            s = socket.create_connection((address, self.cfg.port), timeout=20)
            if self.cfg.tls:
                # Electrum servers mostly use a certificate they made themselves.
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                s = ctx.wrap_socket(s, server_hostname=self.cfg.host)
                # Trusted on first use (S1.6.2.4): the one an admin confirmed, or none.
                seen = hashlib.sha256(s.getpeercert(binary_form=True) or b"").hexdigest()
                self.seen = seen
                if not self.testing and seen != (self.cfg.certSha256 or "").lower():
                    s.close()
                    raise CertificateChanged(
                        "The Electrum server's certificate isn't the one trusted: an admin "
                        "confirms it in Settings › Bitcoin."
                        if self.cfg.certSha256
                        else "Confirm the Electrum server's certificate in Settings › Bitcoin "
                        "first.",
                        seen,
                    )
            self.sock = s
            self.call("server.version", "MoolaKata", "1.4")
        except (OSError, net.EgressRefused) as e:
            raise SourceError(f"{self.cfg.host}:{self.cfg.port} didn't answer: {e}") from None

    def call(self, method: str, *params):
        if self.sock is None:
            self._connect()
        self.n += 1
        msg = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        try:
            self.sock.sendall(msg.encode() + b"\n")
            while b"\n" not in self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise SourceError("The Electrum server closed the connection.")
                self.buf += chunk
                if len(self.buf) > net.MAX_RESPONSE:
                    raise SourceError("The Electrum server's answer is larger than allowed.")
        except OSError as e:
            raise SourceError(f"The Electrum server stopped answering: {e}") from None
        line, self.buf = self.buf.split(b"\n", 1)
        out = json.loads(line, parse_float=Decimal)
        if out.get("error"):
            raise SourceError(f"The Electrum server refused {method}: {out['error']}")
        return out.get("result")

    def close(self):
        if self.sock is not None:
            self.sock.close()

    def test(self) -> str:
        self.testing = True
        ver = self.call("server.version", "MoolaKata", "1.4")
        tip = self.call("blockchain.headers.subscribe")
        self.close()
        out = f"{ver[0] if isinstance(ver, list) else ver} answered: block {tip['height']:,}"
        if self.cfg.tls and self.seen:
            trusted = self.seen == (self.cfg.certSha256 or "").lower()
            out += f" · certificate SHA-256 {self.seen}" + (
                "" if trusted else " (not trusted yet: confirm it)"
            )
        return out

    def _tx(self, txid: str) -> bytes:
        if txid not in self.raw:
            self.raw[txid] = bytes.fromhex(self.call("blockchain.transaction.get", txid, False))
        return self.raw[txid]

    def history(self, addresses: list[str]) -> list[Tx]:
        scripts = {bk.script_of(a): a for a in addresses}
        txs: dict[str, int] = {}
        for script in scripts:
            sh = hashlib.sha256(script).digest()[::-1].hex()
            for h in self.call("blockchain.scripthash.get_history", sh):
                txs[h["tx_hash"]] = h["height"]
        times: dict[int, dt.datetime] = {}
        tip = self.call("blockchain.headers.subscribe")["height"] if txs else 0
        out = []
        for txid, height in txs.items():
            if height > 0 and height not in times:
                header = bytes.fromhex(self.call("blockchain.block.header", height))
                times[height] = dt.datetime.fromtimestamp(
                    int.from_bytes(header[68:72], "little"), dt.UTC
                )
            t = Tx(txid, times.get(height) if height > 0 else None)
            if height > 0:
                t.confirmations = tip - height + 1
            ins, outs = parse_tx(self._tx(txid))
            spent_in = 0
            for ptxid, idx in ins:
                if ptxid == "00" * 32:
                    continue
                _, pouts = parse_tx(self._tx(ptxid))
                script, value = pouts[idx]
                spent_in += value
                if script in scripts:
                    t.net -= value
                    t.addresses.add(scripts[script])
            for script, value in outs:
                if script in scripts:
                    t.net += value
                    t.addresses.add(scripts[script])
            if t.net < 0:
                t.fee = spent_in - sum(v for _, v in outs)
            out.append(t)
        self.close()
        return out


# ---------- Bitcoin Core


class Core:
    def __init__(self, cfg: Config, guard: net.Guard):
        if not cfg.host:
            raise SourceError("Name Bitcoin Core's host first.")
        scheme = "https" if cfg.tls else "http"
        self.url = f"{scheme}://{cfg.host}:{cfg.port}"
        auth = base64.b64encode(f"{cfg.rpcUser or ''}:{cfg.password or ''}".encode()).decode()
        self.client = net.Client(guard, use="bitcoin", headers={"Authorization": "Basic " + auth})

    def call(self, method: str, *params, wallet: str | None = None):
        url = self.url + (f"/wallet/{wallet}" if wallet else "/")
        body = {"jsonrpc": "1.0", "id": "mk", "method": method, "params": list(params)}
        try:
            r = self.client.post(url, json=body)
        except net.httpx.HTTPError as e:
            raise SourceError(
                f"Bitcoin Core at {self.url} didn't answer ({type(e).__name__})."
            ) from None
        if r.status_code == 401:
            raise SourceError("Bitcoin Core refused the RPC user or password.")
        try:
            # Amounts in BTC, read as decimals: a float would lose a satoshi (S14.3).
            out = json.loads(r.text, parse_float=Decimal)
        except ValueError:
            raise SourceError(f"Bitcoin Core answered {r.status_code}.") from None
        if out.get("error"):
            raise SourceError(f"Bitcoin Core refused {method}: {out['error'].get('message')}")
        return out["result"]

    def test(self) -> str:
        info = self.call("getblockchaininfo")
        if info.get("chain") != "main":
            raise SourceError(f"Bitcoin Core follows {info.get('chain')}, not mainnet.")
        return f"Bitcoin Core answered: block {info['blocks']:,}"

    def wallet(self, name: str, wanted: list[tuple[str, int | None]]) -> None:
        """The watch-only descriptor wallet for one wallet account, made or loaded, with its
        descriptors imported over the range derived (a rescan from the start the first
        time, which can take a while on a large chain)."""
        if name not in self.call("listwallets"):
            try:
                self.call("loadwallet", name)
            except SourceError:
                self.call("createwallet", name, True, True, "", False, True)
        have = {
            (d["desc"], tuple(d.get("range") or ()))
            for d in self.call("listdescriptors", wallet=name)["descriptors"]
        }
        new = []
        for desc, top in wanted:
            full = self.call("getdescriptorinfo", desc)["descriptor"]
            rng = (0, top) if top is not None else ()
            if any(h[0] == full and (not rng or (h[1] and h[1][1] >= top)) for h in have):
                continue
            req: dict = {"desc": full, "timestamp": 0, "watchonly": True}
            if top is not None:
                req["range"] = [0, top]
            new.append(req)
        if new:
            self.call("importdescriptors", new, wallet=name)

    def history_of(self, name: str) -> tuple[list[Tx], set[str]]:
        """The wallet's transactions, and every address of its that has received."""
        txs: dict[str, Tx] = {}
        skip = 0
        while True:
            page = self.call("listtransactions", "*", 500, skip, True, wallet=name)
            for e in page:
                t = txs.setdefault(
                    e["txid"],
                    Tx(
                        e["txid"],
                        dt.datetime.fromtimestamp(e["blocktime"], dt.UTC)
                        if e.get("blocktime")
                        else None,
                    ),
                )
                t.confirmations = int(e.get("confirmations") or 0)
                sats = round(e["amount"] * SAT)
                if e["category"] == "receive":
                    t.net += sats
                    t.addresses.add(e["address"])
                elif e["category"] == "send":
                    t.net += sats
                    t.fee = round(-e.get("fee", 0) * SAT)
            if len(page) < 500:
                break
            skip += 500
        for t in txs.values():
            t.net -= t.fee
        used = {
            r["address"]
            for r in self.call("listreceivedbyaddress", 0, False, True, "", True, wallet=name)
        }
        return list(txs.values()), used


def descriptors(key, top: int | None) -> list[tuple[str, int | None]]:
    """A WalletKey as Core descriptors: an address as itself, a key as its receive and change
    chains, ranged to the highest index derived."""
    if key.kind == "address":
        return [(f"addr({key.value})", None)]
    if key.kind == "descriptor":
        # Each chain apart, as every Core version reads them (S1.6.1.4).
        from . import descriptor

        d = descriptor.parse(key.value)
        return [(d.text(f"/{chain}/*"), top or 0) for chain in d.chains]
    raw = bk.b58check_decode(key.value)
    xpub = bk.b58check_encode(bytes.fromhex("0488b21e") + raw[4:])
    inner = {"p2pkh": "pkh({})", "p2sh-p2wpkh": "sh(wpkh({}))", "p2wpkh": "wpkh({})"}[key.script]
    return [(inner.format(f"{xpub}/{chain}/*"), top or 0) for chain in (0, 1)]


def make(cfg: Config, guard: net.Guard):
    if cfg.kind == "electrum":
        return Electrum(cfg, guard)
    if cfg.kind == "core":
        return Core(cfg, guard)
    return Esplora(cfg, guard)
