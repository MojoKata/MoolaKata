from pathlib import Path

import pytest

from moolakata.config import CONFIG_ENV, DEFAULT_CONFIG, RefuseStart, configured, load, parse
from moolakata.main import main

BASE = {
    "server": {"name": "home", "mode": "proxy", "trusted_proxies": ["10.0.0.2"]},
    "paths": {"data": "/var/lib/moolakata", "backups": "/var/backups/moolakata"},
}


def test_parses_a_full_config():
    c = parse(BASE, "test")
    assert c.name == "home"
    assert c.mode == "proxy"
    assert c.port == 37373
    assert str(c.trusted_proxies[0]) == "10.0.0.2"
    assert c.db_path == Path("/var/lib/moolakata/moolakata.db")
    assert c.mail_dir == Path("/var/lib/moolakata/mail")
    assert c.keyring_path == Path("/var/lib/moolakata/keyring")


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"server": {"mode": "open"}}, "server.mode"),
        ({"server": {"port": 0}}, "server.port"),
        ({"server": {"trusted_proxies": ["nope"]}}, "trusted_proxies"),
        ({"server": {"trusted_proxies": [10]}}, "not an address"),
        ({"server": {"trusted_proxies": "10.0.0.2"}}, "a list of addresses"),
        # S13.3: the proxy's own address, never a range anything else could share.
        ({"server": {"trusted_proxies": ["172.16.0.0/12"]}}, "is a range"),
        ({"server": {"trusted_proxies": ["10.0.0.2/31"]}}, "is a range"),
        ({"server": {"trusted_proxies": ["fd00:37::/64"]}}, "is a range"),
        ({"keys": {"master": "/etc/moolakata/master.key"}}, "is not used"),
        ({"paths": {"data": "/d", "backups": "/d/backups"}}, "inside the data directory"),
        ({"paths": {"data": "relative", "backups": "/b"}}, "absolute"),
        ({"tls": {"cert": "/a.crt"}}, "both cert and key"),
        ({"tls": {"names": "money.lan"}}, "list of host names"),
        ({"extra": {}}, "unknown section"),
        ({"server": {"trusted_proxy": ["10.0.0.1"]}}, "unknown key server.trusted_proxy"),
    ],
)
def test_refuses_what_an_operator_must_fix(change, reason):
    raw = {k: dict(v) for k, v in BASE.items()}
    for k, v in change.items():
        raw.setdefault(k, {}).update(v)
    with pytest.raises(RefuseStart, match=reason):
        parse(raw, "test")


def test_missing_or_broken_file_refuses(tmp_path):
    with pytest.raises(RefuseStart, match="does not exist"):
        load(tmp_path / "none.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("[server\n")
    with pytest.raises(RefuseStart, match="not valid TOML"):
        load(bad)


def test_the_config_comes_from_the_file_named_then_the_environment_then_the_default(tmp_path):
    """S17.8: --config names a file; without it the same TOML may be given in MOOLAKATA_CONFIG
    (TrueNAS's Install via YAML has no file to mount); else /etc/moolakata.toml."""
    text = (
        '[server]\nname = "from-env"\nmode = "tls"\n[paths]\ndata = "/d"\nbackups = "/b"\n'
        '[tls]\nnames = ["192.168.1.20"]\n'
    )
    c = configured(None, {CONFIG_ENV: text})
    assert (c.name, c.mode, c.data_dir, c.cert_names) == (
        "from-env",
        "tls",
        Path("/d"),
        ("192.168.1.20",),
    )
    named = tmp_path / "named.toml"
    named.write_text(text.replace("from-env", "from-file"))
    assert configured(str(named), {CONFIG_ENV: text}).name == "from-file"
    with pytest.raises(RefuseStart, match=f"config file {DEFAULT_CONFIG} does not exist"):
        configured(None, {CONFIG_ENV: "  "})
    with pytest.raises(RefuseStart, match=f"{CONFIG_ENV} is not valid TOML"):
        configured(None, {CONFIG_ENV: "[server"})
    with pytest.raises(RefuseStart, match=f"{CONFIG_ENV}: unknown key server.colour"):
        configured(None, {CONFIG_ENV: text.replace('name = "from-env"', 'colour = "red"')})


def test_a_command_reads_its_config_from_the_environment(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    monkeypatch.setenv(
        CONFIG_ENV,
        f'[server]\nmode = "proxy"\n[paths]\ndata = "{data}"\nbackups = "{tmp_path}/b"\n',
    )
    assert main(["keys", "fingerprint"]) == 78
    assert str(data / "keyring") in capsys.readouterr().err  # the paths it was given


def test_refused_start_exits_78_with_one_line(tmp_path, capsys):
    code = main(["--config", str(tmp_path / "none.toml"), "serve"])
    assert code == 78
    err = capsys.readouterr().err.strip().splitlines()
    assert err[-1].startswith("refusing to start: ")
    assert main(["--config", str(tmp_path / "none.toml"), "keys", "fingerprint"]) == 78
    assert capsys.readouterr().err.strip().splitlines()[-1].startswith("refused: ")


def test_a_connection_is_not_closed_after_a_thousand_requests(tmp_path):
    """Over HTTP/2 everything a browser asks travels on one connection; Hypercorn's default
    cap of 1,000 requests closed it under the live stream and stranded requests in flight."""
    from moolakata.listener import hypercorn_config
    from moolakata.main import dev_config

    hc = hypercorn_config(dev_config(37373, stubs=False, peer=False, base=tmp_path))
    assert hc.keep_alive_max_requests >= 1_000_000


def test_dev_hostnames_join_the_self_signed_certificate_which_is_remade_to_cover_them(tmp_path):
    """Testing from another machine (web/dev.md): the certificate names what the browser uses."""
    from moolakata.listener import _covers, hypercorn_config
    from moolakata.main import dev_config

    hypercorn_config(dev_config(37373, stubs=False, peer=False, base=tmp_path))
    cert = tmp_path / "data" / "tls" / "self-signed.crt"
    assert _covers(cert) == {"localhost", "127.0.0.1"}
    first = cert.read_bytes()

    config = dev_config(
        37373, False, False, tmp_path, listen="0.0.0.0", hostnames=("moolakata.loco", "10.0.0.5")
    )
    hc = hypercorn_config(config)
    assert hc.bind == ["0.0.0.0:37373"]
    assert _covers(cert) == {"moolakata.loco", "10.0.0.5", "localhost", "127.0.0.1"}
    second = cert.read_bytes()
    assert second != first

    hypercorn_config(dev_config(37373, stubs=False, peer=False, base=tmp_path))
    assert cert.read_bytes() == second  # a certificate that covers more is kept


def _pair(directory):
    from cryptography import x509

    cert = x509.load_pem_x509_certificate((directory / "self-signed.crt").read_bytes())
    return cert, (directory / "self-signed.key").read_bytes()


def _loads(directory) -> bool:
    import ssl

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(directory / "self-signed.crt", directory / "self-signed.key")
    return True


def test_the_self_signed_certificate_is_renewed_before_it_expires_with_the_same_key(tmp_path):
    """S13.3, S11.1.3: within 30 days of its end the certificate is signed again, and so is one
    whose names change, both with the key peers and the connector pin; one still good is
    kept as it is."""
    import datetime as dt

    from moolakata import clock
    from moolakata.listener import self_signed

    self_signed(tmp_path, ["home", "localhost"])
    cert, key = _pair(tmp_path)
    try:
        clock.fix(cert.not_valid_after_utc - dt.timedelta(days=31))
        self_signed(tmp_path, ["home", "localhost"])
        assert _pair(tmp_path) == (cert, key), "a month and a day left: kept"
        clock.fix(cert.not_valid_after_utc - dt.timedelta(days=29))
        self_signed(tmp_path, ["home", "localhost"])
        renewed, same = _pair(tmp_path)
        assert same == key and renewed != cert
        assert renewed.not_valid_after_utc > cert.not_valid_after_utc
        clock.fix(cert.not_valid_after_utc + dt.timedelta(days=400))
        self_signed(tmp_path, ["home", "localhost"])
        assert _pair(tmp_path)[1] == key, "expired long ago: still the same key"
    finally:
        clock.fix(None)
    self_signed(tmp_path, ["home", "localhost", "money.lan"])
    assert _pair(tmp_path)[1] == key, "a new name: the same key"
    assert _loads(tmp_path)


def test_a_half_written_or_damaged_self_signed_pair_is_made_whole_again(tmp_path):
    """S13.3, S13.6: a key that doesn't match the certificate beside it (a stop between the two
    writes) has the certificate signed again for it; a key that can't be read is made anew;
    neither is kept to refuse every later start."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from moolakata.listener import self_signed

    self_signed(tmp_path, ["home"])
    cert, _ = _pair(tmp_path)
    other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (tmp_path / "self-signed.key").write_bytes(other)
    self_signed(tmp_path, ["home"])
    assert _pair(tmp_path)[1] == other and _pair(tmp_path)[0] != cert
    assert _loads(tmp_path)
    (tmp_path / "self-signed.key").write_bytes(b"half a key")
    self_signed(tmp_path, ["home"])
    assert _pair(tmp_path)[1] != b"half a key" and _loads(tmp_path)
    (tmp_path / "self-signed.crt").write_bytes(b"half a certificate")
    self_signed(tmp_path, ["home"])
    assert _loads(tmp_path)
    assert (tmp_path / "self-signed.key").stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["self-signed.crt", "self-signed.key"]


def _served(ctx) -> bytes:
    """The certificate a TLS context presents to a new connection, over a handshake in memory."""
    import ssl

    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.check_hostname, client.verify_mode = False, ssl.CERT_NONE
    c_in, c_out, s_in, s_out = (ssl.MemoryBIO() for _ in range(4))
    c = client.wrap_bio(c_in, c_out, server_hostname="home")
    s = ctx.wrap_bio(s_in, s_out, server_side=True)
    done: set = set()
    for _ in range(10):
        for side in (c, s):
            try:
                side.do_handshake()
                done.add(side)
            except ssl.SSLWantReadError:
                pass
        s_in.write(c_out.read())
        c_in.write(s_out.read())
        if len(done) == 2:
            break
    return c.getpeercert(binary_form=True)


def test_the_daily_task_renews_the_certificate_into_the_running_listener(server):
    """S13.3: the certificate task signs a self-signed certificate near its end again, with the
    same key, and the running listener's TLS context serves the new one to the next
    connection, with no restart; one still good is left alone."""
    import dataclasses
    import datetime as dt
    import threading

    from cryptography.hazmat.primitives.serialization import Encoding

    from moolakata import clock, listener, runtime
    from moolakata.tasks import ProviderLimits, TaskContext

    server.config = dataclasses.replace(server.config, mode="tls", host="127.0.0.1")
    ctx = listener.hypercorn_config(server.config).create_ssl_context()
    cert, key = _pair(server.config.tls_dir)
    assert _served(ctx) == cert.public_bytes(Encoding.DER)
    runtime.register_tasks(server)
    task = server.tasks._tasks["certificate"]
    run = lambda: task.run(TaskContext(task.name, threading.Event(), ProviderLimits()))  # noqa: E731
    try:
        clock.fix(cert.not_valid_after_utc - dt.timedelta(days=31))
        run()
        assert _pair(server.config.tls_dir) == (cert, key)
        clock.fix(cert.not_valid_after_utc - dt.timedelta(days=29))
        run()
    finally:
        clock.fix(None)
    renewed, same = _pair(server.config.tls_dir)
    assert same == key and renewed.not_valid_after_utc > cert.not_valid_after_utc
    assert _served(ctx) == renewed.public_bytes(Encoding.DER)


def test_tls_names_join_the_self_signed_certificate(tmp_path):
    """tls mode on a local network: the certificate also names what the browser uses."""
    import dataclasses

    from moolakata.listener import _covers, hypercorn_config

    raw = {k: dict(v) for k, v in BASE.items()}
    raw["server"]["mode"] = "tls"
    raw["paths"] = {"data": str(tmp_path / "data"), "backups": str(tmp_path / "backups")}
    raw["tls"] = {"names": ["money.lan", "192.168.1.20"]}
    config = parse(raw, "test")
    assert config.cert_names == ("money.lan", "192.168.1.20")
    hypercorn_config(dataclasses.replace(config, host="127.0.0.1"))
    cert = tmp_path / "data" / "tls" / "self-signed.crt"
    assert _covers(cert) == {"money.lan", "192.168.1.20", "home", "localhost"}


def test_dev_mode_runs_only_from_a_checkout(tmp_path, monkeypatch):
    # S17.7: the image carries no dev.sh, and leaves dev mode's code out.
    from moolakata import main as entry
    from moolakata import paths
    from moolakata.config import Config

    config = Config(
        name="t", mode="proxy", data_dir=tmp_path / "data", backup_dir=tmp_path / "b", dev=True
    )
    entry.refuse_dev(config)  # this checkout
    monkeypatch.setattr(paths, "WEB", tmp_path)
    with pytest.raises(RefuseStart, match="only from a checkout"):
        entry.refuse_dev(config)
    dockerfile = (paths.ROOT / "web" / "install" / "Dockerfile").read_text()
    assert "rm -rf src/moolakata/dev" in dockerfile


def test_every_key_the_file_takes_is_in_the_requirements_and_the_example():
    """S13.3 lists the configuration's keys, as an unknown one refuses the start (S13.6), and
    the example file shows each."""
    from moolakata import paths
    from moolakata.config import KEYS

    req = (paths.ROOT / "docs" / "requirements" / "S13-architecture.md").read_text()
    example = (paths.ROOT / "web" / "install" / "moolakata.toml").read_text()
    for section, keys in KEYS.items():
        for key in keys:
            assert f"`[{section}] {key}`" in req, (section, key)
            assert f"{key} =" in example, (section, key)


def _tls(config, **change):
    import dataclasses

    return dataclasses.replace(config, mode="tls", **change)


def test_a_certificate_with_no_names_or_none_readable_covers_nothing(tmp_path):
    """Read once the pair has loaded (_fits): a damaged one, or one naming nothing, covers no
    name, so the certificate is signed again."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding
    from test_certs import _cert

    from moolakata.listener import _covers

    (tmp_path / "bad.crt").write_text("not a certificate")
    assert _covers(tmp_path / "bad.crt") == set()
    key = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "bare.crt").write_bytes(_cert("x", "x", key, key).public_bytes(Encoding.PEM))
    assert _covers(tmp_path / "bare.crt") == set()


def test_renewal_leaves_a_proxys_and_an_admins_certificate_alone(config, tmp_path, monkeypatch):
    """S13.3: behind a proxy there is no certificate of the server's; one named in [tls] is the
    admin's to renew; a self-signed one renewed before the listener runs is only written."""
    from moolakata import listener

    assert not listener.renew(config)
    named = _tls(config, tls_cert=tmp_path / "a.crt", tls_key=tmp_path / "a.key")
    assert not listener.renew(named)
    assert not (named.tls_dir / "self-signed.crt").exists()
    monkeypatch.setattr(listener, "_serving", None)
    loaded = []
    assert listener.renew(_tls(config), lambda *a: loaded.append(a))
    assert loaded == [] and (config.tls_dir / "self-signed.crt").is_file()
    assert not listener.renew(_tls(config)), "now it fits"


def test_the_listener_serves_the_named_pair_and_refuses_one_missing_or_unloadable(config, tmp_path):
    """S13.3: [tls] cert and key are served as named; one missing, or a pair that won't load,
    refuses the start saying which and why; behind a proxy it is plain HTTP."""
    from moolakata.listener import hypercorn_config, self_signed

    hc = hypercorn_config(config)
    assert hc.certfile is None and hc.bind == [config.bind]
    cert, key = self_signed(tmp_path / "pair", ["money.lan"])
    hc = hypercorn_config(_tls(config, tls_cert=cert, tls_key=key))
    assert (hc.certfile, hc.keyfile) == (str(cert), str(key))
    assert hc.alpn_protocols == ["h2", "http/1.1"]
    gone = tmp_path / "gone.key"
    with pytest.raises(RefuseStart, match=f"TLS file {gone} does not exist"):
        hypercorn_config(_tls(config, tls_cert=cert, tls_key=gone))
    bad = tmp_path / "bad.key"
    bad.write_text("not a key")
    with pytest.raises(RefuseStart, match="the TLS certificate or key cannot be loaded: "):
        hypercorn_config(_tls(config, tls_cert=cert, tls_key=bad))


def _serving_until(monkeypatch, what):
    """listener.run with Hypercorn's serve standing in: `what` runs as serve does, given its
    app, its config and its shutdown trigger."""
    from moolakata import listener

    calls = []

    async def serve(app, hc, shutdown_trigger):
        calls.append(app)
        await what(app, hc, shutdown_trigger)

    monkeypatch.setattr(listener, "serve", serve)
    return calls


@pytest.mark.parametrize(
    ("errno_", "refusal"),
    [
        (98, "port 37373 is already in use"),
        (13, "this account may not listen on port 37373"),
    ],
)
def test_a_port_that_cant_be_listened_on_refuses_the_start(config, monkeypatch, errno_, refusal):
    import asyncio
    import errno

    from moolakata import listener

    assert errno_ in (errno.EADDRINUSE, errno.EACCES)

    async def refused(app, hc, trigger):
        raise OSError(errno_, "no")

    _serving_until(monkeypatch, refused)
    with pytest.raises(RefuseStart, match=refusal):
        asyncio.run(listener.run("app", config, None))


def test_another_failure_to_listen_is_raised_as_it_is(config, monkeypatch):
    import asyncio

    from moolakata import listener

    async def refused(app, hc, trigger):
        raise OSError(99, "cannot assign requested address")

    _serving_until(monkeypatch, refused)
    with pytest.raises(OSError, match="cannot assign"):
        asyncio.run(listener.run("app", config, None))


def test_the_first_signal_ends_the_streams_and_a_repeat_within_a_second_is_the_same(
    config, monkeypatch, caplog
):
    """S13.6: SIGTERM ends the event streams (on_stop) and the listener stops with the host
    socket's; the same signal again within a second (a launcher's double Ctrl-C) is the same
    request, never the second one that stops at once."""
    import asyncio
    import logging
    import signal

    from moolakata import listener

    stopped = []

    async def on_stop():
        stopped.append("streams")

    async def until_stopped(app, hc, trigger):
        if app == "app":
            signal.raise_signal(signal.SIGTERM)
            signal.raise_signal(signal.SIGINT)
        await trigger()

    calls = _serving_until(monkeypatch, until_stopped)
    caplog.set_level(logging.INFO, "moolakata.listener")
    asyncio.run(listener.run("app", config, on_stop, host_app="host"))
    assert calls == ["app", "host"] and stopped == ["streams"]
    assert "stopping (SIGTERM)" in caplog.text and "second signal" not in caplog.text


def test_a_second_signal_later_than_a_second_stops_at_once(config, monkeypatch, caplog):
    import asyncio
    import logging
    import os
    import signal

    from moolakata import listener

    exits = []

    async def turned(done):
        """The loop turned until the signal's handler has run: no time passes."""
        for _ in range(100):
            if done():
                return
            await asyncio.sleep(0)
        raise AssertionError("the signal was never handled")

    def exit_(code):  # the process would end here
        exits.append(code)

    async def on_stop():
        pass

    async def stuck(app, hc, trigger):
        loop = asyncio.get_running_loop()
        signal.raise_signal(signal.SIGTERM)
        await turned(lambda: "stopping (SIGTERM)" in caplog.text)
        ahead = loop.time() + 2
        monkeypatch.setattr(loop, "time", lambda: ahead)
        signal.raise_signal(signal.SIGTERM)
        await turned(lambda: exits)

    monkeypatch.setattr(os, "_exit", exit_)
    _serving_until(monkeypatch, stuck)
    caplog.set_level(logging.INFO, "moolakata.listener")
    asyncio.run(listener.run("app", config, on_stop))
    assert exits == [1] and "second signal: stopping now" in caplog.text


def test_dev_mode_refuses_root_and_an_installed_servers_data(tmp_path, monkeypatch):
    """S17.7: dev mode, with its seed users' fixed password, never runs as root nor on the data
    directory of an installed server."""
    import os

    from moolakata.main import dev_config, refuse_dev

    refuse_dev(dev_config(37373, stubs=False, peer=False, base=tmp_path))
    with pytest.raises(RefuseStart, match="dev mode does not run on an installed server's data"):
        refuse_dev(dev_config(37373, False, False, Path("/var/lib/moolakata/dev")))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(RefuseStart, match="dev mode does not run as root"):
        refuse_dev(dev_config(37373, stubs=False, peer=False, base=tmp_path))


def test_a_frozen_dev_server_has_a_fixed_clock_repeatable_ids_and_no_landlock(
    tmp_path, monkeypatch
):
    """The generated mockup's server (S12.9): its clock fixed at the time given, its ids
    repeatable, and shown as a host without Landlock wherever it is built."""
    import datetime as dt

    from moolakata import clock, ids, parsing
    from moolakata import main as cli

    seen = {}

    def serve(config, seed=False):
        seen.update(now=clock.now(), id=ids.new_id("Acct"), pinned=parsing.PINNED, seed=seed)
        return 0

    monkeypatch.setattr(cli, "serve", serve)
    monkeypatch.setattr(parsing, "PINNED", parsing.PINNED)
    when = "2026-11-02T09:30:00+00:00"
    try:
        assert main(["dev", "--data", str(tmp_path), "--frozen", when, "--seed"]) == 0
        ids.repeatable()
        again = ids.new_id("Acct")  # counted from the start again: the same id
    finally:
        clock.fix(None)
        ids.repeatable(False)
    assert seen["now"] == dt.datetime.fromisoformat(when) and not seen["pinned"] and seen["seed"]
    assert again == seen["id"]


def test_a_server_asking_to_start_again_runs_the_same_command_unseeded(monkeypatch):
    """S15.7.2: after a scheduled re-encryption the same command runs again in this process,
    what an exit would flush flushed first, and a dev server's seed is not planted twice."""
    import atexit
    import os
    import sys

    from moolakata import main as cli
    from moolakata import runtime

    async def restart(config, seed=False):
        return runtime.RESTART

    flushed, ran = [], []
    monkeypatch.setattr(runtime, "start", restart)
    monkeypatch.setattr(atexit, "_run_exitfuncs", lambda: flushed.append(True))
    monkeypatch.setattr(os, "execv", lambda path, args: ran.append((path, args)))
    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "moolakata", "dev", "--seed"])
    assert cli.serve(None, seed=True) == runtime.RESTART
    assert flushed == [True]
    assert ran == [(sys.executable, ["python", "-m", "moolakata", "dev"])]


def test_openapi_prints_the_document(monkeypatch, capsys):
    from moolakata import contract

    monkeypatch.setattr(contract, "openapi_json", lambda: '{"openapi": "3.1.0"}\n')
    assert main(["openapi"]) == 0
    assert capsys.readouterr().out == '{"openapi": "3.1.0"}\n'


def test_a_command_stopped_by_ctrl_c_ends_as_an_interrupted_one(monkeypatch):
    from moolakata import main as cli

    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_openapi", interrupted)
    assert main(["openapi"]) == 130
