# S12.13. Durations

13. **Durations** are typed in one grammar wherever a length of time is asked for (pausing a
    link, S11.7.2, and Settings' timings: the session lifetimes and the lockout, S16.3,
    **Release linked keys after**, S16.9, and the alert threshold, S16.16): one or more
    parts, each a whole number and a unit, `w` (weeks), `d` (days), `h` (hours) or `m`
    (minutes), largest first, each unit at most once, with or without spaces between them:
    `1d`, `90m`, `2w 3d 4h`, `2w3d`. A duration is at least a minute and at most 52 weeks
    (`52w`). It is read by one helper on each side (`web/ui/kit/duration.js`,
    `moolakata/duration.py`), which refuses anything else and says why (*A duration is at most
    52w.*), and shown back the same way, so `2w 3d 4h` reads as typed. A field with a range of
    its own names its ends as durations (*1w or less.*), as a number field names its own
    (*100 or less.*).
