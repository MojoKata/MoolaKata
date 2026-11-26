# Testing the dev server

`web/dev.sh run --seed --stubs` runs the whole server from a checkout (requirements S17.7) at
`https://localhost:37373`, with a self-signed certificate. Sign in as `admin`, `jane` or `john`
with `moolakata-dev`. This page covers reaching it from a browser in the setups we use: on the
same machine, or from a Mac or Linux machine while the server (and often the coding agent)
runs on a Linux VM.

## The options

`web/dev.sh run` passes these to `moolakata dev`:

| Option | Default | What it does |
|---|---|---|
| `--seed` | off | seed users and a year of data (once per data directory) |
| `--stubs` | off | the stub price source instead of real providers |
| `--port N` | 37373 | the port to listen on |
| `--listen ADDR` | `127.0.0.1` | the address to listen on; `0.0.0.0` for every interface |
| `--hostname NAME` | none | a name or address the certificate also covers; repeatable |
| `--data DIR` | `web/.dev` | where the database, backups and mail are kept, with `phrase`, the dev server's recovery phrase, so it unlocks itself (an installed server never stores it, S15.4) |
| `--peer` | off | a second server (port 37374, `web/.dev-peer`) for links |

The certificate lives in `<data>/data/tls/self-signed.crt`. It always covers `localhost` and
`127.0.0.1`, and is made again when it doesn't cover every `--hostname`. A new certificate
means accepting the browser's warning again. Every directory named `web/.dev*` is ignored by
git.

Two things the server checks decide what works:

- **Every change must come from the app's own origin.** The browser's `Origin` has to match
  the `Host` it sent, so the address the browser uses must reach the server unchanged. An SSH
  forward or a plain TCP relay is fine, at any port. A proxy that rewrites `Host` is not.
- **Session cookies are Secure and belong to one host.** `https://localhost:37373` and
  `https://moolakata.loco` are separate sign-ins.

## Same machine

```
web/dev.sh run --seed --stubs
```

Open `https://localhost:37373` and accept the certificate warning.

## From another machine over an SSH forward

This is the usual setup when the agent works on a VM. The server keeps listening on the VM's
loopback only, and nothing else on the network can reach it.

On the VM:

```
web/dev.sh run --seed --stubs
```

On the Mac or Linux machine with the browser:

```
ssh -N -L 37373:localhost:37373 dev@<vm>
```

Then open `https://localhost:37373`. Connections reach the server from `127.0.0.1`.

### Under a name of its own

A name such as `moolakata.loco` keeps its cookies apart from anything else on `localhost`, and
is closer to how a household reaches a real server. Use a made-up name, not a real domain. Avoid
`.local`, which macOS sends to multicast DNS.

1. On the VM, put the name in the certificate:

   ```
   web/dev.sh run --seed --stubs --hostname moolakata.loco
   ```

2. On the browser's machine, point the name at the forward. Add `127.0.0.1 moolakata.loco` to
   `/etc/hosts` (with sudo). On a Mac, then flush its cache:
   `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`.

3. Forward a local port:
   - **Keeping the port:** `ssh -N -L 37373:localhost:37373 dev@<vm>`, then open
     `https://moolakata.loco:37373`.
   - **Without a port in the address** (`https://moolakata.loco`), forward local port 443:
     `ssh -N -L 443:localhost:37373 dev@<vm>`. macOS lets an ordinary user bind 443. Linux needs
     `sudo ssh -N -L 443:localhost:37373 -i ~/.ssh/<key> dev@<vm>`, or a lower
     `net.ipv4.ip_unprivileged_port_start`.

Emails' links are built from `https://localhost:<port>` in dev mode. To get links that open from
the browser's machine, set **Settings › General › Public URL** to the address you use.

## From another machine directly, without SSH

The server has to listen on the VM's network interface, and the certificate has to cover the
name or address the browser uses:

```
web/dev.sh run --seed --stubs --listen 0.0.0.0 --hostname moolakata.loco --hostname <vm-ip>
```

On the browser's machine, map `<vm-ip> moolakata.loco` in `/etc/hosts` (or use the address
itself) and open `https://moolakata.loco:37373`. The VM's firewall must let the port through
(for firewalld: `sudo firewall-cmd --add-port=37373/tcp`). Anyone on that network can reach the
server, so keep this to a private network and to seed data.

**Port 443 on the VM** needs root. Without it, forward 443 to the dev port. Any of these works:
a firewall redirect (`sudo firewall-cmd --add-forward-port=port=443:proto=tcp:toport=37373`), a
lower `net.ipv4.ip_unprivileged_port_start`, or a small TCP relay in a container running on
the host network. Such a relay can run from the MoolaKata image with its own Python, as root
inside the container. The relay must pass bytes through untouched: TLS still ends at the dev
server.

## More than one dev server on a machine

Several agent sessions on one VM can each run a dev server, and the first takes port 37373. A
forward to that port then reaches whichever server holds it, with its own users and passwords,
and the server you meant never sees the request. Give each server its own port and data:

```
web/dev.sh run --seed --stubs --port 37375 --data web/.dev-loco
```

To see what holds a port: `ss -ltnp | grep 37373` on Linux, `lsof -iTCP:37373 -sTCP:LISTEN` on
a Mac. When sign-in fails where it shouldn't, check first whether the server's log shows the
request at all (`moolakata.access POST /ui/api/session`).

## Trusting the certificate

Accepting the browser's warning is enough for testing. To stop the warning, copy the
certificate to the browser's machine (`scp dev@<vm>:MoolaKata/web/.dev/data/tls/self-signed.crt
moolakata-dev.crt`) and trust it:

- **macOS** (Safari and Chrome):
  `security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db
  moolakata-dev.crt`
- **Linux, Chrome or Chromium** (needs `libnss3-tools`):
  `certutil -d sql:$HOME/.pki/nssdb -A -t "P,," -n moolakata-dev -i moolakata-dev.crt`
- **Firefox** keeps its own store: accept the warning once and it remembers the exception.

Trust it again whenever the certificate is made again.

## Checking from the server's machine

An agent on the VM can test the same address the browser uses, without changing `/etc/hosts`:

```
curl -sk --resolve moolakata.loco:443:127.0.0.1 https://moolakata.loco/healthz
```

In Playwright, launch Chromium with `--host-resolver-rules=MAP moolakata.loco 127.0.0.1` and
open pages with `ignore_https_errors=True`.

## Bitcoin backends without a node

`web/dev.sh mocks` runs a fake Esplora, a fake Electrum server and a fake Bitcoin node on
local ports (3006, 50002 and 8332 by default; `--tls` gives the Electrum server a certificate,
whose fingerprint it prints), all answering for one small chain on the dev seed's wallet. In
Settings › Bitcoin, name one of them (a loopback node is named by an admin, so the egress
guard lets it through) and **Test**, then **Check now** on *Cold storage*. The tests run each
real backend against them (`test_mocks.py`); the live nodes are in `docs/test-plan.md`.

## The images for another architecture

`web/install/smoke.sh linux/arm64` builds the server's and the connector's images for arm64
under QEMU and runs them once (requirements S17.8.1). The build machine needs the emulator
registered once: `docker run --privileged --rm tonistiigi/binfmt --install arm64`. Under
emulation the server starts in about half a minute and reads a receipt in about a minute;
its speed on real hardware is the test plan's T7.
