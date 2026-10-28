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
