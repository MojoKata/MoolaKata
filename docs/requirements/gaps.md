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
