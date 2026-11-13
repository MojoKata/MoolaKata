# S12.7. Help pane

7. **Help pane**, on every screen:
   1. **F1** toggles it. While it is closed, a dim quarter-circle with a question mark sits in
      the page's top right corner, and grows into a green circle on hover ("Show help (F1)").
      The pane sits at the right edge; the split drags (up to half the window) and moves with
      the arrow keys. The browser remembers whether it is open and how wide.
   2. **The guides** are Markdown files shipped with the app: `web/ui/guides/<screen>.md`, and
      `<screen>-<panel>.md` for a screen's tabs or sections. **Per-account-type** parts
      (`guides/account-<type>.md`) are placed into the account page's guides by marker lines
      (`{{account-type settings}}`), and each price source has its own part for Settings ›
      Prices.
   3. **It follows the page.** As focus moves to a field, the pane scrolls smoothly to that
      field's heading and highlights it for a moment. That heading stays marked as the
      **active topic** (extra bold, underlined, with a solid ▶ to its left) until focus moves
      to another field with a heading of its own. A field is matched to a `##` heading by
      its label turned into an id ("Lot method" → `lot-method`), or to an id the heading lists
      (`## Lot method {#lots}`). Guides keep the page's order, so moving down the page never
      moves the guide up.
   4. **What a guide holds**: a short paragraph on what the screen is for, a screenshot, and a
      heading for every field, switch and button (what it is for, what to enter, its default),
      with examples for anything typed in a language of its own (rules, patterns, mappings).
      Finance terms (cost basis, wash sale, RMD, TWR and IRR) get a short plain-language
      explanation in the guide of the screen where they appear. The Markdown is a subset:
      headings, paragraphs, lists, tables, code, quotes (shown as notes), images, links, bold,
      italic; raw HTML is shown as text.
   5. **Screenshots** come from the clickable mockup (`web/dev.sh help-shots`, dark theme,
      1280 px, PNG quantized to 256 colours) and are committed.
   6. **Checks**: a test fails when a screen has no guide, a guide's screenshot is missing,
      a field's label finds no heading, the next field down the page sends the guide up, a
      guide uses an acronym the terms (S12.7.7) don't explain, or it names a form the forms
      (S12.7.8) don't list. Tickers and banks in examples and words everyone knows (PDF, URL)
      are listed as plain; a listed form's name (1099-DIV) is no acronym.
   7. **Terms**: an acronym in a guide (AGI, OFX, HELOC), or its plural, never in code or a
      link. Its first use under each heading has a dashed underline and is a tab stop; later
      uses under the same heading look like the text around them until hovered, when they show
      the same underline. On hover, or keyboard focus of a first use, a card shows the acronym,
      what it stands for, and a sentence or two on what it means. Where an official document
      defines it (an IRS publication, a CFPB answer, an RFC), an external-link icon at the
      right of the card's title row links to it: a plain link, opened in a new tab, that can be
      right-clicked or opened in a tab of one's choosing, and named for screen readers by the
      document. The card shows below the term, or above it when there's no room below, and
      stays open while the pointer or focus is on the term or the card, so the pointer and Tab
      both reach the link; leaving both or Escape closes it. It moves with the term as the
      guide scrolls, and closes when the term scrolls out of sight. Screen readers read what a
      first use stands for after it, and its explanation as its description. The terms are one
      Markdown file, `guides/terms.md`: a heading per acronym and what it stands for
      (`## AGI: Adjusted Gross Income`), the explanation under it, and the document as a last
      line that is only a link, in alphabetical order. The hand-written mockup carries the same
      terms, and a test keeps the two alike.
   8. **Forms**: an IRS form a guide names, never in code or a link, is marked as a term is
      (S12.7.7): "Form 8949" and "Schedule D" in full, and "1099-DIV" or "W-2" alone too,
      since they can be nothing else; a bare number ("8949") is never taken for a form. Its
      card shows the form, its title, a sentence or two on what it is for, and the
      external-link icon to the form's page on irs.gov ("About Form 1099-DIV"). The forms are
      one Markdown file, `guides/forms.md`, laid out as the terms are
      (`## Form 8949: Sales and Other Dispositions of Capital Assets`), in alphabetical order.
      The hand-written mockup carries the same forms, and a test keeps the two alike.
