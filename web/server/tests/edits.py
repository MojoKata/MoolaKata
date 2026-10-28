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
