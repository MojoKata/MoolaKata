"""Who opens a receipt's file, kind by kind and reader by reader (requirements S9.6; the values,
taxes and options walk, 10.1): one table of what S9.6 says, every cell asked of the server. A
file is seen by whoever can read what it is attached to: a transaction, an account (a statement,
a loan), an item, a 529 expense, a gift through its gift plan, a donation through its giving
plan, and a tax document through its book; an unattached one is its owner's alone. Attaching
to something needs write on it. Across a link, *Include receipts* decides (test_links).
"""

from conftest import make_user, sign_in
from edits import attach, change, giving_plan, make, saved, share
from test_accounts import add, new_account
from test_receipts import png

KINDS = ("transaction", "statement", "item", "loan", "expense", "gift", "donation",
         "tax-document", "unattached")  # fmt: skip
READERS = ("owner", "co-filer", "writer", "reader", "member", "stranger")


def expected(kind: str, reader: str) -> bool:
    """S9.6, as a table."""
    if reader == "owner":
        return True
    if reader == "stranger" or kind == "unattached":
        return False
    if reader == "co-filer":
        return kind == "tax-document"  # the book is hers; nothing else is shared with her
    return True  # every container here is shared with the writer, the reader and the group


def _made(srv, admin_client) -> dict:
    names = ("alice", "bob", "dave", "erin", "gina", "mallory")
    for n in names:
        make_user(srv, n)
    c = {n: sign_in(srv, n) for n in names}
    uid = {n: c[n].get("/ui/api/session").json()["user"]["id"] for n in names}
    alice = c["alice"]
    pa = alice.get("/ui/api/profile").json()["personId"]
    pb = c["bob"].get("/ui/api/profile").json()["personId"]
    r = make(alice, "Rltn", person1Id=pa, person2Id=pb, relation="spouse", fromDate="2009-06-14")
    assert c["bob"].post(f"/ui/api/relationships/{r.json()['id']}/confirm").status_code == 200
    group = make(admin_client, "Group", name="Helpers", memberIds=[uid["gina"]]).json()
    receipts: dict[str, str] = {}

    def upload(name: str) -> str:
        # Each file its own bytes: the same file uploaded twice is one receipt (S9.4).
        image = png(color=(len(receipts) * 20, 30, 30))
        r = alice.post("/ui/api/receipts", files={"file": (f"{name}.png", image, "image/png")})
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    checking = new_account(alice, name="Checking", mask="1111")
    t = add(alice, checking["id"], "-42.00", "2026-03-02", payee="Hardware store")
    receipts["transaction"] = upload("txn")
    saved(attach(alice, receipts["transaction"], t["id"]))
    receipts["statement"] = upload("statement")
    saved(attach(alice, receipts["statement"], checking["id"], kind="account"))
    homes = new_account(alice, name="Home", type="real-estate")
    house = make(alice, "Item", accountId=homes["id"], name="27 Oak Ln", acquiredOn="2020-01-10",
                 costBasis="400000", valuation="valuations").json()  # fmt: skip
    receipts["item"] = upload("item")
    saved(attach(alice, receipts["item"], house["id"], kind="item"))
    loan = new_account(alice, name="Mortgage", type="mortgage", mask="2222")
    receipts["loan"] = upload("loan")
    saved(attach(alice, receipts["loan"], loan["id"], kind="account"))
    college = new_account(alice, name="529", type="529", mask="3333")
    ex = make(alice, "QExpn", accountId=college["id"], date="2026-08-15", kind="tuition",
              amount="5000").json()  # fmt: skip
    receipts["expense"] = upload("expense")
    saved(attach(alice, receipts["expense"], ex["id"], kind="expense"))
    plan = make(alice, "GfPln", name="Emma Griffin", sex="female").json()
    g = make(alice, "Gift", description="Paints", people=[plan["personId"]]).json()
    receipts["gift"] = upload("gift")
    saved(change(alice, "Gift", g, receiptIds={"add": [receipts["gift"]], "remove": []}))
    saved(giving_plan(alice, 2026, percent="10", incomeBasis="gross", income="100000"))
    church = make(alice, "Orgzn", name="St. Mark's Parish").json()
    d = make(alice, "Dnatn", date="2026-02-01", kind="cash", organisationId=church["id"],
             amount="200").json()  # fmt: skip
    receipts["donation"] = upload("donation")
    saved(change(alice, "Dnatn", d, receiptIds={"add": [receipts["donation"]], "remove": []}))
    book = make(alice, "TaxBk", year=2026, filers=[uid["alice"], uid["bob"]]).json()
    assert c["bob"].post(f"/ui/api/tax-books/{book['id']}/accept").status_code == 200
    receipts["tax-document"] = upload("w2")
    r = make(alice, "TxDoc", bookId=book["id"], form="W-2", issuer="Acme Corp",
             receiptId=receipts["tax-document"])  # fmt: skip
    assert r.status_code == 200, r.text
    receipts["unattached"] = upload("loose")
    giving = alice.get("/ui/api/giving", params={"year": 2026}).json()["plan"]
    shared = [("account", checking["id"]), ("account", homes["id"]), ("account", loan["id"]),
              ("account", college["id"]), ("gift-plan", plan["id"]),
              ("giving-plan", giving["id"]), ("tax-book", book["id"])]  # fmt: skip
    for kind, item_id in shared:
        r = share(alice, kind, item_id, users={uid["dave"]: "write", uid["erin"]: "read"},
                  groups={group["id"]: "read"})  # fmt: skip
        assert r.status_code == 200, (kind, r.text)
    return {"c": c, "receipts": receipts, "transaction": t, "book": book}


def test_a_file_opens_for_whoever_reads_what_it_is_kept_with(server, admin_client):
    world = _made(server, admin_client)
    who = {"owner": "alice", "co-filer": "bob", "writer": "dave", "reader": "erin",
           "member": "gina", "stranger": "mallory"}  # fmt: skip
    wrong = []
    for kind in KINDS:
        rid = world["receipts"][kind]
        for reader in READERS:
            got = world["c"][who[reader]].get(f"/ui/api/receipts/{rid}/file").status_code
            if (got == 200) != expected(kind, reader):
                wrong.append(f"{kind} by the {reader}: {got}")
    assert not wrong, "\n".join(wrong)
    _attaching_needs_write(world)


def _attaching_needs_write(world):
    """S9.6: the writer attaches a receipt of their own to Alice's transaction; the reader
    can't."""
    c, t = world["c"], world["transaction"]
    for who, ok in (("dave", True), ("erin", False)):
        image = png(color=(5, 200 if who == "dave" else 100, 5))
        r = c[who].post("/ui/api/receipts", files={"file": (f"{who}.png", image, "image/png")})
        rid = r.json()["id"]
        got = attach(c[who], rid, t["id"])
        assert (got.status_code == 200) == ok, (who, got.text)
