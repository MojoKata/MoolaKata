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
    6. **The server checks every value again**, whatever the browser did (S13.8).
