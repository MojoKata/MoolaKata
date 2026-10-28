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
   2. **Saved unchanged changes nothing**: every dialog that edits through a draft is opened
      in Chromium on fixture data and saved untouched, and the records read back are what
      they were.
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

   Browser tests that need a page drive it with Playwright, setting the page's clock to the
   server's frozen one where a test freezes it.
