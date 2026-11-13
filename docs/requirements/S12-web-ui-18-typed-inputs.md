# S12.18. Typed inputs

18. **Typed inputs.** Each kind of value is typed in an input of its own, the same on every
    screen, so what it takes, when it is checked and how it is shown never vary (R3.11):
    1. **The kinds**, each with the characters it takes and the form it is checked against:
       an **amount** (digits and one `.`, at most two places), a **quantity** or ratio (digits
       and one `.`), a **percent** (digits, one `.`, and `%` at its end), a **count** (digits),
       a **duration** (digits, `w`, `d`, `h`, `m` and spaces, read as S12.13 says), a **date**
       (the browser's date picker), a **web address** (no spaces; `http://` or `https://`, then
       a host) and **text** (anything). An amount, quantity or count takes a `-` where the
       field takes a negative.
    2. **A key or a paste outside the kind's characters is not taken**, and the field is
       marked with what it takes (*Digits and . only*). A paste, or text put in whole (by
       autofill or dictation), is cleaned first: a dollar sign, spaces and non-breaking spaces
       are dropped, commas where they group thousands, a typographic minus becomes `-`, and an
       amount in parentheses becomes negative where the field takes one. Anything else left
       refuses the whole of it, never a part.
    3. **Checked when the field is left, and at Save**: its form, its bounds, and a bound
       another field sets (*At most* under *At least*). A value that fails is marked: a red
       border, and a tooltip saying why, which a screen reader reads with the field. Any
       change to the field clears its mark; it is checked again when next left. Save marks
       every field that fails and goes on, so each refusal shows under its field (S12.15.4).
    4. **Without a Save** (a filter, a preview), Enter or leaving the field is when its value
       is taken: one not yet checked, or marked, is left out, and what is shown stays as it
       was until the value passes.
    5. **What is shown and what is stored** are the input's own: an amount is shown at its two
       places (`1234.50`) and stored as an exact decimal (S12.12), a percent is shown with its
       `%` and stored as the number, a duration reads back as typed (S12.13), and a date shows
       in the browser's own format and is stored as `YYYY-MM-DD`.
    6. **Read**: every input has a read persona, drawn where the person may only read (a
       record shared with them to read, a form they don't own), never as a control that is
       off:
       1. **Its kind decides how it reads**: an amount as `$1,234.50`, a quantity or count
          grouped, a percent with its `%`, a date as `Oct 12, 2026`, a choice as the chosen
          option's words, a yes or no as a check or a dash in the switch's place, a long text
          with its lines; a blank as `—`.
       2. **A link where it leads somewhere**: a web address opens in a new tab, and a
          reference to a record with a page of its own (an account, a budget, a portfolio, a
          projection) links to that page when the person can see the record. One they can't
          see reads *Not shared with you*, never its id.
       3. **The edit footprint**: the read value sits in the control's own box, unframed, at
          its height and width, with a list's chevron space kept, so a form drawn read and
          drawn to edit don't move. It is reached by Tab, so the guide follows it (S12.7.3),
          and named by its label.
       4. **One switch per form**: a dialog or a screen's form reads as a whole, and a control
          may read on its own. The form's own actions (add a part, remove a row, Save) are
          shown off, saying why (S12.19.1).
    7. **The server checks every value again**, whatever the browser did (S13.8).
