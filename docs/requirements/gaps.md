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

## G25: Shares in the save — Low

**What is named:** S12.15 says every form that changes records edits a draft and saves through
one request (S13.8.11), and S13.8.1 that a kind the save takes has no PUT of its own.

**What is not:** how an item's shares fit that. The share dialog saves the item's grants as a
whole with `PUT /ui/api/shares/{kind}/{id}`, made against the sum of their versions: a level
per user and group, a linked server's people grouped under it with **Include receipts**, and,
for a portfolio, **Share these accounts too**, which shares accounts at read beside it. It asks
before discarding its changes as a draft's dialog does.

**Proposed:** keep the whole-set PUT, since a share set exists once for its item, as a loan's
terms or a wallet's keys do (S13.8.1); or move each grant into the save as a `Share` record
(its level, Include receipts on a linked user's), with Share these accounts too as an action
after it. **Open:** which, and whether the dialog's draft should then also hold a portfolio's
accounts shared too.
