"""Dev mode's linked server (requirements S17.7): griffin-parents, linked and active, with its
two users so linked people can be shared with, and what it shares with Alice and Bob waiting in
its copy. The copy's access key is fixed in dev mode only, so its words are known:
`python -m moolakata.dev.seed_links` prints them. Its address is never reached: dev mode with
stubs makes no outside calls."""

import datetime as dt
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .. import clock, ids
from ..keys import phrase
from ..links import changes, keys
from ..links.copy import public_of
from ..links.manage import apply_directory
from ..store.entities.links import Link, LinkedItem

DEV_COPY_KEY = hashlib.sha256(b"moolakata dev linked copy").digest()[:16]


def words() -> str:
    return " ".join(phrase.to_words(DEV_COPY_KEY))


def _fixed(label: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label).digest())


def seed_links(server, s, people: dict) -> None:
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    from ..store.repos import secrets as secret_repo

    # Dev mode's keys are fixed, so the sample data (and the generated mockup) is the same on
    # every run; a real server makes its link key at random (S11.1.3).
    own = _fixed(b"moolakata dev link key")
    secret_repo.put(
        s,
        server.keys.secrets,
        *keys.SECRET,
        keys.b64(own.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())),
        None,
    )
    peer = _fixed(b"moolakata dev griffin-parents link key")
    link = Link(
        id=ids.new_id("Link"),
        state="active",
        role="inviter",
        peerName="griffin-parents",
        householdName="Margaret & Tom",
        householdAvatar=json.dumps({"kind": "initials", "initials": "MT", "color": "#7a4b9c"}),
        address="https://money.parents.ts.net",
        peerKey=keys.b64(keys.raw_public(peer.public_key())),
        approvedAt=clock.now(),
        lastOkAt=clock.now(),
        pulledAt=clock.now(),
        peerVersion="0.1.0",
        copyPublicKey=public_of(DEV_COPY_KEY),
        copyKeyAt=clock.now(),
        gotSeq=1,
    )
    s.add(link)
    s.flush()
    apply_directory(
        s,
        link,
        {
            "household": {"serverName": "griffin-parents", "name": "Margaret & Tom"},
            "users": [
                {
                    "id": "User_01m4parentsmargaret00000a",
                    "username": "margaret",
                    "displayName": "Margaret Griffin",
                    "email": "margaret@parents.home",
                    "sex": "female",
                },
                {
                    "id": "User_01m4parentstom0000000000b",
                    "username": "tom",
                    "displayName": "Tom Griffin",
                    "email": "tom@parents.home",
                    "sex": "male",
                },
            ],
        },
    )
    alice, bob = people["alice"].id, people["bob"].id
    change = _change(alice, bob)
    now = clock.now()
    for it in change["items"]:
        s.add(
            LinkedItem(
                id=ids.new_id("LItem"),
                linkId=link.id,
                remoteId=it["id"],
                kind=it["kind"],
                ownerName=it["ownerName"],
                sharedAt=dt.datetime.fromisoformat(it["sharedAt"]),
                viewers=json.dumps(it["viewers"]),
                createdAt=now,
            )
        )
    s.flush()
    way = keys.direction(
        keys.fingerprint(keys.raw_public(peer.public_key())),
        keys.fingerprint(keys.raw_public(own.public_key())),
    )
    part = changes.seal_part({"seq": 1, **change}, keys.unb64(public_of(DEV_COPY_KEY)), way)
    _keep(server, link.id, changes.sign(peer, part))


def _keep(server, link_id: str, change: dict) -> None:
    """The change in the copy's inbox as a pull keeps it (link-protocol.md §4.4)."""
    from ..links.copy import folder

    d = folder(server.config.data_dir, link_id) / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    changes.keep(d, link_id, "0000000001", change, {}, keys.unb64(public_of(DEV_COPY_KEY)))


def _months(n: int, end: float, start: float) -> list[dict]:
    today = clock.today().replace(day=1)
    out = []
    for i in range(n):
        y, m = divmod(today.month - 1 - (n - 1 - i), 12)
        day = dt.date(today.year + y, m + 1, 1)
        out.append({"date": day.isoformat(), "value": f"{start + (end - start) * i / (n - 1):.2f}"})
    return out


def _change(alice: str, bob: str) -> dict:
    today = clock.today()
    shared = (clock.now() - dt.timedelta(days=30)).isoformat()
    ira, chk, pf, bud = (
        "Acct_01m4parentsira000000000a",
        "Acct_01m4parentschecking0000b",
        "Pfol_01m4parentsretirement0c",
        "Budgt_01m4parentshousehold0d",
    )

    def item(i, kind, name, viewers):
        return {
            "id": i,
            "kind": kind,
            "name": name,
            "ownerName": "Margaret Griffin",
            "sharedAt": shared,
            "viewers": viewers,
            "includeReceipts": False,
            "version": 1,
        }

    def row(name, balance, change, typ, label, inst):
        return {
            "name": name,
            "balance": balance,
            "change": change,
            "type": typ,
            "typeLabel": label,
            "institution": inst,
            "ownerName": "Margaret Griffin",
        }

    docs = []
    for v in (alice, bob):
        docs += [
            {
                "itemId": chk,
                "path": "",
                "viewer": v,
                "body": {
                    "id": chk,
                    **row(
                        "Joint checking",
                        "18420.55",
                        "-1204.10",
                        "checking",
                        "Checking",
                        "Fifth Third",
                    ),
                },
            },
            {
                "itemId": chk,
                "path": f"/accounts/{chk}",
                "viewer": v,
                "body": {
                    "id": chk,
                    **row(
                        "Joint checking",
                        "18420.55",
                        "-1204.10",
                        "checking",
                        "Checking",
                        "Fifth Third",
                    ),
                    "investing": False,
                },
            },
            {
                "itemId": chk,
                "path": f"/accounts/{chk}/series?range=All",
                "viewer": v,
                "body": {"points": _months(24, 18420.55, 16800), "asOf": today.isoformat()},
            },
            {
                "itemId": chk,
                "path": f"/transactions?account={chk}",
                "viewer": v,
                "body": {
                    "items": [
                        {
                            "date": (today - dt.timedelta(days=d)).isoformat(),
                            "payee": p,
                            "amount": a,
                            "kind": "withdrawal" if a.startswith("-") else "deposit",
                            "categoryLabel": c,
                        }
                        for d, p, a, c in (
                            (2, "Kroger", "-142.18", "Food › Groceries"),
                            (5, "Social Security", "2410.00", "Income › Benefits"),
                            (9, "Duke Energy", "-118.40", "Housing › Utilities"),
                            (12, "CVS Pharmacy", "-36.20", "Health › Pharmacy"),
                        )
                    ],
                    "next": None,
                },
            },
        ]
    docs += [
        {
            "itemId": ira,
            "path": "",
            "viewer": alice,
            "body": {
                "id": ira,
                **row(
                    "Mom's Retirement", "412880.00", "3010.00", "ira", "Traditional IRA", "Vanguard"
                ),
            },
        },
        {
            "itemId": ira,
            "path": f"/accounts/{ira}",
            "viewer": alice,
            "body": {
                "id": ira,
                **row(
                    "Mom's Retirement", "412880.00", "3010.00", "ira", "Traditional IRA", "Vanguard"
                ),
                "investing": True,
            },
        },
        {
            "itemId": ira,
            "path": f"/accounts/{ira}/series?range=All",
            "viewer": alice,
            "body": {"points": _months(36, 412880, 351200), "asOf": today.isoformat()},
        },
        {
            "itemId": ira,
            "path": f"/accounts/{ira}/holdings",
            "viewer": alice,
            "body": {
                "cash": "2480.00",
                "total": "412880.00",
                "holdings": [
                    {
                        "symbol": "VTI",
                        "name": "Vanguard Total Stock Market ETF",
                        "quantity": "820",
                        "value": "244196.00",
                        "gain": "61240.00",
                    },
                    {
                        "symbol": "BND",
                        "name": "Vanguard Total Bond Market ETF",
                        "quantity": "1600",
                        "value": "117376.00",
                        "gain": "-2110.00",
                    },
                    {
                        "symbol": "VXUS",
                        "name": "Vanguard Total International Stock ETF",
                        "quantity": "760",
                        "value": "48828.00",
                        "gain": "6904.00",
                    },
                ],
            },
        },
        {
            "itemId": ira,
            "path": f"/transactions?account={ira}",
            "viewer": alice,
            "body": {
                "items": [
                    {
                        "date": (today - dt.timedelta(days=11)).isoformat(),
                        "payee": "Dividend · VTI",
                        "amount": "842.10",
                        "kind": "dividend",
                        "categoryLabel": "Income › Dividends",
                    },
                    {
                        "date": (today - dt.timedelta(days=40)).isoformat(),
                        "payee": "RMD distribution",
                        "amount": "-4200.00",
                        "kind": "withdrawal",
                        "categoryLabel": "",
                    },
                ],
                "next": None,
            },
        },
        {
            "itemId": pf,
            "path": "",
            "viewer": alice,
            "body": {
                "id": pf,
                "name": "Retirement",
                "value": "412880.00",
                "ownerName": "Margaret Griffin",
            },
        },
        {
            "itemId": pf,
            "path": f"/portfolios/{pf}",
            "viewer": alice,
            "body": {
                "id": pf,
                "name": "Retirement",
                "value": "412880.00",
                "ownerName": "Margaret Griffin",
            },
        },
        {
            "itemId": pf,
            "path": f"/portfolios/{pf}/holdings",
            "viewer": alice,
            "body": {
                "cash": "2480.00",
                "total": "412880.00",
                "holdings": [
                    {
                        "symbol": "VTI",
                        "name": "Vanguard Total Stock Market ETF",
                        "value": "244196.00",
                        "weight": "59.1",
                    },
                    {
                        "symbol": "BND",
                        "name": "Vanguard Total Bond Market ETF",
                        "value": "117376.00",
                        "weight": "28.4",
                    },
                    {
                        "symbol": "VXUS",
                        "name": "Vanguard Total International Stock ETF",
                        "value": "48828.00",
                        "weight": "11.8",
                    },
                ],
            },
        },
        {
            "itemId": pf,
            "path": f"/portfolios/{pf}/series?range=All",
            "viewer": alice,
            "body": {
                "points": _months(36, 412880, 351200),
                "benchmark": "VT",
                "twr": "17.6",
                "irr": "17.1",
                "contributed": "0.00",
                "growth": "61680.00",
                "start": "351200.00",
                "end": "412880.00",
            },
        },
        {
            "itemId": pf,
            "path": f"/portfolios/{pf}/returns",
            "viewer": alice,
            "body": [
                {
                    "id": pf,
                    "name": "Retirement",
                    "periods": {"1M": "0.9", "3M": "3.1", "YTD": "9.8", "1Y": "11.2", "3Y": "7.4"},
                }
            ],
        },
        {
            "itemId": bud,
            "path": "",
            "viewer": alice,
            "body": {"id": bud, "name": "Household", "ownerName": "Margaret Griffin"},
        },
        {
            "itemId": bud,
            "path": f"/budgets/{bud}/month",
            "viewer": alice,
            "body": {
                "month": today.replace(day=1).isoformat(),
                "rows": [
                    {
                        "label": "Groceries",
                        "planned": "600.00",
                        "actual": "412.80",
                        "remaining": "187.20",
                    },
                    {
                        "label": "Utilities",
                        "planned": "280.00",
                        "actual": "236.40",
                        "remaining": "43.60",
                    },
                    {
                        "label": "Health",
                        "planned": "150.00",
                        "actual": "186.20",
                        "remaining": "-36.20",
                    },
                ],
            },
        },
    ]
    return {
        "seq": 1,
        "asOf": clock.now().isoformat(),
        "full": True,
        "items": [
            item(ira, "account", "Mom's Retirement", [alice]),
            item(chk, "account", "Joint checking", [alice, bob]),
            item(pf, "portfolio", "Retirement", [alice]),
            item(bud, "budget", "Household", [alice]),
        ],
        "removed": [],
        "docs": docs,
        "docsRemoved": [],
    }


if __name__ == "__main__":
    print(words())
