# MoolaKata: working rules

## Keep the mockup in step with the requirements

`docs/mockups/MoolaKata-mock.html` is the reference for every screen. Any change to
the requirements (`docs/requirements/`) that touches what a user sees or does (a screen, field, button, dialog,
setting, state, message, or the order of any of them) updates the mockup **in the same
change**. That includes its help-pane guides (`GUIDES` in the file), its sample data, and the
MOCK pill's menu when a new screen, dialog or state needs a way to reach it. A change that only
touches the server's internals needs no mockup change. Say so when you skip it.

Before calling a change done:

1. Open every screen, tab, Settings section and dialog in a headless browser, and fail on any
   page error or console error: `python docs/mockups/check.py shots/` does this and writes
   a screenshot of each to `shots/` (it needs Playwright for Python and its Chromium).
2. Look at screenshots of what changed.

The mockup's `html` element carries `zoom: 2`. Viewport units, breakpoints and pointer
positions in it account for that, so check and screenshot at 2880×1800 (what a 1440×900
window shows).

The web app and its mockup are for desktop browsers. Phone layouts are not checked or fixed:
phones will get a separate, focused PWA later (requirements S12.8).

While the app is being built there are two mockups (requirements S12.9): the hand-written
`MoolaKata-mock.html`, which stays the design reference and is updated with every UI-facing
change, and `MoolaKata-app.html`, generated from the app by `web/ui/mockup/build.py` for the
screens built so far, which `web/check` keeps current.

## Requirements are a statement, not a changelog

The requirements (`docs/requirements/`) say what MoolaKata is and does, in the present tense.
They carry no dates, versions or status lines, no "now", "no longer", "revised", "proposed"
or "approved", and no record of what changed: git holds the history. `docs/schema.md` follows
the same rule. The repository's root README is where repo, build and product status goes,
also without dates or words of approval.

## How the requirements are laid out

- `README.md` holds the decisions (R1), terminology (R2) and design principles (R3), and
  tables of the sections and the gaps. Each section is a file `S<n>-<name>.md`.
- References are ids, never file names: `R1.16`, `S9.8.7`, `G8`, `Q8`. Section ids and their
  first-level items (`S1.2`) are never renumbered or reused; a new one takes the next free
  number. Deeper items may be renumbered with every reference updated in the same change.
- A section file past 500 lines moves its first-level items to their own files
  (`S1-accounts-02-brokerage.md` holds S1.2) and keeps a summary with a table of them.
- **Gaps** (`gaps.md`, and the README's table): areas named but not yet specified, each with a
  lasting id (G1, G2, …). When the build reaches one, propose a reasonable solution for the
  average cases (a Schwab brokerage account, a UMB bank account), write it into its section,
  and record what is still open as a gap. A specified gap is removed; its id is never reused.
- **Open questions** (`questions.md`): ids Q1, Q2, … are shared with the questions asked
  while building, and never reused. An answered question's answer goes into its section and
  the question is removed.
- An idea weighed and turned down goes to `rejected-ideas.md`, with the reason, so it is not
  raised again without a new one.

## Free standing

This repository is self-contained. Docs, mockups and code describe MoolaKata in its own terms
and never refer to other projects as the source of a design or behaviour.

## Vendored browser libraries

A browser library in `web/ui/vendor/` is added or updated only with `web/dev.sh vendor add`
(requirements S17.3.1), never by editing `manifest.json` or committing a tarball by hand. Don't
pass `--young` without the user's reason, and read the diff it writes before committing.

## Schema conventions

`docs/schema.md` sets the database's naming and ID rules. A new table with an `id` gets a row
in its prefix table, kept sorted by prefix, in the same change. A new table declares how it is
seen (`seen=`, schema.md §7), and gets its access view written if it is a rule of its own, in
the same change.

## Reviews

Code reviews follow `docs/REVIEW.md`: its phases, work pad, claim format and `CR<n>-<m>`
ids. Scope (full or incremental) and checking (checked or quick) are recommended from the
measured delta and confirmed with the user. A review runs in serial sessions unless the
user asks, for that review, for parallel agents or a workflow; that is never assumed or
carried over from an earlier one.
