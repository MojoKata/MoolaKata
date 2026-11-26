# Settings: Sign-In and Sessions

How long a sign-in lasts and when repeated failures lock the address they come from. Each length
of time is a duration such as `8h`, `30d` or `2w 3d`: whole numbers of weeks (`w`), days (`d`),
hours (`h`) and minutes (`m`), largest first, and it is shown back that way. **min**,
**default** and **max** under the field fill in its range's ends and its default; a blank, or
one outside the range, is refused at Save.

![Settings: Sign-in and sessions](shots/settings-sessions.png)

## Idle timeout {#idle-timeout}

How long without using MoolaKata before a session ends: `1h` to `1w`, `8h` by default.

## Longest session {#longest-session}

How long a session lasts, used or not: `1d` to `52w`, `4w 2d` (30 days) by default.

## Failed sign-ins before a lockout

Wrong passwords or codes in 15 minutes, from one address, that lock that address. 10 by
default. A username that keeps failing, from anywhere, is only slowed, never locked, so nobody
can lock an admin out by typing wrong passwords from afar. While the server is locked, wrong
recovery phrases at the unlock count against the defaults, 10 for 15 minutes, since these
settings can't be read until it is unlocked.

## Lockout {#lockout}

How long a locked address waits: `1m` to `1d`, `15m` by default.
