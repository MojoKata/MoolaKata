# S12.13. Durations

13. **Durations** are typed in one grammar wherever a length of time is asked for (pausing a
    link, S11.7.2): one or more parts, each a whole number and a unit, `w` (weeks), `d` (days),
    `h` (hours) or `m` (minutes), largest first, each unit at most once, with or without
    spaces between them: `1d`, `90m`, `2w 3d 4h`, `2w3d`. It is read by one helper on each side
    (`app/duration.js`, `moolakata/duration.py`), which refuses anything else and says why, and
    shown back the same way, so `2w 3d 4h` reads as typed.
