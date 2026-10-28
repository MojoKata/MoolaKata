# S17.3. The browser app

3. **The browser app: no build step.** The files in `web/ui` are the files the browser loads.
   1. **Libraries**: Preact (rendering), HTM (JSX-like tagged templates, no `eval`),
      @preact/signals (state), preact-iso (routes and lazy screens), plus the chart library
      (S17.4). Each is **vendored**: its npm tarball is committed under `web/ui/vendor/`,
      named with its exact version in `manifest.json`, and `vendor.py extract` unpacks the
      files the import map points at. No npm, no network at install.
      1. **Adopting a version** goes only through `web/dev.sh vendor add NAME VERSION`. It
         refuses a version published less than 14 days ago unless `--young` gives the reason
         (a security fix), which the manifest entry keeps. It checks the download against
         the registry's integrity hash. Where the registry holds SLSA provenance, it verifies
         it through Sigstore: built by GitHub Actions from the repository the manifest
         records for the package, for this name, version and tarball. A package whose pinned
         version had provenance is refused a version without it. It warns of npm
         dependencies, which must be vendored too unless the served files bundle them. It
         writes the manifest entry (version, publish date, tarball, integrity, repository,
         whether provenance was verified, the unpack directory and the served files), and,
         for an update, a diff of the served files, which is reviewed before the commit.
      2. **The hash** in `manifest.json` is npm's own integrity value for the tarball, so
         anyone can confirm the committed file is what the registry published. `vendor.py
         extract` (in `web/check`, `web/dev.sh` and the image build) refuses a tarball that
         doesn't match it.
   2. **An import map** in `index.html` resolves `import 'preact'` to the vendored file.
      JavaScript with JSDoc types, type-checked by Deno. No minification and no source maps,
      so a stack trace names a file in the repository.
   3. **Strict Content Security Policy**: `script-src 'self' 'nonce-…'` (the nonce covers only
      the import map), `style-src 'self'`, no inline scripts or styles, no `eval`. No
      third-party requests: no CDN, no web fonts, no analytics.
   4. **Size budget**: under 150 KB compressed for the first screen; every other screen is a
      module loaded by a native `import()` on first visit.
   5. **Cache-busting**: the app is served under `/ui/v/<version>/`, with a one-year cache
      in a release. A build between releases (a `-dev` version, S17.10.2.2) and the dev server
      serve the same paths with `no-cache`, since their files change under one version.
      `index.html`, templated with the version and the nonce, is `no-store`.
   6. **Plain CSS** with custom properties and `@layer`: `tokens.css` (colours and sizes, dark
      first), `base.css`, `components.css`. Icons are one SVG sprite.
   7. **The server is the only state.** The browser remembers only how the page looks: theme,
      sidebar, help pane, page size, privacy mode.
   8. Current Chrome, Edge, Safari and Firefox; no polyfills.
   9. **Editing records** (S12.15) goes through one module, `app/draft.js`, never through
      request bodies a dialog builds itself.
      1. **`Record`** holds a record's kind, id, version and state (new, read or deleted), its
         values (`data`) and, for each field changed, the value it had (`modified`). It reads
         and sets fields, puts one or all back, says whether anything changed, and gives the
         changes in the API's form. It neither reads, saves nor draws.
      2. **Fields** come from the OpenAPI document: `moolakata.contract write` writes
         `api/fields.js` beside `api/types.js`, each field's name, type, whether it may be
         empty, its choices and, for a reference, the prefix of what it refers to, so the
         browser's fields can't drift from the server's models (S17.5). Each type parses what
         is typed, formats a value for its input, compares two values and writes the API's
         form. An entity class (`Transaction`, `Gift`, `BudgetLine`) extends `Record` and adds
         what only the browser needs (labels, input hints, defaults, values worked out for
         display), never a field's type.
      3. **Rules** are declared on the entity class: a field that applies only when another
         has a value, and what it becomes otherwise; a field required when; a field set when.
         The same declarations decide which inputs a dialog shows. A hook that runs on a
         change may do what a declaration can't, and is used only then. An edit a rule makes
         is tied to the edit that caused it, and is put back with it.
      4. **Related records** are records of the draft, tied by their reference fields; a
         reference marked as deleted with what it refers to (`schema.md` §4) makes the draft
         delete, and put back, the records it owns with their owner. A set of pairs with no id
         of its own is a list field of the record that holds it.
      5. **`Draft`** reads the records a dialog edits, keeps one Preact signal per record (so
         an edit redraws what reads that record), makes new records' ids, marks checkpoints
         for a dialog opened from a dialog (S12.15.7), and saves through S13.8.11, keeping its
         `Idempotency-Key` while a retry sends the same ops. The live stream (S12.6) never
         changes a draft. It is dropped after a save that succeeds or a **Cancel**, and kept
         after a question, a refusal or a lost connection. In the generated mockup's build
         (S12.9) the ids it makes repeat from run to run, counted apart from the server's.
      6. **The shared form pieces** (`components/draft-form.js`) make a form its fields and
         nothing more: `useDraft` reads its records into a draft and reads them again after
         a 412; `<DraftDialog>` and `<DraftForm>` bring the question before discarding (with a
         guard on the router for a screen's form), the button that saves, then saves anyway
         or reloads, and what a save came to above it; `<RecField>` draws a field by its type
         (text for money and quantities, a list for a choice or a reference, a switch for yes
         or no) bound to its record: its value, what was typed, its refusal, and hidden while a
         rule says it doesn't apply.
      7. **A record that holds from a date on** (a budget's plan line, from a month on: a
         change adds a row from then, earlier months keeping theirs): its entity class says
         which month the form changes it from and sends it with every change (a `changes()`
         that adds it), is taken out by a change rather than deleted (`removal`), and its
         kind on the server makes a row from that month, or changes the record when it starts
         then. A row from that month made since the record was read (a change saved
         meanwhile) makes the change stale (S12.15.5) rather than overwriting it unseen. The
         save's answer names the record as it was sent. One kind is built this way; a
         second would make it a declaration of the draft and the save.
