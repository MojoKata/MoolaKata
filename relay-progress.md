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
