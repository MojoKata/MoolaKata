# Shared VMs

A VM that more than one project tests on (a Windows VM, say) is kept in one place on the machine,
described once, and used by one project at a time. The place is `$VM_DIR`, `~/vm` unless a
project's `local.env` says otherwise ([`../README.md`](../README.md)). Every project that follows
this protocol carries these scripts, unchanged. A VM only one project uses stays in that project's
own folders; this is for the shared ones.

## What's in the folder

| File | What it is |
|---|---|
| `<vm>/` | the VM's folder, or a link to it: its disks, its `README.md` and its `vm.env` |
| `<vm>/README.md` | what the VM is, how it was built, how to rebuild it, and what it keeps for everyone |
| `<vm>/vm.env` | how a project reaches it (below) |
| `<vm>.<project>` | an empty file: that project needs the VM (a *claim*) |
| `<vm>.lock` | held while a project uses the VM; while held, it names the holder |

A VM's name and a project's name are letters, digits, `-` and `_` (a VM's may have a `.`); a
project isn't named `lock`.

## `vm.env`

Shell assignments, read by every project; paths are relative to the VM's folder.

| Setting | What it is |
|---|---|
| `VM_OS` | what runs in it, e.g. `Windows 10 Pro 22H2` |
| `VM_CONTAINER` | the Docker container that runs it, if one does (`docker start` starts it) |
| `VM_SSH_HOST` | where its SSH server is reached (default `127.0.0.1`) |
| `VM_SSH_PORT` | that port (required) |
| `VM_SSH_USER` | the account a project's scripts sign in as (required) |
| `VM_SSH_KEY` | the private key for it (required) |
| `VM_KNOWN_HOSTS` | the VM's host key, as `ssh` keeps it (default `known_hosts`) |

`env.sh VM` prints them, with `VM_HOME` (the VM's folder) and the paths made absolute, for a
script to `eval`. The account, password, key and ports are the VM's, not a project's: every
project uses the same ones, and a rebuild keeps them.

## The scripts

    coworker/vm/claim.sh   VM PROJECT
    coworker/vm/release.sh VM PROJECT
    coworker/vm/lock.sh    VM PROJECT [--no-wait] -- COMMAND [ARG...]
    coworker/vm/env.sh     VM
    coworker/vm/list.sh

- **`claim.sh`** records that a project needs the VM. A script can run it each time: it's
  idempotent.
- **`release.sh`** removes a project's claim. It never deletes a VM: with the last claim gone it
  says so, and the machine's owner decides.
- **`lock.sh`** runs a command holding the VM's lock. A second project's run waits, after saying
  whose run it waits for (`--no-wait`: exits 75 instead). A script can re-run itself under it:

      [ -n "${COWORKER_VM_LOCKED:-}" ] || exec coworker/vm/lock.sh win10 myproject -- "$0" "$@"

- **`env.sh`** prints how to reach the VM (above).
- **`list.sh`** lists each VM, what it is, its claims, and who holds it now.

## Rules

- **One project at a time.** Hold the lock for the whole use, from starting the VM to the last
  file copied back. The projects share its ports, its desktop and its signed-in session.
- **Leave it as you found it.** A setting changed for a run (the screen's size, say) is put back
  or not saved. A project's files go in folders named after the project (on Windows,
  `C:\Users\Public\<project>-…`). What a project installs, it uninstalls, unless the VM's
  `README.md` lists it as kept for everyone.
- **Starting is fine; stopping is the owner's.** A project starts the VM if it isn't running and
  leaves it running.
- **The VM itself is everyone's.** Its account, password, key, ports, operating-system version and
  update policy change only by the machine's owner, through its `README.md`, and a rebuild keeps
  what `vm.env` says.
- What a project claims, and why, is written in that project's own documents.

## Maintenance

- **What's there, who needs it, who's using it:** `list.sh`. A VM listed *unclaimed* is needed by
  no project: ask the machine's owner before deleting it.
- **A held lock with no run behind it** can't happen: the lock is a `flock` on `<vm>.lock`, and it
  goes with the process that holds it. The file's text is only the last holder's name.
- **Adding a VM:** its folder (or a link to it) in `$VM_DIR`, with `README.md` and `vm.env`; then
  each project that needs it claims it.
- **An ISO it boots from** stays in its folder; a hard link in the ISO folder, claimed there like
  any other, shares the space ([`../iso/README.md`](../iso/README.md)).
