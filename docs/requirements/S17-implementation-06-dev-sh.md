# S17.6. `web/dev.sh`

6. **`web/dev.sh`** is the developer's front door: alone it prints its commands (`setup`,
   `run`, `test`, `check`, `mail`, `codegen`, `mockup`, `help-shots`, `deno`, `vendor`,
   `audit`, `base-update`, `mocks`, `mutate`). **`codegen`** writes the generated code only: the OpenAPI
   document, the browser's types and its drafts' fields (`web/ui/api/`), found from the routes
   and the kinds the save takes (S13.8.11), in a few seconds; `web/check`'s drift step fails
   when any is out of date. The generated mockup (`mockup`) and the help guides' screenshots
   (`help-shots`) are other generated content, with commands of their own. **`mutate`** is a mutation run
   (S17.5.12) over the modules named: a scratch copy of the server in `web/.dev/mutate` with what
   it reads from beside itself linked, the lock's `mutation` group installed there, the fast
   tests that import the modules (never the generated worlds or the browser's), a test map
   built afresh every run, its memory watched and the run stopped past a limit; it ends with
   the outcomes by file and the survivors by function. `mutate check` runs one change against
   one test file. `web/pins` holds the versions and hashes of the dev-only downloads
   (Deno, Playwright's Chromium).
