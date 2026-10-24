# Code review 3: the map

Built in Phase 0 (docs/REVIEW.md §4.2) at `6916954`. Lines are newline counts at that commit.
Delta is from review 2's `294792b` (§4.3), per unit in `delta.txt`. Paths are relative to the
repository's root; `src/` is `web/server/src/moolakata/`, `ui/` is `web/ui/`, `tests/` is
`web/server/tests/`, `mig/` is `src/store/alembic/versions/`.

**Two measures of change.** Every file under `web/server/src`, `connector/` and most of `web/ui`
was renamed when the product became MoolaKata (`moneykata` → `moolakata`, 255 renames, nothing else
moved). §1 counts a move as changed, so *changed* counts a renamed file whole. *Content* counts
only lines added (a rename's import lines included), which is closer to what is new to read.

## Units

| Unit | Sections | Code lines | Files | Changed (moves whole) | Content changed | Test lines |
|---|---|---:|---:|---:|---:|---:|
| 01 accounts-imports | S1.1–S1.5, S1.7, S1.11 (types, keeping current, imports, retirement, exchanges, transfers, reconciliation) | 8,858 | 57 | 6,237 (70%) | 930 (10%) | 2,025 |
| 02 items-loans-education-bitcoin | S1.6, S1.8–S1.10 (bitcoin wallets, 529 plans, loans, physical assets) | 8,647 | 29 | 5,962 (68%) | 352 (4%) | 1,406 |
| 03 lots-positions-prices-portfolios | S2, S3, S4, S5 | 11,156 | 50 | 9,007 (80%) | 2,921 (26%) | 1,867 |
| 04 projections-taxes | S6, S8 | 8,415 | 25 | 6,162 (73%) | 829 (9%) | 1,479 |
| 05 budgets-gifts-giving | S7 | 9,973 | 26 | 7,914 (79%) | 5,367 (53%) | 1,680 |
| 06 receipts-storage | S9, S14 | 9,412 | 51 | 8,661 (92%) | 1,866 (19%) | 1,736 |
| 07 users-sharing | S10 | 9,468 | 45 | 7,314 (77%) | 1,235 (13%) | 2,372 |
| 08 linked-servers | S11 | 5,943 | 20 | 4,446 (74%) | 1,825 (30%) | 1,430 |
| 09 web-ui-architecture | S12, S13 | 10,077 | 59 | 5,170 (51%) | 1,793 (17%) | 2,619 |
| 10 encryption-settings | S15, S16 | 6,287 | 18 | 5,019 (79%) | 2,510 (39%) | 544 |
| 11 implementation | S17 | 8,301 | 77 | 6,681 (80%) | 3,250 (39%) | 1,016 |
| 12 connector | S18 | 5,355 | 30 | 4,680 (87%) | 2,052 (38%) | 2,313 |
| **all units** | | **101,892** | 487 | **77,253 (75%)** | **24,930 (24%)** | 20,487 |
| generated and data, not read as code | | 54,086 | 17 | 12,512 | 8,416 | |
| help guides (`ui/guides/`), read for what contradicts the sections | | 6,062 | 260 | 1,417 | 1,417 | |

`check_docs.py` reads citations only under `web/server/src`, `connector` and `web/ui`; files elsewhere (unit 11's packaging and CI) show no cites.

Generated and data: `web/ui/api/openapi.json`, `web/ui/api/types.js`, `web/server/src/moolakata/keys/bip39-english.txt`, `connector/moolakata_connector/bip39-english.txt`, `web/server/src/moolakata/auth/common-passwords.txt.gz`, `web/audit.json`, `web/server/uv.lock`, `web/server/tests/fixtures/*`, `web/server/tests/golden/*`.
`ui/api/openapi.json` and `ui/api/types.js` are written by `python -m moolakata.contract write` and
checked by `web/check`; unit 09 reads `contract.py`, which makes them.

The help guides are read by the unit whose screens they explain (`ui/guides/<screen>*.md`). The
baseline migration `mig/0001_the_initial_schema.py` (3,022 lines) is generated from the tables and
held to them by `store/schema_check.py`; unit 06 reads it against `schema.md` by search, not line
by line. The later migrations go to the unit of their tables.

## First-level items no code cites

From `doccheck.txt`. Each goes to the unit of its section, which judges whether it is built
under other words, scheduled, or **not built**:

- unit 01 or 02: S1.4, S1.5
- unit 03: S2.1, S4.1, S4.8, S4.9
- unit 04: S6.2, S6.5, S6.6, S8.10
- unit 05: S7.6
- unit 06: S14.2, S14.5, S14.8
- unit 07: S10.5
- unit 09: S12.14, S13.1
- unit 10: S15.1, S15.2, S15.5, S16.15
- unit 11: S17.1, S17.9, S17.10
- unit 12: S18.2

## Unit 01: accounts-imports

**Sections:** S1.1–S1.5, S1.7, S1.11 (types, keeping current, imports, retirement, exchanges, transfers, reconciliation). **Code:** 8,858 lines in 57 files; **changed** 6,237, **content** 930, 4 new files. **Tests:** 2,025 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/importers/__init__.py` | 3 | S1:1 | 0/0 moved |
| `src/importers/brokerage.py` | 349 | S1:1 | 0/0 moved |
| `src/importers/csvfile.py` | 326 | S1:2 S3:1 | 33/2 moved |
| `src/importers/ofx.py` | 305 | S3:2 S1:1 S2:1 S14:1 | 53/5 moved |
| `src/importers/parsed.py` | 246 | S3:1 S9:1 | 246/0 |
| `src/importers/statements.py` | 395 | S1:4 | 14/3 moved |
| `src/ledger/__init__.py` | 3 | R3:1 S14:1 | 0/0 moved |
| `src/ledger/balances.py` | 64 | S1:2 R3:1 | 0/0 moved |
| `src/ledger/categories.py` | 124 | S7:2 S1:1 | 25/7 moved |
| `src/ledger/expected.py` | 111 | S1:1 | 3/3 moved |
| `src/ledger/holdingcheck.py` | 78 | S1:1 | 4/2 moved |
| `src/ledger/reconcile.py` | 176 | S1:6 | 17/11 moved |
| `src/ledger/transfers.py` | 33 | S1:1 | 0/0 moved |
| `src/ledger/types.py` | 127 | S1:5 | 12/4 moved |
| `mig/0004_statement_intervals_and_kept_statements.py` | 73 | S1:2 | 1/1 moved |
| `mig/0005_holding_checks_and_statement_values.py` | 113 | S1:1 | 10/10 moved |
| `mig/0029_cash_and_payment_apps.py` | 53 | S1:1 | 53/0 |
| `src/store/entities/accounts.py` | 349 |  | 34/0 moved |
| `src/store/repos/__init__.py` | 2 | S14:1 | 0/0 moved |
| `src/store/repos/ledger.py` | 661 | S1:6 S3:5 S2:2 | 219/53 moved |
| `src/store/tables/accounts.py` | 426 | S1:9 S2:3 S3:3 R3:1 S7:1 S14:1 S18:1 | 60/6 moved |
| `src/ui/accounts.py` | 936 | S1:8 S3:2 S2:1 S12:1 S18:1 | 41/11 moved |
| `src/ui/imports.py` | 1212 | S1:6 S13:2 R1:1 R3:1 | 33/24 moved |
| `ui/account-types/401k.js` | 12 | S1:1 |  |
| `ui/account-types/403b.js` | 12 | S1:1 |  |
| `ui/account-types/457b.js` | 12 | S1:1 |  |
| `ui/account-types/529.js` | 13 | S1:2 |  |
| `ui/account-types/auto-loan.js` | 13 | S1:2 |  |
| `ui/account-types/brokerage.js` | 12 | S1:1 |  |
| `ui/account-types/cash.js` | 13 | S1:1 | 13/0 |
| `ui/account-types/cd.js` | 12 | S1:1 |  |
| `ui/account-types/checking.js` | 12 | S1:1 |  |
| `ui/account-types/collectables.js` | 13 | S1:2 |  |
| `ui/account-types/credit-card.js` | 12 | S1:1 |  |
| `ui/account-types/crypto-exchange.js` | 12 | S1:1 |  |
| `ui/account-types/crypto-wallet.js` | 14 | S1:2 |  |
| `ui/account-types/daf.js` | 12 | S1:1 S7:1 |  |
| `ui/account-types/heloc.js` | 13 | S1:2 |  |
| `ui/account-types/hsa.js` | 12 | S1:1 |  |
| `ui/account-types/index.js` | 84 | S1:5 | 4/0 |
| `ui/account-types/ira.js` | 12 | S1:1 |  |
| `ui/account-types/loan.js` | 13 | S1:2 |  |
| `ui/account-types/money-market.js` | 12 | S1:1 |  |
| `ui/account-types/mortgage.js` | 13 | S1:2 |  |
| `ui/account-types/other-asset.js` | 13 | S1:2 |  |
| `ui/account-types/payment-app.js` | 13 | S1:1 | 13/0 |
| `ui/account-types/personal-loan.js` | 13 | S1:2 |  |
| `ui/account-types/precious-metals.js` | 13 | S1:2 |  |
| `ui/account-types/real-estate.js` | 13 | S1:2 |  |
| `ui/account-types/roth-ira.js` | 12 | S1:1 |  |
| `ui/account-types/savings.js` | 12 | S1:1 |  |
| `ui/account-types/student-loan.js` | 13 | S1:2 |  |
| `ui/account-types/vehicle.js` | 13 | S1:2 |  |
| `ui/screens/account.js` | 1162 | S1:5 S12:1 | 39/11 |
| `ui/screens/accounts.js` | 182 | S12:2 S10:1 |  |
| `ui/screens/import.js` | 709 | S1:5 | 3/3 |
| `ui/screens/new-account.js` | 192 | S12:1 |  |
| `tests/test_accounts.py` | 507 | test | 134/0 |
| `tests/test_brokerage.py` | 256 | test | 2/2 |
| `tests/test_created.py` | 323 | test | 323/0 |
| `tests/test_expected.py` | 119 | test | 3/3 |
| `tests/test_importers.py` | 194 | test | 67/2 |
| `tests/test_ledger.py` | 277 | test | 43/10 |
| `tests/test_statements.py` | 349 | test | 19/1 |

## Unit 02: items-loans-education-bitcoin

**Sections:** S1.6, S1.8–S1.10 (bitcoin wallets, 529 plans, loans, physical assets). **Code:** 8,647 lines in 29 files; **changed** 5,962, **content** 352, 1 new files. **Tests:** 1,406 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/assets/__init__.py` | 272 | S1:4 S14:1 | 3/2 moved |
| `src/bitcoin/__init__.py` | 2 | S1:1 | 0/0 moved |
| `src/bitcoin/descriptor.py` | 215 | S1:1 | 6/6 moved |
| `src/bitcoin/keys.py` | 405 | S1:3 | 32/11 moved |
| `src/bitcoin/sources.py` | 429 | S1:3 S13:1 S14:1 | 13/8 moved |
| `src/bitcoin/stub.py` | 32 | S17:1 | 0/0 moved |
| `src/bitcoin/sync.py` | 304 | S1:4 R3:1 S4:1 S8:1 S16:1 S17:1 | 44/15 moved |
| `src/bitcoin/transfers.py` | 166 | S1:1 S8:1 | 0/0 moved |
| `src/bitcoin/wallet.py` | 130 | S1:1 | 10/2 moved |
| `src/education/__init__.py` | 260 | S1:2 | 0/0 moved |
| `src/loans/__init__.py` | 441 | S1:3 | 26/7 moved |
| `src/loans/payoff.py` | 169 | S1:1 S6:1 S14:1 | 15/17 moved |
| `mig/0009_bitcoin_the_rest.py` | 148 | S1:2 S8:1 | 5/5 moved |
| `mig/0021_wallets_kept.py` | 62 | S1:1 | 62/0 |
| `src/store/entities/assets.py` | 60 |  | 0/0 moved |
| `src/store/entities/education.py` | 111 |  | 2/0 moved |
| `src/store/tables/assets.py` | 88 | S1:1 S8:1 | 8/8 moved |
| `src/store/tables/education.py` | 50 | S1:3 S8:1 S10:1 | 3/3 moved |
| `src/store/tables/loans.py` | 54 | S1:3 S6:1 | 12/7 moved |
| `src/store/tables/wallets.py` | 58 | S1:2 | 0/0 moved |
| `src/ui/education.py` | 565 | S1:4 S10:2 S6:1 S13:1 | 2/2 moved |
| `src/ui/items.py` | 682 | S1:3 S8:1 S13:1 | 2/2 moved |
| `src/ui/loans.py` | 945 | S1:4 S6:2 S13:1 | 34/6 moved |
| `src/ui/wallets.py` | 256 | S1:5 S13:1 | 15/0 moved |
| `ui/components/edu.js` | 639 | S1:1 | 2/3 |
| `ui/components/items.js` | 793 | S1:1 | 1/2 |
| `ui/components/loan.js` | 629 | S1:2 | 43/4 |
| `ui/components/payoff.js` | 485 | S6:1 |  |
| `ui/components/wallet.js` | 197 | S1:2 | 12/4 |
| `tests/test_assets.py` | 224 | test | 4/4 |
| `tests/test_descriptors.py` | 78 | test | 2/2 |
| `tests/test_education.py` | 186 | test | 1/1 |
| `tests/test_loans.py` | 317 | test | 60/3 |
| `tests/test_wallets.py` | 601 | test | 126/16 |

## Unit 03: lots-positions-prices-portfolios

**Sections:** S2, S3, S4, S5. **Code:** 11,156 lines in 50 files; **changed** 9,007, **content** 2,921, 13 new files. **Tests:** 1,867 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/corporate.py` | 132 | S2:1 | 132/0 |
| `src/figures.py` | 162 | S5:4 R3:1 S10:1 S12:1 | 13/2 moved |
| `src/ledger/lots.py` | 737 | S3:9 S2:3 S1:2 R3:1 S8:1 | 301/31 moved |
| `src/ledger/performance.py` | 150 | S5:2 | 0/0 moved |
| `src/ledger/rules.py` | 81 | S2:1 | 81/0 |
| `src/options/__init__.py` | 260 | S3:5 | 16/31 moved |
| `src/options/adjust.py` | 191 | S3:2 | 8/2 moved |
| `src/options/strategies.py` | 563 | S3:5 | 52/12 moved |
| `src/prices/__init__.py` | 7 | S4:1 | 0/0 moved |
| `src/prices/base.py` | 106 | S4:2 S14:1 | 2/1 moved |
| `src/prices/cboe.py` | 148 | S3:2 S4:2 | 1/1 moved |
| `src/prices/coinbase.py` | 43 | S4:2 | 0/0 moved |
| `src/prices/manual.py` | 33 | S4:2 | 2/1 moved |
| `src/prices/massive.py` | 41 | S4:2 | 0/0 moved |
| `src/prices/refresh.py` | 407 | S4:5 S1:1 S12:1 | 75/14 moved |
| `src/prices/stub.py` | 58 | S17:1 | 0/0 moved |
| `src/prices/tiingo.py` | 53 | S4:1 | 0/0 moved |
| `src/reimbursements.py` | 143 | S2:1 S7:1 | 143/0 |
| `mig/0007_strategies.py` | 103 | S3:1 | 11/11 moved |
| `mig/0008_adjusted_contracts.py` | 63 | S3:1 | 1/1 moved |
| `mig/0017_figures.py` | 190 | S2:1 S3:1 S14:1 | 190/0 |
| `mig/0018_rules.py` | 78 | S2:1 | 78/0 |
| `mig/0019_corporate_actions.py` | 58 | S2:1 | 58/0 |
| `mig/0022_typed_prices_are_their_typers.py` | 69 | S4:1 | 69/0 |
| `mig/0030_reimbursable_spending.py` | 117 | S2:1 | 117/0 |
| `src/store/entities/prices.py` | 43 |  | 12/0 moved |
| `src/store/repos/rules.py` | 108 | S2:1 S9:1 | 108/0 |
| `src/store/tables/options.py` | 85 | S3:4 | 2/2 moved |
| `src/store/tables/prices.py` | 47 | S4:2 | 14/2 moved |
| `src/ui/options.py` | 356 | S3:5 S2:1 | 83/2 moved |
| `src/ui/portfolios.py` | 535 | S5:5 R3:1 S3:1 S10:1 | 35/7 moved |
| `src/ui/positions.py` | 479 | S3:6 | 14/12 moved |
| `src/ui/prices.py` | 372 | S4:3 S13:3 S16:1 | 32/27 moved |
| `src/ui/reimbursements.py` | 206 | S2:2 S13:1 | 206/0 |
| `src/ui/rules.py` | 287 | S2:2 | 287/0 |
| `src/ui/strategies.py` | 350 | S3:2 | 1/1 moved |
| `src/ui/transactions.py` | 1082 | S2:4 S1:3 S3:3 S12:2 S8:1 S10:1 S13:1 S14:1 | 128/19 moved |
| `src/valuation.py` | 359 | S4:3 S1:2 S3:2 | 69/18 moved |
| `src/washes.py` | 184 | S3:4 S10:1 | 59/19 moved |
| `ui/components/corporate.js` | 137 | S2:2 | 137/0 |
| `ui/components/optiontrade.js` | 225 | S3:4 S2:1 S4:1 | 11/8 |
| `ui/components/rules.js` | 247 | S2:1 | 247/0 |
| `ui/components/strategies.js` | 429 | S3:3 | 7/12 |
| `ui/components/txtable.js` | 167 | S12:1 |  |
| `ui/screens/portfolio-dialog.js` | 70 | S5:1 |  |
| `ui/screens/portfolio.js` | 259 | S5:1 | 3/2 |
| `ui/screens/portfolios.js` | 52 | S5:1 S12:1 |  |
| `ui/screens/positions.js` | 446 | S3:3 S12:1 | 9/4 |
| `ui/screens/transaction-dialog.js` | 483 | S2:3 S1:1 S7:1 S9:1 | 105/10 |
| `ui/screens/transactions.js` | 155 | S12:2 | 2/0 |
| `tests/test_adjusted.py` | 102 | test | 2/2 |
| `tests/test_figures.py` | 166 | test | 47/3 |
| `tests/test_options.py` | 370 | test | 99/6 |
| `tests/test_positions.py` | 271 | test | 168/3 |
| `tests/test_prices.py` | 403 | test | 84/15 |
| `tests/test_reimbursements.py` | 184 | test | 184/0 |
| `tests/test_rules.py` | 143 | test | 143/0 |
| `tests/test_strategies.py` | 228 | test | 36/4 |

## Unit 04: projections-taxes

**Sections:** S6, S8. **Code:** 8,415 lines in 25 files; **changed** 6,162, **content** 829, 3 new files. **Tests:** 1,479 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/projections/__init__.py` | 526 | S6:7 S1:1 | 57/18 moved |
| `src/projections/assumptions.py` | 93 | S6:1 | 0/0 moved |
| `src/projections/bitcoin.py` | 105 | R1:1 S6:1 | 1/1 moved |
| `src/projections/engine.py` | 222 | S6:3 | 10/3 moved |
| `src/projections/taxtables.py` | 257 | S8:3 S4:1 S6:1 S16:1 | 47/3 moved |
| `mig/0003_tax_book_dependents.py` | 114 | S8:1 | 7/7 moved |
| `mig/0023_edits_after_filing.py` | 86 | S2:1 S8:1 | 86/0 |
| `src/store/entities/projections.py` | 42 |  | 0/0 moved |
| `src/store/entities/taxes.py` | 118 |  | 14/0 moved |
| `src/store/tables/projections.py` | 61 | S6:4 S16:1 | 0/0 moved |
| `src/store/tables/taxes.py` | 169 | S8:8 S2:1 | 27/5 moved |
| `src/taxes/__init__.py` | 2 |  | 0/0 moved |
| `src/taxes/books.py` | 364 | S8:9 | 39/8 moved |
| `src/taxes/closed.py` | 119 | S2:2 S8:1 | 119/0 |
| `src/taxes/dates.py` | 51 | S8:1 | 51/0 |
| `src/taxes/dependents.py` | 365 | S8:5 | 1/1 moved |
| `src/taxes/exports.py` | 222 | S8:2 | 27/4 moved |
| `src/taxes/panels.py` | 1015 | S8:14 S1:1 S3:1 | 129/20 moved |
| `src/ui/projections.py` | 659 | S6:10 S10:1 S13:1 S16:1 | 44/6 moved |
| `src/ui/taxes.py` | 987 | S8:11 S12:1 | 55/13 moved |
| `src/ui/taxpanels.py` | 513 | S8:6 | 43/6 moved |
| `ui/components/plans.js` | 40 | S6:1 | 2/2 |
| `ui/components/taxpanels.js` | 637 | S8:4 | 45/6 |
| `ui/screens/projections.js` | 676 | S6:2 | 20/9 |
| `ui/screens/taxes.js` | 972 | S12:1 | 5/5 |
| `tests/test_golden.py` | 307 | test | 307/0 |
| `tests/test_projections.py` | 358 | test | 109/4 |
| `tests/test_taxbooks.py` | 544 | test | 232/1 |
| `tests/test_taxpanels.py` | 270 | test | 99/3 |

## Unit 05: budgets-gifts-giving

**Sections:** S7. **Code:** 9,973 lines in 26 files; **changed** 7,914, **content** 5,367, 15 new files. **Tests:** 1,680 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/budgets/__init__.py` | 691 | S7:13 S1:2 S2:1 | 691/0 |
| `src/budgets/cache.py` | 88 | S7:1 | 88/0 |
| `src/budgets/envelope.py` | 190 | S7:1 | 190/0 |
| `src/budgets/plan.py` | 228 | S7:4 | 228/0 |
| `src/budgets/recurring.py` | 115 | S7:1 | 2/0 moved |
| `src/budgets/reserves.py` | 226 | S7:3 | 226/0 |
| `src/gifts/__init__.py` | 445 | S7:7 S1:1 | 15/5 moved |
| `src/gifts/holidays.py` | 85 | S7:1 | 0/0 moved |
| `src/giving/__init__.py` | 287 | S7:4 S8:1 | 3/3 moved |
| `mig/0028_what_a_budget_counts.py` | 84 | S7:2 S1:1 | 84/0 |
| `mig/0031_a_budgets_method_and_reserves.py` | 103 | S7:4 | 103/0 |
| `mig/0032_reserves_and_moves.py` | 117 | S7:2 S1:1 | 117/0 |
| `mig/0033_leave_outs.py` | 57 | S7:1 | 57/0 |
| `mig/0034_the_active_budget.py` | 57 | S7:1 | 57/0 |
| `mig/0035_card_payment_lines.py` | 66 | S7:1 | 66/0 |
| `mig/0036_month_reviews.py` | 71 | S7:1 | 71/0 |
| `src/store/entities/budgets.py` | 74 |  | 74/0 |
| `src/store/entities/giving.py` | 57 |  | 0/0 moved |
| `src/store/tables/budgets.py` | 116 | S7:12 | 116/0 |
| `src/store/tables/giving.py` | 78 | S7:4 | 6/6 moved |
| `src/ui/budgets.py` | 1665 | S7:24 S13:2 S10:1 S11:1 S12:1 | 1665/0 |
| `src/ui/gifts.py` | 880 | S7:6 S10:5 S11:1 | 66/13 moved |
| `src/ui/giving.py` | 703 | S7:5 S3:2 S4:1 S8:1 S12:1 | 11/6 moved |
| `ui/screens/budgets.js` | 1800 | S7:15 S2:1 | 1407/79 |
| `ui/screens/gifts.js` | 881 | S7:3 S10:2 S12:1 | 21/4 |
| `ui/screens/giving.js` | 809 | S7:1 S12:1 | 3/6 |
| `tests/test_budget_plan.py` | 152 | test | 152/0 |
| `tests/test_budgets.py` | 429 | test | 164/2 |
| `tests/test_envelope.py` | 129 | test | 129/0 |
| `tests/test_gifts.py` | 276 | test | 41/3 |
| `tests/test_giving.py` | 271 | test | 44/1 |
| `tests/test_moves.py` | 110 | test | 110/0 |
| `tests/test_reserves.py` | 178 | test | 178/0 |
| `tests/test_review.py` | 73 | test | 73/0 |
| `tests/test_scenarios.py` | 62 | test | 62/0 |

## Unit 06: receipts-storage

**Sections:** S9, S14. **Code:** 9,412 lines in 51 files; **changed** 8,661, **content** 1,866, 11 new files. **Tests:** 1,736 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/clock.py` | 25 | S12:1 S14:1 | 0/0 moved |
| `src/exactjson.py` | 92 | S13:1 | 0/0 moved |
| `src/ids.py` | 95 |  | 0/0 moved |
| `src/money.py` | 66 | R1:1 S14:1 | 2/2 moved |
| `src/parsing.py` | 178 | S9:1 | 178/0 |
| `src/paths.py` | 15 |  | 2/2 moved |
| `src/receipts/__init__.py` | 577 | S9:8 S1:3 S8:1 | 95/6 moved |
| `src/receipts/ocr.py` | 207 | S9:2 R3:1 S1:1 | 23/9 moved |
| `src/receipts/parser.py` | 196 | S9:1 | 0/0 moved |
| `src/receipts/reading.py` | 340 | S9:5 S2:1 | 125/66 moved |
| `src/receipts/retention.py` | 339 | S14:4 S1:1 S9:1 | 6/1 moved |
| `src/receipts/worker.py` | 155 | S9:2 | 155/0 |
| `src/sandbox.py` | 179 | S9:1 | 179/0 |
| `src/store/__init__.py` | 2 | S14:1 | 0/0 moved |
| `src/store/alembic/env.py` | 24 |  | 2/2 moved |
| `src/store/alembic/script.py.mako` | 25 |  | 2/2 moved |
| `mig/0001_the_initial_schema.py` | 3022 | S9:1 | 308/308 moved |
| `mig/0002_deleted_generated.py` | 73 |  | 1/1 moved |
| `mig/0006_file_retention.py` | 77 | S14:1 | 1/1 moved |
| `mig/0010_links_the_rest.py` | 59 | S11:1 | 1/1 moved |
| `mig/0011_the_connector.py` | 182 | S18:1 | 3/3 moved |
| `mig/0012_the_pairing_confirmed.py` | 71 | S18:1 | 0/0 moved |
| `mig/0013_the_copy_folder.py` | 58 | S11:1 | 0/0 moved |
| `mig/0014_addresses.py` | 69 | S10:1 S18:1 | 0/0 moved |
| `mig/0015_access_between_users.py` | 95 | S8:1 S10:1 | 95/0 |
| `mig/0016_transport.py` | 61 | S11:3 | 61/0 |
| `mig/0020_the_connector_trusted.py` | 68 | S18:2 | 68/0 |
| `mig/0024_changes_in_cents.py` | 62 | S14:1 | 62/0 |
| `mig/0025_emails_queued_in_the_database.py` | 45 | S15:1 S16:1 | 45/0 |
| `mig/0026_the_last_money_in_cents.py` | 64 | S14:1 | 64/0 |
| `mig/0027_the_connectors_page.py` | 56 | S18:1 | 56/0 |
| `src/store/copy.py` | 49 | S14:2 | 0/0 moved |
| `src/store/db.py` | 139 | S11:1 S13:1 S14:1 | 24/2 moved |
| `src/store/entities/__init__.py` | 43 | S13:1 S14:1 | 0/0 moved |
| `src/store/entities/core.py` | 65 |  | 12/0 moved |
| `src/store/entities/receipts.py` | 44 |  | 0/0 moved |
| `src/store/mapping.py` | 183 | S14:1 | 9/1 moved |
| `src/store/migrate.py` | 157 | S14:1 S15:1 | 6/6 moved |
| `src/store/repos/secrets.py` | 76 | S14:1 | 0/0 moved |
| `src/store/schema_check.py` | 153 |  | 0/0 moved |
| `src/store/tables/__init__.py` | 27 | S14:1 | 0/0 moved |
| `src/store/tables/_base.py` | 115 | S13:1 | 0/0 moved |
| `src/store/tables/core.py` | 54 | S16:1 | 19/2 moved |
| `src/store/tables/receipts.py` | 90 | S1:3 S9:2 S14:2 S7:1 S8:1 | 2/2 moved |
| `src/store/types.py` | 87 | S14:3 | 0/0 moved |
| `src/store/views.py` | 101 |  | 0/0 moved |
| `src/timezones.py` | 138 | S14:2 | 138/0 |
| `src/ui/receipts.py` | 550 | S9:7 S14:3 S13:2 | 109/16 moved |
| `ui/components/receipt.js` | 345 | S9:1 | 13/5 |
| `ui/components/storage.js` | 333 | S14:3 S16:1 |  |
| `ui/screens/receipts.js` | 86 |  |  |
| `tests/test_ids_money.py` | 57 | test | 1/1 |
| `tests/test_reading.py` | 367 | test | 88/3 |
| `tests/test_receipts.py` | 161 | test | 6/2 |
| `tests/test_retention.py` | 188 | test | 24/5 |
| `tests/test_store.py` | 915 | test | 349/62 |
| `tests/test_timezones.py` | 48 | test | 48/0 |

**Cites no section** (the unit judges: serves one under other words, or **untraced**): `src/ids.py`, `src/paths.py`, `src/store/schema_check.py`, `src/store/views.py`, `ui/screens/receipts.js`.

## Unit 07: users-sharing

**Sections:** S10. **Code:** 9,468 lines in 45 files; **changed** 7,314, **content** 1,235, 2 new files. **Tests:** 2,372 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/access.py` | 203 | S10:2 S13:1 | 0/0 moved |
| `src/activity.py` | 36 | R3:1 S10:1 | 0/0 moved |
| `src/auth/__init__.py` | 1 | S10:1 S13:1 | 0/0 moved |
| `src/auth/passwords.py` | 60 | S13:1 | 1/1 moved |
| `src/auth/sessions.py` | 94 | S13:2 | 0/0 moved |
| `src/auth/signup.py` | 255 | S10:2 | 9/6 moved |
| `src/auth/tokens.py` | 15 | S14:1 S15:1 | 0/0 moved |
| `src/auth/twostep.py` | 277 | S10:2 S14:1 | 1/1 moved |
| `src/auth/users.py` | 827 | S10:7 | 84/51 moved |
| `src/mail.py` | 431 | S10:2 S16:2 S13:1 | 192/34 moved |
| `src/mcp.py` | 438 | S10:2 | 33/6 moved |
| `src/people/__init__.py` | 419 | S10:7 S3:1 S8:1 | 108/15 moved |
| `src/people/tree.py` | 254 | S10:1 | 0/0 moved |
| `src/ratelimit.py` | 167 | S10:2 S13:2 | 53/5 moved |
| `src/sharing.py` | 312 | S10:4 S5:2 S8:1 S11:1 | 13/1 moved |
| `src/store/entities/sharing.py` | 44 |  | 0/0 moved |
| `src/store/entities/users.py` | 107 |  | 1/0 moved |
| `src/store/tables/activity.py` | 24 | R3:1 S10:1 | 0/0 moved |
| `src/store/tables/people.py` | 133 | S7:3 S10:3 S1:1 | 8/4 moved |
| `src/store/tables/sharing.py` | 67 | S10:3 S5:1 S11:1 | 0/0 moved |
| `src/store/tables/users.py` | 197 | S10:9 S13:2 S1:1 S7:1 S12:1 S14:1 | 11/0 moved |
| `src/tokens.py` | 103 | S10:3 | 38/2 moved |
| `src/ui/activity.py` | 389 | S10:2 R3:1 S12:1 | 84/8 moved |
| `src/ui/people.py` | 459 | S10:7 S3:1 S7:1 S13:1 | 72/0 moved |
| `src/ui/profile.py` | 335 | S10:3 S13:2 S1:1 S12:1 | 18/9 moved |
| `src/ui/session.py` | 573 | S10:8 S13:4 S1:1 S12:1 | 109/36 moved |
| `src/ui/sharing.py` | 309 | S10:3 S13:2 | 23/1 moved |
| `src/ui/tokens.py` | 129 | S10:1 S13:1 | 4/2 moved |
| `src/ui/users.py` | 300 | S10:4 S13:2 | 17/6 moved |
| `src/ui/welcome.py` | 122 | S10:1 S12:1 S15:1 | 122/0 |
| `ui/components/auth.js` | 29 |  | 2/2 |
| `ui/components/reauth.js` | 46 | S13:1 |  |
| `ui/components/share.js` | 166 | S5:1 S10:1 S13:1 | 10/6 |
| `ui/components/tokens.js` | 169 | S10:1 | 11/8 |
| `ui/screens/activity.js` | 93 | S10:1 | 1/1 |
| `ui/screens/confirm-email.js` | 23 | S10:1 |  |
| `ui/screens/new-server.js` | 107 | S10:1 S12:1 S15:1 | 107/0 |
| `ui/screens/profile.js` | 769 | S10:4 S6:2 S12:1 S13:1 | 48/6 |
| `ui/screens/reset.js` | 40 | S10:1 |  |
| `ui/screens/setup.js` | 73 | S10:1 | 26/12 |
| `ui/screens/signin.js` | 291 | S10:5 | 3/2 |
| `ui/screens/signup-confirm.js` | 24 | S10:1 |  |
| `ui/screens/users.js` | 447 | S10:3 | 9/5 |
| `ui/screens/welcome.js` | 48 | S10:1 | 1/1 |
| `ui/store/session.js` | 63 | S10:1 S15:1 | 16/2 |
| `tests/test_mail.py` | 445 | test | 152/25 |
| `tests/test_mcp.py` | 135 | test | 8/4 |
| `tests/test_people.py` | 405 | test | 46/6 |
| `tests/test_sharing.py` | 229 | test | 27/0 |
| `tests/test_tokens.py` | 131 | test | 37/3 |
| `tests/test_twostep.py` | 240 | test | 50/13 |
| `tests/test_users.py` | 567 | test | 117/17 |
| `tests/test_welcome.py` | 220 | test | 220/0 |

**Cites no section** (the unit judges: serves one under other words, or **untraced**): `ui/components/auth.js`.

## Unit 08: linked-servers

**Sections:** S11. **Code:** 5,943 lines in 20 files; **changed** 4,446, **content** 1,825, 3 new files. **Tests:** 1,430 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/links/__init__.py` | 5 |  | 1/1 moved |
| `src/links/changes.py` | 390 | S11:5 | 390/0 |
| `src/links/client.py` | 220 | S11:2 S13:1 | 220/0 |
| `src/links/copies.py` | 172 | S11:7 | 40/0 moved |
| `src/links/copy.py` | 207 | S11:4 | 14/11 moved |
| `src/links/copydb.py` | 75 | S11:5 | 0/0 moved |
| `src/links/keys.py` | 89 | S11:1 S13:1 S14:1 | 28/0 moved |
| `src/links/manage.py` | 667 | S11:6 S10:2 S12:1 S13:1 | 222/48 moved |
| `src/links/peers.py` | 23 | S11:2 S13:1 | 4/2 moved |
| `src/links/receive.py` | 182 | S11:8 | 68/22 moved |
| `src/links/routes.py` | 349 | S11:6 S13:1 | 349/0 |
| `src/links/sealed.py` | 124 | S11:2 | 2/2 moved |
| `src/links/serve.py` | 546 | S11:6 S10:2 S7:1 S13:1 S14:1 | 121/7 moved |
| `src/links/signing.py` | 248 | S11:1 | 56/10 moved |
| `src/store/entities/links.py` | 76 |  | 5/0 moved |
| `src/store/tables/links.py` | 125 | S11:11 S12:1 S16:1 | 13/1 moved |
| `src/ui/linked.py` | 404 | S11:8 S12:4 S9:2 S13:1 | 76/7 moved |
| `src/ui/links.py` | 436 | S11:9 S13:3 S12:1 | 108/11 moved |
| `ui/components/links.js` | 576 | S11:5 S12:1 | 69/31 |
| `ui/screens/linked.js` | 1029 | S12:3 S10:1 S11:1 | 39/9 |
| `tests/linkpair.py` | 126 | test | 21/16 |
| `tests/test_copies.py` | 168 | test | 54/5 |
| `tests/test_links.py` | 947 | test | 433/17 |
| `tests/test_sealed.py` | 189 | test | 46/17 |

## Unit 09: web-ui-architecture

**Sections:** S12, S13. **Code:** 10,077 lines in 59 files; **changed** 5,170, **content** 1,793, 4 new files. **Tests:** 2,619 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/__init__.py` | 1 |  | 1/0 |
| `src/alerts.py` | 1100 | S1:6 S12:6 S7:3 S18:3 S10:2 S15:2 S3:1 S4:1 S6:1 S9:1 S11:1 S16:1 | 398/43 moved |
| `src/app.py` | 297 | S11:3 S13:3 S15:3 S7:1 S9:1 S12:1 S16:1 S18:1 | 47/10 moved |
| `src/certs.py` | 112 | S11:1 S13:1 S18:1 | 112/0 |
| `src/config.py` | 193 | S13:2 S15:1 S16:1 S17:1 | 49/8 moved |
| `src/contract.py` | 246 | S13:5 R3:1 S17:1 | 107/8 moved |
| `src/duration.py` | 56 | S12:1 | 0/0 moved |
| `src/errors.py` | 133 | S13:2 R3:1 | 13/5 moved |
| `src/events.py` | 120 | S12:1 S13:1 | 1/1 moved |
| `src/jobs.py` | 94 | S13:2 | 34/0 moved |
| `src/listener.py` | 160 | S13:2 | 14/4 moved |
| `src/main.py` | 199 | S17:2 S13:1 | 31/14 moved |
| `src/middleware.py` | 509 | S13:9 R3:1 S11:1 S15:1 S16:1 | 164/11 moved |
| `src/net.py` | 267 | S11:1 S13:1 S18:1 | 267/0 |
| `src/store/entities/alerts.py` | 28 |  | 0/0 moved |
| `src/store/tables/alerts.py` | 44 | S12:1 | 0/0 moved |
| `src/tasks.py` | 263 | S13:3 | 13/3 moved |
| `src/ui/__init__.py` | 1 | S13:1 | 0/0 moved |
| `src/ui/alerts.py` | 97 | S12:1 | 0/0 moved |
| `src/ui/conventions.py` | 329 | S13:6 S1:1 | 26/0 moved |
| `src/ui/dashboard.py` | 299 | S7:2 S5:1 S8:1 S12:1 | 43/5 moved |
| `src/ui/deps.py` | 104 | S13:3 S12:1 | 0/0 moved |
| `src/ui/stream.py` | 45 | S12:1 | 0/0 moved |
| `ui/api/client.js` | 117 | S12:1 S13:1 | 6/6 |
| `ui/app/config.js` | 12 | S12:1 S17:1 | 1/1 |
| `ui/app/dec.js` | 230 | S12:1 S13:1 S14:1 |  |
| `ui/app/duration.js` | 51 | S12:1 | 1/1 |
| `ui/app/format.js` | 221 | S14:4 S12:2 S1:1 S13:1 | 21/0 |
| `ui/app/hooks.js` | 78 | S13:1 |  |
| `ui/app/html.js` | 6 |  |  |
| `ui/app/main.js` | 120 | S12:2 S15:2 S10:1 | 6/3 |
| `ui/app/router.js` | 95 | S10:1 S17:1 | 2/1 |
| `ui/app/sealed.js` | 148 | S18:2 | 34/4 |
| `ui/app/stream.js` | 80 | S12:3 | 7/4 |
| `ui/assets/favicon.svg` | 0 |  |  |
| `ui/assets/icons.svg` | 0 |  | 3/0 |
| `ui/charts/chart.js` | 483 | S6:2 S5:1 S7:1 S12:1 S17:1 |  |
| `ui/charts/echarts.d.ts` | 10 |  |  |
| `ui/components/amount.js` | 24 | S12:2 |  |
| `ui/components/bits.js` | 115 |  |  |
| `ui/components/dialog.js` | 128 | S12:1 | 41/16 |
| `ui/components/fields.js` | 148 | S12:2 R3:1 |  |
| `ui/components/frame.js` | 226 | S12:3 | 3/3 |
| `ui/components/help.js` | 163 | S12:3 | 29/5 |
| `ui/components/icon.js` | 17 | S17:1 |  |
| `ui/components/markdown.js` | 258 | S12:4 | 100/13 |
| `ui/components/menu.js` | 65 | S12:1 |  |
| `ui/components/pager.js` | 65 | S12:1 S13:1 |  |
| `ui/components/term.js` | 95 | S12:1 | 95/0 |
| `ui/components/toast.js` | 21 | S12:1 |  |
| `ui/components/tooltip.js` | 34 | S12:1 |  |
| `ui/index.html` | 32 |  | 2/2 |
| `ui/screens/alerts.js` | 66 | S12:1 |  |
| `ui/screens/dashboard.js` | 206 | S6:1 S12:1 | 32/5 |
| `ui/screens/notfound.js` | 13 |  |  |
| `ui/store/prefs.js` | 46 | S17:1 |  |
| `ui/styles/base.css` | 68 | S17:1 |  |
| `ui/styles/components.css` | 1836 | S12:1 | 93/0 |
| `ui/styles/tokens.css` | 103 | S17:1 |  |
| `tests/test_alerts.py` | 355 | test | 137/14 |
| `tests/test_app.py` | 1030 | test | 254/11 |
| `tests/test_browser_smoke.py` | 167 | test | 59/12 |
| `tests/test_config.py` | 165 | test | 67/14 |
| `tests/test_conventions.py` | 207 | test | 132/10 |
| `tests/test_core.py` | 321 | test | 102/7 |
| `tests/test_duration.py` | 44 | test | 1/1 |
| `tests/test_guides.py` | 127 | test | 127/0 |
| `tests/test_middleware.py` | 124 | test | 44/10 |
| `tests/test_no_network.py` | 79 | test | 6/6 |

**Cites no section** (the unit judges: serves one under other words, or **untraced**): `ui/app/html.js`, `ui/charts/echarts.d.ts`, `ui/components/bits.js`, `ui/index.html`, `ui/screens/notfound.js`.

## Unit 10: encryption-settings

**Sections:** S15, S16. **Code:** 6,287 lines in 18 files; **changed** 5,019, **content** 2,510, 6 new files. **Tests:** 544 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `src/host.py` | 191 | S15:3 S13:1 S14:1 | 191/0 |
| `src/keys/__init__.py` | 1 |  | 0/0 moved |
| `src/keys/cli.py` | 567 | S15:9 S13:1 | 567/0 |
| `src/keys/files.py` | 110 | S11:2 S9:1 S15:1 | 2/2 moved |
| `src/keys/master.py` | 264 | S15:6 | 22/12 moved |
| `src/keys/phrase.py` | 56 | S11:1 S15:1 | 0/0 moved |
| `src/keys/secrets.py` | 62 | S15:2 S14:1 | 1/1 moved |
| `src/keys/welcome.py` | 55 | S15:1 | 55/0 |
| `src/runtime.py` | 455 | S15:7 S11:4 S1:1 S3:1 S9:1 S10:1 S13:1 S16:1 | 206/57 moved |
| `src/settings.py` | 332 | S16:14 S1:3 S11:2 S14:2 R3:1 S9:1 S12:1 S13:1 S15:1 S17:1 | 22/5 moved |
| `src/store/cli.py` | 104 | S15:2 S14:1 | 104/0 |
| `src/store/copies.py` | 328 | S15:5 S14:1 | 32/18 moved |
| `src/store/maintenance.py` | 532 | S15:5 S14:2 S11:1 S16:1 | 240/152 moved |
| `src/store/reencrypt.py` | 379 | S15:2 | 379/0 |
| `src/ui/settings.py` | 1174 | S15:7 S16:6 S14:5 S9:3 S13:3 S1:2 S10:2 R3:1 | 280/46 moved |
| `src/ui/unlock.py` | 125 | S15:4 S10:1 S13:1 | 125/0 |
| `ui/screens/locked.js` | 109 | S15:3 S13:1 | 72/13 |
| `ui/screens/settings.js` | 1443 | S16:4 S15:3 S1:2 S9:1 S12:1 S17:1 | 212/61 |
| `tests/test_keys.py` | 293 | test | 98/15 |
| `tests/test_runtime.py` | 26 | test | 3/3 |
| `tests/test_unlock.py` | 225 | test | 141/21 |

## Unit 11: implementation

**Sections:** S17. **Code:** 8,301 lines in 77 files; **changed** 6,681, **content** 3,250, 33 new files. **Tests:** 1,016 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `.dockerignore` | 14 |  |  |
| `.github/workflows/check.yml` | 63 |  | 63/0 |
| `.github/workflows/release.yml` | 162 |  | 162/0 |
| `publish/truenas/check.sh` | 152 |  | 152/0 |
| `publish/truenas/create-pr.sh` | 256 |  | 256/0 |
| `publish/truenas/media/moolakata-1.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-2.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-3.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-4.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-connector-1.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-connector-2.png` | 0 |  | 0/0 |
| `publish/truenas/media/moolakata-connector-icon.svg` | 0 |  | 11/0 |
| `publish/truenas/moolakata-connector/README.md` | 6 |  | 6/0 |
| `publish/truenas/moolakata-connector/app.yaml` | 35 |  | 35/0 |
| `publish/truenas/moolakata-connector/item.yaml` | 7 |  | 7/0 |
| `publish/truenas/moolakata-connector/ix_values.yaml` | 16 |  | 16/0 |
| `publish/truenas/moolakata-connector/questions.yaml` | 367 |  | 367/0 |
| `publish/truenas/moolakata-connector/templates/docker-compose.yaml` | 48 |  | 48/0 |
| `publish/truenas/moolakata-connector/templates/test_values/basic-values.yaml` | 28 |  | 28/0 |
| `publish/truenas/moolakata-connector/templates/test_values/hostnet-values.yaml` | 26 |  | 26/0 |
| `publish/truenas/moolakata-connector/templates/test_values/https-values.yaml` | 50 |  | 50/0 |
| `publish/truenas/moolakata/README.md` | 7 |  | 7/0 |
| `publish/truenas/moolakata/app.yaml` | 38 |  | 38/0 |
| `publish/truenas/moolakata/item.yaml` | 10 |  | 10/0 |
| `publish/truenas/moolakata/ix_values.yaml` | 17 |  | 17/0 |
| `publish/truenas/moolakata/questions.yaml` | 461 |  | 461/0 |
| `publish/truenas/moolakata/templates/docker-compose.yaml` | 62 |  | 62/0 |
| `publish/truenas/moolakata/templates/test_values/basic-values.yaml` | 34 |  | 34/0 |
| `publish/truenas/moolakata/templates/test_values/hostnet-values.yaml` | 32 |  | 32/0 |
| `publish/truenas/moolakata/templates/test_values/https-values.yaml` | 56 |  | 56/0 |
| `web/VERSION` | 1 |  | 1/1 |
| `web/check` | 54 |  | 7/6 |
| `web/dev.md` | 166 |  | 19/19 |
| `web/dev.sh` | 143 |  | 8/8 |
| `web/install/Dockerfile` | 48 |  | 19/15 |
| `web/install/build-requirements.txt` | 4 |  |  |
| `web/install/compose.connector-truenas.yaml` | 42 |  | 42/0 |
| `web/install/compose.tls.yaml` | 56 |  | 24/17 |
| `web/install/compose.truenas.yaml` | 56 |  | 56/0 |
| `web/install/compose.yaml` | 82 |  | 45/20 |
| `web/install/moolakata.toml` | 28 |  | 28/0 |
| `web/install/proxy/Caddyfile` | 7 |  | 3/3 |
| `web/install/proxy/haproxy.cfg` | 15 |  | 4/4 |
| `web/install/proxy/nginx.conf` | 18 |  | 2/2 |
| `web/install/smoke.sh` | 162 |  | 114/62 |
| `web/pins` | 7 |  |  |
| `web/release.sh` | 418 |  | 418/0 |
| `web/server/pyproject.toml` | 74 |  | 4/4 |
| `src/dev/__init__.py` | 1 |  | 0/0 moved |
| `src/dev/audit.py` | 243 | S17:1 | 4/4 moved |
| `src/dev/base.py` | 98 | S17:1 | 2/2 moved |
| `src/dev/devmode.py` | 76 | S15:1 S17:1 | 1/1 moved |
| `src/dev/mocks.py` | 397 | S17:1 | 4/4 moved |
| `src/dev/seed.py` | 197 | S10:3 S16:2 S12:1 S17:1 | 20/8 moved |
| `src/dev/seed_accounts.py` | 502 | S2:1 S12:1 S17:1 | 30/0 moved |
| `src/dev/seed_assets.py` | 175 | S17:1 | 0/0 moved |
| `src/dev/seed_budgets.py` | 146 | S7:3 S2:1 S17:1 | 146/0 |
| `src/dev/seed_connector.py` | 122 | S18:2 S17:1 | 17/11 moved |
| `src/dev/seed_education.py` | 98 | S17:1 | 0/0 moved |
| `src/dev/seed_gifts.py` | 102 | S17:1 | 0/0 moved |
| `src/dev/seed_giving.py` | 116 | S17:1 | 0/0 moved |
| `src/dev/seed_links.py` | 457 | S11:1 S17:1 | 17/11 moved |
| `src/dev/seed_loans.py` | 169 | S17:1 | 0/0 moved |
| `src/dev/seed_options.py` | 79 | S3:1 S17:1 | 0/0 moved |
| `src/dev/seed_projections.py` | 84 | S17:1 | 0/0 moved |
| `src/dev/seed_receipts.py` | 109 | S17:1 | 0/0 moved |
| `src/dev/seed_sharing.py` | 100 | S17:1 | 0/0 moved |
| `src/dev/seed_taxes.py` | 150 | S8:1 S17:1 | 0/0 moved |
| `src/dev/seed_wallets.py` | 26 | S17:1 | 0/0 moved |
| `src/dev/wheels.py` | 71 | S17:2 | 1/1 moved |
| `src/static.py` | 164 | S17:3 | 9/5 moved |
| `ui/deno.json` | 62 |  |  |
| `ui/mockup/build.py` | 648 | S12:1 S13:1 | 140/18 |
| `ui/mockup/help_shots.py` | 163 | S12:1 | 11/19 |
| `ui/mockup/iso.js` | 56 | S12:1 | 1/1 |
| `ui/mockup/menu.js` | 77 | S12:1 | 8/1 |
| `ui/mockup/runtime.js` | 285 | S15:2 S12:1 S13:1 | 112/41 |
| `tests/conftest.py` | 215 | test | 40/22 |
| `tests/test_install.py` | 425 | test | 311/30 |
| `tests/test_mocks.py` | 116 | test | 9/9 |
| `tests/test_mockup_app.py` | 110 | test | 13/3 |
| `tests/test_static.py` | 88 | test | 15/3 |
| `tests/test_vendor.py` | 62 | test |  |

**Cites no section** (the unit judges: serves one under other words, or **untraced**): `ui/deno.json`.

## Unit 12: connector

**Sections:** S18. **Code:** 5,355 lines in 30 files; **changed** 4,680, **content** 2,052, 5 new files. **Tests:** 2,313 lines.

| File | Lines | Cites | Delta (+/−) |
|---|---:|---|---|
| `connector/.dockerignore` | 4 |  |  |
| `connector/Dockerfile` | 39 | S18:3 S17:1 | 15/10 |
| `connector/moolakata_connector/__init__.py` | 7 | S18:1 | 7/0 |
| `connector/moolakata_connector/client.py` | 205 | S18:3 S13:1 | 205/0 |
| `connector/moolakata_connector/core.py` | 516 | S18:14 | 220/76 moved |
| `connector/moolakata_connector/drivers/__init__.py` | 73 | S18:5 | 6/12 moved |
| `connector/moolakata_connector/drivers/ofx_direct.py` | 109 | S18:2 | 1/1 moved |
| `connector/moolakata_connector/drivers/schwab.py` | 279 | R1:1 S18:1 | 16/4 moved |
| `connector/moolakata_connector/keys.py` | 112 | S18:2 | 29/10 moved |
| `connector/moolakata_connector/main.py` | 251 | S18:7 | 251/0 |
| `connector/moolakata_connector/page.css` | 244 | S18:1 | 244/0 |
| `connector/moolakata_connector/page.py` | 719 | S18:7 | 719/0 |
| `connector/moolakata_connector/sealed.py` | 32 |  | 1/1 moved |
| `connector/moolakata_connector/signing.py` | 74 |  | 16/5 moved |
| `connector/moolakata_connector/sock.py` | 93 | S18:2 | 8/5 moved |
| `connector/moolakata_connector/vault.py` | 202 | S18:5 | 29/13 moved |
| `connector/moolakata_connector/words.py` | 52 | S18:1 | 2/2 moved |
| `connector/pyproject.toml` | 20 | S18:1 | 5/5 |
| `connector/requirements.txt` | 35 |  |  |
| `src/connector/__init__.py` | 6 |  | 2/2 moved |
| `src/connector/files.py` | 177 | S1:2 S9:1 S13:1 S18:1 | 7/9 moved |
| `src/connector/manage.py` | 474 | S18:14 | 101/16 moved |
| `src/connector/routes.py` | 238 | S18:3 | 40/21 moved |
| `src/connector/sealed.py` | 49 | S18:1 | 3/3 moved |
| `src/store/entities/connector.py` | 46 |  | 3/0 moved |
| `src/store/tables/connector.py` | 75 | S18:13 | 11/3 moved |
| `src/ui/connections.py` | 317 | S18:8 S13:2 | 22/19 moved |
| `src/ui/connector.py` | 237 | S18:8 S13:1 S16:1 | 16/2 moved |
| `ui/components/connections.js` | 421 | S18:3 | 41/52 |
| `ui/components/connector.js` | 249 | S18:2 S16:1 | 32/19 |
| `connector/tests/conftest.py` | 25 | test | 3/3 |
| `connector/tests/test_core.py` | 568 | test | 339/28 |
| `connector/tests/test_drivers.py` | 253 | test | 24/62 |
| `connector/tests/test_end_to_end.py` | 257 | test | 121/34 |
| `connector/tests/test_page.py` | 288 | test | 288/0 |
| `tests/test_connections.py` | 253 | test | 60/40 |
| `tests/test_connector.py` | 669 | test | 160/28 |

**Cites no section** (the unit judges: serves one under other words, or **untraced**): `connector/moolakata_connector/sealed.py`, `connector/moolakata_connector/signing.py`, `src/connector/__init__.py`.

