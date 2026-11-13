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
   6. **Plain CSS** with custom properties and `@layer`: the ui-kit's theme (S17.3.10:
      `tokens.css`, colours and sizes, dark first; `kit.css`, its controls), then the app's
      `base.css` and `components.css`, which draw their colours and sizes from the tokens.
      Icons are one SVG sprite, the kit's.
   7. **The server is the only state.** The browser remembers only how the page looks: theme,
      sidebar, help pane, a tour's width, page size, privacy mode; and, for a tab, the tour
      open in it and the counts it started from (S12.17.2).
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
         (its kind's typed input for money, quantities, whole numbers and dates, a list for a
         choice or a reference, a switch for yes or no) bound to its record: its value, what
         was typed, its mark and its refusal, and hidden while a rule says it doesn't apply.
      7. **A record that holds from a date on** (a budget's plan line, from a month on: a
         change adds a row from then, earlier months keeping theirs): its entity class says
         which month the form changes it from and sends it with every change (a `changes()`
         that adds it), is taken out by a change rather than deleted (`removal`), and its
         kind on the server makes a row from that month, or changes the record when it starts
         then. A row from that month made since the record was read (a change saved
         meanwhile) makes the change stale (S12.15.5) rather than overwriting it unseen. The
         save's answer names the record as it was sent. One kind is built this way; a
         second would make it a declaration of the draft and the save.
      8. **Typed inputs** (S12.18) are one component, `<TypedInput>` in
         `kit/fields.js`, given a kind from `kit/kinds.js`: the kind's characters (a
         pattern each typed or pasted character is tested against, in `beforeinput`), its
         paste clean-up (also for text put in whole), its whole-value check and what it says
         when one fails. Over
         `<ValueInput>`'s controls (× in the field; min · default · max or all under it), it keeps the mark: set when the field is
         left, at Save, or when a key or paste is refused, and cleared by any change. Kinds are
         plain data and functions, tested without a page. Read (S12.18.6), every input of
         the kit draws `<ReadValue>` instead, the text its kind gives it (`readText`, and a
         record's page from its id's prefix, which the app passes in); a form reads through
         the kit's one context, `Reading`, which `<DraftDialog read>` and `<DraftForm read>`
         set, its value the reason the form's own actions show.
      9. **Actions and state** (S12.19) are components of `kit/state.js`: `<Action>`
         (a button; given `why`, it is `aria-disabled`, ignores its click and Enter, and shows
         `why` as its tooltip and screen-reader description), `<Empty>` (a line and its
         action), `<StatePill>` (a pill whose tooltip, reached by Tab, explains it),
         `<Attention>` (a one-line notice and its action buttons) and `<RowTool>` (a row's
         pencil or eye, S12.19.5).
   10. **The ui-kit** (`web/ui/kit/`): the app's controls and theme as a package of their own,
       which the app builds on and which never imports the app.
       1. **What it holds**: the theme (`theme/tokens.css`, every colour, size and radius as a
          custom property, dark first and then light; `theme/kit.css`, the controls' styles,
          drawn only from the tokens; the icon sprite); the HTM binding (`kit/html.js`, which
          `app/html.js` passes on); the value types (exact decimals, durations, the kinds of
          S12.18, and formatting, told the user's choices by the app); the fields
          (`Field`, `Input`, `TypedInput`, `NumberInput`, `ValueInput`, `CountInput`,
          `SpinInput` (a small whole number stepped by chevrons and ↑ ↓),
          `Select`, `Switch`, `ReadValue`, `TagInput`, `DateInput`, `TimeInput`); the building
          blocks (tabs,
          chips, avatars, tiles, loading and failure, amounts and percents, and the
          components of S17.3.9.9); and the overlays (the dialog shell and its stack, the
          question before an action, menus, tooltips, toasts, the pager); and the keys every field shares (Home and End in typed text). What knows records,
          drafts, guides, screens or the server stays in the app: `RecField` binds a kit
          control to a record's field, a dialog's guide and its guard against losing changes
          are passed to the dialog shell, and so is the pager's page size.
       2. **A control's contract**: its value in and its change out, `readOnly` (its read
          persona, S12.18.6), `invalid` and `disabled`. The `id` it is given is on the element
          that takes the focus, so the app's guide follows it (S12.7.3). It keeps no state
          its caller can't set.
       3. **On its own**: a module in `kit/` imports only `kit/` and the vendored libraries,
          and a check fails on any other import. So the kit's tests run only when the kit
          changes (S17.10.1), while the app's tests, which draw the kit's controls, run on
          every change.
       4. **Its pages**: `kit/pages/` holds a page per component, its states side by side
          (empty, filled, many and long values, refused, off, read; dark and light), each
          instance with a line saying what it last reported, and beside them its keys, its
          states and its props, written for a reader without the code. The pages load the
          vendored libraries through an import map and carry the app's CSP in a `<meta>`
          tag. They are what the kit's browser tests drive (S17.5.13), and they are
          published: main's on the Pages site under `/kit/`, a pull request's as its run's
          artifact (`web/dev.sh kit-link PR`), linked at the end of its description.
       5. **Copied code**: what the kit adapts from an open-source project keeps its licence.
          `kit/NOTICE.md` names the project, the commit and what was taken into each file,
          with the licence's text; each such file says so in its first line; the dependency
          register lists it (S17.2.1). It is never updated on its own: a later fix there is
          copied as a change of its own, read like any other.
