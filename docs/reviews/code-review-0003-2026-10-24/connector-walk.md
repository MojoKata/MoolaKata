# Walk-through: review 3's connector claims

Started Oct 30, 2026. Decisions log; nothing is applied until the final approval. The claims are
unit 12's (the connector, S18) and the protocol documents' claims about it: CR3-64 to CR3-71,
CR3-325 to CR3-339, CR3-357, CR3-372, CR3-373, CR3-125, CR3-137 to CR3-141, CR3-159. Seven items
need a choice and are walked here; the rest take their remedies as written (agreed with the
final approval): CR3-64 (`apply_report` runs `sign_in_allowed`, dropping an address off the
driver's page), CR3-326, CR3-328 to CR3-332, CR3-335 to CR3-339, CR3-137, CR3-140 (`days` added
to `ofx-direct`'s settings).

## Items

1. CR3-65 (Med): the "Its page" link follows any report, even one from an address no admin
   accepted
2. CR3-66 and CR3-67 (Med): the Schwab driver's option trades (unreadable file; opening or
   closing from the sign; every position as stock; expiries and assignments dropped)
3. CR3-68, CR3-69, CR3-71 (Med), CR3-138, CR3-333, CR3-357, CR3-159 (Low): unsigned answers,
   refusals before the body, and what the connector does with each
4. CR3-70 (Med) with CR3-325 (Low): the host new credentials are sealed for, shown to the owner
   and the admin
5. CR3-139, CR3-327, CR3-334, CR3-125 (Low): ending a pairing (`unpaired` vs `not-paired`,
   unpairing while locked, Reset, a waiting code)
6. CR3-372 with CR3-141 (Low): the address the pairing code carries
7. CR3-373 (Low, question): the wait after five wrong phrases

## Decisions

1. **CR3-65 (1 of 7): two keys, a status key and an action key** (the user's proposal). The
   identity key splits in two. The **status key** stays beside the vault (`pairing.json`) and
   signs only a report that says *locked* (with the version) and `unpaired`; MoolaKata answers
   it with a signed acknowledgement and nothing else (no settings, owners or accounts). The
   **action key**, Ed25519, lives **in the vault** with the sealing key and signs everything
   else: full reports (page, Connection states, sign-in addresses), file posts, `sign-in`,
   `credential/taken`; MoolaKata refuses those under the status key. Pairing (which already
   needs the words) makes both and sends both public halves, each signed by the other; the
   fingerprint the admin confirms is the action key's. Files fetched before a **Lock** wait in
   memory for the next unlock. So a copied volume can only say *locked* or *unpaired*: the
   page link (CR3-65), sign-in links (CR3-64, whose check stays as a second line), forged files,
   deleting a waiting box and reading S18.2.4.4's answers all close. The new-address alert
   stays. No upgrade path: nobody runs MoolaKata yet (the user, Oct 30), so the schema change is
   a plain revision and existing pairings aren't carried. Weighed: the page and locked flag
   only from the accepted address; a report from an unaccepted address changing nothing; the
   page address set by an admin.
2. **CR3-66 and CR3-67 (2 of 7): options written whole, rigorously tested.** The Schwab
   driver writes `SHPERCTRCT` (Schwab's multiplier, else 100); the trade type from
   `positionEffect` (BUYTOOPEN, BUYTOCLOSE, SELLTOOPEN, SELLTOCLOSE; SELLSHORT and BUYTOCOVER
   for stock); OPTINFO whole (call or put, strike, expiry, underlying: from the instrument, else
   from the option's OCC symbol); positions by asset type (POSOPT, POSMF, POSDEBT, POSSTOCK);
   an option's `RECEIVE_AND_DELIVER` as CLOSUREOPT (EXPIRE, ASSIGN, EXERCISE) by what it says;
   anything still unrecognised named in the Connection's message, never dropped silently. Full
   and rigorous tests (the user): fixtures shaped as Schwab's published API for every option
   trade, end, position kind and short stock, each run through the server's OFX reader and
   import, with the resulting lots and strategies checked. The user will supply a real Schwab
   options statement later; recorded as later work (next free L id) to check the driver
   against it. Weighed: options left out with a message; expiries and assignments left out.
3. **CR3-68, CR3-69, CR3-71, CR3-138, CR3-333, CR3-357, CR3-159 (3 of 7): signed or nothing,
   the signature checked before the body.** The connector sends the body's SHA-256 in a header
   (covered by the signature already); MoolaKata verifies the signature on the headers alone,
   refuses an unknown key or the status key with a body (decision 1) before reading anything,
   and compares the hash as the body streams in. In-flight budgets count only the paired key,
   with a process-wide ceiling. Every refusal after the body is read is signed: an unreadable
   file `file-refused` with the reader's message, a file over S16.8's import size `too-large`,
   any fault in a connector route a signed `server-error`. Unsigned are only `locked`, `limit`
   and `too-large` for a body over the hard limit, each on the headers; the protocol lists
   them and the connector acts on no other unsigned answer. The connector handles each file on
   its own: a transport error, `locked`, `limit` or `uploads-in-flight` keeps it for the next
   round; any other refusal drops it and sets the Connection failing with the reason; it goes on
   to the next file and Connection and always sends the after-run report; waiting files are
   capped per Connection (the oldest dropped, named in the message). A failed `sign-in` call
   doesn't end the round. S13.7.6 and the protocol name S16.8's size for statements (S16.10's
   for receipts). The link protocol's same flaw (CR3-72) can take the same header in the links
   group. Weighed: the review's remedies alone (an unknown key refused on its headers; a
   signed-in user who reads the paired key could still fill its budget).
4. **CR3-70 with CR3-325 (4 of 7): the bound host shown, sealed, and the address editable.**
   `ConnectionOut` carries each Connection's host (the OFX settings' `url` host; Schwab's
   fixed `api.schwabapi.com`); the credentials dialog says *Sealed for <host> only* and seals
   that host; Settings › Connector gains a **Host** column (CR3-325). For an existing OFX
   Connection the dialog also shows the server address, filled and editable: a change is saved
   with **Seal and send** (the password again), checked by the server, and the credentials are
   sealed for the new host, so S18.7.3's changed address is reachable without removing the
   Connection. The other OFX settings stay fixed. Mockup: the dialog's host line and address
   field, the column. Tests: **Change credentials** on an OFX Connection in the browser; the
   connector filing it, and the changed-address path, end to end. Weighed: the host read-only
   (a changed address still meaning a new Connection).
5. **CR3-139, CR3-327, CR3-334, CR3-125 (5 of 7): one code; the vault forgotten at the next
   unlock; Reset tells MoolaKata; Unpair withdraws a waiting code.** (a) One `not-paired`
   code, as now: every Connection belongs to its pairing (`manage._end`), so a MoolaKata
   restored from before the pairing has none of its Connections and the vault's credentials
   are filed under ids it no longer knows; operations §6 says such a restore ends the pairing
   (pair again; owners enter their credentials again). (b) Unpairing while locked leaves a
   "forget at the next unlock" mark beside the vault; the next unlock deletes the credentials,
   the sealing key and the action key held for that server; a signed `not-paired` while locked
   sets it too; the host's `unpair` asks for the words to delete at once, and without them sets
   the mark and says so. (c) `reset` sends `unpaired`, signed with the status key (decision 1),
   before it forgets; if MoolaKata can't be reached it says to unpair in Settings › Connector.
   (d) Unpair withdraws a pairing code still waiting, and S18.4.4's sentence says so. Weighed:
   the review's two codes (`unpaired` deletes, `not-paired` keeps the vault), which would keep
   only credentials for Connections that no longer exist.
6. **CR3-372 with CR3-141 (6 of 7): an address of the connector's own.** Settings ›
   Connector's pairing panel gains "The connector reaches MoolaKata at […]", the public URL by
   default; the pairing code carries it (and the certificate fingerprint for it, as for
   MoolaKata's own certificate today), never the link address. The server checks it (https,
   host, port). S18.4.1, S16, the protocol §1.1 and §4.1, operations §8 and DEPLOY §8.3 say
   so; the mockup gains the field and its guide text. Weighed: the public URL alone (a
   household whose public URL goes through an outside proxy would need split DNS or wider
   connector ranges); the public URL, else the link address.
7. **CR3-373 (7 of 7): no wait; a rate limit per address on the page.** The 15-minute wait
   after five wrong phrases goes: the key is 128 random bits (S18.3.1), which no guessing rate
   reaches. The page limits wrong attempts per address (5 a minute), only to bound the logging
   and work a flood causes; the host's `unlock` is never limited (access to the host is the
   authority, S18.3.4); every wrong attempt on the page is still logged with its address.
   S18.3.3 says so, and why; S18.2.4.5 drops "counted toward the wait". Weighed: a 15-minute
   wait per address; the shared wait as specified.
8. **The rest as the review wrote them** (listed above), CR3-64's check kept as a second line
   behind decision 1.
9. **A connector corpus** (added after a look at coverage, Oct 30; the user cares for the
   connector's correctness over network and browser scenarios). Beside the import corpus
   (S17.5.7): Schwab entries, each Schwab-API-shaped data (the account, its positions and
   balances, its transactions) with a `.toml` of expected results written by reading the data,
   run through the driver's `to_ofx` and imported through the API, the account compared line
   by line. Single cases for every transaction and asset type (stock and ETF buy and sell,
   short and cover, mutual fund, bond with accrued interest and coupon, the four option trades,
   expiry, assignment, exercise, dividends cash and reinvested, interest, fees, ACH, wire,
   journal, money market, margin interest, securities moved in and out) and month-long
   scenarios (a covered call written and expiring, rolled, assigned; a put assigned; a spread
   opened and closed; a reinvested dividend). An invariant on every entry: after the import,
   the positions and cash MoolaKata works out equal those Schwab reported in the same data.
   OFX Direct Connect entries from a mock OFX server: bank, card and brokerage statements (with
   options), wrong-password and must-change codes, several accounts, values with `&`, `<` and
   non-ASCII. The connector's own logic as each decision needs (files handled one by one, the
   sign-in path, unpair and reset locked and unlocked). The user's real Schwab statement joins
   the corpus when it comes. Found while weighing it, to confirm against Schwab's schema: the
   driver skips `ACH_RECEIPT`, `ACH_DISBURSEMENT`, `MONEY_MARKET`, `MARGIN_CALL`, `MEMORANDUM`
   and `SMA_ADJUSTMENT`, and takes only a trade's first security (a multi-leg order's other
   legs). Weighed and dropped: command-line, transport and browser coverage beyond what each
   decision needs.

**Final approval:** given Oct 30, 8:19 PM (Chicago), decisions 1 to 9. Commits pushed as they
go, the PR open from the first so CI runs alongside.

## Applied

On branch `cr3-connector` (PR #25), one commit per decision and per claim taken as written, each
with its requirements, protocol, mockup and tests.

| Decision | Claims | Commit | What changed |
|---|---|---|---|
| 1 | CR3-65, CR3-137 | `d84b206` | status and action keys; `actionKey`/`statusKey` (revision 0043); `status-key`, `keys-unsigned`; the protocol's glance and §4.1-§4.2 |
| 2, 9 | CR3-66, CR3-67 | `4aa8e4b` | the Schwab driver's `statement`; OFX Direct Connect's codes and several accounts; the connector corpus; G28, L14 |
| 3 | CR3-68, CR3-69, CR3-71, CR3-138, CR3-333, CR3-357, CR3-159 | `d11b0d1` | `MK-Conn-Body-SHA256`; the signature and key before the body; signed refusals; `IN_FLIGHT_ALL`; each file on its own |
| 4 | CR3-70, CR3-325 | `f2d9ceb` | `host`, `address`, `settings` (the owner's) on a Connection; *Sealed for … only*; the address in the credentials dialog; the Host column |
| 5 | CR3-327, CR3-334, CR3-139, CR3-125 | `8dbba0e` | the `forget-on-unlock` mark; `unpair` with the words; `reset` tells MoolaKata; operations §6 |
| 6 | CR3-372, CR3-141 | `11c8960` | `connectorAddress`, the field in Settings › Connector |
| 7 | CR3-373 | `3e10eeb` | no vault wait; five wrong tries a minute per address on the page |
| as written | CR3-326, CR3-328, CR3-329, CR3-330, CR3-331, CR3-332, CR3-335, CR3-336, CR3-337, CR3-338, CR3-339, CR3-140, CR3-64 | `030422e` to `0ae6907` | one commit each |

Where the work differs from the decision as written, and why:

1. **Decision 1**: a status report's answer carries `certificate` as well as `ok`: it is public,
   and a connector locked for long must still follow a renewed own certificate (protocol §1.2).
   An action-key report keeps its `locked` flag rather than being taken as unlocked.
2. **Decision 3**: the 60-calls-a-minute `limit` is signed (it is checked after the signature,
   still before the body); the unsigned refusals are `locked`, `uploads-in-flight` and the
   hard `too-large`. The connector keeps a file on a signed `server-error` and on an unsigned
   answer it can't read, since neither is the file's fault, and drops it on any other
   refusal. Its uploads count as they are read rather than by a declared length, which makes
   "only the paired key" hold without a lookup in the middleware; all callers together have four
   times one caller's budget.
3. **Decision 4**: admins see each Connection's host and never its settings; its owner's view
   carries them, for the dialog's draft.
4. **Decision 5**: `unpair` on the host asks for the words only when the vault is locked, and
   reaches MoolaKata first when the connector hadn't yet (a restart).
5. **Decision 7**: only wrong tries count toward the page's five a minute.
6. **Decision 9**: the corpus runs in the server's tests, beside the import corpus whose
   machinery it uses. A broker's file sets the account's cash to its own, so the cash check
   alone can't show a missing row: the invariant also adds up the rows. Building it found what
   the decisions didn't name: an OFX server that answers with several accounts, sign-on codes
   15000, 15502 and 3000, a refused statement (all now handled), and a short sale of stock
   (G28).
7. **CR3-140**: `days` is a setting the API takes and the driver honours; no dialog offers it.
8. **CR3-329**: `status` no longer waits for the round; the round still holds its lock around
   its calls, so `pair` and `connect` on the host wait for a round in progress.
