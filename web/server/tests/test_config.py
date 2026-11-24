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
    # S17.6: the image carries no dev.sh, and leaves dev mode's code out.
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
