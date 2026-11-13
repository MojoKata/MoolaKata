# S12.6. Live updates

6. **Live updates**: the frame keeps one Server-Sent Events stream open (`GET /ui/api/events`).
   It carries fingerprints and counts, never data: prices refreshed, an import finished, a
   statement read, a share received or removed, the categories changed, a linked pull done, a
   background task finished (a backup, a re-encryption), a sign-up request (for admins), a new
   alert (its count, never its title), the badges' counts (Alerts among them), a save, bulk
   categorise or rules applied (to the user who made it, so their other pages read again), and
   the server's version. A screen whose data changed reloads it through its usual routes. The stream never
   extends the session, ends after a few minutes (the browser reconnects), and takes the page
   to sign-in or *account is disabled* when the session ends.
