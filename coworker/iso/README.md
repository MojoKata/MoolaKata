# Shared ISOs

One folder on the machine for every ISO its projects need, so each is downloaded once, checked
once, and deleted only when no project needs it any more. The folder is `$ISO_DIR`,
`~/claude-downloads/iso` unless a project's `local.env` says otherwise ([`../README.md`](../README.md)). Every project that follows
this protocol carries these scripts, unchanged, and any of them can manage the folder.

## What's in the folder

| File | What it is |
|---|---|
| `<iso>` | the ISO, complete and checked |
| `<iso>.sha256` | its SHA-256, as `<hash>  <iso>` (what `sha256sum -c` reads) |
| `<iso>.<project>` | an empty file: that project needs the ISO (a *claim*) |
| `<iso>.part` | a download in progress or stopped; `download.sh` resumes it |
| `<iso>.lock` | held while `download.sh` fetches that ISO, so a second one waits |
| `<iso>.bad` | a copy that failed its SHA-256 and was set aside; delete it once looked at |

A project name is letters, digits, `-` and `_`, and isn't `sha256`, `sha256sum`, `part`, `lock`
or `bad`.

## The scripts

    coworker/iso/download.sh ISO PROJECT ISO_URL SHA_URL
    coworker/iso/claim.sh    ISO PROJECT
    coworker/iso/release.sh  ISO PROJECT
    coworker/iso/list.sh     [--verify]

- **`download.sh`** fetches `ISO_URL` as `ISO.part`, checks its SHA-256 against `SHA_URL`, renames
  it into place and claims it for `PROJECT`. `SHA_URL` may be the one hash or a mirror's list that
  names the ISO (a `sha256sum.txt`); the hash is kept as `ISO.sha256`. Run the same command again
  after a failure and it resumes from the `.part`. An ISO already there and matching is only
  claimed; one that doesn't match is set aside as `.bad` and fetched again. A host the machine
  can't reach directly is fetched through a container (`curlimages/curl`), when Docker is there.
- **`claim.sh`** records that a project needs an ISO already there (or about to be).
- **`release.sh`** removes a project's claim; with the last claim gone it removes the ISO and its
  `.sha256`, `.part`, `.bad` and `.lock`.
- **`list.sh`** lists every ISO, there or claimed and still on its way, with its size and claims;
  `--verify` checks each against its SHA-256.

## Rules

- **Never** download an ISO into a project's own folder, and never delete one a project still
  claims: `release.sh` is the only way an ISO leaves.
- A project checks an ISO's SHA-256 before using it (`sha256sum -c --status <iso>.sha256` in the
  folder); `download.sh` does on every fetch.
- A project claims what it uses when it starts using it (its scripts can run `claim.sh` each time:
  it's idempotent), and releases it when it's done with it for good, not after each run.
- What a project claims, and why, is written in that project's own documents.

## Maintenance

- **What's there and who needs it:** `list.sh`. An ISO listed *unclaimed* is needed by no project:
  ask the machine's owner, then delete it (or `claim.sh` it for the project that does need it).
- **Check every ISO is intact:** `list.sh --verify`.
- **Leftovers:** a `.part` no download is running for can be resumed (`download.sh`, same
  arguments) or deleted; a `.bad` can be deleted once looked at; a `.lock` with no ISO is harmless.
- **Replacing an ISO with a newer release:** download the new one under its own name, move each
  project's claim to it as that project moves (`claim.sh` the new, `release.sh` the old), and the
  old one goes with its last claim.
- **An ISO a VM boots from** belongs to the VM's folder ([`../vm/README.md`](../vm/README.md)); a
  hard link to it here, claimed like any other, shares the space instead of keeping two copies.
