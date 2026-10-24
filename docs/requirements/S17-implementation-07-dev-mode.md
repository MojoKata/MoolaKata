# S17.7. Dev mode

7. **Dev mode** (`web/dev.sh run --seed --stubs`, `moolakata dev`) runs the whole server from a
   checkout as the current user, relaxing the surroundings, never the rules: sessions, CSP,
   encryption and sharing behave as in production. The one exception is the recovery phrase: a
   dev server makes its key on first run and keeps the phrase in `web/.dev/phrase`, so it
   unlocks itself at every start; its data is throwaway, and an installed server never does
   this (S15.4). `https://localhost:37373` with a self-signed certificate, `web/.dev/` for
   data, receipts and mail, seed users (`admin`, `alice`, `bob`, a *Household* group), a year
   of seeded transactions across every account type, open and closed option positions with an
   assignment and a wash sale, budgets, two projections, receipts, a **stub price source**
   (deterministic random walks, `--stubs`), and a **stub wallet source** (a made-up history,
   the same for an address every time), which nothing outside answers. The stub is a source
   Settings › Bitcoin saves like any other, and a seeded server saves it; until then wallets
   wait, as an installed server's do (S16.7). A second dev server on another port with `--peer`
   lets links be exercised on one machine. Emails are written to `web/.dev/mail/` and their
   links printed. A red **DEV** pill shows on every screen. For testing from another machine,
   `--listen` sets the address it listens on and each `--hostname` adds a name (or address) to
   its certificate, which is made again when it doesn't cover them all; `web/dev.md` describes
   the setups. Dev mode refuses to run as root, outside a checkout or on an installed server's
   data directory, and never calls a real provider unless one is configured; the image leaves
   dev mode's code out.
