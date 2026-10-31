# MoolaKata: database schema conventions

These conventions apply to the main database and to every linked copy (requirements S11.9,
S14.1). The tables are declared with SQLAlchemy Core in
`web/server/src/moolakata/store/tables/` (requirements S17.1).

## 1. Naming

1. **Tables** have a capitalized, singular name: `User`, not `Users`.
2. **Tables for many-to-many relationships** have plural names: `UserGroups`,
   `TaxBookFiler`.
   Their primary key is the pair of foreign keys (`userId`, `groupId`). They have no `id`
   column and no prefix.
3. **Field names** are camelCase and start with a lowercase letter.
   1. Acronyms of 3 or more characters are written as words.
   2. For example, `encodeHtml` or `htmlEncode`, not `encodeHTML` or `HTMLEncode`.
4. **Primary keys** are named `id`. A foreign key to a table ends with `Id`: `userId`.
   1. A primary key is the table's prefix, an underscore, and a Crockford-encoded UUIDv7
      (§2): `User_01k7ab4vstfggspkjt3my8wzr2`.
   2. The alphabet is in ascending byte order, so sorting the strings gives the same order
      as sorting the UUIDs. The first 10 characters (`01k7ab4vst`) are the 48-bit
      millisecond timestamp, since 10 × 5 = 50 bits covers the 48-bit time plus the 2
      padding bits.
5. **Prefixes** are tracked in the table in §3, sorted by prefix in byte order (`A`–`Z` before
   `a`–`z`). Each row gives:
   1. the prefix (slug),
   2. the table's name,
   3. a description of the table.

The same names are used in Python and in the API's JSON. A table's columns, the attributes
of its entity dataclass and the fields the browser receives all have the same spelling, so
there's no layer that translates names.

## 2. Primary keys

- **The prefix** is at most 5 characters, starts with a capital letter, and is unique
  across all tables. With the underscore, it takes up to 6 characters.
- **The UUIDv7** is encoded as one 128-bit number in base 32, most significant digit first,
  in exactly 26 lowercase characters from the alphabet `0123456789abcdefghjkmnpqrstvwxyz`.
  The letters `i`, `l`, `o` and `u` are not used.
  - The first character is always `0`–`7`, because 26 × 5 = 130 bits.
  - The decoder rejects uppercase letters and the letters left out of the alphabet, so each
    ID has exactly one spelling.
- **Column:** `id TEXT PRIMARY KEY`. Each table with an `id` is a `WITHOUT ROWID` table and
  has a `CHECK` constraint on the ID's form:
  ```sql
  CHECK (id GLOB 'User_*' AND length(id) = 31)
  ```
  The length is the prefix's length + 1 + 26.
- **Record fields.** Each table with an `id` also has `version` (an integer that changes with
  every save, which the API's `If-Match` compares, requirements S13.8.6), `createdAt` and
  `updatedAt`.
- **Made in the browser.** A record a browser dialog creates (requirements S12.15.3) takes
  an ID the browser makes the same way: the UUIDv7 from its clock and `crypto.getRandomValues`,
  with the table's prefix. The server accepts it only in exactly this form, with the prefix of
  the table it goes in, a time within a day of the server's clock, and not already taken
  (requirements S13.8.11.2); `createdAt` is the server's time. Every other ID is made by the server.
- **IDs reveal when a row was created.** File names and anything else visible on disk,
  such as receipt files and a linked copy's files (requirements S11.9), use separate random
  names and never an ID.

```
UUIDv7 (hex):   0199d4b2-6f3a-7c21-9b4e-5a1d3c8e7f02
Crockford:      01k7ab4vstfggspkjt3my8wzr2
Transaction ID: Txn_01k7ab4vstfggspkjt3my8wzr2
```

## 3. Prefixes

Tables for many-to-many relationships have no prefix (§1.2), so they are not listed. Each
list is sorted by prefix, and a prefix is unique across both.

### 3.1 Tables

The prefixes of the tables that exist.

| Prefix | Table            | Description                                                                                           |
|--------|------------------|-------------------------------------------------------------------------------------------------------|
| Acct   | Account          | One place money is held, owned by one user, with an account type.                                     |
| Actv   | Activity         | A change worth showing: who made it and what it is about, never an amount.                            |
| AlSt   | AlertState       | One person's state of an alert: when they saw it, dismissed it, were emailed it.                      |
| Alert  | Alert            | Something that needs a user's attention, one per cause, open until the cause clears.                  |
| Anchr  | Anchor           | A balance the institution reported on a date, that the account's balance is checked against.          |
| Asmpt  | AssumptionSet    | A user's expected returns, volatility and inflation for projections.                                  |
| BdgAc  | BudgetAccount    | An account a budget covers, and where its money comes from: a card's payer, reserves' source.         |
| BdgLn  | BudgetLine       | One category's planned amount in a budget, from a month on, monthly or yearly.                        |
| BdgMv  | BudgetMove       | An amount put into a category for a month: from another, *To Budget* or landed money. |
| BdgRv  | BudgetReview     | A budget's month marked reviewed: by whom, when, and the figures it had then.       |
| Bdgt   | Budget           | A user's plan per category over chosen accounts; shared with a group for a household.                 |
| Cat    | Category         | A budget category given to bank transactions.                                                         |
| Cnctr  | Connector        | The MoolaKata Connector paired with this server: its public keys, its reports' state (S18.4).         |
| CntAc  | CountedAccount   | Whether a user counts an account shared with them in their own totals.                                |
| Cntrb  | Contribution     | Who a deposit into a 529 came from, and whether it is a five-year election.                           |
| Conn   | Connection       | One sign-in at one institution, kept by the connector and owned by a user (S18.6).                    |
| CorpA  | CorporateAction  | A split, symbol change, spin-off or merger of a holding, the transactions it makes named by it.       |
| Dnatn  | Donation         | One charitable gift to an organisation, into a donor-advised fund, or a grant from one.               |
| EdPln  | EducationPlan    | A 529 account's plan: its state, name, beneficiary and opening date.                                  |
| Email  | QueuedEmail      | An email waiting to go out through SMTP, until it is sent or its link expires.                        |
| EstPy  | EstimatedPayment | A filing's estimated tax payment for a quarter, matched to its transaction.                           |
| Filng  | Filing           | One return in a tax book (federal, state or local), with its progress and result.                     |
| GfPln  | GiftPlan         | One user's gift plan for a person: holidays, anniversaries, budget, lead time, notes.                 |
| Gift   | Gift             | A gift to or from a person for an occasion, from idea to given.                                       |
| Group  | Group            | A named set of users that shares are granted to.                                                      |
| GvPln  | GivingPlan       | A user's giving target for a year: a percentage of income, or an amount.                              |
| HdChk  | HoldingCheck     | A position a brokerage statement or file shows on a day, checked against what is held then.          |
| Hold   | Holding          | What an account holds of one instrument at a point in time.                                           |
| Imprt  | Import           | One file imported into an account, with the dates it covers.                                          |
| Imprv  | Improvement      | An improvement to a property, added to its cost basis.                                                |
| Instr  | Instrument       | A thing with a price: a stock, fund, coin, option contract or currency.                               |
| Item   | Item             | A physical asset: metals, a collectable, a property or a vehicle, with how it is valued.              |
| LItem  | LinkedItem       | An item a link brings in, as the main database knows it: kind, owner and who it names.                |
| Link   | Link             | A link with another MoolaKata server: its state, address and key.                                     |
| LkCol  | LinkColour       | The colour a user chose for a linked household's window.                                              |
| LkFil  | LinkFile         | A receipt file a linked server's change named that hasn't reached the copy yet.                       |
| LkSnt  | LinkSent         | What this server last sent a linked server of a shared item, as a hash: a cache.                      |
| Loan   | Loan             | A loan account's terms: principal, rate, term, escrow, PMI, resets and recasts.                       |
| Lot    | Lot              | One acquisition of an instrument, and what remains open.                                              |
| LotPk  | LotPick          | How much of a lot a sale took, when the lots were picked.                                             |
| Lyout  | StatementLayout  | What statement import learned of an institution's layout: section signs, lines to skip.               |
| Map    | ImportMapping    | A saved column mapping for one institution's CSV files.                                               |
| OTTkn  | OneTimeToken     | An emailed link's token, as its hash: an invitation, a reset, an email change.                        |
| Occsn  | Occasion         | A dated occasion in a gift plan: an anniversary, a holiday, a custom date.                            |
| OptCt  | OptionContract   | An option's contract: underlying, call or put, strike, expiry, multiplier, root and deliverable.      |
| Orgzn  | Organisation     | An organisation given to: its EIN, whether gifts to it are deductible, causes, pledges.               |
| Persn  | Person           | Someone in the household's life: every user, and people who never sign in.                            |
| Portf  | Portfolio        | A named set of accounts, or parts of them, charted as one.                                            |
| Price  | Price            | One instrument's close on one market day, from a source, kept for ever.                               |
| Prjct  | Projection       | How money will grow toward a goal; an active one is tracked against its baseline.                     |
| Pyoff  | PayoffPlan       | A saved overpayment plan for a loan; one may be the plan being followed.                              |
| QExpn  | QualifiedExpense | A qualified education expense a 529's withdrawals are matched with.                                   |
| RCode  | RecoveryCode     | A two-step recovery code, as its hash, usable once.                                                   |
| RcLnk  | ReceiptLink      | What a receipt is attached to: a transaction, an account, an item, a gift, a donation.                |
| Rcpt   | Receipt          | An uploaded file, encrypted on disk, with a date, an amount and what it is attached to.               |
| Recon  | Reconciliation   | A statement's closing date and balance, ticked off against the transactions.                          |
| Rltn   | Relationship     | A dated link between two people: spouse, couple, child, friend, colleague, family.                    |
| Rmbrs  | Reimbursement    | A deposit paired with reimbursable spending: how much of it pays that spending back.                 |
| Rule   | Rule             | One of a user's categorisation and payee rules: what a transaction matches and what the rule sets.    |
| Secr   | Secret           | A secret sealed on its own: an API key, a password or a private key.                                  |
| Sessn  | Session          | A signed-in browser's session, its token kept as a hash.                                              |
| Setng  | Setting          | One setting an admin saved, by its key; a key with none stands at its default.                        |
| Sgnup  | SignupRequest    | A person's request for an account, from confirming the email to an admin's decision.                  |
| Share  | Share            | A grant of an account or portfolio to a user, group or linked server.                                 |
| Split  | Split            | A part of a transaction's amount given its own category.                                              |
| Src    | PriceSource      | A source of daily prices: its name, whether it is on, and its order per class.                        |
| StLeg  | StrategyLeg      | An instrument held as part of a strategy: an option leg, or shares with their quantity.               |
| Strat  | Strategy         | Option legs and shares held together as one, or a proposal turned down (S3.5).                       |
| Tag    | Tag              | A user's own tag, by name: on their transactions, their receipts and what their rules set.            |
| TaxBk  | TaxBook          | One user's, or a married couple's, tax records for one tax year.                                      |
| TaxFg  | TaxFigure        | An admin's correction of a shipped tax-table figure for one year.                                     |
| Token  | AccessToken      | A user's read-only token for the MCP endpoint, kept as a hash of its secret.                          |
| TxBkA  | TaxBookAccount   | An account a tax book counts or leaves out, and who added it.                                         |
| TxBkF  | TaxBookFiler     | A filer of a tax book, and when they accepted it.                                                     |
| TxChg  | TaxBookChange    | An edit made anyway to a year whose federal return was filed, and how it was settled.                 |
| TxDep  | TaxBookDependent | A person a tax book's filers claim for the year: how claimed, months lived with them, student.        |
| TxDoc  | TaxDocument      | A tax document received (W-2, 1099) or filed (a return, a notice), with its file.                     |
| Txn    | Transaction      | One dated movement in an account.                                                                     |
| TyPrc  | TypedPrice       | A price a user typed for an instrument on a day: it values their own accounts only.                   |
| User   | User             | A person who signs in here, or a user of a linked server (with `linkId`).                             |
| Valtn  | ItemValuation    | A dated value of an item, with its source.                                                            |
| WAddr  | WalletAddress    | An address a bitcoin wallet watches, typed or derived from its key; worked out again.                 |
| WKey   | WalletKey        | An extended public key or an address a bitcoin wallet account holds, as entered.                      |
| WashS  | WashSale         | A loss disallowed as a wash sale, moved to its replacement's basis; worked out again from the trades. |
| XfrMt  | TransferMatch    | A bitcoin transfer out of one of the owner's accounts and in to another, proposed as a pair.          |

### 3.2 Reserved

The prefixes of the entities the requirements name whose tables are not declared yet. A row
moves to §3.1 when its table is.

| Prefix | Table          | Description                                                                         |
|--------|----------------|-------------------------------------------------------------------------------------|
| Posn   | Position       | An instrument held in an account, followed from open to closed.                     |

## 4. Soft deletes

Records are never removed from the database: they are marked deleted. The exceptions are in
§4.4.

1. **Fields.** Every table, many-to-many tables included, has:

   | Field         | Type      | Meaning                                                  |
   |---------------|-----------|----------------------------------------------------------|
   | `deleted`     | boolean   | the record itself was deleted: `deletedAt IS NOT NULL`   |
   | `deletedAt`   | timestamp | when; null while the record is not deleted               |
   | `deletedById` | `User` FK | who; null when the server deleted it (a sync, a job)     |

   `deletedAt` is the fact; `deleted` is a virtual generated column computed from it, so the
   two can't disagree and nothing writes `deleted`. It is there for reading: the
   `<Table>Effective` views and the partial unique indexes (§4.3) use it. A `CHECK` keeps
   `deletedById` null while `deletedAt` is. Restoring a record clears `deletedAt` and
   `deletedById`. Re-adding a row that a many-to-many table already holds as deleted restores
   it. A copy of rows between tables names its columns and leaves `deleted` out, since a
   generated column takes no value.
2. **Effective deletion.** A record is also deleted when something it is *deleted with* is
   (§6.3): a transaction when its account is. *Deleted with* is a foreign key declared
   `ondelete="CASCADE"` to a soft-deletable table. Each table has a view, named
   `<Table>Effective` (`TransactionEffective`), with every column of the table plus:
   1. `effectiveDeleted`: the record's own `deleted`, or the `effectiveDeleted` of any record
      it is deleted with;
   2. `effectiveDeletedAt`: the earliest `deletedAt` along that chain.

   The views are generated from the table declarations, chaining each parent's view, so a
   new cascading foreign key changes the view with it. Code reads through the views and
   leaves out effectively deleted records unless it asks for them.
3. **Uniqueness** ignores deleted records: a unique index is partial, `WHERE NOT deleted`, so
   a deleted name or username can be used again.
4. **Exceptions**, removed outright:
   1. **sessions and one-time tokens** (invitation, sign-up confirmation, reset, email
      change, a sign-in waiting for its two-step code), when used or expired, and two-step
      recovery codes when used or replaced;
   2. **a secret's old ciphertext** when the secret is replaced or removed, so an old API key
      or token can't be recovered from the database or a later backup;
   3. **linked copies**: another household's data, removed with the share or link it came
      by, at **Reset copy**, an inbox change once it is applied (requirements S11.9), and a
      receipt waiting to reach the copy once it has (`LinkFile`, S11.4);
   4. **work queues and counters**: receipt-reading jobs, emails waiting to go out (when sent
      or when their link expires), sign-in and access-key attempt counters, the background
      tasks' last runs, and the live stream's state;
   5. **caches**, rebuilt from the records: thumbnails, computed series kept for speed, and
      wash sales, worked out again from the trades whenever they change, and a bitcoin
      wallet's addresses, derived again from its keys and its explorer or node, a budget's
      month figures, worked out again when what they come from changes (requirements
      S7.3.10), and what a link brings in, replaced from each pull.

   Activity entries and alerts are never deleted at all: Activity is kept as it was
   written, and alerts are resolved, then age out of the list
   (requirements S12.11).

## 5. Checks

A test fails when:

1. a table or field name breaks §1;
2. a table with an `id` has no row in §3.1, a row in §3.1 names no table, a prefix is listed
   twice, or a list in §3 is not sorted by prefix;
3. a table with an `id` lacks the `WITHOUT ROWID` option or the ID's `CHECK` constraint.
4. a table outside the exceptions of §4.4 lacks the fields of §4.1 or their `CHECK`, or its
   `<Table>Effective` view is missing or does not match its cascading foreign keys;
5. a table doesn't say how it is seen (§7), a child's key is not a `NOT NULL` foreign key to
   a table with an access view, a table needing an access view has none or one that differs
   from what its declaration makes now, or an access view lacks the six columns of §7.2.

## 6. Ended records

Records are never removed (requirements S14.10). When a record ended decides when the files
attached to it (receipts, statements) expire under their retention, and so when file pruning
may remove them. When a record ended is worked out, never stored, so it follows the records
as they change.

1. **`endedAt`**: for each table a file can be attached to (`Transaction`, `Account`,
   `Item`, `QualifiedExpense`, `Gift`, `Donation`), when the record stopped being needed for
   anything ongoing, or none while it still is. It is worked out by the server's retention
   rules (`receipts/retention.py`) from the rules below, and only file pruning and a file's
   *Kept until* ask for it, so its cost never falls on everyday queries.
2. **Its own end**: declared with the table, as an expression over its own row and the
   rows it is deleted with. A deleted record's own end is the earlier of its declared end and
   its `effectiveDeletedAt`. Without a declared end, a record ends only when it is effectively
   deleted.

   | Its own end | Tables |
   |---|---|
   | never | `Instrument`, `Price` (requirements S4.6), `TypedPrice`, `TaxFigure`, `Setting` while set; `TaxBook` and with it `Filing`, `EstimatedPayment`, `TaxDocument`, `TaxBookDependent`, `TaxBookFiler`, `TaxBookAccount`, `TaxDependentAccounts`; `User` (users are made inactive, not deleted, S10.2) |
   | its date | `Transaction`, `Anchor`, `Holding` (as of), `HoldingCheck` (as of), `Reconciliation` (the statement's), `Donation`, `QualifiedExpense`; `Receipt` (its own date, or when it was uploaded) |
   | an event | `Account`: deleted, or closed with nothing in it still open; `Lot`: the sale of its last share; `Import`: its latest transaction's end; `BudgetLine`: the month before a later line for its category starts; `Gift`, given or received: the later of its occasion and its purchase; `Occasion` with a year: its date; `GivingPlan`: the end of its year; `Item`: its sale; `AccessToken`: expiry or revoking; `SignupRequest`: decided, or expired unconfirmed; `Link`: unlinked; `Connector`: unpaired or replaced; `Connection`: removed; `Relationship`: its `to` date; `Strategy`: its last option leg closed |
   | when deleted | `TransferMatch`, `Budget`, `Portfolio`, `Projection`, `AssumptionSet`, `Person`, `GiftPlan`, a `Gift` still an idea or planned, `Organisation`, `PayoffPlan`, `Group`, `Share`, `PriceSource`, `ImportMapping`, `StatementLayout`, `Rule`; a remote `User` with its link |
   | its parent's | `BudgetMove`, `BudgetReview`, `BudgetLeaveOuts`, `Reimbursement`, `Split`, `LotPick`, `StrategyLeg`, `TransactionTags`, `RuleTags`, `ReceiptTags`, `WalletKey`, `OptionContract`, `BudgetAccount`, `PortfolioAccounts`, `CountedAccount`, `ShownProjections`, `GiftPersons`, `ReceiptLink`, `EducationPlan`, `Contribution`, `Loan`, `ItemValuation`, `Improvement`, `UserGroups`, `LinkColour`; a yearly `Occasion` |
   | `Activity` | when it was written |

3. **What a foreign key does**: each foreign key is declared with one of these, for when
   the record it points at (the parent) is deleted and for when each one ends:

   | Ruling             | When the parent is deleted                       | Ending |
   |--------------------|--------------------------------------------------|--------|
   | **deleted with**   | the record is deleted with it (`ondelete="CASCADE"`, §4.2) | it ends with its parent, which ends no earlier than it |
   | **keeps ref**      | the record stays and shows the parent, marked deleted | the parent ends no earlier than the record |
   | **keeps name**     | the record stays and shows the parent's name as it was, marked deleted or closed | each ends on its own; the parent's row stays, deleted, so its name is read from it |
   | **nullifies**      | the record stays and the key is cleared          | each ends on its own |
   | **prevents delete**| deleting the parent is refused while the record exists | each ends on its own |

   A record's `endedAt` is the latest of its own end and the `endedAt` of every record that
   keeps a ref to it, or is deleted with it; if any of those is null, so is its own.

   Whatever ends or is deleted still counts in figures before its end (requirements R3.10):
   a budget or portfolio counts an account up to the date it closed, and shows it after as
   *UMB Checking (closed)*.
4. **The rulings.** A key to a user or person that is not listed (`ownerId`, `createdById`,
   `enteredById`, `decidedById`, `updatedById`, …) keeps name.

   | Ruling | Keys |
   |---|---|
   | **deleted with** | `accountId` of `Transaction`, `Anchor`, `Holding`, `HoldingCheck`, `Lot`, `Import`, `Reconciliation`, `WalletKey`, `EducationPlan`, `QualifiedExpense`, `Loan`, `PayoffPlan`, `Item`, `Rule`; `Split.transactionId`; `Lot.transactionId` (also keeps ref); `LotPick.lotId`, `LotPick.saleId`; `TransactionTags`, `RuleTags`, `ReceiptTags` both keys; `Strategy.accountId`, `StrategyLeg.strategyId`; `CorporateAction.accountId`; `TransferMatch.outId`, `TransferMatch.inId`; `OptionContract.instrumentId`; `Price.instrumentId`, `TypedPrice.instrumentId`; `BudgetLine.budgetId`; `BudgetAccount.budgetId`; `BudgetMove.budgetId`, `BudgetMove.transactionId` (the landed money it gives); `BudgetReview.budgetId`; `BudgetLeaveOuts` both keys; `Reimbursement.spendingId`, `splitId` and `paybackId`; `PortfolioAccounts.portfolioId`; `CountedAccount`, `ShownProjections`, `UserGroups`, `LinkColour` both keys; `GiftPlan.personId`; `Occasion.giftPlanId`; `GiftPersons.giftId`; `ReceiptLink.receiptId`; `TaxBookFiler.bookId`, `TaxBookAccount.bookId`, `Filing.bookId`, `EstimatedPayment.filingId`, `TaxDocument.bookId`, `TaxDocument.filingId`, `TaxBookDependent.bookId`; `TaxDependentAccounts` both keys; `Contribution.transactionId`; `ItemValuation.itemId`, `Improvement.itemId`; `Share.itemId`, `Share.userId`, `Share.groupId`; `AccessToken.userId`; `User.linkId`; `Connection.ownerId` (a user's sign-ins go with them) |
   | **keeps ref** | `Transaction.importId`, `instrumentId`, `reconciliationId`; `Transaction.transferId` and `optionTransactionId`, both ways; `Transaction.corporateActionId` (deleting the action deletes its transactions); `CorporateAction.instrumentId`; `Lot.transactionId`, `Lot.instrumentId`; `LotPick.saleId`; `Holding.instrumentId`; `HoldingCheck.importId`, `HoldingCheck.instrumentId`; `OptionContract.underlyingId`; `Strategy.underlyingId`, `StrategyLeg.instrumentId`; `Gift.transactionId`; `Donation.transactionId`, `Donation.instrumentId`; `ReceiptLink.itemId` (the receipt ends no earlier than what it is linked to); `TaxDocument.receiptId`; `QualifiedExpense.transactionId`; `Loan.securedById`; `User.personId`; `Connection.connectorId` (a Connection outlives a replaced pairing only as history) |
   | **keeps name** | `categoryId` of `Transaction`, `Split`, `BudgetLine`, `Rule`; `BudgetMove.fromCategoryId`, `toCategoryId`, `cardId`; a `Loan`'s budget categories; `BudgetAccount.movedFromId`, `paidFromId`; `BudgetLine.heldInId`, `BudgetLine.projectionId`; `BudgetAccount.accountId`, `PortfolioAccounts.accountId`; what a `Projection` is built on (it waits for its owner to choose again before recomputing); `GiftPersons.personId`; `Donation.organisationId`, `fromAccountId`, `dafAccountId`; `TaxBookAccount.accountId`, `TaxDocument.accountId`, `TaxBookDependent.personId`; `Filing.resultTransactionId`, `EstimatedPayment.transactionId`; `EducationPlan.beneficiaryId`; `Contribution.fromPersonId`; `Relationship.person1Id`, `person2Id`; every key to a user or person not listed elsewhere |
   | **nullifies** | `Anchor.importId`, `Holding.importId`; `User.activeBudgetId` (the user then follows none until they choose); an account's `connectionId` (its sync turns off, requirements S18.6.4) |
   | **prevents delete** | `Category.parentId`; `Filing.amendsId` |

   **One exception**: deleting a person deletes the gifts still ideas or planned for that
   person alone; gifts bought, given or received keep the person's name (requirements
   S7.8.6).
5. **Prices** never end (requirements S4.6), and the exceptions of §4.4 are removed on
   their own schedules.

## 7. Access views

Who reads a record, and what more they may do with it, is decided in the database, once per
table, by a view named `<Table>Access` (`AccountAccess`). Every query a user's request makes
joins the views of the tables it reads (requirements S10.3), so nothing a user can't see is
ever read for them.

1. **How a table is seen.** Each table declares it with its columns (`Seen` in
   `store/tables/_base.py`):

   | Declared | Tables | Its view |
   |---|---|---|
   | root (its share kind) | `Account`, `Portfolio`, `Budget`, `GivingPlan`, `Projection` | generated: its owner holds everything, a share (S10.3) gives read or `writable`, directly or through an active group |
   | child (its key) | the records of one record: `Transaction` (`accountId`), `Split` (`transactionId`), `BudgetLine` (`budgetId`), `Filing` (`bookId`), `Occasion` (`giftPlanId`), … | generated: seen as the record its `NOT NULL` key names is; `writable` and `deletable` are that record's `writable`, `configurable` its `configurable`, never `shareable` |
   | rule (its share kind, for a root) | `TaxBook`, `Person`, `GiftPlan` (roots with rules of their own); `Receipt`, `ReceiptLink`, `Gift`, `Donation`, `Organisation`, `Reimbursement`, `TransferMatch`, `Relationship`, `WashSale`, `Alert`, `ImportMapping`, `TaxBookFiler`, `Activity`, `User`, `Group`, `Share`, `LinkedItem` | written by hand in `store/access_views.py`, one function each, citing its requirement |
   | per-user (its user column) | `AccessToken`, `AlertState`, `CountedAccount`, `LinkColour`, `TypedPrice`, `Tag`, `Rule`, `StatementLayout`, `AssumptionSet`, `Connection` | generated: its user's alone, `writable` and `deletable`; `Connection` also `configurable` (its credentials) |
   | admin | `Setting`, `PriceSource`, `Connector`, `Link`, `LinkFile`, `LinkSent`, `QueuedEmail`, `SignupRequest` | generated: every admin holds everything; no one else reads it |
   | relation | the many-to-many tables (§1.2) | none: a query asks for one side's records and joins that side's view, and the other side's when it returns both |
   | household | `Category`, `Instrument`, `OptionContract`, `Price`, `TaxFigure` | none: every signed-in user reads it |
   | server | `Secret`, `TaskRun`, `Session`, `RecoveryCode`, `OneTimeToken` | none: only the server's own code reads it |

2. **Columns.** One row per live record and user who reads it:

   | Column | Meaning |
   |---|---|
   | `targetId` | the record's `id` |
   | `userId` | the user who reads it |
   | `writable` | changes what it holds (S10.3.2) |
   | `deletable` | deletes it |
   | `shareable` | changes its sharing, and sees who holds it |
   | `configurable` | changes its settings and what it covers, and sees and changes its secrets |

   The four are 0 or 1. Each implies `writable`. Several ways to a record (its owner, a share,
   a group's share, a tax book's filers) collapse to one row with the highest of each. Being
   the owner is not a column: whether a record is one's own is a fact of the record
   (`ownerId`, or its parent's; a tax book's accepted filers' too).
3. **Who holds anything.** Only active, live users (S10.1.7) and live memberships of active
   groups (S10.5); being an admin is a live membership of the active Admins group (S10.1.8). A
   linked server's user only ever reads, and only what is shared with them (S10.3.3).
4. **Live records only.** The views read the `<Table>Effective` views (§4.2): a deleted
   record has no rows, and seeing deleted records is the server's alone.
5. **Kept current** as the Effective views are: dropped before a migration and made again
   after it, at every start, each after the views it reads, from the declarations. They are
   no migration's business.
6. **Scoped sessions.** A session opened for a user's request names the user
   (`db.read(user=…)`, `db.tx(user=…)`), and every ORM query in it reads only what the user's
   views give them: each table with a view gets `EXISTS (SELECT 1 FROM <Table>Access WHERE
   targetId = id AND userId = :user)` beside whatever the query asks, lists, a record fetched
   by its id and joined tables alike. Code that needs the permissions joins the view itself.
   The server's own work opens a session unscoped, naming why (`db.tx(unscoped="…")`): a
   sweep, a job, sign-in, a link's pull. Inside a user's session, one statement may read as
   the server, naming why (`scoping.unscoped`), when what it reads serves the server (a
   setting's value, whether a file is kept already) and is never handed to the user; such a
   statement selects columns, never records, so a user's session holds only records they
   read.
