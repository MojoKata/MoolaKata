# S12.18. Typed inputs

18. **Typed inputs.** Each kind of value is typed in an input of its own, the same on every
    screen, so what it takes, when it is checked and how it is shown never vary (R3.11):
    1. **The kinds**, each with the characters it takes and the form it is checked against:
       an **amount** (digits and one `.`, at most two places), a **quantity** or ratio (digits
       and one `.`), a **percent** (digits, one `.`, and `%` at its end), a **count** (digits),
       a **duration** (digits, `w`, `d`, `h`, `m` and spaces, read as S12.13 says), a **date**
       (S12.18.10), a **time of day** (S12.18.11), a **web address** (no spaces; `http://` or
       `https://`, then a host) and **text** (anything). An amount, quantity or count takes a
       `-` where the field takes a negative.
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
    5. **What is shown and what is stored** are the input's own: an amount is shown grouped at
       its two places (`1,234.50`) and stored as an exact decimal (S12.12), a quantity is shown
       grouped, a percent is shown with its `%` and stored as the number, a duration reads back
       as typed (S12.13), a date is shown as `Oct 12, 2026` and stored as `YYYY-MM-DD`, and a
       time of day is shown as `5:30 PM` and stored as `HH:MM`.
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
          and named by its label. A form that flips from read to edit fades its frames in
          over 150 ms (none with reduced motion), its Edit focuses the first field, and Save
          or Cancel takes the focus back to Edit.
       4. **One switch per form**: a dialog or a screen's form reads as a whole, and a control
          may read on its own. The form's own actions (add a part, remove a row, Save) are
          shown off, saying why (S12.19.1), and it closes with Close.
       5. **Only what the row doesn't say**: a dialog that reads leaves out a field with
          nothing in it (a blank, a switch that is off) and, opened from a record's row, the
          fields that row shows. Opened from elsewhere (a link, a tour), it keeps every field
          that has a value.
    7. **The server checks every value again**, whatever the browser did (S13.8).
    8. **Numbers as they are typed** (amounts and quantities; a count, a year or a code is not
       grouped): the digits sit at the field's right end and the commas that group them appear
       as they are typed, so the number grows to the left. After each change the caret keeps
       its place among the digits (as many digits to its right as before), and Backspace just
       after a comma takes the digit before it.
       1. **An amount in dollars is typed from its cents**, as a cash register takes it: each
          digit comes in at the right, so `1` reads `0.01`, `12` reads `0.12` and `123` reads
          `1.23`. A `.` is passed over, and Backspace takes the last digit off.
       2. **A quantity, and bitcoin, are typed as written**: a `.` starts the fraction, and
          leaving the field pads the fraction to the places its kind has, where it has a fixed
          number. A field with fixed places takes no digit past them as it is typed: the key is
          refused and the field marked (*At most 2 places.*).
       3. A paste is read as a whole value (S12.18.2), whichever way the field is typed:
          `$1,234.5` pasted into an amount is `1,234.50`. A `-` changes the sign where the field
          takes a negative.
    9. **Units**: an amount in dollars shows `$` before its digits, inside the field; a quantity
       shows its unit after them (`shares`, `days`, `%`, or `BTC` or `sats`, as the user chose
       in Profile, S1.6.4). A unit is neither typed nor stored: a click on it puts the caret in
       the field, and a `%` typed into a percent is taken and dropped.
    10. **Dates**: at rest a date reads `Oct 12, 2026`. In the field it can be typed as
        `10/12/2026`, `10/12/26`, `10/12` (this year), `oct 12`, `Oct 12, 2026`, `today`,
        `tomorrow` or `yesterday`;
        leaving the field shows it as `Oct 12, 2026` again, and anything else is marked
        (S12.18.3, *Type a date, such as 10/12/2026.*).
        1. **The calendar**: a button at the field's right end, or ↓ (with Alt or without),
           opens a month of days below it, on the field's date or today. In it, the arrows
           move a day or a week, Page Up and Page Down a month, Home and End to the week's
           first and last day; Enter or a click picks the day, Escape closes it, and either
           way the focus goes back to the field. The grid is always six weeks, so it keeps
           its size from month to month.
        2. **Bounds**: a day before or after the field's bounds is shown off in the calendar,
           and a typed one is refused in the bound's words (*On or after Jan 1, 2020.*).
    11. **Times of day**: at rest a time reads `5:30 PM`. It can be typed as `5:30 pm`,
        `5:30p`, `530p`, `5p`, `17:30`, `noon` or `midnight`; without am or pm a time is read
        on the 24-hour clock (`5:30` is morning). Anything else is marked (*Type a time, such
        as 5:30 PM.*).
        1. **The picker**: a clock button at the field's right end, or ↓, opens the times of
           day below it by the quarter hour: a row an hour, under **AM** and **PM** headings,
           each row the hour (`7:00`, bold), `:15`, `:30` (bold) and `:45`, a dot between,
           lined up on their colons. It shows 7 AM to 6 PM, stretched to take in the field's
           time; a chevron at its top left shows three hours earlier until midnight is in it,
           one at its bottom left three hours later until 11 PM is, in a margin of their own
           that stays when they go, so the times never move and the scroll bar has the right. It is as tall as 7 AM to
           6 PM, and scrolls, to the hours just shown, once more are. While the page is open,
           it opens again showing the hours it last showed. The field's time is marked (a time
           between quarters marks the quarter before it, outlined) and has the focus: ← → move a quarter, ↑ ↓ an hour, Page Up and Page Down
           three hours, Home and End to the hour's :00 and :45, showing more hours as they go
           past those shown; Enter or a click picks, Escape closes, and the focus goes back to
           the field.
    12. **Several of a list** (a record's tags, a gift's people): each chosen item is a chip
        with its own ×, and after them a box to type in. Typing lists the matches below it
        (tags most used first, people by name); Enter, or a comma, adds the one highlighted,
        or what was typed, and the list stays open for the next; Backspace in the empty box
        takes off the last chip; a paste of names separated by commas adds each. A click on a
        chip, or ← at the start of the box, takes the focus to the chips: the arrows move
        along them, Home and End to the first and back to the box, and Backspace or Delete
        takes the chip off. What was typed becomes a chip when the field is left, not when a
        chip takes the focus. Two names that differ only in case are one, and
        the spelling chosen first is kept; an item already chosen is not added again.
        1. **New items**: where the list may grow (tags), a name that matches none is a new
           item, made with the record when it is saved. Where it can't (people, who are
           added on their own page), a name that matches none is refused (*No match*).
        2. **Many chips**: the field grows a row at a time to three rows of chips, and then
           scrolls. A field kept to one line (a filter) scrolls sideways instead, showing its
           end (the box to type in) at rest, and a count over its left edge (‹ 3) says how
           many chips are out of sight there; a click on it goes back to the first, and a
           screen reader reads it as *3 before*.
    13. **The focus and the keys stay with the field**: a click on anything in or under it (its ×, a word
        under it, a list's option, a calendar's day, a picker's time, a chevron) leaves the
        focus in the field, never on the page. In anything typed into, Home and End go to the
        start and end of the line as drawn (with Shift, selecting to it; with Ctrl or Cmd, in a
        box of several lines, to its start and end), on a Mac too, where a browser would
        otherwise scroll the page; an open list's Home and End stay its own.
    14. **Small counts are stepped**: a whole number with bounds a hundred or so apart (months
        lived with a dependent, a loan's term and draw period, a wallet's gap limit, the days
        of backups kept, the years receipts and statements are kept, lockout failures, a
        password's least length, the largest receipt, a projection's ages and years) has, at
        its right end, a chevron up and one down that step it by one, as ↑ and ↓ do (Page Up and
        Page Down by ten), each off at its bound; a blank steps from its least. It is still
        typed, and checked, as a count is.
