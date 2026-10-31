"""Dev mode (requirements S17.7): the whole server from a checkout, as the current user. It
relaxes the surroundings, never the rules: sessions, CSP, encryption and sharing behave as in
production."""

import hashlib
import logging
import os

from .. import clock
from ..config import Config, RefuseStart
from ..keys import master, phrase

log = logging.getLogger("moolakata.dev")


def prepare(config: Config) -> bytes:
    """A dev server makes its own master key on first run, without the recovery-phrase step,
    and keeps the phrase in a file beside its data (`web/.dev/phrase`): dev data is throwaway,
    and a server that asks for twelve words at every restart is no use to develop against.
    An installed server never does this (S15.4). Returns the key, for the unlock at start."""
    for d in (config.data_dir, config.backup_dir, config.mail_dir):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    phrase_file = config.data_dir.parent / "phrase"
    if not config.keyring_path.exists():
        # The generated mockup's build (a frozen clock): a key made from fixed words, so its
        # fingerprint comes out the same every time.
        key = hashlib.sha256(b"mockup").digest()[:16] if clock.frozen() else os.urandom(16)
        master.create_keyring(config, key)
        remember_phrase(config, key)
        log.info("dev: made a master key; its phrase is in %s", phrase_file)
        return key
    try:
        return phrase.from_words(phrase_file.read_text())
    except (OSError, phrase.PhraseError) as e:
        raise RefuseStart(
            f"dev: {config.keyring_path} exists but {phrase_file} doesn't hold its phrase ({e}); "
            f"remove {config.data_dir.parent} to start over"
        ) from None


def remember_phrase(config: Config, key: bytes) -> None:
    """The dev server's phrase file, written again after a rotation in Settings, so the
    restart that follows unlocks with the new phrase."""
    fd = os.open(config.data_dir.parent / "phrase", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(" ".join(phrase.to_words(key)) + "\n")


def after_start(server, seed: bool) -> None:
    if seed:
        from .seed import seed as run_seed

        run_seed(server)


def enable_stub_prices(server) -> None:
    """--stubs: the stub price source, first for every class it serves (S17.7)."""
    import json

    from sqlalchemy import false, select

    from .. import ids
    from ..prices import SOURCES
    from ..store.entities.prices import PriceSource

    cls = SOURCES["stub"]
    with server.db.tx(unscoped="dev mode: the seed") as s:
        row = s.scalars(
            select(PriceSource).where(PriceSource.name == "stub", PriceSource.deleted == false())
        ).first()
        if row is None:
            s.add(
                PriceSource(
                    id=ids.new_id("Src"),
                    name="stub",
                    enabled=True,
                    preference=json.dumps({c: 0 for c in sorted(cls.classes)}),
                )
            )
        else:
            row.enabled = True
