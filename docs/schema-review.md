# Schema review

What a later review of the database's schema (`docs/schema.md`) is to look at. Each entry
says what the table or field is today and the question it raises. Every table has a synthetic
id (§2) except a pure relation: a many-to-many table of two keys and nothing of its own.

1. **`TaskRun`**: each background job's last run (`startedAt`, `finishedAt`, `error`), keyed by
   the job's name as the code registers it (`backups`, `pruning`, `mail`, …). It carries
   values of its own, so it falls under the id rule; it was left as it is because the code
   finds a job's row by its name. Give it an id, the name a unique column?
2. **An organisation's causes** (`Organisation.causes`): a JSON list of words describing a
   charity ("education, health"), used like tags on the giving screens (S7.9). Should causes be
   records of their own, shared across organisations, as tags are records (`Tag`)?
3. **Tags shared in a household**: a `Tag` is its owner's, as S2.6 says (the user's own). A
   household would rather share one set of tags ("vacation", "tax-deductible"), each person
   still tagging only for themselves, or tagging for everyone. Who owns a shared tag, who may
   rename it, and what a receiver of a shared account sees.
4. **The pure relations** have no id of their own, by the rule above: `BudgetLeaveOuts`,
   `GiftPersons`, `PortfolioAccounts`, `ReceiptTags`, `RuleTags`, `ShownProjections`,
   `TaxDependentAccounts`, `TransactionTags`, `UserGroups`. Each is changed as a set held by
   its record (`{add, remove}`, S13.8.11.1). Does any of them gain a value of its own (who
   added it, when), and so an id?

## Records changed outside the save

Every form edits a draft and saves it through `POST /ui/api/save` (S12.15, S13.8.11). These
records are still changed by an action, an upload, a flow or the server itself. Each is a
question for the review: keep it outside the save, or move it in.

5. **Actions that change fields of records**, the first candidates for the save:
   1. `Transaction`: bulk categorise (`POST /transactions/categorise`, up to 1,000 at once,
      no versions); *both real* (`duplicateAnswer` on each twin); *keep off chain*
      (`offChainAt`, `offChainKeptAt`, with its version); *apply rules* (`POST /rules/apply`,
      the uncategorised in every account the user writes).
   2. `Projection`: activate and deactivate (`active`, `baseline`, `baselineAt`, the one it
      replaces made a scenario); *Start goal* on a 529 makes one.
   3. `PayoffPlan`: follow, or stop (`following`, `followingSince`, on every plan of the
      loan).
   4. `Relationship`: a marriage confirmed by the other spouse; `Person`: a linked server's
      user joined to a person.
   5. `TaxBookFiler`: a filer's `acceptedAt` (`POST /tax-books/{id}/accept`); `TaxBookChange`:
      settled by *No amendment needed*.
   6. `AlertState`: seen and dismissed; `TransferMatch`: a bitcoin transfer answered.
   7. `Receipt`: read again, one or all (an admin's), replacing only empty or read fields.
6. **Actions that make records from others**: budget copy (`Budget`, its lines and moves),
   *Mark reviewed* (`BudgetReview`, the month's figures kept), *roll* and *settle* (option
   trades, `Lot`s), *adjust contracts* (`OptionContract`), the import steps (`Import`,
   `Holding`, `HoldingCheck`, `ImportMapping`, `StatementLayout`), wallet sync
   (`WalletAddress`), price refresh (`Price`), and uploads (`Receipt`). Each works out what it
   makes on the server; a draft would hold only the request.
7. **Flows and the server's own state**, kept apart from drafts on purpose: sign-in and
   sessions (`Session`, `RecoveryCode`, `OneTimeToken`), signup (`SignupRequest`), a user's
   password, email and two-step, linked servers (`Link`, `LinkedItem`, `LinkSent`, `LinkFile`),
   the connector (`Connector`, a `Connection`'s credential as a `Secret`), and what the server
   writes alone (`Activity`, `Alert`, `QueuedEmail`, `Instrument`, `WashSale`, `TaskRun`).
   Is any of them a record a person edits, and so one for the save?
