# S12.1. Frame

1. **Frame**: drawn once around every signed-in screen, from one list of navigation entries;
   no screen draws or changes it.
   1. A **sidebar** pinned to the viewport: the household's avatar and name with the version
      (and a red **DEV** pill in dev mode), the navigation with count badges, and at its
      foot the signed-in user's
      tile with the **theme** button (crescent moon for dark, lightbulb for light, palette
      for the system's; a click moves to the next). A round button on its edge collapses it
      to icons and opens it again; the browser remembers which.
   2. The **help pane** on the right (S12.7), and a **toast** area for confirmations: each
      slides up from the bottom, stays a moment and slides back down, so it is noticed (no
      movement with reduced motion).
   3. Shared components: one popup menu (closes on choosing, Escape, or a click or focus
      outside), dialogs, styled tooltips that also show on keyboard focus and reach screen
      readers, and a **pager** for long lists (Transactions, Activity): a page size of 100,
      500 or 1000 kept per browser, the rows shown out of the list's total ("1–500 of 2,624")
      with a jump to its pages (S13.8.5), and rows that arrive while reading counted on an
      orange **+N new** pill instead of shifting the page. Every password field (a password,
      an API key, the SMTP or node password) carries an **eye** button at its right end that
      shows what was typed and hides it again (the eye struck through while shown), labelled
      for screen readers. A secret that isn't the person's own sign-in (a recovery phrase, an
      API key, a bank's password for the connector) is plain text drawn as discs (blurred past
      reading where a browser draws no discs) until the eye shows it, so a password manager
      neither offers to fill it nor fills the person's
      MoolaKata password into it; the person's own password (signing in, setting it, changing
      it, confirming who they are) stays a password field, for the manager. A segmented
      choice (None · Read · Write) cross-fades from one button to the next. A **dialog** masks the content, not the guide: the sidebar and the
      page are dimmed and out of reach, for the pointer, the keyboard and screen readers,
      while the help pane beside it shows the dialog's guide and stays in reach, its links and
      terms working. A dialog opened over another, and the question over a dialog, darken the
      page once: only the top one's mask is drawn. The dialog is centred over the content; Tab goes round its fields and
      then the guide's, Escape or a click on the dimmed content closes it (unless it holds
      changes not saved, S12.15.6), and focus returns to where it was.
   4. An orange **update** pill under the brand when the server was upgraded since the page
      loaded; a click reloads.
