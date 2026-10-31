"""The connector's loop (requirements S18.5, S18.7, S18.8, docs/connector-protocol.md): every
5 minutes a signed report to MoolaKata, answered with what waits; sealed credentials collected
into the vault, bound to the host they may be sent to; each Connection's driver run at its
interval, never against a host its credentials aren't bound to; what it fetched posted for its
accounts, a post refused for a limit kept for a later run."""

import http.client
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import client, keys, sealed, signing
from .client import Egress, ServerError, Transport
from .drivers import Account, Driver, File, registry
from .vault import Vault, VaultError
from .words import PhraseError

log = logging.getLogger("connector")
REPORT_SECONDS = 300
# MoolaKata down or locked is waited for, never a reason to stop (S18.3.2): the wait grows
# from 15 seconds to the report's 5 minutes.
RETRY_FIRST = 15
# While a Connection waits for a sign-in, the report comes every 15 seconds for 10 minutes, so
# an address pasted back is exchanged at once (S18.5).
SIGN_IN_SECONDS = 15
SIGN_IN_FOR = 600
# What a pairing's keys sign of one another (S18.4.2, S18.4.5).
SEALING_LABEL = b"moolakata connector sealing key\x00"
STATUS_LABEL = b"moolakata connector status key\x00"
ACTION_LABEL = b"moolakata connector action key\x00"
SHOWN = ("label", "driver", "state", "message")  # each Connection, in `status`
WAITING_KEPT = 10  # files kept for a later round, per Connection: the newest
# A post MoolaKata can't take now, kept for a later round, and what the Connection says of it
# (S18.8, protocol §7); any other refusal drops the file.
KEEP = {
    "limit": "the owner's upload limit",
    "uploads-in-flight": "too many uploads arriving at once",
    "locked": "MoolaKata is locked",
    "not-confirmed": "the pairing's confirmation",
    "answer-unsigned": "MoolaKata's answer wasn't signed",
    "server-error": "MoolaKata failed; it is logged there",
}


@dataclass
class ConnectionState:
    id: str
    driver: str
    label: str
    settings: dict
    accounts: list[Account]
    state: str = "new"
    message: str | None = None
    last_run: float | None = None
    last_added: int | None = None
    found: list[dict] = field(default_factory=list)
    sign_in: str | None = None
    sign_in_at: float | None = None  # since when the sign-in has waited
    backlog: list[File] = field(default_factory=list)


class Core:
    def __init__(self, data: Path, transport: Transport | None = None, drivers=None):
        self.data = data
        data.mkdir(parents=True, exist_ok=True)
        self.vault = Vault(data / "vault.json")
        self.egress = Egress()
        self.transport = transport or Transport(self.egress)
        self.drivers: dict[str, Driver] = drivers or registry()
        self.pairing = keys.load(data / "pairing.json")
        self.server: client.Server | None = None
        self.connections: dict[str, ConnectionState] = {}
        self.last_report: float | None = None
        self.last_error: str | None = None
        self.confirmed: bool | None = None  # what MoolaKata's last answer said (S18.4.2)
        self.page: str | None = None  # its page's address, for every report (S18.11.1)
        self.unlocked_at: float | None = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.retry = 0.0  # the wait before trying MoolaKata again; none while it answers
        if self.pairing:
            # Reached from the loop, once the socket is open: MoolaKata may be down or locked
            # at the connector's start, and an admin must still be able to unlock it (B30).
            self.egress.allow(_host(self.pairing.address))

    # ----- pairing -----

    def _attach(self, pairing: keys.Pairing) -> None:
        self.pairing = pairing
        self.egress.allow(_host(pairing.address))
        hi = client.hello(self.transport, pairing.address, pairing.pins())
        # The key itself must hash to the fingerprint paired with, whatever the answer says it
        # is (S18.4.2).
        key = client.server_key(hi)
        if keys.fingerprint(key) != pairing.server_fp:
            raise ServerError("fingerprint-mismatch", "The server's key isn't the one paired with.")
        self.server = client.Server(pairing, self.transport, key, self._certificate)

    def _certificate(self, pinned: str, following: str | None) -> None:
        """MoolaKata announced its next certificate key, in a signed answer, or started using
        the one it announced: the pairing keeps the keys it may present (protocol §1.2)."""
        with self._lock:
            p = self.pairing
            if p is None:
                return
            p.cert, p.cert_next = pinned, following
            keys.save(self.data / "pairing.json", p)

    def pair(self, code: str) -> str:
        """`moolakata-connector pair <code>` (S18.4.2): check the server's fingerprint against
        the code, make the keys, introduce the connector. Returns its fingerprint to compare.
        The vault must be unlocked: the sealing key's private half goes into it (S18.4.5)."""
        if self.vault.locked:
            raise VaultError("unlock the vault first: the sealing key is kept in it")
        c = decode_code(code)
        self.egress.allow(_host(c["a"]))
        cert = c.get("t") if isinstance(c.get("t"), str) else None
        hi = client.hello(self.transport, c["a"], frozenset([cert]) if cert else None)
        key = client.server_key(hi)
        if keys.fingerprint(key) != c["f"]:
            raise ServerError(
                "fingerprint-mismatch",
                "The server at that address doesn't have the key the code names: nothing sent.",
            )
        private, public = keys.new_sealing_key()
        action_private, action_public = keys.new_action_key()
        action = Ed25519PrivateKey.from_private_bytes(action_private)
        pairing = keys.make(c["a"], c["f"], action_public, public, cert)
        server = client.Server(pairing, self.transport, key, self._certificate)
        # The action key signs the sealing key, so a browser seals only to the key of the
        # connector an admin confirmed (S18.4.5); the action and status keys sign each other,
        # so MoolaKata knows both are this connector's. The call itself is the action key's.
        out = server.call(
            "/connector/v1/pair",
            {
                "code": code,
                "sealingKey": keys.b64(public),
                "sealingSignature": keys.b64(action.sign(SEALING_LABEL + public)),
                "statusKey": keys.b64(pairing.status_public),
                "statusSignature": keys.b64(action.sign(STATUS_LABEL + pairing.status_public)),
                "actionSignature": keys.b64(pairing.status.sign(ACTION_LABEL + action_public)),
                "version": client.VERSION,
            },
            key=action,
        )
        # The fingerprint shown is worked out here, from the key itself; an answer naming
        # another means the server took some other key, and nothing is kept (S18.4.2).
        if out.get("connectorFingerprint") != pairing.fingerprint:
            raise ServerError(
                "fingerprint-mismatch",
                "MoolaKata's answer names another connector's key: nothing kept. Pair again.",
            )
        # Only now, MoolaKata having taken it, does the new pairing replace the old (S18.4.2).
        keys.save(self.data / "pairing.json", pairing)
        with self._lock:
            self.pairing, self.server = pairing, server
            self.connections = {}
            for cid in self.vault.ids():
                self.vault.delete(cid)
            self.vault.keep_keys(private, action_private)
        self._wake.set()
        return keys.short(pairing.fingerprint)

    def unpair(self) -> None:
        """Forget the server and delete every credential held for it (S18.4.4)."""
        with self._lock:
            if self.server:
                try:
                    self.server.call("/connector/v1/unpaired", key=self._key())
                except (ServerError, Exception) as e:
                    log.warning("the server wasn't told of the unpairing: %s", e)
            self._forget()

    def _forget(self) -> None:
        """The pairing gone: its file, every credential, and the sealing and action keys, so no
        box sealed to it opens here again and nothing is signed for it (S18.4.4)."""
        keys.forget(self.data / "pairing.json")
        self.pairing = self.server = None
        self.connections = {}
        self.confirmed = None
        if not self.vault.locked:
            for cid in self.vault.ids():
                self.vault.delete(cid)
            self.vault.keep_keys(b"", b"")

    def _action(self) -> Ed25519PrivateKey:
        """The action key, from the vault: every call but a locked report and `unpaired` is
        signed with it (S18.4.2). Raises while the vault is locked."""
        raw = self.vault.action_key()
        if not raw:
            raise VaultError("this pairing has no action key: pair again")
        return Ed25519PrivateKey.from_private_bytes(raw)

    def _key(self) -> Ed25519PrivateKey:
        """The key a report or `unpaired` is signed with: the action key while the vault is
        open, else the status key, which can say no more than that it is locked."""
        if self.vault.locked:
            return self.pairing.status
        return self._action()

    def reset(self, phrase: str) -> str:
        """New words (S18.3.4): a new vault under the words typed at the command line or
        confirmed on its page, and unpaired, so the next `pair` makes both keys afresh. Returns
        its fingerprint."""
        with self._lock:
            keys.forget(self.data / "pairing.json")
            self.pairing = self.server = None
            self.connections = {}
            self.confirmed = None
            try:
                self.vault.reset(phrase)
            except PhraseError as e:
                raise VaultError(str(e)) from None
            self.unlocked_at = time.time()
            return self.vault.fingerprint()

    # ----- the loop -----

    def status(self) -> dict:
        """What the connector is doing, without waiting for the round: a run or a post may take
        minutes, and the health check, `status` and its page answer at once (S18.3.2). Each
        field is read once; the Connections from a copy of the map the round may change."""
        pairing, connections = self.pairing, self.connections.copy()
        return {
            "paired": pairing is not None,
            "server": pairing.address if pairing else None,
            "fingerprint": keys.short(pairing.fingerprint) if pairing else None,
            "locked": self.vault.locked,
            "vault": self.vault.fingerprint(),
            "confirmed": self.confirmed,
            "unlockedAt": self.unlocked_at,
            "page": self.page,
            "lastReport": self.last_report,
            "lastError": self.last_error,
            "reachable": self.server is not None,
            "retryIn": int(self.retry) if self.retry else None,
            "connections": {c.id: {k: getattr(c, k) for k in SHOWN} for c in connections.values()},
        }

    def unlock(self, phrase: str) -> None:
        self.vault.unlock(phrase)
        self.unlocked_at = time.time()
        self._wake.set()

    def made(self, key: bytes) -> None:
        """A vault made on its page (S18.11.2), unlocked under its new key."""
        with self._lock:
            self.vault.create(key)
            self.unlocked_at = time.time()
        self._wake.set()

    def lock(self) -> None:
        self.vault.lock()
        self.unlocked_at = None

    def _known(self, connection_id: str) -> ConnectionState:
        c = self.connections.get(connection_id)
        if c is None and self.server is not None:
            self.tick()
            c = self.connections.get(connection_id)
        if c is None:
            raise VaultError(
                "the connector hasn't heard of that Connection yet: check its id, or try "
                "again after its next report"
            )
        return c

    def goes_to(self, connection_id: str) -> dict:
        """Where credentials typed for a Connection would go, for the admin to confirm before
        typing them (S18.7.2): the host they'd be bound to, or the driver's own hosts."""
        with self._lock:
            c = self._known(connection_id)
            d = self.drivers.get(c.driver)
            return {
                "label": c.label,
                "driver": c.driver,
                "host": self._binds(c),
                "hosts": list(d.hosts_for(c.settings)) if d else [],
            }

    def connect(self, connection_id: str, credentials: dict, host: str | None) -> None:
        """Credentials typed on this host (S18.7.2), straight into the vault, bound to the host
        the admin confirmed (S18.7.3), so the Connection must be known here; refused when its
        settings name another host now."""
        with self._lock:
            c = self._known(connection_id)
            if self._binds(c) != host:
                raise VaultError(
                    f"the Connection now names {self._binds(c) or 'its driver'}'s host, not the "
                    f"{host or 'driver'}'s you confirmed: nothing filed; run connect again"
                )
            self.vault.put(connection_id, credentials, host)
            c.state, c.message, c.last_run = "ok", "credentials received", None
        self._wake.set()

    def _binds(self, c: ConnectionState) -> str | None:
        d = self.drivers.get(c.driver)
        return d.binds(c.settings) if d else None

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                self.retry = 0.0
            except Exception as e:  # the loop never dies on one bad report
                self.last_error = f"{type(e).__name__}: {e}"
                self.retry = min(max(self.retry * 2, RETRY_FIRST), REPORT_SECONDS)
                log.warning("report failed, trying again in %ds: %s", self.retry, e)
            self._wake.wait(self.next_wait())
            self._wake.clear()

    def next_wait(self) -> float:
        """Seconds to the next report: the retry's growing wait after a failure; 15 while a
        sign-in waits, for 10 minutes; else 5 minutes."""
        if self.retry:
            return self.retry
        now = time.time()
        for c in self.connections.values():
            if c.sign_in and now - (c.sign_in_at or now) < SIGN_IN_FOR:
                return SIGN_IN_SECONDS
        return REPORT_SECONDS

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def tick(self) -> None:
        """One round: report, collect, run what is due, post. Unattached, it says hello first;
        MoolaKata not answering raises, for the loop to try again later."""
        if self.server is None:
            if self.pairing is None:
                return
            try:
                self._attach(self.pairing)
            except ServerError, VaultError:
                raise
            except Exception as e:
                raise ServerError(
                    "server-unreachable",
                    f"MoolaKata at {self.pairing.address} isn't answering ({type(e).__name__}); "
                    "waiting for it",
                ) from e
        with self._lock:
            locked = self.vault.locked
            # Locked, the report is the status key's and says only that (S18.5): nothing in it
            # or its answer is about a Connection, and nothing is run or posted.
            report = {"locked": True} if locked else self._report()
            try:
                answer = self.server.call("/connector/v1/report", report, key=self._key())
            except ServerError as e:
                if e.code == "not-paired":
                    # MoolaKata, in a signed answer, no longer knows this connector: unpaired
                    # there, after a lost host, so nothing it held is kept (S18.4.4).
                    self._forget()
                raise
            self.last_report, self.last_error = time.time(), None
            if locked:
                return
            self._apply(answer)
            ran = False
            for c in list(self.connections.values()):
                if self._due(c):
                    self._run(c)
                    ran = True
            self._post_backlogs()
            if ran:  # what each run came to, at once rather than at the next round (S18.5)
                self._apply(
                    self.server.call("/connector/v1/report", self._report(), key=self._action())
                )
                self.last_report = time.time()

    def _report(self) -> dict:
        """The whole report, the action key's: the vault is open."""
        return {
            "locked": False,
            **({"page": self.page} if self.page else {}),
            "connections": [
                {
                    "id": c.id,
                    "state": c.state,
                    "message": c.message,
                    "lastRunAt": _iso(c.last_run),
                    "lastRunAdded": c.last_added,
                    "institutionAccounts": c.found,
                    "signInAddress": c.sign_in,
                }
                for c in self.connections.values()
            ],
        }

    def _apply(self, answer: dict) -> None:
        if "confirmed" in answer:
            self.confirmed = bool(answer["confirmed"])
        seen = set()
        for rep in answer.get("connections") or []:
            cid = rep["id"]
            seen.add(cid)
            c = self.connections.get(cid)
            if c is None:
                c = self.connections[cid] = ConnectionState(
                    cid, rep.get("driver", ""), rep.get("label", ""), rep.get("settings") or {}, []
                )
            c.settings = rep.get("settings") or c.settings
            c.label = rep.get("label") or c.label
            c.accounts = [
                Account(a["id"], a.get("syncAccount"), a.get("formats") or [])
                for a in rep.get("accounts") or []
            ]
            box = rep.get("sealed") or {}
            if box.get("ciphertext") and not self.vault.locked:
                self._collect(c, box["ciphertext"], box.get("sealedAt"))
        for cid in answer.get("removed") or []:
            self.connections.pop(cid, None)
            if not self.vault.locked:
                self.vault.delete(cid)
        for cid in list(self.connections):
            if cid not in seen:
                self.connections.pop(cid)

    def _collect(self, c: ConnectionState, box: str, server_at: str | None) -> None:
        """A sealed credential, opened with the sealing key from the vault and filed bound to
        the host the Connection's settings name now (S18.7.1, S18.7.3). The time sealed into it
        must be later than the credential held's, so an older box handed over again is
        refused; MoolaKata is told which box was taken, so a newer one waits."""
        try:
            opened = sealed.open_box(box, self.vault.sealing_key() or b"", c.id)
        except Exception:
            c.state, c.message = "failing", "the credentials were sealed for another connector"
            return
        at, host = opened.get("sealedAt"), opened.get("host")
        if host != self._binds(c):
            c.state, c.message = "failing", "the credentials were sealed for another server"
            return
        held = self.vault.sealed_at(c.id)
        if isinstance(at, int | float) and at == held:
            # The box already filed, whose `taken` didn't reach MoolaKata: say so again.
            self._taken(c, server_at)
            return
        if not isinstance(at, int | float) or at < held:
            c.state, c.message = "failing", "a box older than the credentials held was refused"
            return
        self.vault.put(c.id, opened.get("credentials") or {}, host, at)
        c.state, c.message, c.sign_in, c.last_run = "ok", "credentials received", None, None
        self._taken(c, server_at)

    def _taken(self, c: ConnectionState, server_at: str | None) -> None:
        """MoolaKata told the box is filed, so it deletes its copy (protocol §4.3.2). A call that
        fails is tried again when the same box comes back, and the rest of the answer is
        applied meanwhile."""
        try:
            self.server.call(
                f"/connector/v1/connections/{c.id}/credential/taken",
                {"sealedAt": server_at},
                key=self._action(),
            )
        except Exception as e:
            log.warning("MoolaKata wasn't told a box was filed; at its next report: %s", e)

    def _due(self, c: ConnectionState) -> bool:
        d = self.drivers.get(c.driver)
        if d is None or (d.needs and self.vault.locked):
            return False
        return c.last_run is None or time.time() - c.last_run >= d.interval

    def _run(self, c: ConnectionState) -> None:
        d = self.drivers[c.driver]
        creds = None
        if d.needs:
            creds = self.vault.get(c.id)
            if creds is None:
                address = d.sign_in(c.settings)
                if address and c.sign_in != address:
                    c.sign_in, c.sign_in_at = address, time.time()
                    self._tell_sign_in(c, address)
                c.state, c.message, c.last_run = "new", "waiting for credentials", time.time()
                return
            bound, wanted = self.vault.host(c.id), d.binds(c.settings)
            if bound != wanted:
                # The settings now name another host than the one the credentials were
                # filed for (S18.7.3): nothing is sent until the owner enters them again.
                self.vault.delete(c.id)
                c.state, c.last_run = "needs-sign-in", time.time()
                c.message = (
                    f"the server address changed from {bound or 'none'} to {wanted or 'none'}: "
                    "enter the credentials again"
                )
                return
        try:
            # This run reaches its driver's hosts and no other: not MoolaKata, not another
            # driver's (S18.1.2).
            own = client.Egress()
            own.allow(*d.hosts_for(c.settings))
            r = d.run(c.settings, creds, c.accounts, self.transport.with_egress(own))
        except client.EgressRefused as e:
            c.state, c.message, c.last_run = "failing", f"refused: {e}", time.time()
            return
        except Exception as e:
            c.state, c.message, c.last_run = "failing", f"{type(e).__name__}: {e}", time.time()
            return
        c.state, c.message, c.last_run = r.state, r.message, time.time()
        c.found = r.found or c.found
        if r.sign_in and r.sign_in != c.sign_in:
            c.sign_in_at = time.time()
        c.sign_in = r.sign_in
        if r.credentials is not None:
            self.vault.put(c.id, r.credentials, self.vault.host(c.id))
        if r.sign_in:
            self._tell_sign_in(c, r.sign_in)
        c.backlog.extend(r.files)
        c.last_added = 0
        if len(c.backlog) > WAITING_KEPT:
            # The oldest go: a later run fetches the same days again (S18.8).
            gone = c.backlog[: len(c.backlog) - WAITING_KEPT]
            c.backlog = c.backlog[-WAITING_KEPT:]
            c.message = f"{len(gone)} older file{'s' if len(gone) != 1 else ''} not posted: " + (
                ", ".join(f.name for f in gone)
            )

    def _tell_sign_in(self, c: ConnectionState, address: str) -> None:
        """MoolaKata told where the owner signs in (S18.7.1). A call that fails ends nothing:
        the report carries the address too, and the round goes on (S18.5)."""
        try:
            self.server.call(
                f"/connector/v1/connections/{c.id}/sign-in",
                {"address": address},
                key=self._action(),
            )
        except Exception as e:
            log.warning("MoolaKata wasn't told of a sign-in; the report carries it: %s", e)

    def _post_backlogs(self) -> None:
        """Each file on its own (S18.8, protocol §7): one MoolaKata can't take now waits for a
        later round; one it refuses is dropped and the Connection says why; either way the next
        file, and the next Connection, are posted."""
        for c in self.connections.values():
            kept: list[File] = []
            why = ""
            for f in c.backlog:
                try:
                    out = self._post(c, f)
                except ServerError as e:
                    if e.code in KEEP:
                        kept.append(f)
                        why = KEEP[e.code]
                    else:
                        c.state, c.message = "failing", f"{f.name}: {e.message}"
                    continue
                except (VaultError, OSError, http.client.HTTPException, signing.Refused) as e:
                    # Locked meanwhile, MoolaKata out of reach, or an answer that isn't its own.
                    kept.append(f)
                    why = f"not posted yet ({type(e).__name__}: {e})"
                    continue
                imported = out.get("imported") or {}
                c.last_added = (c.last_added or 0) + int(imported.get("added") or 0)
            c.backlog = kept
            if c.backlog and c.state == "ok":
                c.message = f"{len(c.backlog)} waiting: {why}"

    def _post(self, c: ConnectionState, f: File) -> dict:
        import hashlib

        digest = hashlib.sha256(f.data).hexdigest()
        meta = {"connectionId": c.id, "format": f.fmt, "fileName": f.name, "sha256": digest}
        meta["fetchedAt"] = _iso(time.time())
        b = "mk-connector-" + digest[:16]
        part = '--{}\r\nContent-Disposition: form-data; name="{}"{}\r\nContent-Type: {}\r\n\r\n'
        body = b"".join(
            [
                part.format(b, "meta", "", "application/json").encode(),
                json.dumps(meta).encode(),
                (
                    "\r\n"
                    + part.format(b, "file", f'; filename="{f.name}"', "application/octet-stream")
                ).encode(),
                f.data,
                f"\r\n--{b}--\r\n".encode(),
            ]
        )
        path = f"/connector/v1/accounts/{f.account_id}/files"
        return self.server.call(
            path, body=body, ctype=f"multipart/form-data; boundary={b}", key=self._action()
        )


def decode_code(code: str) -> dict:
    code = "".join(code.split())
    if not code.startswith("mkp1."):
        raise ServerError("code-invalid", "That isn't a pairing code: it starts mkp1.")
    try:
        out = json.loads(keys.unb64(code[5:]))
        assert isinstance(out, dict) and {"a", "f", "c"} <= set(out)
    except ValueError, AssertionError:
        raise ServerError("code-invalid", "The pairing code is damaged: copy it whole.") from None
    return out


def _host(address: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(address).hostname or ""


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    import datetime as dt

    return dt.datetime.fromtimestamp(t, dt.UTC).replace(microsecond=0).isoformat()
