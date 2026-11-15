# Relay progress: retire review 3's ids

## Batch 1 of 4

- Files done: 41
- Citations removed: 108
- GH links added: none
- Notes: almost all were beside a requirement id or had the why in the words around them, and
  were dropped. Labels at the head of a test comment (`# CR3-n: …`) lost the label, the rest
  capitalised. One bare marker got a why: `options/strategies.py` roll proposal,
  `# CR3-408` → `# as its view shows it` (an unnamed strategy is named by its shape, as in
  its view). No requirement ids were added in place of a CR3 id.
- **Doubts**: none. (Uncommitted changes to `docs/mutation-testing.md` and
  `docs/requirements/rejected-ideas.md` were in the working tree, not from this batch; left
  unstaged.)

## Batch 2 of 4

- Files done: 33 (31 by hand; `web/ui/api/openapi.json` and `types.js` regenerated with
  `web/dev.sh codegen`, all their docstrings' sources in this batch's ui/*.py files)
- Citations removed: 58 by hand, plus 6 in the generated files
- GH links added: none
- Notes: nearly all were beside a requirement id or had the why around them, and were dropped;
  no requirement ids added in place of a CR3 id. One bare marker got a why:
  `components/payoff.js` `// exact (CR3-411)` → a line above the comparison: compared by
  value, since `!==` reads two equal amounts as different. Two references to the tax years
  walk (a file under `docs/reviews/`) went too: `taxes/panels.py` `_stored_washes` docstring
  (": the walk's decision 3.6" dropped) and `ui/imports.py:191` ("(S2.8, the filed tax years
  walk's decision 1.1)" → "(S2.8)"). `moolakata.contract check` passes.
- **Doubts**: `web/server/src/moolakata/ui/save.py:355` (not in this batch) also cites "tax
  years walk's decision 1"; left for the batch that holds it, or the coordinator.

## Batch 3 of 4

- Files done: 45
- Citations removed: 91 CR3 ids (88 in the tests and fixtures, 3 in `durations.json`'s keys,
  changed to match the three renamed `test_saved_unchanged_a_form_changes_nothing` ids in
  `test_browser_drafts.py` exactly), and 23 references to walks and their decisions
- GH links added: none
- Notes: most were beside a requirement id or a docstring's leading label with the why after
  it, and were dropped (the label's next word capitalised). One requirement id added in place
  of a CR3 id: `test_budget_history.py:34` "The claim (CR3-45):" → "R3.10:" (History reads as
  it was; the finding's own item, and what the test pins). "The claim" in `test_budget_lines`
  went too. Two bare markers got a why, each as a comment line above its assert:
  `test_browser_positions.py:552` (CR3-407: the toast says what the save did, never a bare
  Saved) and `test_browser_taxpanels.py:312` (CR3-415: sold with no lot to match, its day
  bought is missing, never its sale day). `test_browser_drafts.py`: "CR3-2 and its kind" and
  "CR3-2's fourth case" rewritten to stand alone. Walk references the brief's grep doesn't
  match went too: `test_access.py`'s access-views and mine walk decision numbers ("(decision
  5)", "(decision 7.2: …)", and the bare "(4.1)", "(1d.3)", "(1e.3)" … beside `HOLDS`; "as
  the decisions say"), `test_browser_figures.py:1` ("the values, taxes and options walk,
  4.3"), and `test_importers.py:240` ("Walk item 13:"). Fixtures: only their `about` text and
  a comment changed; no test reads `about` or compares it.
- **Doubts**: none.
