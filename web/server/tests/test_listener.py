"""Settings › Network's listener, read only (requirements S13.3, S16.14, CR3-12, CR3-308): its
mode and port; in `proxy` mode the proxies whose forwarded headers count; in `tls` mode whether
the certificate was given or is the server's own, which is for testing."""

import dataclasses
import ipaddress
from pathlib import Path

import pytest
from conftest import make_user, sign_in


def listener(server, admin_client, **config) -> dict:
    server.config = dataclasses.replace(server.config, **config)
    r = admin_client.get("/ui/api/settings/listener")
    assert r.status_code == 200, r.text
    return r.json()


def test_proxy_mode_names_its_trusted_proxies(server, admin_client):
    nets = (ipaddress.ip_network("172.30.37.10"), ipaddress.ip_network("fd00:37::/64"))
    assert listener(server, admin_client, trusted_proxies=nets) == {
        "mode": "proxy",
        "port": 37373,
        "trustedProxies": ["172.30.37.10", "fd00:37::/64"],
        "certificate": None,
    }


@pytest.mark.parametrize("given, certificate", [(None, "own"), (Path("/certs/nas.pem"), "given")])
def test_tls_mode_says_whose_certificate(server, admin_client, given, certificate):
    nets = (ipaddress.ip_network("172.30.37.10"),)
    got = listener(
        server, admin_client, mode="tls", port=8443, trusted_proxies=nets, tls_cert=given,
        tls_key=given,
    )  # fmt: skip
    assert got == {"mode": "tls", "port": 8443, "trustedProxies": [], "certificate": certificate}


def test_only_an_admin_sees_it(server):
    make_user(server, "alice")
    assert sign_in(server, "alice").get("/ui/api/settings/listener").status_code == 403
