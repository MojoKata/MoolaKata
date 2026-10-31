"""`moolakata-connector` (requirements S18.3, S18.4, S18.7.2, S18.11): `serve` runs the
connector and its page; `init` makes the vault and its words on a terminal, the other way to
the page's welcome; the rest talk to the running connector over its socket: `unlock`, `lock`,
`status`, `pair <code>`, `unpair`, `connect <connection id>`, `reset`."""

import argparse
import contextlib
import getpass
import io
import logging
import os
import secrets
import signal
import sys
from pathlib import Path

from . import VERSION, sock, words
from .vault import Vault, VaultError

DATA = Path(os.environ.get("MOOLAKATA_CONNECTOR_DATA", "/var/lib/moolakata-connector"))
SOCKET = Path(os.environ.get("MOOLAKATA_CONNECTOR_SOCKET", "/run/moolakata-connector/sock"))


SHEET = """MoolaKata Connector vault words

  vault:  {fingerprint}

{rows}

Keep them in the household's password manager. They are never stored: the vault
opens only with them, and `reset` is the only way on without them."""


def sheet(phrase: list[str], fingerprint: str) -> str:
    rows = "\n".join(f"  {i:>2}. {w}" for i, w in enumerate(phrase, 1))
    return SHEET.format(fingerprint=fingerprint, rows=rows)


def confirm_three(phrase: list[str], ask=input, say=print) -> bool:
    for _ in range(3):
        picks = sorted(secrets.SystemRandom().sample(range(12), 3))
        ok = all(
            (t := ask(f"word {i + 1}: ").strip().lower()) == phrase[i]
            or (len(t) >= 4 and phrase[i].startswith(t))
            for i in picks
        )
        if ok:
            return True
        say("That is not right. Check the words and try again.")
    return False


def open_tty() -> io.TextIOWrapper:
    """The controlling terminal, to read and write, opened as getpass opens it: a terminal
    can't seek, and open("/dev/tty", "r+") asks for a file that can."""
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    return io.TextIOWrapper(io.FileIO(fd, "w+"), encoding="utf-8")


class Terminal:
    """The words go to the terminal, never standard output, so no log keeps them (S18.3.1);
    without one, `init` and `reset` refuse."""

    def __init__(self) -> None:
        try:
            self.f = open_tty()  # held for the run
        except OSError:
            raise SystemExit(
                "refused: the words are shown on a terminal only; run it with -it"
            ) from None

    def say(self, text: str = "") -> None:
        self.f.write(text + "\n")
        self.f.flush()

    def ask(self, prompt: str) -> str:
        self.f.write(prompt)
        self.f.flush()
        return self.f.readline()


def cmd_init(args, tty=None) -> int:
    """The key is made in memory and the vault written only once three of its words come back
    (S18.3.1): a terminal closed meanwhile leaves no vault whose words nobody kept."""
    from .vault import fingerprint

    t = tty or Terminal()
    DATA.mkdir(parents=True, exist_ok=True)
    v = Vault(DATA / "vault.json")
    if v.exists():
        print(f"refused: {v.path} already exists; `reset` replaces it", file=sys.stderr)
        return 78
    key = secrets.token_bytes(16)
    phrase = words.to_words(key)
    t.say(sheet(phrase, fingerprint(key)))
    t.say("\nType back three of the words to show they are written down.")
    if not confirm_three(phrase, ask=t.ask, say=t.say):
        print("refused: the words were not confirmed; no vault was made", file=sys.stderr)
        return 78
    try:
        v.create(key)
    except VaultError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 78
    print(f"Made {v.fingerprint()}. Start the connector, then unlock it with the words.")
    return 0


def cmd_reset(args, tty=None) -> int:
    """Lost words (S18.3.4): new words made here and shown on the terminal, three typed back,
    then handed to the running connector, which replaces the vault and unpairs."""
    from .vault import fingerprint

    t = tty or Terminal()
    t.say("This deletes the vault: every credential in it, and the pairing with MoolaKata.")
    if t.ask("Type RESET to go on: ").strip() != "RESET":
        print("refused: not confirmed; nothing changed", file=sys.stderr)
        return 1
    key = secrets.token_bytes(16)
    phrase = words.to_words(key)
    t.say(sheet(phrase, fingerprint(key)))
    t.say("\nType back three of the words to show they are written down.")
    if not confirm_three(phrase, ask=t.ask, say=t.say):
        print("refused: the words were not confirmed; nothing changed", file=sys.stderr)
        return 1
    out = _ask({"command": "reset", "words": " ".join(phrase)})
    print(f"Made {out['fingerprint']}, unpaired. Pair again: every credential is entered anew.")
    if not out.get("told"):
        print(
            "MoolaKata couldn't be told: Unpair it there, in Settings › Connector.", file=sys.stderr
        )
    return 0


def cmd_unpair(args) -> int:
    """Forget the paired server and the credentials held for it (S18.4.4). A locked vault needs
    its words to be cleared now; without them it is cleared at its next unlock."""
    request: dict = {"command": "unpair"}
    if _ask({"command": "status"}).get("locked"):
        phrase = getpass.getpass(
            "the vault's 12 words, to delete its credentials now (Enter: at the next unlock): "
        )
        if phrase.strip():
            request["words"] = phrase
    out = _ask(request)
    if out.get("cleared"):
        print("unpaired; the credentials and keys held for that server are deleted")
    else:
        print("unpaired; the vault is locked, so its credentials go at its next unlock")
    return 0


def cmd_serve(args) -> int:
    from . import page
    from .core import Core

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        settings = page.Settings.from_env()
    except ValueError as e:
        print(f"refusing to start: {e}", file=sys.stderr)
        return 78
    core = Core(DATA)
    core.page = settings.address
    sock.serve(core, SOCKET)
    try:
        page.serve(core, settings, DATA)
    except OSError as e:
        print(f"refusing to start: its page can't listen on {settings.port}: {e}", file=sys.stderr)
        return 78
    where = settings.address or f"port {settings.port}"
    if not core.vault.exists():
        logging.info("MoolaKata Connector %s: no vault yet; its page makes one, %s", VERSION, where)
    else:
        logging.info(
            "MoolaKata Connector %s: locked, %s; its page is %s",
            VERSION,
            "paired" if core.pairing else "not paired",
            where,
        )
    signal.signal(signal.SIGTERM, lambda *_: core.stop())  # docker stop: a clean exit
    with contextlib.suppress(KeyboardInterrupt):
        core.run_forever()
    logging.info("stopped")
    return 0


def _ask(request: dict) -> dict:
    out = sock.ask(SOCKET, request)
    if "error" in out:
        print(f"refused: {out['error']}", file=sys.stderr)
        raise SystemExit(1)
    return out


def cmd_unlock(args) -> int:
    phrase = getpass.getpass("the vault's 12 words: ")
    try:
        words.from_words(phrase)
    except words.PhraseError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    _ask({"command": "unlock", "words": phrase})
    print("unlocked")
    return 0


def cmd_simple(what: str):
    def run(args) -> int:
        out = _ask({"command": what})
        if what == "status":
            for k, v in out.items():
                print(f"{k}: {v}")
        else:
            print(what + "ed" if what != "lock" else "locked")
        return 0

    return run


def cmd_pair(args) -> int:
    """Needs the vault unlocked: the sealing key the pairing makes goes into it (S18.4.5)."""
    out = _ask({"command": "pair", "code": args.code})
    print(f"paired: this connector's fingerprint is {out['fingerprint']}")
    print("Compare it with what MoolaKata shows under Settings › Connector.")
    return 0


def cmd_connect(args) -> int:
    """Credentials typed here, never through MoolaKata (S18.7.2): the host they go to is shown
    first, and they are filed only once the admin confirms it."""
    where = _ask({"command": "goes-to", "id": args.id})
    hosts = where["host"] or ", ".join(where["hosts"]) or "no host"
    print(f"{where['label']} ({where['driver']}): its credentials go to {hosts} only.")
    if input("Is that the institution's own host? [y/N] ").strip().lower() not in ("y", "yes"):
        print("nothing filed")
        return 1
    creds = {}
    print(f"credentials for {args.id} (empty name ends):")
    while True:
        name = input("field: ").strip()
        if not name:
            break
        creds[name] = getpass.getpass(f"{name}: ")
    _ask({"command": "connect", "id": args.id, "credentials": creds, "host": where["host"]})
    print(f"filed in the vault, bound to {hosts}")
    return 0


COMMANDS = {
    "serve": ("run the connector (the default)", lambda: cmd_serve, None),
    "init": ("make the vault and show its words", lambda: cmd_init, None),
    "unlock": ("unlock the vault with its words", lambda: cmd_unlock, None),
    "lock": ("lock the vault", lambda: cmd_simple("lock"), None),
    "status": ("what the connector is doing", lambda: cmd_simple("status"), None),
    "unpair": ("forget the paired server and its credentials", lambda: cmd_unpair, None),
    "reset": ("a new vault with new words (the old one is lost)", lambda: cmd_reset, None),
    "pair": ("pair with MoolaKata, with the code Settings shows", lambda: cmd_pair, "code"),
    "connect": ("type a Connection's credentials here", lambda: cmd_connect, "id"),
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moolakata-connector", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command")
    for name, (text, func, arg) in COMMANDS.items():
        cmd = sub.add_parser(name, help=text)
        if arg:
            cmd.add_argument(arg)
        cmd.set_defaults(func=func())
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return getattr(args, "func", cmd_serve)(args)


if __name__ == "__main__":
    sys.exit(main())
