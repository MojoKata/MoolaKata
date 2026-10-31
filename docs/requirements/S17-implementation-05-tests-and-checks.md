# S17.5. Tests and checks

5. **Tests and checks**, all run by `web/check`, with no Node.js: pytest with a throwaway SQLite per test (most of the
   weight: lots, gains, wash sales, option assignment, imports, budgets, projections, sharing,
   links), browser component tests in headless Chromium driven by Playwright for Python, Deno
   check/lint/fmt, ruff, OpenAPI and typedef drift, mockup drift, the help-guide checks and
   the dependency register's hash check (S17.2.1), and the requirements' own checks: every id
   cited in the documents or the code names an item, the README's tables match the files,
   no section file passes 500 lines, and the schema's prefixes are in order.

   **How tests are written.** The server's tests run across a worker per core
   (`pytest -n auto`, pytest-xdist), so each test makes what it needs (its database, its
   servers, its files under its own temporary folder) and leaves nothing another can see; the
   browser modules run in one process, sharing the household seeded once (later work, L16).
   Code is shaped for this: what a route, a task or a call does lives in functions beneath it,
   tested without a running server or a network, and a fake stands where the network or the
   clock begins, never in place of the code above it. A test waits on an event or a
   condition, with a generous timeout, never for a fixed time unless the time is what it tests;
   a test that waits for time passing moves an injected clock. Code that turns on the shape of
   its data has its axes named and a case for each combination, and where they multiply past
   reason the choice of cases is written down. A bug that got past the tests is fixed with the
   test that covers its kind, not just its case.
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
      call or one file, through a fake that stands where the sockets are (`net.network`), so
      the real client's guard, decoding, ceiling and pins run above it; the rest goes
      through, and the failure is recorded and alerted. The client's ceiling is checked on
      every content coding × announced length × way of reading × size
      (`tests/test_net.py`), and over real sockets in `tests/test_core.py`.
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
      5. **The connector corpus** (S18.9): what a connector driver fetches, shaped as its
         institution's API or server gives it, in `web/server/tests/fixtures/connector/`:
         Schwab Trader API data (an account's positions and balances and its transactions,
         `.json`) run through the Schwab driver, and OFX servers' answers (`.ofx`) run
         through OFX Direct Connect against a server that answers with them; each driver's
         file imported as the connector's post is, and compared as above, with the lots it
         makes (each open position's side and basis, each close's realized gain and how it
         closed) and the strategies Positions proposes (`tests/test_connector_corpus.py`). A
         case for every kind of transaction and asset each driver handles, the four option
         trades and an option's three ends, an order of several legs, and what each driver
         can't do: a Schwab transaction it can't write whole is named, never dropped unsaid;
         an OFX server's refusals give the run's state and words. **Invariant** over every
         entry that leaves nothing out: what the institution reported, its cash and its
         positions, is what MoolaKata works out from the rows, nothing held that it didn't
         report; and the next day's file, the same days fetched again, adds nothing. A
         household's own data joins as L14 says.

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
         merge to `main`, the coverage site. The terminal's and the job summary's table gives
         each area's files, its lines and branches as a bar of ten characters (each a tenth)
         with the percentage, the counts reached, and its floor, marking an area below its
         floor; its last rows are the server's areas together, the browser's, and every area
         as one (the connector's too), each summed from their counts. `files.json` keeps each
         file's counts, and where its line-by-line report is.
      4. **The floor**: `web/coverage-floor.json` holds each area's line and branch floor; an
         area below its floor fails the check. `python -m moolakata.dev.coverage floor`
         raises each to what was measured less a slack in lines and in branches (a count,
         not points: one branch is a point of a one-file area), as a percentage rounded down
         to a tenth, and never lowers one: a lower floor is written by hand, with its reason
         in the commit. The slack is 3 for the server's and the connector's areas, whose
         tests measure the same each run, and 20 for the browser app's, whose figures move
         with the browser tests' timing. `totals.json` keeps each area's counts for it.
      5. **The coverage site**: the repository's GitHub Pages site
         (`https://mojokata.github.io/MoolaKata/`) holds the HTML reports of the last merge
         to `main` and the history of every merge since the site began. Its page shows:
         1. **The headline**: line and branch coverage of every area as one, with the counts
            behind them, each side's line coverage, and the number of files.
         2. **By area**: each area's lines and branches as a bar with a tick at its floor (red
            below it), the percentage, the change since the merge before and the counts
            reached; its files and floor; and, last, the rows that sum the areas as the
            job summary does. Clicking an area opens its files, each with the same bars and
            counts and a link to its line-by-line report. Clicking a heading sorts the areas
            and their files by it (name, lines, lines reached, branches, branches taken; a
            count sorts by size), lowest lines first to start. A filter keeps the files
            whose path holds what is typed, opening each area that has one.
         3. **Over the merges**: a chart of each area, and of the server's and the browser's
            areas as one, with each merge's figures on hover; and every merge in a table.

         `python -m moolakata.dev.coverage site` builds it into `web/.dev/coverage/site/`,
         with `files.json` beside the page:
         4. **The history** is the site's `history.json`, one entry per merge: its commit,
            date, subject, pull request (from the squash merge's subject) and totals by
            area. It lives on the site alone. Each build reads it back from the published
            site and adds its own entry last; a run done again for the same commit replaces
            that commit's entry.
         5. **Never started over**: a site that answers with no `history.json` starts an
            empty one only while the site itself isn't there. Any other failure to read it
            fails the build in CI, so a bad moment never loses the history.
         6. **Published** by `check.yml` (S17.10.1) after a passing check on `main`. Run
            anywhere else, the build is a preview of what publishing that commit would show,
            and publishes nothing.

      `web/dev.sh coverage [pytest arguments]` measures the tests named (all by default) and
      the browser modules' unit tests the same way, and reports them, without the floor, with
      a preview of the coverage site.
   9. **Signed calls**: every route a linked server or the connector calls goes through one
      gate (`links/gate.py`), and the gate is tested on its axes (`tests/test_gate.py`): each
      way a call fails its checks (no signature, a forged one naming a real key, an unknown
      key, a nonce again, a stale time, a body past its size, a body other than the one
      signed) × each protocol × each kind of body (JSON, a receipt's sealed bytes, a
      multipart file). Each is refused before a byte of its body is read and leaves no trace:
      nothing counted against the key it names, no upload held, no file written, no row
      added. A body whose pieces move the server's clock past a minute is still taken. A test
      reads both routers and fails on a signed route that skips the gate, and a forged call
      naming a real key leaves no trace on any route. While one call's work runs, held on an
      event, another is answered.

   Browser tests that need a page drive it with Playwright, setting the page's clock to the
   server's frozen one where a test freezes it. Whenever a test waits for the page, and before
   a page's coverage is taken, the page settles first: none of its requests in flight (and
   none for 150 ms, the time for a screen to start what it fetches next), no Loading
   placeholder showing, and each chart drawn. A test then leaves each screen in the same state
   every run, and what the tests reach doesn't depend on how soon a test moves on. What still
   varies is the order in which a screen's parallel requests answer.
