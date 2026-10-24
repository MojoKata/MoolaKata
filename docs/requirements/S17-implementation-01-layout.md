# S17.1. Layout

1. **Layout**:

   ```
   README.md
   .github/workflows/    check.yml (web/check on every pull request), release.yml (S17.10)
   docs/                 requirements/ (README.md and its sections), schema.md, api.md,
                         link-protocol.md, connector-protocol.md, operations.md,
                         DEPLOY.md (a test server on Proxmox or TrueNAS, its screenshots
                         in deploy/), dependencies.md (the register, S17.2.1),
                         test-plan.md (the manual tests, S17.9.7.8),
                         mockups/MoolaKata-mock.html
   web/
     VERSION  dev.sh  release.sh  check  pins
     ui/                 index.html, deno.json, app/{main,router,config,hooks,format}.js,
                         api/, store/, screens/, components/, charts/ (the chart wrappers),
                         account-types/ (one module per type: fields, icon, help),
                         styles/{tokens,base,components}.css, assets/icons.svg,
                         guides/, vendor/, tests/, mockup/
     server/             src/moolakata/: main.py, app.py, config.py, runtime.py, listener.py,
                         middleware.py, static.py, settings.py, tasks.py, alerts.py, mail.py,
                         mcp.py, ui/ (routes per area), auth/, keys/ (the master key, its
                         phrase, secrets), store/ (tables/, entities/, repos/, mapping.py,
                         alembic/), ledger/ (lots, gains, corporate actions), washes.py,
                         options/, prices/ (one TickerSource per source), bitcoin/ (esplora,
                         electrum, core, descriptors), importers/ (ofx, csv, statements),
                         budgets/, projections/, loans/ (schedules, payoff planner), assets/
                         (items, valuations), education/, people/, gifts/ (occasions, holiday
                         tables), giving/, taxes/ (8949, txf, limits tables), receipts/
                         (storage, thumbnails, the reader and its worker, the field parser,
                         retention), links/, dev/ (dev mode, seed data, the wheel check)
     install/            Dockerfile, compose.yaml, compose.tls.yaml, compose.truenas.yaml,
                         compose.connector-truenas.yaml, moolakata.toml, smoke.sh, proxy/
                         (reverse-proxy examples)
   connector/            the MoolaKata Connector (S18): its core, drivers, page and image
   publish/truenas/      the server's and the connector's apps for TrueNAS's catalog,
                         check.sh, which tries them, and create-pr.sh, which proposes them
                         (S17.8.3.1)
   ```
