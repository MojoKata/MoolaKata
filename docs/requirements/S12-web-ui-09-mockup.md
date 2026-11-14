# S12.9. The clickable mockup

9. **The clickable mockup**: one HTML file that opens from disk and sends nothing anywhere,
   showing every screen and dialog on sample data. Its purple **MOCK** pill (where the DEV
   pill goes) jumps to any screen, switches users, opens dialogs and changes state (prices
   stale, privacy mode). There are two files while the app is being built:
   1. **`docs/mockups/MoolaKata-mock.html`**, hand-written: the design reference for every
      screen. A change to what users see updates it in the same change. CI keeps each run's
      copy as its artifact (linked from its summary), so a pull request's design opens from
      it, and publishes main's on the Pages site. Its MOCK pill opens and closes a pane of a
      fixed width at the left, beside the app (which moves over, never covered): every
      screen, Settings section, dialog, user and state, grouped by the navigation's sections
      in their order, then by what has none (Profile, the linked households, signing in, a
      new server, a locked server, the connector's page, who is signed in, states),
      alphabetical within a group, with a filter at its top that matches an item's words or
      its address: an address pasted into it (where the address bar can't be used, as in a
      viewer that frames the file) is offered as a link. Each is an address that opens it when
      typed into the address bar, so one can be shared: a screen `#/budgets`, a
      section `#/settings/keys`, a dialog over its screen `#/settings?dialog=prune`, a user
      `?as=bob`, states `?on=stale,privacy`. What only happens (a new alert arriving) is a
      button.
   2. **`MoolaKata-app.html`**, generated: `web/ui/mockup/build.py` inlines the app and an
      in-page fake backend, for the screens built so far, the linked household window among
      them. Not committed: CI builds and opens it each run, keeps it as the run's artifact
      (linked from its summary), and publishes main's on the Pages site. It records each
      sample user in turn, as each signs in
      (what one sees can show who has signed in so far): several browsers in that user's
      session open the screens, tabs, ranges and dialogs at once, and each answer is asked of
      the server once and kept as one browser opening them all in order would keep it.

   When the generated file covers every screen, it replaces the hand-written one and takes
   its name. `docs/mockups/check.py` opens every screen, tab, Settings section and dialog of
   the hand-written mockup in headless Chromium and fails on any page or console error.
