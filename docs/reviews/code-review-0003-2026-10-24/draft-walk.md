# Walk-through: Draft and Record (client-side change tracking)

Started Oct 28, 2026. Decisions log; nothing is applied until the final approval.

## Settled before the walk

1. Name: `Draft` (the edit session), holding `Record`s.
2. Merge on a 412 `stale-version` in the first version.
3. An "unsaved changes?" prompt now, with its requirements and mockup change.
4. `Draft` and `Record` are built first, before the High fixes; CR3-2's fix is the first user.
5. Directions given by the user: Fields defined per entity type (array or Map by name); entities
   extend `Record` and hold their own rules; the browser may make ids (GUIDs) so new related
   records can reference each other; one general "save Draft" route takes the creates, updates
   and deletes of the whole Draft and saves them all-or-nothing in one database transaction.

## Items

1. Field definitions: where they come from, and the field types
2. Record and its entity subclasses: what they hold
3. Related records: children and foreign keys in one Draft
4. Ids made in the browser
5. The save: one route, one database transaction
6. Questions a save asks (confirm) and refusals
7. Versions and the merge on 412
8. The "unsaved changes?" prompt
9. The Draft's life: reactivity, the live stream, discard
10. Rollout, tests, and where it is written down

## Decisions

1. **Field definitions** (option 3): generated from the server's OpenAPI document into
   `api/fields.js`, as `types.js` is, with the drift check; the server's models say more for it
   (`Literal[...]` choices, declared kinds for money, quantity, date, month, id with its prefix).
   Entity classes add UI-only details (label, input hint, display precision), never a type.
   Field types: text, money, quantity, percent, int, bool, date, month, choice, ref, list (ordered
   unless marked a set), json; each with `parse`, `format`, `equal`, `toWire`. `data` holds
   server-form values only; text that doesn't parse yet stays in the input with its field error.
2. **Record and entity subclasses** (option 3 with (b)): `Record` holds entity type, id,
   version, state (new, loaded, deleted), `data`, `modified`, `get`/`set`/`revert`/`revertAll`,
   `changed`, `changes()`; no fetching, saving or drawing. Subclasses hold defaults, rules,
   computed display values (getters, never stored) and quick checks (the server's refusal is
   final). Rules are declarations (`when`/`otherwise`, required when, set when), which also drive
   which inputs show; an `onSet` hook is allowed but not preferred, for what declarations can't
   say. Edits a rule makes are linked to the field that caused them and revert with it.
3. **Related records** (option 3, revised): every foreign key is a `ref` field, marked "deleted
   with its target" where schema.md's rules say so; a deleted record's owned records are marked
   deleted with it and revert with it. Pure links with no id (`GiftPersons`, `TransactionTags`)
   are a set-valued list field on their owner, saved as added or removed pairs. Every child list
   has a stated order: a natural one (a field, or creation time through the UUIDv7 id), sorted
   the same way by the server's query and the Draft; a `position` field only where the
   requirements let the person arrange the order.
4. **Ids made in the browser** (option 1): the browser makes real UUIDv7 ids (`crypto.
   getRandomValues`, the server's alphabet, a same-millisecond counter as `ids.uuid7` has). Each
   entity declares its prefix (generated, item 1); `Record` and every `ref` field inherit the
   form check. The server checks every id it is given with a typed annotation built on
   `ids.is_id` (now unused), refusing at the field with 422: right prefix for the table, exact
   form, a time near its own clock (window to set when written), not already taken. `createdAt`
   stays the server's clock. Tests: the Draft takes its id maker (Deno tests pass a counted one);
   browser tests set the page clock to a frozen server clock (`page.clock.install`); the
   generated mockup's build gets a repeatable mode in the page config, counted like `_counted`
   but apart from the server's count; direct API tests for each refusal.
5. **The save** (option 1): one route, `POST /ui/api/save`, `{ ops: [{ op, entity, id, version,
   fields }] }`, set fields as `{ add, remove }`. Each entity's create/change/delete logic moves
   into functions taking the open transaction, in a registry; the per-record routes stay (MCP,
   one-click actions) as thin wrappers over the same functions. Updates are partial: changed
   fields merged onto the record, then the whole record checked. Foreign keys deferred to
   commit; creates, then updates, then deletes. Every op checked as its own route would; one
   refusal rolls back all. Stream events, alerts and jobs once after commit, de-duplicated;
   Activity per change. `Idempotency-Key` on the request. The answer gives each touched record's
   new version and stored form. A cap on ops and body size within S13. Refactor entity by entity
   as dialogs move to Drafts.
6. **Asks and refusals** (option 1): the server applies the whole save, gathers every ask
   (`reconciled-period`, `closed-year`, `reserve-balance`, …) without stopping at the first,
   rolls back and answers 409 `confirm-needed` with each ask's `code`, record `id` and message;
   the dialog shows them all; **Save anyway** resends `confirm: [{ code, id }]`, and the server
   goes ahead only if every ask it finds is in that list (a new one is asked again). Refusals:
   every op checked and every field error collected before the rollback; each error carries
   the record's `id` and `field`; the Draft hangs it on its record and field (a child shown as a
   row: on the row; otherwise the form). A stale version is item 7's.
7. **Versions on 412** (option 3, replacing "merge on 412 in the first version" settled before
   the walk): no merge. Any stale version rolls the whole save back (item 5); the dialog says the
   records changed since it was opened and the changes weren't saved, and offers to reload it
   fresh (the edits are lost) or cancel. Why: all or nothing; a very rare case not worth the
   logic, nor the risk of correlated fields surprising the person after a merge. S13.8.6's "the
   screen shows what changed and the person can make the change again on top" is rewritten to
   match; the server's 412 keeps carrying `current` for other API callers.
8. **Unsaved changes prompt** (option 2): "Discard your changes?" with **Keep editing** (focused)
   and **Discard**, on Escape, ✕, **Cancel** and Back while `draft.changed`; a click on the
   dimmed area does nothing while there are changes (closes as now without); leaving the page
   gives the browser's own `beforeunload` prompt. A session ended or a server locked with a
   dialog open: the sign-in or locked screen says unsaved changes were lost. Written into S12
   with the dialogs' common behaviour; the mockup gets the prompt as a state on the MOCK menu.
9. **The Draft's life**: it loads from the resource it saves to (never a screen's computed
   figures), each Record keeping its loaded version; live-stream events don't touch it; it is
   discarded on a successful save or Cancel/Discard, kept after an ask, refusal or network
   failure, made fresh on a 412 reload; its `Idempotency-Key` is reused while retries send the
   same ops. (A) One Preact signal per Record; `draft.changed` and computed values are
   `computed` over them. (B) Child dialogs by ownership: a record not owned by anything in the
   parent's Draft (a new person, category, organisation) is made in its own Draft, saved by its
   own Save, and the parent sets its `ref`; cancelling the parent leaves it. A record owned by
   the parent's records (a split, a plan line's reserve, an occasion) is edited in the parent's
   Draft inside a checkpoint (an undo log since the mark): **Done** keeps and closes with no
   request, Cancel/Escape rolls back to the mark, the prompt compares against the mark; saved
   with the parent; its refusals show on its row and, reopened, at its field.
10. **Rollout** (the user's packaging): this review's PR (`code-review-0003`) carries the fixes
    of CR3-1, CR3-3 and CR3-4, the Draft's requirements (S12, S13.8, schema.md §2, api.md, S17,
    mockup states), and the Draft/Record machinery with its tests, unused by any dialog. The
    next PR puts it to use: the plan and estimate dialogs (CR3-2), the prompt in `Dialog`, the
    save-unchanged browser tests; later PRs the remaining dialogs (CR3-29, CR3-43, CR3-35 first).

**Approved** by the user, Oct 28, 2026, 9:25 AM, with the test points for the High claims'
fixes, written into S17.5 as each fix lands.
