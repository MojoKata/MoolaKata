# Walk: `mine` and the four permissions in the API and the browser

Decision 6.4 of the access-views walk (`access-views-walk.md`) kept the API's `level` and
`canWrite`, derived from the views, and left the move to `mine` and the four permissions to the
next PR. This walk settles its shape.

**Found:** 26 API fields say what the reader may do: `level` (owner, write, read) on 15
schemas, `canWrite` on 15 (BookDetail has both). Four more `level` fields (UserGrant,
GroupGrant, ShareRecord, Via) are a share's level. About 120 browser reads in 25 files. The
requirements name only a share's level.

## Decisions

1. **The names (locked Nov 1, 3:55 PM).** The user chose a group over flat fields: it keeps the
   reader's permissions out of the entity's own field names, and these fields only ever travel
   from the server to the browser.
   1. The group is `access`.
   2. `mine` is inside it (a fact of the row, not a permission, but as reader-relative and as
      display-only).
   3. Its fields keep the views' column names: `access.mine`, `access.writable`,
      `access.deletable`, `access.shareable`, `access.configurable`.
   4. Two guards: a static check that no request body schema in the API document has
      `access`; `Record` hoists `access` out of the data it is given into a read-only
      `rec.access`, kept out of its data, `changes()` and snapshots. A new record has none and
      is fully editable until saved.

   Creation became its own item (2): which parent permission allows a child to be made.

2. **Creation (locked Nov 1, 3:58 PM).** Each table declares how its records are made, as each
   declares how they are seen.
   1. A `creates` field on `Seen`, beside `key` and `writes`.
   2. Its values: `Via(key, permission)` (that permission on the parent the key names; a
      child's default is its key and its `writes`), `"anyone"` (any signed-in user: roots,
      Receipt), `"own"` (per-user tables), `"admin"` (admin tables), `"never"` (the server's
      own), `"code"` (written in the hook: Relationship, Person, User, Group, Connector, Link;
      the parent's answer says whether Add is offered). Household tables declare their own.
   3. Two more forms: all of several `Via`s (Reimbursement, TransferMatch: both sides
      `writable`); by kind, a kind column picking the parent's view (ReceiptLink's target,
      Share's item with `shareable`).
   4. `save.py` checks the declaration before the hook: an unreadable parent 404, a parent
      read without the permission 403. Hooks keep their state rules; their hand checks go. A
      table-driven test over every saveable kind proves both answers.
   5. Codegen writes each rule into the API document (`x-creates` on its `…Record` schema) and
      `fields.js`; `draft.canAdd(Cls, parent)` reads the parent's `access`; every Add control
      uses it.

3. **Which objects carry `access` (locked Nov 1, 4:00 PM).**
   1. Records the reader reads (rows and details) carry the whole group, all five fields, from
      one shared model.
   2. Wrappers over a parent's list (ItemsView, LoanView, MonthView, ContributionsView,
      WithdrawalsView) lose `canWrite`; their components use the parent's `access` and
      `canAdd`.
   3. A reference that offers an action carries the `access` of the item it names (InBudget,
      for *Leave out*); one that offers none carries none.

   Raised and withdrawn in item 6: the budget screen's Settings button on `canWrite`
   (`screens/budgets.js:288`) is right; a budget's own fields are `writable`, and its accounts
   picker already shows only to the owner (`screens/budgets.js:1552`).

4. **Shares (locked Nov 1, 4:17 PM).** The user's refinement: a share is a coloured edge
   between an item and a grantee, one table per shareable kind, its colour a row of a class
   table holding the views' permission columns.
   1. **AccessClass** holds `writable`, `deletable`, `shareable`, `configurable` and a unique
      `name`; fixed rows `read` and `write`, seeded by the migration (a further class is a
      requirements change). Each root's access view takes a share's permissions from its
      class, not from a hard-coded "a share gives `writable` at most".
   2. **`<Table>Share`**, generated for each shareable kind from its `Seen` declaration:
      `targetId` (cascading key to the item), `userId` or `groupId` (a check that exactly one
      is set), `accessClassId`, `includeReceipts`, `createdById`, soft delete; two partial
      unique indexes, (targetId, userId) and (targetId, groupId). It is an entity: its own
      prefixed id, a row each in schema.md's prefix table.
   3. The API names the class by its name: `allow: "read" | "write"` (ShareRecord's
      successors, Via), `"none" | "read" | "write"` (UserGrant, GroupGrant), typed in the API
      document; the share dialog is unchanged on screen.
   4. No polymorphic `Share` table and no union view. A generated registry (kind to
      `<Table>Share`, from the `Seen` declarations) serves the reads across kinds (*Shared by
      me*, the incoming list, the linked-server crossing and its listing,
      `remove_link_shares`), merged in Python. If that grows, *Shared by me* can show one kind
      at a time.
   5. Each share table gets a generated access view: whoever holds `shareable` on its target
      reads and changes it; the grantee reads their own.
   6. One save kind per share table (`AccountShareRecord {targetId, userId | groupId, allow}`,
      …); the share dialog picks the record class by kind.
   7. The linked-server protocol matches the schema: no `kind` mapped at the edge (nothing
      runs MoolaKata yet; a compatibility layer waits until one is needed).
   8. `ShareLevel` goes: each root's view joins its own share table, AccessClass and group
      memberships.
   9. All of it on this PR.

5. **A tax book waiting to be accepted (locked Nov 1, 4:19 PM).** `GET /tax-books` answers
   `{books: BookRow[], waiting: WaitingBook[]}`; `WaitingBook` is `{id, year, filers, label}`
   with no `access` (the user reads no row of it), so BookRow's `access` is always the view's.

6. **Which permission each browser control reads (locked Nov 1, 4:21 PM).**
   1. Editing, and rows one can edit: `access.writable`.
   2. Add controls and pickers of accounts one can add to: `canAdd(Cls, parent)` (2.5).
   3. *Share*, and fetching an item's shares: `access.shareable`.
   4. *Delete*: `access.deletable`.
   5. Settings proper (a kind's `settings` fields, what it covers: an account's settings form,
      a budget's accounts picker, a portfolio's accounts, a projection's *Make active* / *Stop
      following*, bitcoin pairs): `access.configurable`.
   6. Whose it is (the *Mine* / *Shared with me* / *Shared by me* filters, shared-with-me marks
      and labels, an account's *Your view of it*, a projection's *Show on my Dashboard*, "your
      / Alice's assumptions", one's own active projections for a goal): `access.mine`.

   A pill's "read" / "write" comes from `access.writable`; share levels read the share's
   `allow`. No behaviour changes: an owner holds all four and a share at most `writable`, so
   each rule picks the same people as the owner check it replaces.

7. **Where `mine` comes from (locked Nov 1, 4:22 PM).** A `mine` column in every access view,
   beside the four permissions: a plain root's owner row 1 and share rows 0; a child its
   parent's; a tax book its owner and accepted filers; a person one's own person, or one added
   and not yet joined (an admin holds all four without it); receipts, gifts, donations their
   owner's row; per-user rows 1; receipt links and other read-only paths 0. `access` comes from
   one row of one query. Guards: a test that a `mine` row is the owner's row; a static check
   that nothing authorises on it (`need()` takes only the four permissions). It stays a fact,
   never a permission (access walk, decision 2); the views' docstring and schema.md §7 say so.

