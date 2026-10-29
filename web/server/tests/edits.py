"""Changes made as a dialog's draft makes them (requirements S13.8.11): one record changed or
deleted through the save, for tests of what a change does rather than of the save itself."""

from decimal import Decimal


def _save(c, op: dict, confirm: bool):
    r = c.post("/ui/api/save", json={"ops": [op]})
    if confirm and r.status_code == 409 and r.json()["code"] == "confirm-needed":
        asks = [{"code": a["code"], "id": a["id"]} for a in r.json()["asks"]]
        r = c.post("/ui/api/save", json={"ops": [op], "confirm": asks})
    return r


def change(c, entity: str, record: dict, confirm: bool = False, **fields):
    """`record` (as read, with its id and version) with `fields` changed; `confirm` answers
    the questions the change asks."""
    op = {"op": "update", "entity": entity, "id": record["id"], "version": record["version"],
          "fields": fields}  # fmt: skip
    return _save(c, op, confirm)


def remove(c, entity: str, record: dict, confirm: bool = False):
    op = {"op": "delete", "entity": entity, "id": record["id"], "version": record["version"]}
    return _save(c, op, confirm)


def saved(r) -> dict:
    """The record a one-op save answered with."""
    assert r.status_code == 200, r.text
    return r.json()["saved"][0]["record"]


def asked(r) -> list[str]:
    """The codes of the questions a save asked."""
    assert r.status_code == 409 and r.json()["code"] == "confirm-needed", r.text
    return [a["code"] for a in r.json()["asks"]]


def edit(c, entity: str, path: str, confirm: bool = False, **fields):
    """`fields` changed on the record its route `path` reads, at the version it has now."""
    return change(c, entity, c.get(path).json(), confirm, **fields)


def drop(c, entity: str, path: str, confirm: bool = False):
    """The record its route `path` reads, deleted at the version it has now."""
    return remove(c, entity, c.get(path).json(), confirm)


def new_id(prefix: str) -> str:
    """An id as the browser makes one, from the server's clock (schema.md §2)."""
    from test_save import made_at

    from moolakata import clock

    return made_at(prefix, clock.now())


def terms(c, account_id: str, **values):
    """A loan's terms set as the account's dialogs set them (S1.9): made when it has none,
    else changed."""
    have = c.get(f"/ui/api/accounts/{account_id}/loan").json()["terms"]
    if have is None:
        op = {"op": "create", "entity": "Loan", "id": new_id("Loan"),
              "fields": {"accountId": account_id, **values}}  # fmt: skip
        return _save(c, op, False)
    return change(c, "Loan", have, **values)


def sell(c, item_id: str, soldOn, proceeds, fees="0"):
    """An item's sale recorded (S1.10.5)."""
    path = f"/ui/api/items/{item_id}"
    return edit(c, "Item", path, soldOn=soldOn, proceeds=proceeds, saleFees=fees)


def plan529(c, account_id: str, **values):
    """A 529's plan set as its Settings set it (S1.8.1): made when it has none, else changed."""
    have = c.get(f"/ui/api/accounts/{account_id}/plan529").json()
    if have["id"] is None:
        op = {"op": "create", "entity": "EdPln", "id": new_id("EdPln"),
              "fields": {"accountId": account_id, **values}}  # fmt: skip
        return _save(c, op, False)
    return change(c, "EdPln", have, **values)


def giving_plan(c, year: int, **values):
    """A year's giving plan set as its dialog sets it (S7.9.1): made when there is none, else
    changed."""
    have = c.get("/ui/api/giving", params={"year": year}).json()["plan"]
    if have is None:
        op = {"op": "create", "entity": "GvPln", "id": new_id("GvPln"),
              "fields": {"year": year, **values}}  # fmt: skip
        return _save(c, op, False)
    return change(c, "GvPln", have, **values)


def wallet(c, account_id: str, text: str, gap_limit: int | None = None):
    """A wallet's keys and addresses set as its account's draft sets them (S1.6.1)."""
    fields = {"walletKeys": text} | ({"gapLimit": gap_limit} if gap_limit else {})
    return edit(c, "Acct", f"/ui/api/accounts/{account_id}", **fields)


def reconcile(c, account_id: str, date: str, balance: str) -> dict:
    """A statement to tick off against (S1.11.6), started as its dialog starts it."""
    fields = {"accountId": account_id, "statementDate": date, "statementBalance": balance}
    op = {"op": "create", "entity": "Recon", "id": new_id("Recon"), "fields": fields}
    return saved(_save(c, op, False))


def share(c, kind: str, item_id: str, users=None, groups=None, receipts=None, too=False):
    """An item shared as its dialog's draft shares it (S10.4): for each user and group named,
    its grant made, changed or taken away (`none`); Include receipts per linked server; with
    `too`, a portfolio's accounts its people can't see shared at Read in a second save, as the
    dialog's Share these accounts too does. The last save's answer."""
    v = c.get(f"/ui/api/shares/{kind}/{item_id}").json()
    linked = {u["id"]: link["linkId"] for link in v["links"] for u in link["users"]}
    people = v["users"] + [x for g in v["links"] for x in g["users"]]
    have = {("userId", u["id"]): u for u in people}
    have |= {("groupId", g["id"]): g for g in v["groups"]}
    receipts = receipts or {}
    wanted = [(("userId", k), x) for k, x in (users or {}).items()]
    wanted += [(("groupId", k), x) for k, x in (groups or {}).items()]
    for (field, gid), g in have.items():
        if g.get("shareId") and linked.get(gid) in receipts and (field, gid) not in dict(wanted):
            wanted.append(((field, gid), g["level"]))
    ops = []
    for (field, gid), level in wanted:
        g = have.get((field, gid)) or {}
        rec = {
            "kind": kind,
            "itemId": item_id,
            field: gid,
            "level": level,
            "includeReceipts": bool(receipts.get(linked.get(gid), g.get("includeReceipts"))),
        }
        if not g.get("shareId"):
            if level != "none":
                ops.append(
                    {"op": "create", "entity": "Share", "id": new_id("Share"), "fields": rec}
                )
        elif level == "none":
            ops.append(
                {"op": "delete", "entity": "Share", "id": g["shareId"], "version": g["version"]}
            )
        else:
            fields = {k: rec[k] for k in ("level", "includeReceipts")}
            ops.append(
                {
                    "op": "update",
                    "entity": "Share",
                    "id": g["shareId"],
                    "version": g["version"],
                    "fields": fields,
                }
            )
    r = c.post("/ui/api/save", json={"ops": ops})
    if too and r.status_code == 200:
        v = c.get(f"/ui/api/shares/{kind}/{item_id}").json()
        yours = {a["id"] for a in v["accounts"] if a["yours"]}
        ops = [
            {
                "op": "create",
                "entity": "Share",
                "id": new_id("Share"),
                "fields": {"kind": "account", "itemId": aid, "userId": uid, "level": "read"},
            }
            for uid, aids in v["hidden"].items()
            for aid in aids
            if aid in yours
        ]
        if ops:
            r = c.post("/ui/api/save", json={"ops": ops})
    return r


def save_settings(c, values: dict):
    """Settings saved as their sections' drafts save them (S16): each key's record changed, or
    made when it has none. The save's answer: a value its definition refuses names its key."""
    v = c.get("/ui/api/settings").json()
    ops = []
    for key, value in values.items():
        ref = v["records"].get(key)
        if ref:
            op = {"op": "update", "entity": "Setng", "id": ref["id"], "version": ref["version"],
                  "fields": {"value": value}}  # fmt: skip
        else:
            op = {"op": "create", "entity": "Setng", "id": new_id("Setng"),
                  "fields": {"key": key, "value": value}}  # fmt: skip
        ops.append(op)
    return c.post("/ui/api/save", json={"ops": ops})


def tag(c, name: str) -> str:
    """The caller's tag of this name (S2.6): its id, the tag made through the save when new."""
    have = {t["name"]: t["id"] for t in c.get("/ui/api/tags").json()["items"]}
    if name.lower() in have:
        return have[name.lower()]
    op = {"op": "create", "entity": "Tag", "id": new_id("Tag"), "fields": {"name": name}}
    return saved(c.post("/ui/api/save", json={"ops": [op]}))["id"]


def create(c, entity: str, confirm: bool = False, **fields):
    """A record made as a form's draft makes it: an id made the browser's way, through the
    save; the save's answer."""
    op = {"op": "create", "entity": entity, "id": new_id(entity), "fields": fields}
    return _save(c, op, confirm)


def loan_payment(c, loan_id: str, date: str, amount, from_account: str | None = None,
                 transaction: str | None = None, parts: dict | None = None):  # fmt: skip
    """A loan payment as its dialog's draft records it (S1.9.3): the loan's transaction split
    by the schedule (or by `parts`), with its bank half made from `from_account`, or paired
    with the bank `transaction` already recorded. The save's answer."""
    amount = str(amount)
    split = c.get(f"/ui/api/accounts/{loan_id}/loan/split",
                  params={"date": date, "amount": amount}).json()  # fmt: skip
    values = parts or {k: split[k] for k in split["categories"]}
    txn = {"accountId": loan_id, "date": date, "amount": amount, "payee": "Payment",
           "kind": "transfer" if from_account or transaction else "deposit"}  # fmt: skip
    ops = []
    if from_account:
        name = c.get(f"/ui/api/accounts/{loan_id}").json()["name"]
        bank = {"op": "create", "entity": "Txn", "id": new_id("Txn"),
                "fields": {"accountId": from_account, "date": date, "amount": f"-{amount}",
                           "kind": "transfer", "payee": name}}  # fmt: skip
        ops.append(bank)
        txn["transferWithId"] = bank["id"]
    elif transaction:
        txn["transferWithId"] = transaction
    tid = new_id("Txn")
    ops.insert(0, {"op": "create", "entity": "Txn", "id": tid, "fields": txn})
    for part, value in values.items():
        if Decimal(str(value or 0)):
            ops.append({"op": "create", "entity": "Split", "id": new_id("Split"),
                        "fields": {"transactionId": tid, "amount": str(value),
                                   "categoryId": split["categories"].get(part)}})  # fmt: skip
    return c.post("/ui/api/save", json={"ops": ops})


def option_trade(c, account_id: str, day: str, action: str, underlying: str, right: str,
                 strike, expiry: str, contracts, premium, fees="0", multiplier=None,
                 confirm: bool = False):  # fmt: skip
    """An option trade as its dialog's draft records it (S3.2): a transaction of the trade's
    kind with its contract, its amount the cash the trade comes to. The save's answer."""
    from moolakata import options

    amount = options.cash(action, Decimal(str(contracts)), Decimal(str(premium)),
                          Decimal(str(fees or 0)), int(multiplier or 100))  # fmt: skip
    fields = {"accountId": account_id, "date": day, "kind": action, "symbol": underlying,
              "right": right, "strike": str(strike), "expiry": expiry,
              "quantity": str(contracts), "price": str(premium), "fees": str(fees or 0),
              "amount": str(amount), "multiplier": multiplier}  # fmt: skip
    return create(c, "Txn", confirm, **fields)
