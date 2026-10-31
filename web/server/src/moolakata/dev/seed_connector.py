"""Dev mode's MoolaKata Connector (requirements S17.7, S18): paired, unlocked, reporting, with
Alice's Schwab and credit-union sign-ins and Bob's bank, so the screens and the
generated mockup show the connector as a household uses it. Its keys are fixed so the sample
data is the same on every run; it never answers, since nothing calls it (S18.2.2)."""

import datetime as dt
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import false, select

from .. import clock, ids
from ..links import keys
from ..store.entities.accounts import Account
from ..store.entities.connector import Connection, Connector


def seed_connector(s, people: dict) -> None:
    alice, bob, admin = people["alice"], people["bob"], people["admin"]
    action, status = (
        Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(b"moolakata dev connector " + which).digest()
        )
        for which in (b"action", b"status")
    )
    sealing = X25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"moolakata dev connector sealing").digest()
    )
    now = clock.now()
    row = Connector(
        id=ids.new_id("Cnctr"),
        state="paired",
        actionKey=keys.b64(action.public_key().public_bytes_raw()),
        statusKey=keys.b64(status.public_key().public_bytes_raw()),
        sealingKey=keys.b64(sealing.public_key().public_bytes_raw()),
        pairedAt=now - dt.timedelta(days=3, hours=4),
        pairedById=admin.id,
        lastReportAt=now - dt.timedelta(minutes=3),
        locked=False,
        connectorVersion="0.1.0",
        protocol=1,
    )
    s.add(row)
    s.flush()

    def connection(owner, driver, label, state, message, run, added, found, settings):
        c = Connection(
            id=ids.new_id("Conn"),
            ownerId=owner.id,
            connectorId=row.id,
            driver=driver,
            label=label,
            state=state,
            message=message,
            lastRunAt=now - run if run else None,
            lastRunAdded=added,
            institutionAccounts=json.dumps(found),
            settings=json.dumps(settings, sort_keys=True),
        )
        s.add(c)
        return c

    schwab = connection(
        alice,
        "schwab",
        "Schwab login",
        "ok",
        "14 new",
        dt.timedelta(hours=2),
        14,
        [{"name": "Individual", "last4": "4417"}, {"name": "Rollover IRA", "last4": "0921"}],
        {"appKey": "dev-app-key"},
    )
    connection(
        alice,
        "ofx-direct",
        "Credit union",
        "needs-sign-in",
        "the password was refused",
        dt.timedelta(days=1, hours=5),
        None,
        [{"name": "Everyday Checking", "last4": "1204"}],
        {
            "url": "https://ofx.creditunion.example/",
            "org": "CU",
            "fid": "1204",
            "accountType": "CHECKING",
            "accountId": "1204",
        },
    )
    bank = connection(
        bob,
        "ofx-direct",
        "UMB Bank",
        "ok",
        "1 statement",
        dt.timedelta(days=1),
        1,
        [{"name": "Checking", "last4": "3311"}],
        {
            "url": "https://ofx.umb.example/ofx",
            "org": "UMB",
            "fid": "1001",
            "accountType": "CHECKING",
            "accountId": "3311",
        },
    )
    s.flush()
    # The accounts they keep current (S18.6.2): Alice's brokerage from Schwab, Bob's checking
    # from his bank's OFX server.
    brokerage = s.scalars(
        select(Account).where(
            Account.ownerId == alice.id, Account.type == "brokerage", Account.deleted == false()
        )
    ).first()
    if brokerage is not None:
        brokerage.connectionId, brokerage.syncAccount = schwab.id, "Individual ••4417"
    checking = s.scalars(
        select(Account).where(
            Account.ownerId == bob.id, Account.type == "checking", Account.deleted == false()
        )
    ).first()
    if checking is not None:
        checking.connectionId, checking.syncAccount = bank.id, "Joint Household ••3311"
