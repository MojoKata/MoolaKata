"""Mocks of the bitcoin backends (docs/test-plan.md): a fake Esplora, Electrum server and
Bitcoin Core speaking the subset MoolaKata uses (bitcoin/sources.py), over real sockets, so
the code that talks to a node can be tried without one, and the manual test plan's T1–T4 have
a rehearsal. One small chain stands behind all three: the dev seed's wallet (the public BIP84
test key) funded at its first address, part of it spent with change, and a later receive past
the first gap.

    python -m moolakata.dev.mocks [--esplora PORT] [--electrum PORT] [--core PORT] [--tls]

Point Settings › Bitcoin at them: Esplora at `http://<host>:PORT/api`, an Electrum server at
`<host>:PORT` (its certificate's fingerprint is printed), Bitcoin Core at `<host>:PORT`
with any RPC user and password.
"""

import argparse
import datetime as dt
import hashlib
import json
import socketserver
import ssl
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ..bitcoin import keys
from .seed_wallets import TEST_ZPUB

TIP = 919_402
SAT = 100_000_000
OTHER = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"  # someone else's


def _raw(ins, outs) -> bytes:
    """A segwit transaction's bytes, enough for bitcoin.sources.parse_tx."""
    b = (2).to_bytes(4, "little") + b"\x00\x01" + bytes([len(ins)])
    for txid, idx in ins:
        b += bytes.fromhex(txid)[::-1] + idx.to_bytes(4, "little") + b"\x00" + b"\xff" * 4
    b += bytes([len(outs)])
    for script, value in outs:
        b += value.to_bytes(8, "little") + bytes([len(script)]) + script
    return b + b"\x00" * len(ins) + b"\x00" * 4


def _txid(raw: bytes) -> str:
    return hashlib.sha256(hashlib.sha256(raw).digest()).digest()[::-1].hex()


class Chain:
    """Three transactions on the test wallet: 0.5 BTC in at receive 0 (height 900,000); 0.2
    sent from it to someone else with the change at change 0 (900,100); 0.1 in at receive
    19 (919,390), past the first gap. Each is confirmed deeply enough."""

    def __init__(self):
        key = keys.extended(TEST_ZPUB)
        self.first = key.address(0, 0)
        self.change = key.address(1, 0)
        self.far = key.address(0, 19)
        coinbase = _raw([("00" * 32, 0xFFFFFFFF)], [(keys.script_of(OTHER), 50 * SAT)])
        fund = _raw([(_txid(coinbase), 0)], [(keys.script_of(self.first), 50_000_000)])
        spend = _raw(
            [(_txid(fund), 0)],
            [(keys.script_of(OTHER), 20_000_000), (keys.script_of(self.change), 29_999_000)],
        )
        later = _raw([(_txid(coinbase), 0)], [(keys.script_of(self.far), 10_000_000)])
        self.raw = {_txid(t): t for t in (coinbase, fund, spend, later)}
        self.height = {_txid(fund): 900_000, _txid(spend): 900_100, _txid(later): 919_390}
        self.height[_txid(coinbase)] = 800_000
        self.time = {h: 1_700_000_000 + (h - 800_000) * 600 for h in self.height.values()}
        self.by_address = {
            self.first: [_txid(fund), _txid(spend)],
            self.change: [_txid(spend)],
            self.far: [_txid(later)],
        }

    def esplora_tx(self, txid: str) -> dict:
        ins, outs = _parse(self.raw[txid])
        vin = []
        for ptxid, idx in ins:
            if ptxid == "00" * 32:
                vin.append({"is_coinbase": True})
                continue
            script, value = _parse(self.raw[ptxid])[1][idx]
            vin.append(
                {
                    "txid": ptxid,
                    "vout": idx,
                    "prevout": {
                        "scriptpubkey_address": keys.address_of_script(script),
                        "value": value,
                    },
                }
            )
        vout = [{"scriptpubkey_address": keys.address_of_script(s), "value": v} for s, v in outs]
        spent = sum(i["prevout"]["value"] for i in vin if "prevout" in i)
        h = self.height[txid]
        return {
            "txid": txid,
            "vin": vin,
            "vout": vout,
            "fee": max(0, spent - sum(v for _, v in outs)) if spent else 0,
            "status": {"confirmed": True, "block_height": h, "block_time": self.time[h]},
        }

    def header(self, height: int) -> bytes:
        return bytes(68) + self.time.get(height, 1_700_000_000).to_bytes(4, "little") + bytes(8)

    def core_entries(self) -> list[dict]:
        out = []
        for a, txids in self.by_address.items():
            for txid in txids:
                ins, outs = _parse(self.raw[txid])
                mine_out = sum(v for s, v in outs if keys.address_of_script(s) == a)
                spent = sum(
                    _parse(self.raw[p])[1][i][1]
                    for p, i in ins
                    if p != "00" * 32 and keys.address_of_script(_parse(self.raw[p])[1][i][0]) == a
                )
                h = self.height[txid]
                base = {
                    "txid": txid,
                    "address": a,
                    "blocktime": self.time[h],
                    "confirmations": TIP - h + 1,
                }
                if mine_out:
                    out.append({**base, "category": "receive", "amount": mine_out / SAT})
                if spent:
                    fee = spent - sum(v for _, v in outs)
                    sent = sum(v for s, v in outs if keys.address_of_script(s) != a)
                    out.append(
                        {**base, "category": "send", "amount": -sent / SAT, "fee": -fee / SAT}
                    )
        return out


def _parse(raw: bytes):
    from ..bitcoin.sources import parse_tx

    return parse_tx(raw)


# ---------- Esplora (HTTP)


class EsploraHandler(BaseHTTPRequestHandler):
    chain: Chain

    def log_message(self, *a):
        pass

    def _send(self, body, status=200):
        data = json.dumps(body).encode() if not isinstance(body, str) else body.encode()
        self.send_response(status)
        self.send_header(
            "Content-Type", "application/json" if not isinstance(body, str) else "text/plain"
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] == "api":
            parts = parts[1:]
        c = self.chain
        if parts == ["blocks", "tip", "height"]:
            return self._send(str(TIP))
        if len(parts) >= 3 and parts[0] == "address" and parts[2] == "txs":
            if len(parts) == 5 and parts[3] == "chain":
                return self._send([])
            return self._send([c.esplora_tx(t) for t in c.by_address.get(parts[1], [])])
        if len(parts) == 2 and parts[0] == "tx" and parts[1] in c.raw:
            return self._send(c.esplora_tx(parts[1]))
        self._send({"error": "not found"}, 404)


# ---------- Electrum (TCP JSON-RPC lines, TLS optional)


class ElectrumHandler(socketserver.StreamRequestHandler):
    chain: Chain

    def handle(self):
        c = self.chain
        for line in self.rfile:
            try:
                req = json.loads(line)
            except ValueError:
                break
            method, params = req.get("method"), req.get("params") or []
            result, error = None, None
            if method == "server.version":
                result = ["MoolaKata mock Electrum 1.0", "1.4"]
            elif method == "blockchain.headers.subscribe":
                result = {"height": TIP, "hex": c.header(TIP).hex()}
            elif method == "blockchain.scripthash.get_history":
                by_hash = {
                    hashlib.sha256(keys.script_of(a)).digest()[::-1].hex(): v
                    for a, v in c.by_address.items()
                }
                result = [{"tx_hash": t, "height": c.height[t]} for t in by_hash.get(params[0], [])]
            elif method == "blockchain.block.header":
                result = c.header(int(params[0])).hex()
            elif method == "blockchain.transaction.get":
                raw = c.raw.get(params[0])
                if raw is None:
                    error = {"code": 1, "message": "no such transaction"}
                else:
                    result = raw.hex()
            else:
                error = {"code": -32601, "message": f"unknown method {method}"}
            answer = {"jsonrpc": "2.0", "id": req.get("id"), "result": result, "error": error}
            self.wfile.write(json.dumps(answer).encode() + b"\n")


class ElectrumServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, chain: Chain, tls: bool):
        handler = type("H", (ElectrumHandler,), {"chain": chain})
        super().__init__(addr, handler)
        self.context = None
        self.cert_sha256 = None
        if tls:
            cert, key = self_signed()
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(cert, key)
            self.cert_sha256 = hashlib.sha256(
                ssl.PEM_cert_to_DER_cert(Path(cert).read_text())
            ).hexdigest()

    def get_request(self):
        sock, addr = super().get_request()
        if self.context is not None:
            sock = self.context.wrap_socket(sock, server_side=True)
        return sock, addr


def self_signed() -> tuple[str, str]:
    """A certificate for the mock Electrum server, made fresh each start."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "moolakata-mock-electrum")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    d = Path(tempfile.mkdtemp(prefix="mk-mock-"))
    (d / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(d / "cert.pem"), str(d / "key.pem")


# ---------- Bitcoin Core (HTTP JSON-RPC)


class CoreHandler(BaseHTTPRequestHandler):
    chain: Chain
    wallets: dict[str, list[dict]]

    def log_message(self, *a):
        pass

    def do_POST(self):
        if not self.headers.get("Authorization", "").startswith("Basic "):
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(length) or b"{}")
        method, params = req.get("method"), req.get("params") or []
        wallet = self.path.split("/wallet/")[1] if "/wallet/" in self.path else None
        c, result, error = self.chain, None, None
        if method == "getblockchaininfo":
            result = {"chain": "main", "blocks": TIP, "headers": TIP}
        elif method == "listwallets":
            result = sorted(self.wallets)
        elif method == "loadwallet":
            if params[0] not in self.wallets:
                error = {"code": -18, "message": "no such wallet"}
            else:
                result = {"name": params[0]}
        elif method == "createwallet":
            self.wallets[params[0]] = []
            result = {"name": params[0]}
        elif method == "getdescriptorinfo":
            result = {"descriptor": f"{params[0]}#mockchk", "checksum": "mockchk"}
        elif method == "listdescriptors":
            result = {"descriptors": self.wallets.get(wallet, [])}
        elif method == "importdescriptors":
            self.wallets.setdefault(wallet, []).extend(params[0])
            result = [{"success": True} for _ in params[0]]
        elif method == "listtransactions":
            entries = c.core_entries()
            skip = int(params[2]) if len(params) > 2 else 0
            result = entries[skip : skip + int(params[1] if len(params) > 1 else 10)]
        elif method == "listreceivedbyaddress":
            result = [{"address": a, "amount": 0} for a in c.by_address]
        else:
            error = {"code": -32601, "message": f"unknown method {method}"}
        data = json.dumps({"result": result, "error": error, "id": req.get("id")}).encode()
        self.send_response(200 if error is None else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Mocks:
    """The three servers on the ports asked for (0 for any free one), in threads."""

    def __init__(self, esplora: int | None, electrum: int | None, core: int | None, tls=False):
        self.chain = Chain()
        self.esplora = self.electrum = self.core = None
        if esplora is not None:
            h = type("E", (EsploraHandler,), {"chain": self.chain})
            self.esplora = ThreadingHTTPServer(("127.0.0.1", esplora), h)
        if electrum is not None:
            self.electrum = ElectrumServer(("127.0.0.1", electrum), self.chain, tls)
        if core is not None:
            h = type("C", (CoreHandler,), {"chain": self.chain, "wallets": {}})
            self.core = ThreadingHTTPServer(("127.0.0.1", core), h)
        self.threads = [
            threading.Thread(target=s.serve_forever, daemon=True)
            for s in (self.esplora, self.electrum, self.core)
            if s is not None
        ]

    def start(self) -> Mocks:
        for t in self.threads:
            t.start()
        return self

    def stop(self) -> None:
        for s in (self.esplora, self.electrum, self.core):
            if s is not None:
                s.shutdown()
                s.server_close()

    def ports(self) -> dict[str, int]:
        return {
            name: s.server_address[1]
            for name, s in (
                ("esplora", self.esplora),
                ("electrum", self.electrum),
                ("core", self.core),
            )
            if s is not None
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--esplora", type=int, default=3006)
    p.add_argument("--electrum", type=int, default=50002)
    p.add_argument("--core", type=int, default=8332)
    p.add_argument("--tls", action="store_true", help="the Electrum server with TLS")
    args = p.parse_args(argv)
    m = Mocks(args.esplora, args.electrum, args.core, args.tls).start()
    ports = m.ports()
    print(f"Esplora:      http://127.0.0.1:{ports['esplora']}/api")
    print(f"Electrum:     127.0.0.1:{ports['electrum']}" + (" (TLS)" if args.tls else " (no TLS)"))
    if m.electrum.cert_sha256:
        print(f"  certificate SHA-256 {m.electrum.cert_sha256}")
    print(f"Bitcoin Core: 127.0.0.1:{ports['core']} (any RPC user and password)")
    print(f"The wallet: {TEST_ZPUB}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        m.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
