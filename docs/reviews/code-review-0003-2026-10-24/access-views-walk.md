# Walk-through: access views

Started Oct 31, 2026, from the receipts walk ([`receipts-walk.md`](receipts-walk.md), CR3-47):
the user chose to move every visibility rule into `<Table>Access` views, built on the receipts
PR (`cr3-receipts`) as its first commit(s). Decisions log; nothing is applied until the final
approval.

## Items

1. Which tables get a view, split by category (the user, 2:24 PM): 1a many-to-many relations,
   1b roots, 1c children, 1d rules of their own, 1e rows joining two items, 1f per-user rows,
   1g household-wide and server data. Each category's own rules are settled in its sub-item,
   so item 4 keeps only what crosses them (inactive users and groups, remote users).
2. What a view returns
3. How views are defined and kept current
4. The hard rules in SQL (filers, gifts, donations, people, projections, inactive and remote
   users, rows joining two items)
5. Enforcement
6. What happens to the Python rules
7. Moving the call sites over
8. Paths outside the ORM
9. Where it is written down

Found while surveying, for item 4: `gifts.visible_gifts` hides a gift from the person it is
for, `gifts.level_on_gift` does not, and `receipts._kept_level` uses the latter (not yet run).

## Decisions

1. **Many-to-many tables (1a of 9): no view of their own.** The nine pure relations (no
   synthetic id): UserGroups, GiftPersons, PortfolioAccounts, ReceiptTags, RuleTags,
   TransactionTags, TaxDependentAccounts, BudgetLeaveOuts, ShownProjections. They declare
   *relation*. A query never asks for a relation's rows alone: it asks for one side's rows
   (a portfolio's accounts are `select Account … where portfolioId = ?`, joined through
   PortfolioAccounts), and that side's view is joined as for any other query of it
   (AccountAccess, so viewers see only the accounts shared with them, S5.1.1). A query
   returning both sides joins both views. Tables with an id that join
   two items (Relationship, TransferMatch, WashSale, Reimbursement, Contribution) are entities
   and stay in item 4.

2. **Permissions as booleans (2a of 9, taken ahead of 1b).** A view's row means the user reads
   the item; no row, they don't. Four boolean columns say what more they hold, each collapsed
   over several paths with `MAX`:
   1. `writable`: changes what the item holds.
   2. `deletable`: deletes it.
   3. `shareable`: changes its sharing, and sees who holds it.
   4. `configurable`: its settings, what it covers (a budget's, portfolio's or tax book's
      accounts; which projection is active) and its secrets (an account's connection and sync
      account, credentials). A fifth column (`secretsReadable`) comes only if seeing secrets
      and changing settings must part.

   Every permission implies `writable`, by how the views are built, and a test holds it. There
   is **no `owner` column**: is-it-mine (net worth, *shared by me*, the inbox, one's own
   projections always shown) is a fact of the row, its `ownerId` or its parent's, never a
   permission to check. **Tax books:** accepted filers hold all four, and a filer's book is
   their own for is-it-mine (`ownerId` = me or an accepted filer), with no *shared with me*
   mark. The Python names *read*, *write*, *owner* remain only where text is shown or a 403 is
   worded.

3. **Roots (1b of 9).** A base view `ShareLevel(kind, itemId, userId, writable)` collapses
   direct and active-group shares for active users, once. The six plain roots (Account,
   Portfolio, Budget, GiftPlan, GivingPlan, Projection) get a generated
   `<Root>Access(targetId, userId, writable, deletable, shareable, configurable)`: the owner's
   row with all four true, and `ShareLevel`'s rows of its kind (a share gives `writable` at
   most). `TaxBookAccess` and `PersonAccess` are hand-written on the same base: the book adds
   its accepted filers with all four; the person keeps S10.10.2's rules: all four for the
   person's own user, admins, and whoever added them until they join; read for every local user
   when not private, and through a `person` share or a gift plan for them; remote users only
   the share paths. Weighed: each root written out in full; one `ItemAccess(kind, …)` view.

4. **Children (1c of 9).** Each child declares its parent key (`info={"accessVia": …}`), never
   guessed (six tables have two cascading keys); `schema_check` holds it to a NOT NULL
   cascading key to a table with access. Grandchildren chain through their parent's view
   (Split → TransactionAccess → AccountAccess), generated in dependency order like the
   Effective views. A child's `writable` and `deletable` are its parent's `writable` (deleting a
   transaction is a write on its account, S10.3), `configurable` is the parent's, `shareable`
   never. A child's other keys (heldInId, resultTransactionId, receiptId, transferId, …) are no
   access path: what they point at is shown through its own view (as 1a); a parent's figures
   over items the reader can't see (a shared budget's actuals) are item 8's.

5. **Rules of their own (1d of 9).**
   1. `ReceiptAccess`: the owner's row with `writable` and `deletable` (`shareable` and
      `configurable` false: no sharing, no settings); each live link adds the target's row
      through its kind's view (Transaction, Account for a statement, Item, QualifiedExpense,
      Gift, Donation), `writable` when the target is, never `deletable`; a tax document's file
      read only through TaxDocumentAccess. *Deleted only when nothing links to it* stays a
      state rule in code.
   2. `ReceiptLinkAccess`: a link is seen exactly when its target is; its `writable` and
      `deletable` (detach) are the target's `writable`. CR3-47's list is a query of
      ReceiptLink through it; the hidden count is the rest.
   3. `GiftAccess`: the owner's row with `writable` and `deletable`; others through the
      owner's gift plans for its people, read when any is held, `writable` only when all are
      held writable; the person it is for never sees it until it is received, on every path
      (closing the `level_on_gift` / `_kept_level` gap).
   4. `DonationAccess`, `OrganisationAccess`: the owner's row with `writable` and `deletable`;
      read for whoever reads one of the owner's giving plans (a donation: its year's;
      an organisation: any); a plan share never makes them writable.
   5. AssumptionSet is per-user: it moves to 1f.

6. **Rows joining two items (1e of 9).**
   1. Contribution is a child of its transaction (1c); its person a reference.
   2. WashSale is a child of its sale: seen by whoever reads the sale (its disallowed loss is
      part of that sale's figures), the replacement through its own view; every permission
      false (a cache nobody edits).
   3. Reimbursement is seen when either side is readable (each side shows its own sum);
      `writable` and `deletable` (pair, unpair) when both are writable.
   4. TransferMatch is its `ownerId`'s, while both transactions are readable to them;
      `writable` and `deletable` (confirm, turn down) when both are writable.
   5. Relationship is seen when both people are readable; `writable` and `deletable` when one
      of them is the user's own person, or for an admin (S10.10.4); spouse confirmations stay
      a state rule in code.

7. **Per-user rows (1f of 9).**
   1. AccessToken, AlertState, CountedAccount, LinkColour, TypedPrice, Tag, Rule,
      StatementLayout, AssumptionSet, Connection declare `per-user <column>`; a generated view
      gives the user their own rows with `writable` and `deletable`, nobody else a row;
      Connection adds `configurable` (its credentials).
   2. Alert, hand-written, read only: one's own, and for an admin the admins' alerts but for
      those they hold as owner of what failed (S12.11.2); dismissing lives in AlertState.
   3. ImportMapping: the owner's with `writable` and `deletable`; read for whoever can write to
      one of the owner's accounts (an import uses the account owner's mappings).
   4. TaxBookFiler: a child of its TaxBook, and the invited user's own row, readable and
      `writable` (answer the invitation) before they accept.
   5. Activity, a rule of its own, read only (S10.8): the actor, the owner, the subject
      readable through its kind's view, a *share removed* entry naming the user or their
      group, and for admins users, groups, links, Settings and keys.
   6. Session, RecoveryCode, OneTimeToken, SignupRequest move to 1g (read by sign-in before a
      user is known).

8. **Household-wide and server data (1g of 9).**
   1. Category, Instrument, OptionContract, Price, TaxFigure declare `household`: no view;
      every signed-in local user reads every live row. Writes stay role checks in code (any
      user adds a category; admins change tax figures; only the server's jobs write instruments
      and prices). Weighed: a generated view for them (a pointless join on Price).
   2. Setting, PriceSource, Connector, Link, LinkFile, LinkSent, QueuedEmail, SignupRequest
      declare `admin`: a generated view gives every active admin all four, nobody else a row.
      Settings every browser needs are served by a route reading them as the server.
   3. `UserAccess`, `GroupAccess`, hand-written: every active local user reads active users,
      active groups and linked servers' users (S10.4, S10.3.3); admins read all, inactive too,
      with `writable` and `deletable`; a user is `writable` on their own User row.
   4. `ShareAccess`, hand-written: whoever has `shareable` on the item reads and changes its
      shares; a receiver reads the shares that reach them, directly or through a group (*via*).
   5. `LinkedItemAccess`: read for the local users in its `viewers`, and admins; a cache,
      written by nobody.
   6. Secret, TaskRun, Session, RecoveryCode, OneTimeToken declare `server`: no view; read only
      by server code, through item 5's unscoped way in.

9. **What a view returns (2 of 9).** `<Table>Access(targetId, userId, writable, deletable,
   shareable, configurable)`, the four as 0/1; no *via* column (the Share dialog's group names
   come from ShareAccess). One row per (targetId, userId): several paths collapse with
   `GROUP BY` and `MAX`, so `inner join <Table>Access A on T.id = A.targetId and A.userId = ?`
   never duplicates a row (weighed: a row per path through `EXISTS`). Live rows only: the views
   build on the Effective views, so joining one needs no `live()`; deleted rows are read only by
   server code until G26 says who sees them. Performance is held by query plans, not timings: a
   test runs `EXPLAIN QUERY PLAN` on each child view joined as callers join it and fails when a
   child table is scanned rather than searched; a root view becomes a table rebuilt on share
   changes only if that is ever needed.

10. **How views are defined and kept current (3 of 9).** Each table declares how it is seen in
    its `info` through a helper: `Seen.root(kind)`, `Seen.child(key)`, `Seen.rule()`,
    `Seen.per_user(column)`, `Seen.relation()`, `Seen.household()`, `Seen.admin()`,
    `Seen.server()`. All access SQL lives in `store/access_views.py` as SQL text: templates for
    the generated views, one function per hand-written view returning its `CREATE VIEW`, with a
    docstring citing its requirement (weighed: Core expressions; separate `.sql` files). The
    views are dropped before migrations and made after them at start, in dependency order
    after the Effective views, with no Alembic revision; test databases the same way.
    `schema_check` fails a table with no declaration, a child key that is not a NOT NULL
    cascading key to a table with access, a missing view or a generated one that differs from
    what is generated now, and a view without the six columns. Each view is a Table object
    (`access_table(table)`, like `view_table`) for Core and ORM joins.

11. **Inactive users, groups and remote users (4 of 9).** An inactive or deleted user has no
    row in any view, their own items included (S10.1.7); what they shared stays readable by its
    receivers. Only active groups and live memberships grant; being an admin is a live
    membership of the active Admins group, so every admin path follows it. Remote users get
    only what `read` shares to them give and what follows from those (children, gifts through a
    shared plan, people through a share), never another permission, never per-user, admin,
    household or role rows; one deactivated on their server is inactive here. *Include
    receipts* is ReceiptAccess's own rule: for a remote user a link path counts only when the
    share reaching the target has it ticked, and a gift's documents likewise. GiftPlanAccess
    gives a remote user no row for a plan whose person is a user of the same link (S7.8.5).
    `links/serve.shared_items` becomes a query of the views for the link's users; the serve
    path keeps answering through the same routes, so the views alone decide what crosses.

12. **Enforcement (5 of 9).**
    1. Reads are scoped automatically: a request's session carries its user
       (`db.read(user=…)`, `db.tx(user=…)`), and a `do_orm_execute` hook adds
       `with_loader_criteria(Entity, Entity.id.in_(select targetId from <T>Access where userId =
       :user))` for every entity with a view (lists, `s.get` misses, joined entities,
       relationship loads). Code needing the permission columns joins the view explicitly.
    2. Server work opens `db.tx(unscoped="<why>")`; a session with neither a user nor a reason
       refuses any query of a table with a view.
    3. Scoped and unscoped loads never share a session (an identity-map hit skips the query);
       a request needing a server-side read opens a second, unscoped session.
    4. Writes are checked at flush as a backstop: a new row needs its parent's `writable` (a new
       root makes its creator the owner), a change `writable`, or `configurable` when a changed
       column is declared a setting, a Share row `shareable`, a soft delete `deletable`; a
       failure answers 403. Routes keep their own checks for their messages. Each table
       declares its setting columns.
    5. Two tests: every GET route walked as each user of a seeded household with partial
       access, failing on any id in a response the user's views don't give them; a static
       check failing on `text()` or `exec_driver_sql` touching a table with a view outside
       `store/`.

13. **What happens to the Python rules (6 of 9).**
    1. The Python level functions are deleted (`access.level_of`, `account_level`,
       `visible_accounts`, `portfolio_level`, `visible_portfolios`, `visible_budgets`, `reach`,
       `taxes/books.level`/`visible`, `gifts.level_on_gift`/`visible_gifts`,
       `people.level`/`visible`, `projections.visible`, `receipts.level`/`visible`/
       `_kept_level`/`target_level`/`can_unlink`). Lists become plain scoped queries; one item
       needing a permission goes through `access.need(s, Entity, id, "writable")`: 404 with
       no row, 403 with the kind's existing message without the permission.
    2. `access.holders` becomes a query of the root's view by `targetId`; *via* comes from
       ShareAccess; the 403 messages move into `access.need`.
    3. Choices among readable rows stay Python, as queries over the views (a gift plan per
       person, one's own first; one's own giving plan first for a year).
    4. The API's `level` and `canWrite`: this PR derives them from the view (*owner* when all
       four are held, *write* when `writable`, else *read*), so the browser is unchanged. The
       user: everything is cleaned up for consistency **after this PR**: the API and browser
       move to `mine` and the four permissions (38 API fields, 153 browser reads in 25 files,
       the API document, the generated mockup, browser tests), as the next PR.

14. **Moving the call sites over (7 of 9).** Commits on `cr3-receipts`, each passing its quick
    checks: (1) declarations, `store/access_views.py`, `schema_check`, the plan test, the parity
    test, with nothing using the views yet; (2) sessions carry a user or an `unscoped` reason,
    the scoping hook; (3) routes by area: accounts and children, budgets, portfolios, tax
    books, gifts/giving/people, projections, receipts, Activity/alerts/sharing/Profile, links;
    (4) the flush backstop with each table's setting columns; (5) the Python rules deleted;
    (6) the leak sweep and the static check; then the receipts walk resumes (CR3-47, 48, 56).
    The parity test (old level against new permissions for every user and item, deliberate
    differences listed with their decision ids) lives from (1) to (5) only and is deleted with
    the Python rules; in that commit its edge-case household (admin, groups, an inactive user,
    accepted and pending filers, a gift's recipient, a linked server's user) becomes a lasting
    test of the views with each user's permissions written out. Each deliberate change of
    behaviour (1d.3 gift recipient, 1d.2 receipt links, 2a.3 filer's book, Activity and Alert
    where they differ) is a commit of its own with its test and requirement line. Every commit
    is pushed as made (`check.yml` cancels a PR's running check on each push: nothing queues);
    the full `web/check` once at the end, then a comment on the PR.

15. **Paths outside a plain query (8 of 9).**
    1. An item's figures are part of the item: budget actuals, tax book panels, a gift plan's
       budget, a giving plan's pace, projection results are computed in an unscoped session
       named for the item, each by its own rule of which accounts count (S7.1.1 and R3.4;
       S8.14.2); the transactions behind a figure are listed only through their views.
       Portfolios are the exception (S5.1.1): computed in the viewer's scoped session.
    2. Receipt search: `ReceiptSearch` (FTS5, raw SQL for ids) has no view; its ids are loaded
       as Receipts through the scoped session. Searching link payees waits for CR3-47.
    3. MCP tools open sessions with the token's user, scoped like the browser (S10.9).
    4. Linked copies (`copydb`, separate databases) stay checked in code against
       LinkedItemAccess before a copy is read; what a copy holds the peer's views decided.
    5. Background work (alerts, emails, the reader, prices, sweeps, backups, link internals)
       runs unscoped with named reasons; what it addresses to a user goes through that user's
       views (an account's alert to its holders by AccountAccess; Activity per 1f.5).

16. **Where it is written down (9 of 9).** `docs/schema.md` §7 *Access views* (declarations,
    the six columns, generated and hand-written views with each category's rule, live rows
    only on §4.2, scoped and unscoped sessions, the flush check); the project CLAUDE.md's
    *Schema conventions*: a new table declares how it is seen, in the same change. S10.3.2
    names the owner's permissions beyond write (delete; share; settings, what it covers, and
    secrets), S10.3 says every read goes through them, S14.1 a line on the views and their
    enforcement; each deliberate change in its own section with its commit (S7.8.5 the gift's
    recipient on every path; S8.14.3 and S10.6 a filer's book their own). `rejected-ideas.md`:
    one polymorphic `ItemAccess` view; visibility checked per route in Python. G26: the views
    cover live rows only, so seeing deleted rows needs its own path. The mockup is checked
    with each commit; expected unchanged (level derived as today), the filer's *shared with
    me* mark the one candidate; a commit that needs no mockup change says so.

## Final approval

Given by the user Oct 31, 3:17 PM, for all sixteen decisions as written above.

## Applied

1. **Step 1: declarations and views.** Every table declares `seen=` in its constructor
   (`record`, `exception`; `pairs` is always a relation). `store/access_views.py` holds the
   generated and hand-written views and five base views (`AccessUser`, `AccessMember`,
   `AccessAdmin`, `ShareLevel`, `ReceiptTarget`); `views.sync` makes them after the Effective
   views. `schema_check` and `docs/schema.md` §5 item 5 and §7. Deviations:
   1. 1c.1 asked a child's key to be cascading; it asks only `NOT NULL`. `WalletKey.accountId`
      has no `ondelete`, and the parent's view already leaves a deleted parent's children out,
      so cascading adds nothing to access.
   2. 1d.3 gave others `writable` on a gift when all its plans are writable; they also get
      `deletable` then, as today (a gift is deleted through the same check as it is changed,
      `ui/gifts.py:_editable`).
   3. 1d.1's tax-document path reads through `TaxDocumentAccess` where `configurable`: the
      book's owner and accepted filers, as S9.6 says (*by the tax book's filers*), not every
      reader of the book.
   4. The plan test (2.4) compares each child query with and without its view: a child table
      with no index on its parent key (`BudgetReview`) already scans without one.
2. **Step 2: scoped sessions** (c81b3df). `db.read/tx(user=…)` or `(unscoped="…")`;
   `scoping.unscoped` for one column statement; `access.need`, `perms`, `listing`,
   `holders_of`; settings read as the server.
3. **Step 3a: every session names its scope.** Every UI route's session carries its caller
   (87 by a script: a function with the Caller `c`), sign-in, the welcome and side-effect
   writes name `unscoped=`, and every server session (jobs, links, the connector, mail,
   alerts) names `<module>: <function>`. Deviations and what the move found:
   1. 5.1 asked `with_loader_criteria(… IN (subquery))`; SQLAlchemy recursed forever on a
      query reading a table both directly and in a correlated subquery (alerts). The hook adds
      a plain `EXISTS` per table with a view at the query's top level (joined or aliased; on
      the optional side of an outer join, `id IS NULL OR …`). A subquery is left as written:
      it filters, it never returns records. Reloading an expired record isn't scoped again.
   2. `scoping.as_server(s, why)`: work that must read across users inside a user's request
      runs in a second session on the same connection, in a savepoint (decision 8.1 and
      5.3): a tax book's detail, panels and exports; a portfolio's series and returns (with
      the viewer's own deleted accounts, R3.10); a budget's recurring payments; a giving
      plan's income; a projection's tracking; wash sales across spouses; an import, which
      matches the rows the owner deleted (S1.3.2). The user's session reads afresh after it.
   3. Read as the server, one column statement each, as the code did before: a setting's
      value; whether a receipt's file is kept already; the user or group a share names (an
      inactive one is in no one's view, so the refusal says *inactive*, not *unknown*);
      whether a link is live; the names Activity's entries give (one shared and removed
      since keeps its name, S10.8); one person, once, and asking to share a private one
      (S10.10.3); the people a gift is for, deleted ones too (S7.8.6); what paid for a gift,
      named *an account not shared* (S11.5.2); the accounts a connection keeps current, on
      the connector's page (S16.2); a just-deleted record's answer to its save.
   4. 1g.2 made `Connector` and `Link` admin data: every user reads whether a connector is
      paired and the key credentials are sealed to (S16.1), and a linked server's name and
      state (its people in the Share dialog, its window, S10.4, S11). Both are rules: admins
      hold them, every local user reads them. `Connection` too: its owner holds it, admins
      read each one's state on the connector's page (S16.2).
   5. 1g.3: every user reads their own User row (a linked server's user too, as the routes
      that answer a link run as them); only a local user changes it.
   6. A removed receiver's tags go by one UPDATE (the server's bookkeeping on their rows);
      a pending filer's books list reads those books as the server, and accepting reads the
      invitation, then the book as theirs.
   7. Found by the move, and fixed before it shipped: *Remove orphans* in Settings › Storage
      ran in the admin's session, where other users' receipts are in no view, so it would have
      taken their files for orphans and removed them. Storage's counts, pruning and orphans
      are the household's and run as the server;
      `test_an_admins_household_wide_file_work_counts_every_users_files` fails without that.
4. **Step 3b: unnamed sessions refused** (aca0a99).
5. **Step 3c: the routes read through the views.** Lists are `access.listing` (`access.accounts`
   for accounts), one record `access.need` or a thin fetcher over it (`access.account`,
   `portfolio`, `budget`; `books.get`, `people.get`, `receipts.get`, `gifts.plan_by_id`,
   the projections' `_get`), which take *read*, *write* or a permission's name: deleting asks
   `deletable`, choosing what is active or counted `configurable`, sharing `shareable`
   (`_owner_only`); share counts are `access.holders_of`; Activity's filter is its view;
   is-it-mine checks compare `ownerId` (net worth, *Count in my totals*, a portfolio's
   accounts). The old rule functions (`access.reach`, `level_of`, `account_level`,
   `books.level`, `people.level`, `receipts.level`/`_kept_level`, `gifts.level_on_gift`/
   `visible_gifts`, `giving.visible_plans`) remain only for the parity test, and go in step
   5 with it. Deviation from 6.1: the single-record fetchers stay as names (one line over
   `access.need` each, giving the API's level), as they read better at the ~100 call sites
   than `access.need` with an entity.
6. **Step 4: the write check.** As 5.4, with two choices the tests made: a change is checked
   before the flush, against the view as it stands; a new record is checked at the commit, so
   that what is made with it counts (a gift is in its plans only once its people are). Setting
   columns: `Account`'s twelve (`ui/accounts.py`'s list), `Projection.active`, its baseline;
   `BudgetAccount` and `TaxBookAccount` ask `configurable` for any write. Activity, Alert and
   QueuedEmail are written for everyone and not checked. Found: joining a linked server's
   user to a person changed their User row and their own person, which the joiner doesn't
   hold; the server does it, for one who may change the person.
7. **Step 5: the Python rules deleted.** `access.reach`, `level_of`, `account_level`,
   `holders`, `RANK`, `higher`, `groups_of`; `books.level`, `people.level`,
   `receipts.level`/`_kept_level`/`_on_tax_document`, `gifts.visible_gifts`/`level_on_gift`,
   `giving.visible_plans`; the last production uses of them (`people.may_join`,
   `receipts.detach_kept`) ask the views. The parity test went with them; its household
   stays, with the rows the seed lacks (a reimbursement, a transfer match and a wash sale on
   both sides of a share), as `test_who_holds_what`: each user's permissions written out per
   record. Decision 9.2's lines: S10.3.2 and S10.3 (the permissions, decided by the views),
   S14.1.1.4, S7.8.5 (the person a gift is for, nor what is kept with it). Deviation from 7.3:
   the changes of behaviour came with the commits that made them (the gift's recipient with
   step 1's views, Activity's people entries with 3c), not a commit each; the walk log says
   which.
8. **Step 6: the sweeps.** `tests/test_leaks.py`: every GET route (but the live stream, which
   holds a request open for minutes) called by admin, alice, bob, dave and erin of the
   household, filled with the household's edge-case records where the user reads them;
   every id in an answer must be in that user's view, or one of three named on purpose
   (a tax book's filers' accounts, S8.14.2; the connector page's accounts, S16.2; a book a
   filer is named on, S8.14.1). 19 s across five workers. The static check: outside
   `store/`, no `text()` or `exec_driver_sql()` names a table with a view. Found and fixed:
   1. A transfer named its other half's id to someone who can't read that account (the
      account's name was already hidden); the sweep catches it again if it comes back.
   2. Settings › Receipts' counts and *Read again* and Settings › Bitcoin's wallet count ran
      in the admin's scope (raw SQL counted everyone's; *Read again* would have re-read
      only the admin's receipts); they are the server's now, and a test fails without that.
   3. CR3-47's leak is closed by step 3a: bob's view of the receipt lists only the joint
      account's link, its links and their transactions read through his views. How the
      dialog says it is kept with more is the receipts walk's item 1.
