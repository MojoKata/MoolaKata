"""The clients `sign_in` opened, closed after their test by conftest's `_signed_in_closed`.

Kept here, not in conftest: pytest imports conftest again for each session a process runs, and
mutmut runs several in one (listing, stats, clean tests, then every change in a fork of that
process), while a test module keeps the `sign_in` it first imported. Each conftest then had its
own list, the closer emptied the newest, and every client opened through an older one stayed
open with its event loop's thread. A module imported the ordinary way is imported once, so
every conftest shares this list."""

clients: list = []
