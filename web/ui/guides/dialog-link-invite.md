# Invite a Server to Link

## Link code {#link-code}

Give it to the other server's admin, by any channel: it holds this server's link address and its
key's fingerprint, and a one-time secret. It works once, for 24 hours; **Withdraw** on the
invitation stops it sooner. When the other admin enters it, their server appears as **wants to
link**, with its fingerprint: compare fingerprints with them (by phone, in person) before
approving. The code carries this server's certificate as read at its link address, or, when
that can't be reached and this server serves HTTPS itself, the one it serves. When neither can
be read, no code is made, since it would carry no key for the other server to pin: the dialog
says *This server can't read its own certificate at its link address*, and the link address in
Settings › Linked Servers is the one to check.
