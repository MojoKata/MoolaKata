# Draft and Record: client-side change tracking with one atomic save

An architecture for how a browser application edits stored records. Each form tracks its own
changes and sends them all in one request, which the server applies all or nothing.

## The problem it solves

Without it, each form builds the request body it sends on its own, often from the figures the
screen shows rather than from the records as stored. Each record kind then has its own create,
change and delete routes, each with its own checks, its own errors and its own handling of
concurrent edits. Two kinds of defect follow from that:

1. **A form saved unchanged changes data.** A body rebuilt from display figures carries
   derived values (totals, carried amounts, spread amounts) back into stored fields.
2. **Child records lose their identity.** A form that saves a parent with its rows replaces
   the rows with new ones, so anything that pointed at an old row (a pairing, a planned item,
   a reference) is left pointing at a deleted record.

## The design

### Record

A `Record` is one stored record as the client edits it. It holds:

- the record's kind, id, version and state: new, read or deleted;
- `data`, the values in the server's stored form (never display text);
- `modified`, a sparse map of the original value of each field changed since it was read.

It offers `get`, `set`, `revert`, `revertAll`, `changed` and `changes()`. It doesn't fetch,
save or draw anything.

An **entity class** extends `Record` for each kind. It adds:

- defaults;
- rules, written as declarations ("required when", "set when", `when`/`otherwise`). The same
  declarations decide which inputs show. A hook (`onSet`) is allowed for what a declaration
  can't say, but declarations are preferred. An edit a rule makes is tied to the field that
  caused it and reverts with that field.
- computed display values, as getters that are never stored;
- quick checks for fast feedback. The server's refusal is final.

### Field definitions

Field definitions are generated from the server's API schema, so the client's types can't
drift from the server's (a drift check fails when they would). The field types are text,
money, quantity, percent, integer, boolean, date, month, choice, reference, list (ordered
unless marked a set) and JSON. Each type has `parse`, `format`, `equal` and `toWire`. Entity
classes add only UI details (label, input hint, display precision), never a type.

Text that doesn't parse yet stays in its input with a field error. It counts as a change, and
nothing is sent while it's there.

### Draft

A `Draft` is one editing session over a set of records:

1. It reads its records from the resources it will save to, never from a screen's computed
   figures. Each record keeps the version it was read at.
2. It keeps one reactive signal per record. Whether anything changed, and every computed
   value, derive from those signals.
3. Live updates from the server don't touch an open draft.
4. It is discarded after a successful save, on Cancel and on Discard. It is kept after a
   question, a refusal or a network failure. A stale save (below) replaces it with a fresh one.

**Related records.** Every foreign key is a reference field. One marked "deleted with its
target" makes a deleted record's owned records deleted with it, and they revert with it. A
pure link with no values of its own is a set-valued list on its owner, saved as added and
removed pairs. Every child list has a stated order (a field, or creation time through the
id), sorted the same way by the server's query and by the draft.

**Child forms, by ownership:**

- A record that belongs to nothing in the parent's draft (a new person or category, say) gets
  its own draft and its own Save. The parent then sets its reference, and cancelling the
  parent leaves it saved.
- A record owned by the parent's records is edited in the parent's draft, inside a
  **checkpoint** (an undo log since a mark). Done keeps the edits and closes without a
  request; Cancel rolls back to the mark. The edits are saved with the parent.

### Ids made by the client

The client makes real, time-ordered ids (UUIDv7, with the kind's prefix). That lets a new
parent and its new children reference each other before anything is saved. The server checks
every id it is given:

- the right prefix for its table, and the exact form;
- a time near the server's own clock;
- not already taken.

The record's creation time stays the server's clock. Tests pass the draft a counted id maker
and freeze the page's clock, so their output is repeatable.

### The save

All writes go through one route, `POST /save`, with this body:

```
{ ops: [ { op, entity, id, version, fields } ], confirm: [ { code, id } ] }
```

Set-valued fields are sent as `{ add, remove }`.

1. **All or nothing.** Each kind's create, change and delete logic is a function that takes
   the open database transaction, kept in a registry. Foreign keys are checked at commit.
   Creates run first, then changes, then deletes. Every op is checked as a route of its own
   would check it, and one refusal rolls everything back.
2. **Partial changes.** The changed fields are merged onto the stored record, and then the
   whole record is checked.
3. **Every error at once.** Every op is checked and every field error collected before the
   rollback. Each error names its record's id and field, and the draft hangs it on that
   record's field, or on its row when the child shows as a row.
4. **Questions (asks).** The server applies the whole save and collects every warning that
   needs consent, such as editing a closed period. It then rolls back and answers 409 with
   each ask's `code`, the record's `id` and a message. The form shows them all. **Save
   anyway** resends the same ops with `confirm` listing them. The server goes ahead only if
   every ask it finds is in that list, so a new one is asked again.
5. **Side effects after commit.** Live-update events, alerts and background jobs run once
   after the commit, de-duplicated. The activity log gets one entry per change.
6. **Retries.** The request carries an `Idempotency-Key`, reused while retries send the same
   ops.
7. **The answer** gives each touched record's new version and stored form.
8. **Limits.** The number of ops and the body size are capped.

A kind the save takes has no PATCH, PUT or DELETE route of its own, only its reads and
actions.

### Stale versions

Any stale version rolls the whole save back. The form says the records changed since it was
opened and nothing was saved, and offers to reload fresh (losing the edits) or to cancel.
There is no merge:

- the case is rare;
- a merge is the riskiest logic in the design;
- a merge can surprise the person with combinations of correlated fields that neither edit
  intended.

The server's 412 still carries the current record for other API callers.

### Unsaved changes

While a draft has changes, Escape, the close button, Cancel and Back ask "Discard your
changes?", with **Keep editing** focused and **Discard**. A click outside the form does
nothing. Leaving the page brings up the browser's own prompt. A session that ends, or a server
that locks while a form is open, says that the unsaved changes were lost.

## When it fits

- Forms that edit a record together with its owned rows.
- Forms whose display figures differ from what is stored.
- An application that is the only caller of its own write API.

It fits less well when outside clients write through the same API. They would have to learn
the op protocol, versions and asks instead of plain per-record routes. A separate, simple
public write API on the same kind functions is the usual answer.

## Conclusion: the impact of the design

The tables weigh the change from per-form request bodies and per-record write routes to
Draft/Record and one save. Building the Draft/Record machinery itself is left out; the tables
cover only what changed by moving every form onto it. Figures come from the codebase it was
applied to: about 50 record kinds and about 30 forms, measured from the commits that moved
those forms.

Impact runs from 10 (largest) down to 1 in each table.

### Upsides

Lines the design after the change won.

| Effect | Before | After | Impact |
|---|---|---|---|
| A form saved unchanged, and child records' identity | Bodies rebuilt from display figures; rows replaced on every save. Five defects found in review: corrupted plans, lost pairings, lost planned items, a lost amended filing, documents that couldn't be changed | Only changed fields sent; rows changed in place keep their ids. One table of 35 forms saved unchanged guards the whole class | 10 |
| Edits across several records | Several requests per form; a failure part-way left a half-saved state | One transaction, all or nothing | 9 |
| Write API surface | 86 PATCH/PUT/DELETE routes, each with its own checks, errors and version handling | One save route over 52 registered kinds; 5 other write routes left (sessions, keys, uploads) | 8 |
| Form behaviour | Each form built its body, saved and showed errors its own way | About 30 forms share one dialog/form layer; 34 entity classes declare their rules | 7 |
| Errors and questions | The first refusal stopped the request; a question per route | Every field error and every ask returned at once, each on its record and field; consent bound to `{code, id}` | 7 |
| Losing typed work | Escape or a stray click dropped edits silently | Discard prompt, the browser's leave-page prompt, and a notice when a session ends | 6 |
| Tests | Per-route and per-form tests, no test for the defect class | One saved-unchanged table, the shared behaviour tested once, a helper that edits as a form does; test code grew by about 1,800 lines | 6 |
| New parent with new children | The server made ids, so new records couldn't reference each other before saving | Client-made, time-ordered ids, checked by the server; tests need a frozen clock and counted ids | 5 |
| Side effects | Each route fired its events, alerts and jobs, sometimes several times per form | Once after commit, de-duplicated | 4 |
| Data model | Some link tables with values had composite keys only | Every editable row has its own id; migrations needed | 3 |
| Client and server types | Hand-kept; the field definitions file was 138 KB | Generated from the API schema with a drift check; under 1 KB for the kinds the save takes | 3 |
| Round trips | One request per record touched | One request per form | 2 |

### Downsides

Lines the code before the change won.

| Effect | Before | After | Impact |
|---|---|---|---|
| Outside API clients | Plain per-record REST writes | Must speak the op protocol, versions and asks | 5 |
| Server code size | Checks spread across route handlers | Net growth of about 2,700 lines while the forms moved (some of it features bundled with the move) | 4 |
| A concurrent edit | Per-record 412 that could show what changed, so the person could redo the edit on top | Any stale record rolls the whole save back; the person reloads and loses the edits (rare) | 4 |
| Rules in two places | Rules on the server only | Entity classes repeat some quick checks for feedback (the server's refusal stays final) | 3 |
| Reading logs | The method and path showed what was written | Every write is `POST /save`; ops have to be logged to see what changed | 2 |
| Size of one save | No limit beyond the request size | Capped number of ops and body size | 1 |

**Verdict.** After wins every line scored 6 or higher. Before wins only lower-impact lines:
simpler access for outside clients, less server code, a gentler outcome for a rare concurrent
edit, one place for rules, readable logs and unlimited batch size. The trade favours
Draft/Record wherever the application is the only caller of its write API.
