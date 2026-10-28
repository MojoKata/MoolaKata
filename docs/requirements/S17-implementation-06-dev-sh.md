# S17.6. `web/dev.sh`

6. **`web/dev.sh`** is the developer's front door: alone it prints its commands (`setup`,
   `run`, `test`, `check`, `mail`, `codegen`, `mockup`, `help-shots`, `deno`, `vendor`,
   `audit`, `base-update`, `mocks`). **`codegen`** writes the generated code only: the OpenAPI
   document, the browser's types and its drafts' fields (`web/ui/api/`), found from the routes
   and the kinds the save takes (S13.8.11), in a few seconds; `web/check`'s drift step fails
   when any is out of date. The generated mockup (`mockup`) and the help guides' screenshots
   (`help-shots`) are other generated content, with commands of their own. `web/pins` holds the versions and hashes of the dev-only downloads
   (Deno, Playwright's Chromium).
