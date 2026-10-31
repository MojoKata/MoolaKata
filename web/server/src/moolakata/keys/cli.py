"""`moolakata keys …` (requirements S15.4, S15.6, S15.7): run on the host as one-off
containers of the same image, or, for `unlock` and `break-glass`, against the server running on
this host, over its Unix socket (host.py). The master key is the recovery phrase: every command
that needs it asks for it, with echo off, and none writes it anywhere. No command shows a
phrase: a key is made and rotated in the browser (S15.4.4, S15.7.1), so no terminal, and no log
Docker keeps of one, ever holds a new phrase. What a command did is queued for Activity
(`maintenance.queue_host_event`), since a one-off container cannot open the database without
the phrase."""

import getpass
from collections.abc import Callable

from ..config import Config, RefuseStart, configured
from . import master, phrase

SERVER_UID = 10001  # the image's own account, which owns the data directory
Ask = Callable[[str], str]
Say = Callable[[str], None]


def _say(text: str) -> None:
    print(text)


def _hidden(prompt: str) -> str:
    return getpass.getpass(prompt)


def read_phrase(ask: Ask = _hidden, prompt: str = "recovery phrase (12 words): ") -> bytes:
    """The master key from a typed phrase; a phrase that isn't one refuses the command."""
    try:
        return phrase.from_words(ask(prompt))
    except phrase.PhraseError as e:
        raise RefuseStart(f"not a valid phrase: {e}") from None


def fingerprint_of(config: Config) -> str:
    """The fingerprint of the master key the keyring was wrapped under; no phrase needed."""
    return master.fingerprint(master.read_keyring(config.keyring_path).master_id)


def verify(
    config: Config,
    ask: Ask = _hidden,
    say: Say = _say,
    record: Callable[[str, bool], None] | None = None,
) -> bool:
    """Whether a typed phrase unwraps this server's keyring, changing nothing (S15.6.5)."""
    ring = master.read_keyring(config.keyring_path)
    try:
        typed = phrase.from_words(ask("recovery phrase (12 words): "))
    except phrase.PhraseError as e:
        say(f"not a valid phrase: {e}")
        return False
    try:
        master.unwrap(typed, ring)
        ok = True
    except ValueError:
        ok = False
    say(
        f"match: the phrase is the key {master.fingerprint(ring.master_id)}"
        if ok
        else f"no match: these words are {master.fingerprint(typed)}, not this server's key "
        f"{master.fingerprint(ring.master_id)}"
    )
    if record:
        record(ring.master_id, ok)
    return ok


CHOICES = {"r": "reencrypt", "d": "delete", "l": "leave", "": "reencrypt"}


def ask_copies(found: list[dict], ask: Ask, say: Say, all_: str | None = None) -> dict[str, str]:
    """Each copy's choice (S15.7.1, S15.7.2): re-encrypt (the default), delete or leave;
    `all_` answers for every copy (`--reencrypt-all`, `--delete-old`, `--leave-all`)."""
    if not found:
        return {}
    out = {}
    say(f"\n{len(found)} copies on this host (the host's own snapshots and backups are not here):")
    for c in found:
        how = {
            "current": "can be re-encrypted",
            "phrase": "under an earlier data key, this phrase: can be re-encrypted",
            "previous": f"under an earlier phrase ({c.get('masterKey')}): left or deleted",
            "unknown": "its keyring cannot be read",
        }[c["opens"]]
        line = f"  {c['name']} ({c['kind']}, {c['made'][:10]}, {c['bytes'] // 1048576} MB): {how}"
        if all_ is not None:
            out[c["name"]] = all_
            continue
        say(line)
        answer = ask("    [R]e-encrypt, [d]elete or [l]eave (R): ").strip().lower()[:1]
        out[c["name"]] = CHOICES.get(answer, "reencrypt")
    return out


def reencrypt_offline(
    config: Config,
    ask: Ask = input,
    say: Say = _say,
    ask_hidden: Ask = _hidden,
    all_copies: str | None = None,
) -> dict:
    """`moolakata keys reencrypt`, the server stopped (S15.7.2): the phrase typed, each copy's
    choice, and the journal run to its end at once, the data directory locked."""
    from ..store import copies as copies_
    from ..store import reencrypt

    key = read_phrase(ask_hidden, "recovery phrase (12 words): ")
    try:
        current = master.unlock_keys(config, key)
    except master.WrongPhrase as e:
        raise RefuseStart(str(e)) from None
    choices = (
        {}
        if reencrypt.journal(config) is not None
        else ask_copies(
            [
                {
                    "name": c.name,
                    "kind": c.kind,
                    "made": c.made.isoformat(),
                    "bytes": c.bytes,
                    "masterKey": master.fingerprint(c.ring.master_id) if c.ring else None,
                    "opens": copies_.opens_with(c, current),
                }
                for c in copies_.copies(config)
            ],
            ask,
            say,
            all_copies,
        )
    )
    done = reencrypt.at_once(config, key, choices, "host")
    say("Re-encrypted under a new data key.")
    for name in done.get("receiptsSetAside") or []:
        say(f"  receipt file set aside, opening under neither key: {name}")
    for name, outcome in (done.get("copies") or {}).items():
        say(f"  {name}: {outcome}")
    return done


def break_glass(config: Config, say: Say = _say) -> int:
    """`moolakata keys break-glass` (S15.5.2): a code from the running, unlocked server, over
    its socket, to type into Settings › Key storage › Rotate in place of a lost phrase. The
    rotation's new phrase is then shown in the browser, never here."""
    from .. import host

    try:
        with host.client(config, timeout=30) as c:
            r = c.post("/host/keys/break-glass")
    except host.NotRunning as e:
        say(f"refused: {e}")
        return 1
    if r.status_code != 200:
        say(f"refused: {host.detail(r)}")
        return 1
    out = r.json()
    say(
        f"{out['code']}\n\nType it into Settings › Key storage › Rotate, in place of the "
        f"current phrase, before {out['expiresAt'][11:16]} UTC. It works once, for 15 "
        "minutes; every admin is told it was asked for."
    )
    return 0


def unlock(config: Config, ask: Ask = _hidden, say: Say = _say) -> int:
    """`moolakata keys unlock` (S15.4.2): the phrase handed to the server running on this
    host over its Unix socket, never the network, to the same unlock as the locked screen's."""
    from .. import host

    words = ask("recovery phrase (12 words): ")
    try:
        phrase.from_words(words)
    except phrase.PhraseError as e:
        say(f"refused: not a valid phrase: {e}")
        return 1
    try:
        with host.client(config, timeout=300) as c:
            r = c.post("/host/unlock", json={"phrase": words})
    except host.NotRunning as e:
        say(f"refused: {e}")
        return 1
    if r.status_code != 200:
        say(f"refused: {host.detail(r)}")
        return 1
    state = r.json()
    if state.get("reencrypting"):
        # A re-encryption runs before the server serves (S15.7.2): followed here to its end.
        say("the phrase opened the keyring: re-encrypting under a new data key first")
        import time

        seen = None
        while state.get("reencrypting"):
            p = state["reencrypting"]
            now = (p.get("stage"), p.get("done") // 100 if p.get("total") else None)
            if now != seen:
                seen = now
                total = f" {p['done']} of {p['total']}" if p.get("total") else ""
                say(f"  {p.get('stage')}{total}")
            time.sleep(2)
            with host.client(config, timeout=30) as c:
                state = c.get("/host/unlock").json()
        if state.get("locked"):
            say(f"refused: {state.get('error') or 'the re-encryption did not finish'}")
            return 1
    say(f"unlocked: {state.get('fingerprint', '')}")
    return 0


def register(sub) -> None:
    k = sub.add_parser("keys", help="the master key: its recovery phrase and the keyring (S15)")
    ks = k.add_subparsers(dest="keys_command", required=True)
    ks.add_parser("fingerprint", help="print the fingerprint of the key in use").set_defaults(
        func=_fingerprint_cmd
    )
    ks.add_parser("verify", help="check a typed phrase against the keyring").set_defaults(
        func=_verify_cmd
    )
    e = ks.add_parser(
        "reencrypt", help="a new data key for everything, with the server stopped (S15.7.2)"
    )
    h = e.add_mutually_exclusive_group()
    h.add_argument("--reencrypt-all", action="store_true", help="re-encrypt every copy on the host")
    h.add_argument("--delete-old", action="store_true", help="delete every copy on the host")
    h.add_argument("--leave-all", action="store_true", help="leave every copy as it is")
    e.set_defaults(func=_reencrypt_cmd)
    ks.add_parser("unlock", help="unlock the server running on this host").set_defaults(
        func=_unlock_cmd
    )
    ks.add_parser(
        "break-glass",
        help="a code to rotate a lost phrase in Settings › Key storage (the running server)",
    ).set_defaults(func=_break_glass_cmd)


# Every `keys` command is queued for Activity (S15.4.7), whichever way it ends.


def _fingerprint_cmd(args) -> int:
    from ..store.maintenance import queue_host_event

    config = configured(args.config)
    fp = fingerprint_of(config)
    print(fp)
    queue_host_event(config, "key.fingerprint-shown", {"fingerprint": fp})
    return 0


def _unlock_cmd(args) -> int:
    from ..store.maintenance import queue_host_event

    config = configured(args.config)
    code = unlock(config)
    if code != 0:  # the server records an unlock itself, however it came
        queue_host_event(config, "key.unlock-refused", {})
    return code


def _verify_cmd(args) -> int:
    from ..store.maintenance import queue_host_event

    config = configured(args.config)
    ok = verify(
        config,
        record=lambda kid, ok: queue_host_event(
            config,
            "key.verified" if ok else "key.verify-failed",
            {"fingerprint": master.fingerprint(kid)},
        ),
    )
    return 0 if ok else 1


def _reencrypt_cmd(args) -> int:
    from ..store.maintenance import queue_host_event

    config = configured(args.config)
    flags = {"reencrypt": args.reencrypt_all, "delete": args.delete_old, "leave": args.leave_all}
    done = reencrypt_offline(config, all_copies=next((k for k, on in flags.items() if on), None))
    queue_host_event(
        config,
        "keys.reencrypted",
        {
            "why": "host",
            "receiptsSetAside": len(done.get("receiptsSetAside") or []),
            "secretsSetAside": len(done.get("secretsSetAside") or []),
            "copies": done.get("copies") or {},
        },
    )
    return 0


def _break_glass_cmd(args) -> int:
    return break_glass(configured(args.config))  # the server records it in Activity itself
