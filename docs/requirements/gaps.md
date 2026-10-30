# Gaps

Areas the requirements name but don't yet specify. Each has a lasting id: a gap that is
closed is removed, its text goes into the section it belongs to, and its id is never used
again. A new gap takes the next number. The [README](README.md#gaps) lists them. Each carries
a rank: **High** blocks the first release, **Med** is needed before it but blocks nothing
yet, **Low** can follow it.

## G23: Real receipt fixtures for the reader — Low

**What is named:** S17.5 says a set of fixture receipts (phone photos, flatbed scans,
text-layer PDFs; skewed, faded, rotated) runs through the real RapidOCR worker against expected
date, total and merchant, with an accuracy floor.

**What is not:** the set. `test_reading.py` draws its receipts with Pillow and skews, blurs and
rotates them, which proves the pipeline and the parser but not the models on real paper, and
its 80% floor was set on those drawings.

**Settled:** a dozen real receipts the household photographs and scans (a thermal grocery
receipt, a restaurant one with a tip line, a gas pump, a faded one, a curled one, an emailed
PDF invoice with a text layer, a scanned statement page), with no card numbers, names or
addresses beyond what the merchant prints, under `web/server/tests/fixtures/receipts/` with an
`expected.json` of date, total and merchant each; the floor set from the first run on them and
recorded in the test; the synthetic test kept beside it for pipeline regressions. Built in
milestone 7 part 9 (S17.9.7). **Waits on:** the receipts themselves.

## G25: Real exported files for the import corpus — Low

**What is named:** S17.5.7's import corpus, whose files are shaped as institutions export
them.

**What is not:** files from the institutions themselves. The corpus's files are written to
the formats as they are documented and commonly seen, so a quirk no one wrote down (a column
named otherwise, a trailer, a date or sign written another way) shows only when a real file
meets the reader.

**Settled:** each real file the household exports (a bank's QFX and CSV, a card's CSV, a
broker's OFX, history CSV and statement PDF, an exchange's CSV, a plan's statement) joins the
corpus as another entry with the same kind of `.toml`, its expected results written by reading
it, never from what MoolaKata makes of it. Before it is committed, account numbers, names,
addresses and card digits are replaced, and amounts are kept so the file still adds up. A file
not yet cleaned can be kept in a git-ignored folder the same tests read when it is there.
**Waits on:** the household's exports.

## G26: Seeing and recovering what was deleted — Low

**What is named:** deleting, which asks first (S12.16), and the deleted rows an import still
matches and leaves deleted (S1.3.2).

**What is not:** a way to see what was deleted or to bring it back. A deleted transaction,
gift or rule is kept, marked deleted (`schema.md`), but no screen lists such records, so one
deleted by mistake can only be entered again, and a file that carries a deleted transaction
never brings it back.

**Settled:** nothing yet. **Waits on:** a *Show deleted* choice on the lists that delete
(transactions first), each deleted row with **Recover**, which undeletes it through the save.

## G27: Correcting an instrument's class — Low

**What is named:** S2.1's instrument classes, which decide which price source fetches an
instrument (S4.3) and whether average cost is offered for it (S2.3).

**What is not:** a way to change one. An instrument's class comes from where it was first seen:
an OFX file's security list, a statement, a trade typed by hand, or a CSV's symbol by its shape
(S1.3.2), which makes an ETF a listed share and can't tell a money-market fund from a mutual
fund. Instruments are kept once per server, so a class set wrongly is wrong for every account
that holds it.

**Settled:** nothing yet. **Waits on:** a screen that shows an instrument (its name, class,
CUSIP and price source), where an admin corrects the class.

