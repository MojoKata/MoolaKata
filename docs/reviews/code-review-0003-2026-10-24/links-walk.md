# Walk-through: review 3's link claims

Started Oct 31, 2026. Decisions log; nothing is applied until the final approval. The claims are
unit 8's (linked servers, S11) and unit 9's gzip ceiling: CR3-50 to CR3-55, CR3-57, CR3-72.

## Items

1. CR3-50 (Med): two servers whose link ended can never link again
2. CR3-52, CR3-53, CR3-72 (Med): what `/link` checks before a call's body (a linked key's
   limits used up by anyone, a slow receipt refused as clock skew, a stranger's 20 MB join)
3. CR3-51 (Med): a peer's exchange or delivery answered on the event loop
4. CR3-54 (Med): the minute's sweep deletes receipts that arrived while locked
5. CR3-55 (Med): a locked copy's inbox keeps its registry in plain JSON
6. CR3-57 (Med): the 20 MB ceiling counts compressed bytes

## Decisions

1. **CR3-50 (1 of 6): linking again retires the old row.** A join (both `join` and
   `answer_join`, in the join's own transaction) from a key whose link here has *ended*
   soft-deletes that row, so the new link takes its place in the list; one whose link is
   *broken* is ended first (its copies deleted, as any end does) and then retired the same way,
   the admin's code being the consent; the new link starts with a full snapshot. The unique
   index stays as it is, so every lookup by key still finds at most one live row. S11.6 says what
   linking again does, `link-protocol.md` §4 a line; the mockup's *Broken* guide and the row's
   hint say linking again replaces this link. Tests: end then relink, broken then relink, both
   sides. Weighed: the unique index leaving ended rows out (every key lookup must then filter
   them); the ended row brought back to life.
2. **CR3-52, CR3-53, CR3-72 (2 of 6): signed, or the body isn't read** (the connector's
   decision 3, carried to `/link`). Every call sends `MK-Link-Body-SHA256` (the hash its
   signature already covers); the signature, time and nonce are checked on the headers before a
   byte of the body, and the body must hash to it as it streams. A call counts against a link's
   limit only once its signature checks, before that against its address as an unknown key's
   does; the upload budget counts a link body as it is read, and only a verified call's body is
   read. Answers: their time is checked when their headers arrive, their signature at the end
   over the streamed hash (the `file` answer, large exchange answers). `join` takes a body cap
   of its own, 16 KB, refused on its headers. Protocol stays 1 (no installs). `link-protocol.md`
   §3, §4.3; S11.1.3, S13.7.5.4, S13.7.6. Tests: a spoofed key leaves the link's limit alone; a
   body taking over 60 s is taken (injected clock); a 20 MB join refused on its headers.
   Weighed: the review's remedies alone (a `deliver` naming a linked key still written to disk
   before its signature); those plus a per-address limit for failed signatures.
3. **CR3-51 (3 of 6): `/link` and `/connector` off the event loop.** Each route keeps the async
   part that reads and checks its body (decision 2) and hands its synchronous work to the thread
   pool (`run_in_threadpool`): `answer_exchange`, `answer_deliver`, `answer_join`,
   `apply_report`, `apply_locked`, `files.post` and the rest; `_deliver_file` reads its stream on
   the loop and writes through a thread. `DELIVERED` gets a lock (the nonces have one). S13 gains
   the rule: no request holds the event loop with database, file or network work. Tests: a
   slowed `answer_exchange` and a slowed connector file post don't hold up `/healthz`. The UI's
   async routes already hand their work to the import pool or a job. **Later (L15):** the test
   server runs asyncio's debug mode and fails a test whose callback holds the loop past a
   threshold, to catch the next route that does (the threshold is to be tuned against CI's
   runners). Weighed: `/link` alone (the connector's statement read still holds the server).
4. **CR3-54 (4 of 6): one lock per link for `take`, `apply` and the sweep.** `take` (a pull's
   fetching and placing of its receipts) and `apply` (opening the inbox at unlock) hold the
   link's lock (a `threading.Lock` per link, in `copies.py`) throughout; the sweep tries it
   without waiting and skips that link this minute when held. `apply` also checks each file it
   names exists before writing its `File` row, and turns a missing one into a receipt not
   arrived, asked for again (S11.9.5.3). Tests: the review's sweep during `apply` (receipts
   kept), a long pull, a missing file made not arrived. Weighed: the sweep keeping every file an
   inbox entry names (plus a pull's files in flight); a staging folder only `apply` and `take`
   move out of.
5. **CR3-55 (5 of 6): the inbox entry sealed to the copy's key.** `enqueue` seals the `.json`
   entry (the change's registry and the local receipt names) to the copy's public key with
   `sealed.seal`, as the `.mks` beside it is; `apply` opens it with the private key it holds for
   the `.mks`, and still checks the source's signature over registry and sealed part together.
   The inbox shows only random names, sizes and file times (S11.9.10); S11.9.1 says the entry
   is sealed. Tests: a locked inbox's files hold none of the registry's names or ids in the
   clear; apply still verifies and applies. Weighed: the source sealing the registry (a
   protocol change, the receiver reading it on arrival all the same); the `.json` reduced to the
   sequence and names, the signature checked on arrival only (root could swap a waiting `.mks`).
6. **CR3-57 (6 of 6): the ceiling counts decoded bytes, in the transport.** `_Transport`
   decodes gzip and deflate itself (`zlib`, never asked for more than the ceiling's rest), caps
   the decoded bytes at the client's ceiling, removes `Content-Encoding` so httpx doesn't decode
   again, and refuses any other encoding; `net.Client` sends `Accept-Encoding: gzip, deflate`.
   Every caller is covered (`.json()`, `.content`, streams) whatever a server sends; `get_bytes`
   keeps working. S13.5 says the ceiling counts decoded bytes. Tests: a gzip answer decoding
   past the ceiling, through `.json()`, refused at the ceiling; deflate likewise; a small gzip
   answer read right; an unknown encoding refused. Checked: MoolaKata's server never compresses
   its answers; brotli and zstd aren't installed; the connector reads through `http.client`
   (no decoding, 25 MB cap). Weighed: `identity` asked and any encoding refused (a source that
   compresses regardless would stop working); every caller through `get_bytes` (a rule in ten
   callers instead of one place).

## Testing (Oct 31)

Asked before the final approval: how these slipped by, and what covers each category. Found:
the link harness (`tests/linkpair.py` `Wire`) replaces `net.Client` and re-implements its
ceiling on decoded bytes, so no link test runs `net._Transport`; `TestClient` sends each body
at once and one call at a time (no time passing in a body, no two calls together, no sweep
mid-operation); the tests follow features, not the link's lifecycle (no table of states,
CR3-150); nothing asserts a refused call left no trace, nor scans the data folder; the
signed-call check is written twice (`/link`, `/connector`), decision 3 of the connector walk
fixed one; two orphan sweepers with different rules, and `receipts/retention.remove_orphans`
deletes a receipt mid-upload (its file is written in the upload's transaction, before the row
commits): CR3-375, found by reading. Walked as eight items:

1. One signed-call gate for `/link` and `/connector`
2. A refusal matrix built from the routers
3. `Wire` below the real client, and the transport matrix
4. The link's lifecycle as a transition table
5. Concurrency tests on events
6. One file store and one sweeper rule (CR3-54, CR3-375)
7. A canary scan of the data folder
8. Parallel tests

### Testing decisions

1. **T1 (1 of 8): one signed-call gate for both protocols.** A decorator in `signing`,
   `signed_route(scheme, states=…, body=…)`, runs one order for `/link` and `/connector`: the
   headers verified (body hash, key, time, nonce, signature); a hook finds the caller (the paired
   connector and which key; the link and its state); the verified key's limits counted; the body
   streamed against its hash (JSON in memory, a file through a thread); the route's service
   function run in the thread pool; a fault a signed `server-error`. Each route is its decorator
   and a plain function `(srv, caller, body) -> dict`, tested without HTTP. Carries decisions 2
   and 3. Weighed: the link copy fixed in place (two copies to drift); a shared header check only
   (the order and the threading still hand-written per route).
2. **T2 (2 of 8): the gate tested on its axes, every route held to it.** At the gate: attack
   (no signature; a bad signature naming a linked key; an unknown key; a replayed nonce; a stale
   time; a body over the cap; a body not matching its hash) × protocol (link, connector) × body
   kind (JSON, streamed file, multipart), about 30 cases where the combination exists, each
   asserting the refusal and no trace (the verified key's limit, the in-flight budget, the
   upload folders and `links-in/`, every table's row count with Activity, and a wrapped
   `receive` showing nothing past the headers was asked for); and a slow body per kind (an
   injected clock moving 90 s across its chunks) taken. At the routes: a test reads both
   routers and fails on any route but `hello` not wrapped by the gate, and each route takes one
   forged call naming a real linked or paired key, no trace. About 45 cases, in-process, no
   sleeps. Weighed: every route × every attack (the gate's cases fifteen times over); the three
   claims' regressions alone.
3. **T3 (3 of 8): `Wire` below the real client.** `_Transport` takes an inner transport:
   production the httpcore pool over `_Backend`, tests one that runs `guard.check` as `_Backend`
   does, checks the pins against the certificate fingerprint `Wire` gives each test server, and
   routes to that server's app; `net.Client`, `_Transport`, the decoder and the ceiling are the
   real code in every link test, and `Wire`'s `Capped` copies go. The transport matrix on the
   same seam with `httpx.MockTransport`: encoding (none, gzip, deflate, unknown) × declared
   length (none, true, a lie) × read (`.json()`, `.content`, stream, `get_bytes`) × size (under,
   over), 96 cases in memory; two loopback-socket tests for the layer below (an oversized gzip
   answer, a pin mismatch). Weighed: the matrix on `net.Client` only (link tests still on a
   re-implementation); link tests over real loopback servers (slow, ports, flakes).
4. **T4 (4 of 8): the link's lifecycle in one pure module.** `links/lifecycle.py` holds state
   (*broken* on *active* and *paused*) × event (invite; the code entered here; a join arriving;
   approve; the peer answering *active*; pause; resume or a pause running out; end here;
   `link-ended`; `not-linked`; a good call; linking again) → the new state or a refusal, and
   state → the calls it allows (T1's gate reads its `states` from it). `manage.py` changes a
   state only through `lifecycle.step`; a test fails on any `.state =` elsewhere in `links/`.
   Tests: every state × event pair (about 100, pure); `link-protocol.md` §4's table held to the
   module's; five two-server sequences (end then relink, broken then relink, a peer restored
   from an older backup, *requested* then end, pause then end). S11.7 lists the same states.
   Settles CR3-150. Weighed: the table in the documents only, with two-server tests; relinking
   tests only.
5. **T5 (5 of 8): in-process concurrency tests, checkpoints and an inventory of pairs.** The
   event loop: `httpx.AsyncClient` over the ASGI app, two calls in flight, a service function
   blocked on a `threading.Event` not holding up `/healthz`, per protocol and body kind.
   Checkpoints: a no-op `checkpoint(name)` at the steps of operations that write files or rows
   in more than one step (`take`, `apply`, `deliver`, receipt upload, import), a test hooking
   one to run the competing task there, each checkpoint in turn. The inventory: each of the
   eleven tasks, what it touches, and the operations touching the same data outside a
   transaction; each pair a checkpoint test, the inventory kept in the test module. Known pairs:
   linked-copies and `take`/`apply`/`unlock`; *Remove orphans* and a receipt upload (CR3-375);
   the hourly links task and *Pull now* on one link; pruning and an upload, if pruning removes
   files. Timeouts generous (30 s), waits on events, never `sleep`. Weighed: a real Hypercorn
   subprocess (slow, races found by luck); the claims' regressions alone.
6. **T6 (6 of 8): one `FileStore`, one sweep rule** (replaces decision 4's lock; takes
   CR3-375). A small class per folder (the main `receipts/`, each copy's `receipts/`):
   `writing(name)` registers a file while its operation runs (upload, `take`, `deliver`),
   dropped once its row commits or the operation fails; `busy()` marks the store for an
   operation naming files in bulk (`apply` at unlock). One rule: skip a busy store; remove only
   files unregistered, named by no row, and older than a generous grace (30 minutes). Both
   sweepers become `store.sweep(named)`; `apply`'s existence check (decision 4) stays.
   `reencrypt`, backups and restore read `*.mkr` as today. CR3-375 (*Remove orphans* during an
   upload deletes its file: the file written in the upload's transaction, the thumbnail drawn,
   the row committed after) goes into review 3's table and is fixed here. Weighed: staged
   `.pending` names renamed on commit (every reader must know them; a locked copy's receipts
   stay staged for days); decision 4 as locked, CR3-375 left to the receipts group.
7. **T7 (7 of 8): a canary scan of what's on disk.** One scenario on two linked servers seeds
   distinctive strings in every field that carries a person's data (owner and user names, an
   account, payee, memo, an amount 31415.92, a category, a tax book's title, a receipt's file
   name and text), then shares with receipts, pulls while the copy is locked, sends a large
   change in parts, uploads a receipt, imports OFX, holds a statement for mapping, takes a
   connector report and file, makes a backup, writes an email with SMTP off, locks and
   restarts. Every file under the data and backups folders is scanned for each canary (UTF-8,
   UTF-16, JSON `\u` escapes, the amount's other forms), only S15.7's mail folder allowed (the
   test cites it); the captured logs hold none; and every file must be a known kind by its
   header (SQLCipher with no plain SQLite header, sealed, keyring, an allowed plain file), so an
   unknown kind fails before it holds data. Weighed: a test per writer (the next writer
   untested); CR3-55's regression alone.
8. **T8 (8 of 8): the server tests in parallel, in this PR, first.** `pytest-xdist` through
   the dependency process (S17.3, `dependencies.md`, the audit); `web/check` and CI split
   pytest in two, the server suite under `-n auto` and the browser modules (`test_app.py`,
   `test_browser_drafts.py`, `test_mockup_app.py`) serial as today; coverage combined across
   workers (`parallel = true`, as the browser tests' server already is); shared state fixed at
   its cause, a `serial` marker only for what truly can't share. These are the branch's first
   commits, so every test the decisions add runs in parallel from the start. **Later (L16):**
   parallel browser tests (a seeded household and a Chromium per worker, browser coverage from
   several writers). Weighed: all of it in its own PR next; all of it later.

## Final approval

Given Oct 31, 10:58 AM, for decisions 1 to 6 as the testing decisions revise them (decisions 2
and 3 through T1's gate; decision 4 through T6's `FileStore`) and T1 to T8. Applied on
`cr3-links`, in this order: T8; T3 and decision 6; T1, T2, decisions 2 and 3; T4 and decision
1; T6, T5, decision 4 and CR3-375; decision 5 and T7; review 3's table, L15 and L16.

## Applied

On branch `cr3-links` (PR #26), one commit per step of the approved order, each with its
requirements, protocol, mockup and tests.

| Step | Claims | Commit | What changed |
|---|---|---|---|
| T8 | — | `3ebb35a` | pytest-xdist; the server's tests under `-n auto`, the browser modules in one process; S17.5's *How tests are written*; L16 |
| T3, 6 | CR3-57 | `363aa6e` | `net.network`, the seam where the sockets are; `Wire` beneath the real client; the decoded-byte ceiling; `tests/test_net.py` |
| T1, T2, 2, 3 | CR3-51, CR3-52, CR3-53, CR3-72 | `065e90f` | `links/gate.py` for both routers; `MK-Link-Body-SHA256`; answers' time on arrival; `tests/test_gate.py`; L15 |
| T4, 1 | CR3-50, CR3-150 | `0fbe06e` | `links/lifecycle.py`; linking again; link-protocol §4.6; `tests/test_lifecycle.py` |
| T6, T5, 4 | CR3-54, CR3-375 | `40e5201` | `filestore.py`; `checkpoints.py`; `tests/test_races.py` and its inventory |
| 5, T7 | CR3-55 | `fbf75d2` | the inbox entry sealed (`.mke`); `tests/test_canaries.py` |

Where the work differs from the decisions as written, and why:

1. **T1**: the gate is `links/gate.py`, not part of `signing`: `signing` stays the crypto with
   no web framework in it. Unknown keys' bodies are no longer read at all: a signed refusal
   needs only the hash the call names, so `UNKNOWN_BODY` went. `/connector` gained the same
   per-address count for calls that fail (`conn_unknown`), and the connector takes an
   address's unsigned `limit` as it says. `pair` takes 64 KB at most, as `join` takes 16 KB.
2. **Decision 1**: the broken row's hint stays short (*end it, or link again*): the longer one
   made the row twice its height; the *Broken* guide says linking again replaces the link.
3. **T5**: the pull's checkpoint is each fetched receipt (`receipt.fetched`), which a pull and
   a late receipt's fetch share. The inventory found **CR3-376**: two pulls of one link at once
   take a change out of order. It is a strict xfail in `tests/test_races.py`, for the user to
   decide (below). Remove orphans in the upload test reads in its own read transaction: today
   the upload's write lock (CR3-48) keeps the two apart, so CR3-375 is latent until CR3-48 is
   fixed.
4. **T6**: a delivered receipt holds the copy's store busy while it is kept and named, as a
   pull does; prune's removal goes through the store too (`FileStore.remove`), with the upload
   holding a reused file.
5. **T7**: the scenario leaves out the connector's report and file (they go through the same
   import as an upload), a change sent in parts, an email with SMTP off (the mail folder is
   plain by S15.7) and a restart; the backup is made directly, as its task makes it.

### Left for the user

1. **CR3-376**: how the two sides serialize pulls of one link. A lock held across a call to the
   peer deadlocks when both servers pull at once; the choices weigh a per-link lock on the
   pulling side, a refusal to the peer while one runs (`busy`, taken like `limit`), and taking a
   change already held as a repeat.
