# S17.9. Milestones

9. **Milestones**. The requirements describe the finished product; this is the
   order to build it in. Each milestone ends with `web/check` passing, a Docker image that
   runs, and the generated mockup covering what was built.
   1. **Milestone 1, the foundation and one household's accounts:**
      1. **Repository and tooling**: the layout of S17.1, `web/dev.sh`, `web/check`
         (pytest, ruff, Deno, Playwright, OpenAPI and typedef drift), `uv.lock`, and the
         Docker image for amd64 and arm64 with `compose.yaml` (S17.8).
      2. **Server core**: configuration, the listener in both modes (S13.3), the refused
         start (S13.6), the security policies (S13.7), the API conventions (S13.8), the live
         stream (S12.6), background tasks (S13.4) and dev mode with seed data (S17.7).
      3. **Storage and keys**: the SQLCipher database, the master key with its recovery
         phrase, `keys` commands and data key (S15), Alembic, the schema conventions with
         prefixed ids, soft-delete fields and `<Table>Effective` views, and the schema
         checks (`schema.md`); backups (S14.6).
      4. **Users**: the default admin's setup, invitations (email written to a folder until
         SMTP is set), sign-in, sessions, password reset, the active flag, groups, and
         Profile (time zone, theme). Two-step sign-in can wait for milestone 2.
      5. **Accounts and transactions**: account types for banking, cards, brokerage and
         retirement (S1.1, without loans, 529s, physical assets or crypto); manual entry,
         CSV and OFX/QFX import (S1.3.1–S1.3.2); transactions with categories; holdings and
         lots from brokers' files (S2); transfers matched (S1.7); reconciliation's coverage
         and anchors (S1.11).
      6. **Prices**: the `TickerSource` interface with Tiingo, Coinbase, manual and the dev
         stub (S4), the daily refresh, stored closes and staleness.
      7. **Sharing between users**: accounts and portfolios, read and write, users and
         groups (S10.3–S10.7), and Activity (S10.8).
      8. **The app**: the frame, navigation, help pane with its guides, theme and privacy
         mode (S12); Dashboard (net worth, accounts, needs attention), Accounts, an account's
         Overview, Transactions and Reconcile, the Transactions screen, Portfolios with
         Performance and Holdings, Settings (General, Sign-in and sessions, Passwords,
         Prices, Imports, Backups, Key storage) and Users and Groups.
      9. **The mockup** generated from the app for these screens (S12.9); the hand-written
         mockup stays the reference for everything not built yet.
   2. **Milestone 2**, in nine parts:
      1. **Two-step sign-in** (S10.1.6): TOTP set up from a QR code in Profile, the code
         after the password, ten recovery codes, and an admin's reset.
      2. **SMTP and emails**: Settings › Email with **Send a test email**, every email of
         S10.1.9 sent through it, and sign-up with its approval (S10.1.4).
      3. **Alerts** (S12.11): the screen, its badge, the emails and their daily summary,
         Settings › Alerts, and the causes milestone 1 and 2 have built.
      4. **Budgets** (S7.1–S7.5): planned, actual and rollover per category, the budget
         screens and recurring transactions.
      5. **Receipts** (S9.1–S9.7): upload, encrypted storage, thumbnails, the viewer, links
         and the inbox, sharing and retention.
      6. **Reading receipts** (S9.8): the worker process, RapidOCR with its shipped models,
         the field parser, matching, search and Settings › Receipts.
      7. **Statement import** (S1.3.3.1–S1.3.3.4): bank and card statements, read and
         checked, with their layout learned per institution.
      8. **Projections and assumptions** (S6.1–S6.9): Profile › Assumptions, the models,
         scenarios, active projections with tracking, the Dashboard's Plans card, and
         Settings › Tax tables with the contribution limits and the bitcoin models' figures.
         Retirement and savings-target goals; the education goal comes with 529s.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   3. **Milestone 3**, in nine parts:
      1. **Loans** (S1.9): terms, the amortization schedule, payments split from their
         transfers, reconciling with the servicer, and the loan's screen.
      2. **The payoff planner** (S6.10): plans against the schedule, recast, and the extra
         invested instead.
      3. **Physical assets** (S1.10): items, their valuations (spot for metals, dated
         values, depreciation), real estate with its loans' equity, and selling.
      4. **529 plans** (S1.8) and the **education goal** (S6.2.2), with the college-cost
         averages in the tax tables.
      5. **Gifts** (S7.7–S7.8): people, occasions and holidays, gifts and ideas, history,
         privacy, the gift-tax flag and the occasion alerts.
      6. **Charitable giving** (S7.9): giving plans, donations and organisations, pledges,
         donor-advised funds and the Giving screen.
      7. **Tax books** (S8.14–S8.17): filers, accounts counted, sharing, filings, tax
         documents and what is carried forward.
      8. **The tax panels and exports** (S8.1–S8.13): Form 8949 and Schedule D with wash
         sales, income, retirement, deductions, the documents checklist, giving, education,
         gifts, loans and physical assets; 8949 CSV, TXF and the PDF summary.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   4. **Milestone 4**, in nine parts:
      1. **Positions** (S3.1, S3.9): the Positions screen, open and closed, with each lot's
         holding period, and realized and unrealized gains by year, month, account and
         instrument.
      2. **Options** (S3.2, S3.3): option contracts as instruments, the four opening and
         closing trades, short options as negative lots, and their gains at close.
      3. **Expiry, assignment and exercise** (S3.4, S3.6): expiry applied the day after out
         of the money, an in-the-money expiry asked about, and assignment and exercise
         folding the premium into the stock's basis or proceeds.
      4. **Option marks and trades** (S3.7, S3.9, S4.5): marks from a source, typed, or
         intrinsic; per-trade P/L and return on capital at risk; options in Form 8949 and
         flagged for wash-sale review; and the wash-sale basis carried into the replacement
         lot.
      5. **Bitcoin wallets** (S1.6.1, S1.6.3): addresses and extended public keys, the
         addresses derived from them with a gap limit, and the form that refuses keys and
         seed phrases.
      6. **Bitcoin sources** (S1.6.2): Settings › Bitcoin with a public explorer or the
         household's own node (Esplora, an Electrum server, Bitcoin Core), and the wallets'
         balances and history kept current from it.
      7. **Access tokens** (S10.9.1): Profile › Access tokens, their scope and expiry, shown
         once and stored as a hash.
      8. **The MCP endpoint** (S10.9): `/mcp` over Streamable HTTP, read-only tools through
         the user's shares, limited and recorded in Activity.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   5. **Milestone 5**, in nine parts:
      1. **Link keys and the protocol** (S11.1.3): each server's Ed25519 link key,
         signed calls with their timestamp and nonce checks, the `/link` listener, the
         `Link` record, and `docs/link-protocol.md` with how versions differ.
      2. **Invitations** (S11.1, S11.6, S11.7): the link code, the request and its
         approval, Settings › Linked servers with Pause and End link, and each side's
         active users and household name and avatar sent at every exchange, kept as remote
         `User` records.
      3. **Sharing with linked people** (S10.3.3, S10.4): the Share dialog's people on each
         linked server (None · Read) and Include receipts, and shares suspended or removed
         with their remote user or link.
      4. **The linked copy and its access key** (S11.9.1–S11.9.4, S11.9.8): the copy's
         folder and SQLCipher database, the 12-word access key and the keys derived from it,
         unlocking with its limits, the sweeper that locks an unused copy, Lock now and
         Reset copy.
      5. **Sealed files** (S11.9.5, S11.9.6): the streaming MKR1 format, the inbox of sealed
         changes applied in order once unlocked with each signature checked, receipts
         written straight into the copy, and the full snapshot when the inbox overflows.
      6. **Pulls** (S11.3.1, S11.4, S11.5, S11.8): each shared item worked out at its source
         as the people it names see it, versioned so only changes travel, signed, pulled
         hourly and on Pull now by whichever side can reach the other, copies deleted when a
         share or link ends, and each pull recorded on both sides.
      7. **The linked household window** (S12.10): the avatar menu and the Linked households
         card, `/ui/linked/<link-id>/` with the household's avatar and name, a colour per
         user, the header strip, the locked state asking for the words, and the screens
         read only from the copy.
      8. **Alerts and receipts across links** (S11.5.1, S12.11): a failing link and a first
         share waiting for its access key alerted, receipts and tax documents shown from the
         copy through decryption, and what an older or newer peer does.
      9. **The mockup** generated from the app for these screens, and the Docker image, with
         two servers linked.
   6. **Milestone 6**, what the requirements settled after milestone 5, in nine parts:
      1. **People and relationships** (S10.10, S7.7): people with sex and dates, every user
         a person, dated relationships and the family tree, gift plans, the duplicate-name
         check and ask-to-share, the spouse read by date for wash sales and tax books, and a
         deleted person's gifts. Tax-book dependents (S8.14.5).
      2. **Statements, more of them** (S1.3.3.5, S1.3.3.6, S1.11.7): a combined statement
         split per account, a statement kept without reading, and statements expected per
         account with their alert.
      3. **Brokerage and plan statements** (S1.3.3.8): the summary as a balance anchor, the
         positions as a holdings check, the cash activity, and trades offered to the trade
         dialog.
      4. **File retention and pruning** (S14.10, S16.17): when each record ended, a
         category's and the statements' retention, each file's *Kept until* and Keep, and
         Settings › Storage with Prune.
      5. **Strategies** (S3.5): grouping proposed and by hand, rolls, the shapes, max profit
         and loss, breakevens, and capital at risk now and at open on Positions, the account
         and the portfolio.
      6. **Adjusted contracts** (S3.10): whole-number splits applied with the stock's, other
         adjustments from the OCC memo with their root and deliverable, linked on import,
         assigned and exercised by deliverable, and marked under the new root.
      7. **Bitcoin, the rest** (S1.6, S1.7.1, S8.19): output descriptors, the node's
         certificate trusted on first use, confirmations and reorgs, bitcoin kept in sats
         with Profile's BTC or sats, transfers between wallets matched with their lots, and
         network fees as sales.
      8. **Links, the rest** (S11, S12.10): every screen of each shared kind in the linked
         window, `/link/` as a path, sync oldest to newest with its progress, and Pause for a
         duration with Resume now (S12.13).
      9. **The mockup** generated from the app for these screens, and the Docker image.
   7. **Milestone 7**, what the first release still needs, in ten parts. The build has no
      bitcoin node, arm64 machine, second network or Schwab developer account, so what needs
      one is built against a mock here and tried for real from the manual test plan
      (S17.9.7.8):
      1. **Python 3.14**: `requires-python`, a fresh `uv.lock` with its egress audit
         (S17.2.1), the image's base, the wheel check and the register, so the connector
         starts on it too. Every native dependency publishes wheels for it on both
         architectures, and 3.14 is supported two years longer than 3.12.
      2. **The connector protocol**: `docs/connector-protocol.md` in the form of the link
         protocol (pairing from the one-time code, the signed calls, the report, collecting
         a sealed credential, posting a file, the refusals, the version rule), and the
         `Connector` and `Connection` tables (`schema.md` §3.2).
      3. **MoolaKata's side** (S18.4, S18.5): the `/connector/v1/` routes, pairing with its
         code and re-authentication, Settings › Connector with Pair and Unpair, the two
         admin alerts and the silent-connector check (S13.4).
      4. **Connections in the app** (S18.6, S18.7): the account's **Sync using MoolaKata
         Connector** switch, Profile › Connections, the credential dialog sealing to the
         connector's key in the browser (X25519 in WebCrypto), the command for typing them
         on the connector's host, and the owner's alert.
      5. **The connector core** (S18.1–S18.3): `connector/`, its vault and words, lock and
         unlock over its socket, pairing, signed calls, the egress allowlist, its image and
         the `connector` service in `install/compose.yaml` (S18.10), and `operations.md` §8.
      6. **The posting path** (S18.8), proved end to end with a driver that needs no
         credentials.
      7. **OFX Direct Connect and Schwab** (S18.9.1, S18.9.2), each built against a mock of its
         institution: a fake OFX server, and a stub serving recorded shapes of the Trader API's
         answers. The live Schwab trial is in the test plan.
      8. **Mocks and the manual test plan**: a fake Esplora, Electrum server and Bitcoin
         Core RPC speaking the subset MoolaKata uses, for the tests and the generated
         mockup's recordings; the arm64 image built under QEMU and smoke-run under
         emulation; and `docs/test-plan.md`, one numbered test per thing the build can't
         try, each with the environment it needs, its steps and what passing looks like:
         wallets against Fulcrum, electrs, Bitcoin Core 27 and later and a self-hosted
         mempool; links over an overlay such as Tailscale and over a forwarded port; the
         arm64 image on real hardware; the Schwab driver with a real developer account; an
         install on Proxmox and on TrueNAS (`DEPLOY.md` §3–4); and a restore drill
         onto a new host. A release says which were run.
      9. **Hardening**: `web/dev.sh audit` and the register's hash check in `web/check`
         (S17.2.1), the base image's update process (S13.7.11), and the real receipt
         fixtures for the reader (S17.5).
      10. **The mockup** generated from the app for these screens, both images, and
         `web/check`.
   8. **Milestone 8**, what the second review of the requirements against the code found the
      first release still needs, in nine parts:
      1. **Access**: host commands over the server's Unix socket, and the example's trusted
         proxy narrowed to the proxy's own address (S13.3, S13.6); a linked household's
         receipts served as a local receipt is (S11.9.6.5); access tokens made with the
         password again and stopped by a password change (S10.9.4); the password again on every
         action of S13.7.2, a secret cleared when its host changes (S16.2, S16.7); and access
         between users as S7.1.1, S7.9.1, S8.14, S9.6 and S10.10 say.
      2. **Transport**: TLS verified on links and the connector, a certificate of a server's
         own pinned through its code (S11.1, S18.4); signed answers naming the caller and the
         request; only `link-ended` ending a link (S11.6); link changes and receipts sealed end
         to end to the receiving copy's key (S11.4, `docs/link-protocol.md`).
      3. **The reader's sandbox** (S9.8.4.2), with every file a person or the connector brings
         parsed in it.
      4. **Key operations**: the journal, re-encryption only while the server isn't serving,
         rotation that re-encrypts (S15.7), the restore that re-wraps the receipts (S15.6.8),
         host commands taking the data directory's lock (S15.4.7), and the unlock's report of
         what a restored database can't open, re-encryption's progress and restoring a
         `pre-upgrade/` copy.
      5. **Figures**: the lots, wash sales, reinvestments, deductions, options from broker
         files and loan rates the review found wrong, and Form 8949's digital-asset boxes
         (S8.1).
      6. **Categorisation and payee rules** (S2.6, S2.7).
      7. **The rest of what was promised**: symbol changes, spin-offs and mergers (S2.4); the
         closed-year confirmation (S2.8); a short stock lot from an assignment with no shares
         (S3.4); `/link`'s rate limits (S13.7.5.4) and uploads in flight (S13.7.6); the
         orphan-file sweeper and who viewed linked data (S11.8, S11.9.6.6); the recovery-code
         and new-address emails (S10.1.9); a tax document's file through its tax book and
         receipts on gifts and donations (S8.16, S9.3); the alerts S12.11.1 lists that aren't
         raised yet; problem types and codes in the OpenAPI document (S13.8.3); and a separate
         allowlist for each driver, with its test (S18.1.2).
      8. **The connector**: the Folder driver taken out (S18.9), the lost-host response
         (S18.4.4, S18.5.4), the credential bound to the host sealed with it (S18.7.3), the
         sealing key signed by the identity key, the sign-in host pinned, and the quick
         exchange of a landed address (S18.5).
      9. **The rest of the review's findings**, the generated mockup and help shots for what
         changed, both images, and `web/check`.
   9. **Milestone 9**, what the second review's account of its findings against the code
      (`docs/reviews/initial-code-review-2.md`, section 12) found still open, in nine parts:
      1. **Sign-in**: a two-step sign-in ended after five wrong codes, one code checked at a
         time, the slowdown before the check, and the lockout counting an IPv6 address by its
         /64 (S10.1.6.3, S13.7.5.1); reactivation, re-authentication and the current-password
         check behind the sign-in guard, a reactivation request answered the same whatever the
         account, and sign-up taking the same time for an address already known (S10.1.4.1,
         S10.1.7); and what errors and logs may hold (S13.7.8, S13.7.9).
      2. **Email queued in the database** (S16.2, S15.1.7): an email waits there until it is
         sent or its link expires, a refused one keeps only its recipient, subject and error,
         and a written email stays in the mail folder as long as its link works.
      3. **The connector**: the key MoolaKata's `hello` gives hashed against the pairing's
         fingerprint (S18.4.2), and `connect` showing the host the credentials will go to and
         filing them once the admin confirms it (S18.7.2).
      4. **Links**: a call not yet signed by a known key refused before it opens a transaction
         (S13.7.5.4); a copy's key gone with its release; a change applied once and in order
         (S11.9.5.3); a pull recorded with its link (S11.8); a shared budget naming only the
         accounts shared (S11.3.1); a person shared to a linked server (S10.3); what flows each
         way in Settings › Linked servers (S11.7); and the link protocol's answers and
         refusals stated once (`docs/link-protocol.md` §1.3, §7).
      5. **The host and the reader**: a PDF page rendered within the pixel cap (S9.8.4.3);
         uploads held in memory (S13.7.6); Remove copy asking for the phrase too (S16.13);
         `verify-backup` showing when a backup was made; the live stream's alert event without
         a title; dev mode only from a checkout; pruning that counts no deleted receipt
         (S14.10.5); a restore that leaves the receipt files where they are (S15.6.8); and an
         unlock counted as a check of the recovery phrase (S15.6.5).
      6. **Figures**: an option's expiry decided on the expiry day's close only (S3.6); a wash
         sale's replacement in an IRA (S3.8.3); an adjusted strike rounded (S3.10.1); PMI in a
         payoff plan (S1.9.5); a portfolio's returns keeping a deleted account, a donated
         replacement's holding period, and TXF's codes (S5.2, S7.9.3, S8.2); and the last
         money columns in cents (S14.3).
      7. **Imports, wallets, alerts and the contract**: imports' answers in exact numbers
         (R1.9); no wallet read until Settings › Bitcoin is saved (S16.7); skips learned only
         from lines left out by choice (S1.3.3.4); the stale statement value's alert (S4.3);
         a loan's statements checked on its Overview (S1.11); and every problem code, and
         every 422, in the OpenAPI document (S13.8.3).
      8. **Tests**: a golden-file case for each figure the second review found wrong (S17.5),
         a `Location` test that follows what it names, and tests for the fixes that had none.
      9. **The rest**: the generated mockup and help shots for what changed, both images, the
         review's section 12 brought up to date, and `web/check`.
   10. **The first release** is the nine milestones. The build's branch is committed and pushed
      part by part, and merges into `main` only once all of it is built and the requirements
      have their final approval.
   11. **After the first release**: the items of [later work](later.md), L1 to L12.
   12. **Milestone 10**, after the first release: budgets as S7 describes them, in ten parts,
       each pushed on its own and the whole checked at its end:
       1. **What a budget counts** (S7.2, S7.3.1–S7.3.3, S7.3.9): savings categories and the
          shipped *Cash*, *Savings* and *Loan payments*; refunds in the month they land, and
          pending transactions left out; money leaving or entering the budget, listed to sort
          when it has no category, and the accounts left out named when a budget is made or
          edited; and loan payments counted at the bank, split by the schedule or whole as each
          loan says (S1.9.7), starting with a test of how a matched loan payment counts before
          the change.
       2. **Cash and payment apps** (S1.1, S1.7, S1.11.7): the `cash` and `payment-app` types,
          their icons, forms and statement defaults; cash taken out paired with its deposit in a
          cash account; and a cash account outside a budget counted as *Cash*.
       3. **Reimbursable spending** (S2.9, S7.3.4): the mark on a transaction or a split, with
          its amount and who owes it; **Awaiting reimbursement**; paybacks offered and paired,
          one deposit paying back several; and what budgets count of each.
       4. **A budget's method, options and plan** (S7.1.3–S7.1.6, S7.3.6–S7.3.8, S7.2.1): the
          method and options chosen at creation and the options changed in its settings; each
          card's *paid from* and each savings account's *moved from*, with the default worked
          out (S7.1.6); *Gifts* and *Giving* planned by their plans; what overspending
          does, per line; a savings line naming a projection; and **Estimate from history**.
       5. **Reserves** (S7.10): targets changing from a month on, balances worked out, Funded,
          the question before a balance stops being kept, *held in* across several accounts,
          and **Where the money is** with *to move*, *backed*, a shortfall, landed money left
          unassigned until given, and **Withdrawals allowed a month** (S1.2) with moves back
          summed into one transfer and the warning past the limit.
       6. **Moves and leave-outs** (S7.11, S7.3.5, S12.2.3): moves between categories, reserves among them, and
          **Cover from…**, the month's moves, their Activity, a move in a past month; and a
          transaction's **In budgets** line with each budget's **Leave out**.
       7. **The active budget and scenarios** (S7.12, S12.2.1, S12.2.6): each user's active
          budget, **Make active**, **Copy as scenario…**, **Compare**, the scenario's banner,
          the Budgets list, and the Dashboard's card of the active budget's month.
       8. **Envelope budgets** (S7.13): *To Budget* from the budget's first month, assignments
          by the plan and by moves, card payment lines, *owed, not backed*, a starting debt,
          and what an overspent envelope does at the month's end.
       9. **The review, the cache and the alert** (S7.14, S7.3.10, S7.6, S12.11): a month
          marked reviewed and flagged when it later changes; month figures kept, worked out
          again when what they come from changes, and **Refresh**; and the cash before payday on each checking account with
          recurring payments.
       10. **The rest**: a golden-file case for every new figure (S17.5): carries and
           rollover, reserves, moves, *to move*, *To Budget*, card payment lines, a loan's
           split, reimbursements and money leaving the budget; the generated mockup and help
           shots for what changed; both images; and `web/check`.
