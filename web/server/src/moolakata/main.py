"""The `moolakata` command."""

import argparse
import asyncio
import datetime as dt
import logging
import os
import sys
from pathlib import Path

from . import paths
from .config import CONFIG_ENV, DEFAULT_CONFIG, Config, RefuseStart, configured

EX_CONFIG = 78
log = logging.getLogger("moolakata")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "httpcore", "hpack", "hypercorn.access", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def dev_config(
    port: int,
    stubs: bool,
    peer: bool,
    base: Path | None = None,
    listen: str = "127.0.0.1",
    hostnames: tuple[str, ...] = (),
) -> Config:
    """Dev mode (requirements S17.7): the whole server from a checkout, as the current user."""
    base = base or paths.WEB / (".dev-peer" if peer else ".dev")
    return Config(
        name="dev-peer" if peer else "dev",
        mode="tls",
        host=listen,
        port=port,
        cert_names=hostnames,
        data_dir=base / "data",
        backup_dir=base / "backups",
        mail_folder=base / "mail",
        socket_path=base / "run" / "sock",
        dev=True,
        stubs=stubs,
    )


def refuse_dev(config: Config) -> None:
    if os.geteuid() == 0:
        raise RefuseStart("dev mode does not run as root")
    # Only from a checkout (S17.6): the image carries no dev.sh, so its seed users and their
    # fixed password never run where a household's server does.
    from . import paths

    if not (paths.WEB / "dev.sh").exists():
        raise RefuseStart("dev mode runs only from a checkout of the repository, not the image")
    installed = Path("/var/lib/moolakata")
    if config.data_dir.resolve().is_relative_to(installed):
        raise RefuseStart("dev mode does not run on an installed server's data directory")


def serve(config: Config, seed: bool = False) -> int:
    from .runtime import RESTART, start

    code = asyncio.run(start(config, seed=seed))
    if code == RESTART:
        # The server asked to start again (a re-encryption, S15.7.2): the same command, in
        # this same process, so no restart policy is relied on; it starts locked. A dev
        # server's seed is not planted twice.
        import atexit

        atexit._run_exitfuncs()  # what an exit would flush (logs, coverage), as exec skips it
        args = [a for a in sys.orig_argv if a != "--seed"]
        os.execv(sys.executable, args)  # noqa: S606 - this very command, again
    return code


def cmd_serve(args) -> int:
    return serve(configured(args.config))


def cmd_dev(args) -> int:
    port = args.port or (37374 if args.peer else 37373)
    config = dev_config(
        port,
        args.stubs,
        args.peer,
        Path(args.data) if args.data else None,
        listen=args.listen,
        hostnames=tuple(args.hostname),
    )
    refuse_dev(config)
    if args.frozen:
        from . import clock, ids

        clock.fix(dt.datetime.fromisoformat(args.frozen))
        ids.repeatable()
        # The mockup shows a host without Landlock, wherever it is built: its note and alert.
        from . import parsing

        parsing.PINNED = False
    return serve(config, seed=args.seed)


def cmd_health(args) -> int:
    """The image's health check: is this container's server alive, answering /healthz at
    all (S13.6)? It prints the answer: `ok`, or `starting`, `re-encrypting`, `locked` or
    `uninitialised`, all alive, so an orchestrator waiting for healthy containers lets the
    server wait for its phrase. Whether it is ready is /healthz's own answer, for a monitor."""
    import httpx

    config = configured(args.config)
    scheme = "https" if config.mode == "tls" else "http"
    try:
        # Loopback to this container's own listener; its certificate may be self-signed.
        r = httpx.get(f"{scheme}://127.0.0.1:{config.port}/healthz", verify=False, timeout=4)  # noqa: S501
    except httpx.HTTPError as e:
        print(f"unhealthy: {e}", file=sys.stderr)
        return 1
    try:
        status = r.json()["status"]
    except ValueError, KeyError, TypeError:
        print(f"unhealthy: /healthz answered {r.status_code}", file=sys.stderr)
        return 1
    print(status)
    return 0


def cmd_openapi(args) -> int:
    from .contract import openapi_json

    sys.stdout.write(openapi_json())
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moolakata", description="MoolaKata server")
    p.add_argument(
        "--config",
        help=f"the config file (default: the TOML in {CONFIG_ENV}, else {DEFAULT_CONFIG})",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="run the server (the default)")
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("dev", help="run the server from a checkout, for development")
    d.add_argument("--seed", action="store_true", help="seed users and a year of data")
    d.add_argument("--stubs", action="store_true", help="use the stub price source")
    d.add_argument("--peer", action="store_true", help="a second server, for links")
    d.add_argument("--port", type=int)
    d.add_argument("--data", help="where dev mode keeps its data (default web/.dev)")
    d.add_argument(
        "--listen",
        default="127.0.0.1",
        metavar="ADDR",
        help="the address to listen on (default 127.0.0.1; 0.0.0.0 for every interface)",
    )
    d.add_argument(
        "--hostname",
        action="append",
        default=[],
        metavar="NAME",
        help="a name or address the certificate also covers, such as moolakata.loco (repeatable)",
    )
    d.add_argument(
        "--frozen",
        metavar="WHEN",
        help="a fixed clock and repeatable ids, for the generated mockup (an ISO time with zone)",
    )
    d.set_defaults(func=cmd_dev)

    h = sub.add_parser("health", help="check that the running server answers")
    h.set_defaults(func=cmd_health)

    o = sub.add_parser("openapi", help="print the API's OpenAPI document")
    o.set_defaults(func=cmd_openapi)

    from .keys import cli as keys_cli
    from .store import cli as db_cli

    keys_cli.register(sub)
    db_cli.register(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    setup_logging(args.verbose)
    func = getattr(args, "func", cmd_serve)
    try:
        return func(args)
    except RefuseStart as e:
        # A one-off command (keys, db) refuses; only the server "starts".
        starting = args.command in (None, "serve", "dev")
        print(f"{'refusing to start' if starting else 'refused'}: {e}", file=sys.stderr)
        return EX_CONFIG
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
