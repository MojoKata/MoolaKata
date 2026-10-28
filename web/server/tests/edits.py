"""Changes made as a dialog's draft makes them (requirements S13.8.11): one record changed or
deleted through the save, for tests of what a change does rather than of the save itself."""


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
