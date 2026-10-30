# S17.5. Tests and checks

5. **Tests and checks**, all run by `web/check`, with no Node.js: pytest with a throwaway SQLite per test (most of the
   weight: lots, gains, wash sales, option assignment, imports, budgets, projections, sharing,
   links), browser component tests in headless Chromium driven by Playwright for Python, Deno
   check/lint/fmt, ruff, OpenAPI and typedef drift, mockup drift, the help-guide checks and
   the dependency register's hash check (S17.2.1), and the requirements' own checks: every id
   cited in the documents or the code names an item, the README's tables match the files,
   no section file passes 500 lines, and the schema's prefixes are in order.
   Browser tests use a small in-page runner (`web/ui/tests/run.js`) and a fake API; one
   smoke test drives a running dev server. **Golden files**: a fixture portfolio with known
   8949 rows and TXF output, checked byte for byte. **Receipt reading**: the field parser is
   tested on OCR text, and a set of fixture receipts (phone photos, flatbed scans, text-layer
   PDFs; skewed, faded, rotated) runs through the real RapidOCR worker against expected date,
   total and merchant, with an accuracy floor that a change must not drop below.

   **Kinds of test** that each change in their area adds to:
   1. **Browser modules** without a page (`app/draft.js`, `app/dec.js`, `app/duration.js`)
      are unit-tested by `deno test`, with the draft's id maker passed in so ids repeat.
   2. **Saved unchanged changes nothing**: every form that edits through a draft is opened in
      Chromium and saved untouched, and the records read back are what they were: one
      table-driven test, a row per form (where to open it, how, and what reads its records),
      over one household seeded once through the API (`tests/browser.py`, which also holds the
      server, the browser and signing in). What every draft form does (the question before
      discarding, Back, a click outside, typed text, questions, a reload after a 412) is
      tested once, on the shared form pieces; a form has a test of its own only for what it
      alone does.
   3. **Workflows** that carry what one use learned or saved into the next (import, correct,
      import the next statement) run end to end through the API.
   4. **Faults one at a time**: a link's or the connector's exchange is made to fail at one
      call or one file, through fakes that keep the real transport's limits and timeouts; the
      rest goes through, and the failure is recorded and alerted.
   5. **Limits that fit**: every size a setting allows (S16) is checked against every path
      it travels (a request, an answer, a link's file, an upload in flight).
   6. **A hostile worker**: code run under the reader's worker's sandbox (S9.8.4) tries what
      it must not do (a socket of any kind, a local listener of its own account, a signal to
      another process), and each attempt is refused.
   7. **The import corpus**: files shaped as institutions export them (OFX and QFX downloads,
      bank, card, broker and exchange CSVs, bank and plan statements kept as their text and
      drawn into a PDF), each beside a `.toml` that says what the file is like, the account it
      goes into and what MoolaKata makes of it: the import's counts, the coverage, the
      transactions, holdings, cash, balance and holdings checks, and each instrument's class
      and whether a real price source fetches it (dev mode's stub prices every class, so it
      can't show one that none does). The expected results are written by reading the file,
      never from what the code makes of it. In `web/server/tests/fixtures/imports/`, imported
      through the API with every question answered as the import dialog's defaults answer it
      (`tests/corpus.py`, `tests/test_import_corpus.py`):
      1. **Expected results**, compared section by section.
      2. **Invariants** over every file: imported again it adds and changes nothing; its rows
         in the other order, a later download that overlaps it imported before or after it,
         and (for OFX) its times written as evening in a US zone each leave the account as the
         file alone does; a row the owner deleted stays deleted when the file comes again.
      3. **Sequences**: a table of steps (make an account, import a file or a changed copy,
         check a result) for what one import leaves for the next.
      4. **The browser offers what the server takes**: the ways an account is kept and the
         columns a mapping names, read from the browser's lists, against the server's.

      A part that waits on a fix is an expected failure named by its claim or question
      (`[xfail]` in the file's `.toml`), strict, so the fix takes the mark away. A change to
      importing adds a file, an expected result or a sequence that fails before it. Real
      exported files join the corpus as G25 says.

   Browser tests that need a page drive it with Playwright, setting the page's clock to the
   server's frozen one where a test freezes it.
