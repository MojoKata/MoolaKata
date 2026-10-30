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

   8. **Coverage**: what the tests reach, measured on every run of `web/check`, with no
      service outside the repository and its own GitHub Pages site. coverage.py measures lines and branches in every
      Python process the tests start (the server the browser tests run included; the
      reader's worker, started with no environment, is not), and the connector. For the
      browser app, `deno test --coverage` and the browser tests' pages (V8's precise
      coverage through Chromium's DevTools protocol, written in Deno's form) are read
      together by `deno coverage`; a file no test loads counts as not reached.
      `python -m moolakata.dev.coverage report` then gives:
      1. **By area**: line and branch coverage of each server package (its top-level modules
         as one), each directory of the browser app, and the connector. A browser file's
         branches count only where its code ran.
      2. **The changed lines**: how many of the lines added or changed since the base (the
         merge base with `main`; in CI, the commit before) the tests reach, and each stretch
         they don't.
      3. **Where it is shown**: the terminal; HTML reports in `web/.dev/coverage/html/`; in
         CI, the job's summary, a notice with the headline and one on each of the nine
         largest unreached stretches of changed lines (shown on those lines in a pull
         request), and the HTML as the run's `coverage` artifact, kept 30 days; after each
         merge to `main`, the coverage site.
      4. **The floor**: `web/coverage-floor.json` holds each area's line and branch floor; an
         area below its floor fails the check. `python -m moolakata.dev.coverage floor`
         raises each to what was measured less three lines and three branches (a count,
         not points: one branch is a point of a one-file area), as a percentage rounded down
         to a tenth, and never lowers one: a lower floor is written by hand, with its reason
         in the commit. `totals.json` keeps each area's counts for it.
      5. **The coverage site**: the repository's GitHub Pages site
         (`https://mojokata.github.io/MoolaKata/`) holds the HTML reports of the last merge
         to `main` and the history of every merge since the site began. Its page shows each
         area's line and branch coverage and the change since the merge before, with the
         floors; a chart of each area (and of the server's and the browser's areas as one,
         weighted by lines) over the merges, with each merge's figures on hover; and every
         merge in a table. `python -m moolakata.dev.coverage site` builds it into
         `web/.dev/coverage/site/`:
         1. **The history** is the site's `history.json`, one entry per merge: its commit,
            date, subject, pull request (from the squash merge's subject) and totals by
            area. It lives on the site alone. Each build reads it back from the published
            site and adds its own entry last; a run done again for the same commit replaces
            that commit's entry.
         2. **Never started over**: a site that answers with no `history.json` starts an
            empty one only while the site itself isn't there. Any other failure to read it
            fails the build in CI, so a bad moment never loses the history.
         3. **Published** by `check.yml` (S17.10.1) after a passing check on `main`. Run
            anywhere else, the build is a preview of what publishing that commit would show,
            and publishes nothing.

      `web/dev.sh coverage [pytest arguments]` measures the tests named (all by default) and
      the browser modules' unit tests the same way, and reports them, without the floor, with
      a preview of the coverage site.

   Browser tests that need a page drive it with Playwright, setting the page's clock to the
   server's frozen one where a test freezes it. Whenever a test waits for the page, and before
   a page's coverage is taken, each chart on it is drawn first, so what the tests reach doesn't
   depend on how soon a test moves on.
