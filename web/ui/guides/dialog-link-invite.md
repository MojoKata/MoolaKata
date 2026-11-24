# Invite a Server to Link

## Link code {#link-code}

Give it to the other server's admin, by any channel: it holds this server's link address and its
key's fingerprint, and a one-time secret. It works once, for 24 hours; **Withdraw** on the
invitation stops it sooner. When the other admin enters it, their server appears as **wants to
link**, with its fingerprint: compare fingerprints with them (by phone, in person) before
approving. While this server can't read its own certificate at its link address, no code is
made, since it would carry no key for the other server to pin: the dialog says so instead.
