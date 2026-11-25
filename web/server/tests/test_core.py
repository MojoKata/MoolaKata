import asyncio
import datetime as dt
import gzip
import threading
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from moolakata import exactjson, net
from moolakata.dev.waits import eventually_async, turn
from moolakata.events import Broker
from moolakata.jobs import Jobs
from moolakata.ratelimit import SignInGuard, Window
from moolakata.tasks import Daily, Every, ProviderLimits, TaskError, Tasks
from moolakata.ui.conventions import Model, Money, Paging
from moolakata.ui.stream import stream

UTC = dt.UTC


def test_daily_runs_at_its_time_in_its_zone():
    d = Daily(lambda: (dt.time(18, 0), "America/New_York"))
    last = dt.datetime(2026, 10, 12, 22, 0, tzinfo=UTC)  # 18:00 EDT
    assert d.next_due(last, last) == dt.datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
    started = dt.datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    # Never run: yesterday's run is owed, so it is due at once.
    assert d.next_due(None, started) <= started


def test_every_waits_before_its_first_run():
    e = Every(3600, first_after=30)
    t = dt.datetime(2026, 1, 1, tzinfo=UTC)
    assert e.next_due(None, t) == t + dt.timedelta(seconds=30)
    assert e.next_due(t, t) == t + dt.timedelta(hours=1)


def test_provider_limits_spread_calls():
    clock = [0.0]
    limits = ProviderLimits(clock=lambda: clock[0])
    limits.set("tiingo", [(2, 60), (3, 3600)])
    assert limits.delay("tiingo") == 0
    assert limits.delay("tiingo") == 0
    assert limits.delay("tiingo") == pytest.approx(60)
    clock[0] = 61
    assert limits.delay("tiingo") == 0
    clock[0] = 130
    assert limits.delay("tiingo") == pytest.approx(3600 - 130)


def test_a_second_refresh_shares_the_providers_windows_until_its_limits_change():
    """S13.4: each refresh sets its source's limits; set again unchanged, the calls already
    made in the hour still count, and only a changed limit starts the windows afresh."""
    clock = [0.0]
    limits = ProviderLimits(clock=lambda: clock[0])
    limits.set("tiingo", [(2, 3600)])
    assert [limits.delay("tiingo") for _ in range(2)] == [0, 0]
    clock[0] = 600  # Refresh Prices pressed ten minutes later
    limits.set("tiingo", [(2, 3600)])
    assert limits.delay("tiingo") == pytest.approx(3000)
    limits.set("tiingo", [(3, 3600)])
    assert limits.delay("tiingo") == 0


def test_tasks_record_runs_and_keep_error_text_out_unless_safe():
    recorded = {}
    done = threading.Event()

    def record(name, run):
        recorded[name] = run
        if len(recorded) == 2:
            done.set()

    tasks = Tasks(record=record)

    def leaky(ctx):
        raise ValueError("Checking 1234 is short $50")

    def safe(ctx):
        raise TaskError("Tiingo answered 401")

    tasks.register("leaky", leaky, None)
    tasks.register("safe", safe, None)
    tasks.run_now("leaky")
    tasks.run_now("safe")
    tasks.tick()
    assert done.wait(5)
    tasks.stop()
    assert recorded["leaky"].error == "ValueError"
    assert recorded["safe"].error == "TaskError: Tiingo answered 401"


def test_egress_guard():
    guard = net.Guard(
        resolver=lambda h, p: {
            "api.tiingo.com": ["203.0.113.5"],
            "evil.example": ["169.254.169.254"],
            "node.lan": ["127.0.0.1"],
        }[h]
    )
    guard.allow(["api.tiingo.com", "evil.example", "node.lan"])
    guard.check("api.tiingo.com", 443)
    with pytest.raises(net.EgressRefused, match="not a host"):
        guard.check("example.com", 443)
    with pytest.raises(net.EgressRefused, match="metadata"):
        guard.check("evil.example", 443)
    with pytest.raises(net.EgressRefused, match="loopback"):
        guard.check("node.lan", 50001)
    guard.allow(["node.lan"], allowed_by_name={"bitcoin": ["node.lan"]})
    guard.check("node.lan", 50001, "bitcoin")
    with pytest.raises(net.EgressRefused):
        guard.check("127.0.0.1", 80)


def test_a_host_named_by_an_admin_is_exempt_only_for_its_own_client():
    """S13.5, S11.2: the SMTP server an admin named may be on loopback, but a link, a price
    source or the bitcoin client asking for the same host is refused, whoever named it."""
    guard = net.Guard()
    guard.allow(["127.0.0.1"], allowed_by_name={"smtp": ["127.0.0.1"]})
    assert guard.check("127.0.0.1", 25, "smtp") == "127.0.0.1"
    for use in ("link", "bitcoin", None):
        with pytest.raises(net.EgressRefused, match="loopback"):
            guard.check("127.0.0.1", 2019, use)
    with pytest.raises(net.EgressRefused, match="loopback"):
        net.Client(guard, use="link").get("https://127.0.0.1:2019/")
    with pytest.raises(net.EgressRefused, match="loopback"):
        net.Client(guard).get("https://127.0.0.1:2019/")


def test_client_refuses_before_connecting():
    client = net.Client(net.Guard())
    with pytest.raises(httpx.TransportError):
        client.get("https://example.com/")


def test_windows_and_sign_in_lockout():
    clock = [0.0]
    w = Window(3, 60, clock=lambda: clock[0])
    assert [w.hit("s") for _ in range(4)][-1] == pytest.approx(60)
    clock[0] = 60
    assert w.hit("s") == 0

    g = SignInGuard(clock=lambda: clock[0])
    for _ in range(9):
        assert not g.failed("jane", "10.0.0.5")
    assert g.failed("Jane", "10.0.0.5")
    # The address is locked; the username is only slowed, from any address (S13.7.5.1).
    assert g.locked("10.0.0.5") == pytest.approx(15 * 60)
    assert g.locked("10.0.0.6") == 0
    assert g.delay("jane", "10.0.0.6") == 3.5  # ten failures: half a second past the third
    g.succeeded("jane")
    assert g.delay("jane", "10.0.0.6") == 0
    clock[0] += 15 * 60
    assert g.locked("10.0.0.5") == 0


def test_a_username_is_slowed_half_a_second_per_failure_past_the_third():
    """S13.7.5.1: 0.5 × (failures − 3) seconds, up to five: none on the third, half a second
    on the fourth."""
    g = SignInGuard(clock=lambda: 0.0)
    waits = []
    for _ in range(14):
        g.failed("jane", f"10.0.0.{len(waits)}", threshold=100)
        waits.append(g.delay("jane", "10.0.0.99"))
    assert waits[:5] == [0, 0, 0, 0.5, 1.0]
    assert waits[-1] == 5.0, "fourteen failures: no more than five seconds"


def test_a_window_forgets_the_keys_whose_events_have_lapsed():
    # S13.7.5.5: counters in memory, kept no longer than they count.
    clock = [0.0]
    w = Window(3, 60, clock=lambda: clock[0])
    for n in range(100):
        w.hit(f"10.0.0.{n}")
    assert len(w) == 100
    assert w.wait("10.9.9.9") == 0 and w.count("10.9.9.9") == 0 and len(w) == 100
    clock[0] = 60
    w.hit("10.0.1.1")
    assert len(w) == 1, "the lapsed keys are dropped"


def test_the_sign_in_guard_forgets_what_has_lapsed():
    # S13.7.5.5: failures, lockouts and a pending sign-in's wrong codes are dropped once they
    # no longer count, so a scan of new usernames doesn't grow the server's memory.
    clock = [0.0]
    g = SignInGuard(clock=lambda: clock[0])
    for n in range(50):
        g.failed(f"user{n}", f"10.0.{n}.1", threshold=1)
        g.code_wrong(f"pending{n}")
    assert g.delay("someone-new", "10.9.9.9") == 0
    assert g.held() == {"addresses": 50, "usernames": 50, "locks": 50, "codes": 50, "trying": 0}
    clock[0] = 15 * 60
    g.failed("jane", "10.1.1.1")
    assert g.held() == {"addresses": 1, "usernames": 1, "locks": 0, "codes": 0, "trying": 0}


def test_a_login_longer_than_any_username_or_email_counts_against_the_address_alone():
    # Usernames are 2 to 32 characters and an email at most 254 (S10.1): a longer login names
    # nobody, so it is never kept, though it counts toward the address's lockout.
    g = SignInGuard()
    long = "x" * 255
    for _ in range(9):
        assert not g.failed(long, "10.0.0.5")
    assert g.held()["usernames"] == 0
    assert g.failed(long, "10.0.0.5") and g.locked("10.0.0.5") > 0
    g.failed("y" * 254, "10.0.0.6")
    assert g.held()["usernames"] == 1


def test_the_lockout_counts_an_ipv6_address_by_its_64():
    # S13.7.5.1: one household's /64 is one address to the lockout.
    clock = [0.0]
    g = SignInGuard(clock=lambda: clock[0])
    for i in range(10):
        g.failed("jane", f"2001:db8:1:2::{i + 1:x}")
    assert g.locked("2001:db8:1:2::ffff") > 0
    assert g.locked("2001:db8:1:3::1") == 0


def test_a_two_step_sign_in_takes_one_code_at_a_time_and_five_in_all():
    # S10.1.6.3: a second code waits for the first; the fifth wrong one ends the sign-in.
    g = SignInGuard()
    assert g.checking("t1") and not g.checking("t1")
    g.checked("t1")
    assert g.checking("t1")
    assert [g.code_wrong("t1") for _ in range(5)] == [False] * 4 + [True]
    assert not g.code_wrong("t1"), "a new count once it ended"


def test_money_fields_refuse_floats():
    class Body(Model):
        amount: Money

    # In JSON an amount is an exact number literal (S13.8.2); in Python, a Decimal.
    assert exactjson.dumps(Body(amount="12.30").model_dump(mode="json")) == '{"amount": 12.30}'
    assert Body(amount=Decimal("12.3")).model_dump() == {"amount": Decimal("12.3")}
    with pytest.raises(ValidationError):
        Body(amount=12.3)  # never through a float
    with pytest.raises(ValidationError):
        Body(amount="12.345")
    with pytest.raises(ValidationError):
        Body(amount="1", extra=1)


def test_paging_takes_an_offset_and_counts_the_whole():
    p = Paging(offset=2, limit=2)
    assert p.page([1, 2, 3, 4, 5]) == {"items": [3, 4], "total": 5, "offset": 2, "limit": 2}
    assert Paging(offset=10, limit=2).page([1, 2]) == {
        "items": [],
        "total": 2,
        "offset": 10,
        "limit": 2,
    }


def test_stream_delivers_from_threads_and_ends_on_close():
    async def scenario():
        broker = Broker()
        broker.bind(asyncio.get_running_loop())
        sub = broker.subscribe("User_a", "h1")
        other = broker.subscribe("User_b", "h2")

        async def ok():
            return None

        out = []

        async def read():
            async for chunk in stream(broker, sub, {"version": "1"}, ok, seconds=5):
                out.append(chunk.decode())

        reader = asyncio.create_task(read())
        await turn()
        threading.Thread(target=broker.publish, args=("prices", {"asOf": "x"}, ["User_a"])).start()
        await eventually_async(lambda: len(out) == 3, what="the prices event read")
        await broker.close_all()
        await asyncio.wait_for(reader, 30)
        assert other.queue.qsize() == 1  # only the closing notice: prices went to User_a
        return out

    out = asyncio.run(scenario())
    assert out[0].startswith("retry:")
    assert out[1].startswith("event: hello")
    assert out[2] == 'event: prices\ndata: {"asOf": "x"}\n\n'
    assert len(out) == 3


def test_stream_ends_when_the_session_does():
    async def scenario():
        broker = Broker()
        broker.bind(asyncio.get_running_loop())
        sub = broker.subscribe("User_a", "h1")

        async def ended():
            return "signed-out"

        return [c.decode() async for c in stream(broker, sub, {}, ended, seconds=5, keepalive=0.05)]

    out = asyncio.run(scenario())
    assert out[-1] == 'event: session\ndata: {"state": "signed-out"}\n\n'


def test_jobs_are_their_users_own():
    seen = []
    jobs = Jobs(announce=seen.append)
    job = jobs.create("import", "User_a")
    assert jobs.get(job.id, "User_b") is None
    assert jobs.get(job.id, "User_a") is job
    jobs.update(job, state="done", progress=1.0, result={"added": 3})
    assert seen == [job] and job.finished is not None


def test_run_now_starts_at_once_once_the_tasks_have_started():
    ran = threading.Event()
    tasks = Tasks()
    tasks.register("backups", lambda ctx: ran.set(), None)

    async def main():
        tasks.start()  # its first tick runs nothing: the task has no schedule
        await turn()
        try:
            assert tasks.run_now("backups")
            return await asyncio.to_thread(ran.wait, 10)  # well inside a 15-second tick
        finally:
            tasks.stop()

    assert asyncio.run(main())


@pytest.fixture
def tls_peer(tmp_path):
    """A server on loopback with a certificate of its own, answering every request; a long
    answer is sent chunked, with no length announced."""
    import socket
    import ssl
    import threading

    from moolakata.listener import self_signed

    cert, key = self_signed(tmp_path, ["peer.lan"])
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                raw, _ = srv.accept()
            except TimeoutError:
                continue
            try:
                with ctx.wrap_socket(raw, server_side=True) as tls:
                    request = tls.recv(65536)
                    if b"/gzip" in request:
                        # 1 MB of zeros, about a kilobyte as gzip: under any ceiling on the wire.
                        bomb = gzip.compress(b"0" * (1 << 20))
                        head = f"Content-Encoding: gzip\r\nContent-Length: {len(bomb)}\r\n"
                        tls.sendall(b"HTTP/1.1 200 OK\r\n" + head.encode() + b"\r\n" + bomb)
                    elif b"/long" in request:
                        tls.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
                        piece = b"x" * 4096
                        for _ in range(8):
                            tls.sendall(b"1000\r\n" + piece + b"\r\n")
                        tls.sendall(b"0\r\n\r\n")
                    else:
                        tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            except OSError, ssl.SSLError:
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    der = x509.load_pem_x509_certificate(cert.read_bytes()).public_bytes(Encoding.DER)
    yield port, net.key_fingerprint(der)
    stop.set()
    t.join(2)
    srv.close()


def test_a_servers_own_certificate_is_pinned_by_its_key(tls_peer):
    """S11.1.3, S13.5: the address the guard checked is the one connected to; a certificate of
    the server's own is accepted only by the key pinned for it, checked before anything is
    sent; a public check refuses it; and an answer past the ceiling is cut off, chunked or not,
    and counted as it decodes, over the sockets as tests/test_net.py counts it above them."""
    port, fp = tls_peer
    lookups = []

    def resolver(host, p):
        lookups.append(host)
        return ["127.0.0.1"]

    guard = net.Guard(resolver=resolver)
    guard.allow(["peer.lan"], allowed_by_name={"link": ["peer.lan"]})
    url = f"https://peer.lan:{port}/"
    assert net.Client(guard, use="link", pins=[fp]).get(url).text == "ok"
    assert lookups == ["peer.lan"], "looked up once, by the guard"
    with pytest.raises(net.CertificateRefused) as e:
        net.Client(guard, use="link", pins=["0" * 64]).get(url)
    assert e.value.fingerprint == fp
    with pytest.raises(httpx.ConnectError):
        net.Client(guard, use="link").get(url)  # a public check: no root vouches for it
    with pytest.raises(net.ResponseTooLarge):
        net.Client(guard, use="link", max_bytes=10_000, pins=[fp]).get(url + "long")
    with pytest.raises(net.ResponseTooLarge):
        net.Client(guard, use="link", max_bytes=10_000, pins=[fp]).get(url + "gzip").json()


def test_this_servers_own_certificate_is_read_through_the_guard(tls_peer):
    """S13.5: the probe of this server's own link address for its certificate is an outbound
    call like any other: to the address the guard checked, never to loopback unless allowed;
    one it can't read is told apart from a public certificate."""
    from moolakata import certs

    port, fp = tls_peer
    guard = net.Guard(resolver=lambda host, p: ["127.0.0.1"])
    guard.allow(["127.0.0.1", "peer.lan"])
    with pytest.raises(certs.Unread):
        certs._probe(guard, f"https://127.0.0.1:{port}")
    with pytest.raises(certs.Unread):
        certs._probe(guard, f"https://money.example:{port}")  # not a host it may reach
    # Allowed by name for a link, as between two dev servers on one machine.
    guard.allow(["peer.lan"], allowed_by_name={"link": ["peer.lan"]})
    assert certs._probe(guard, f"https://peer.lan:{port}") == fp
    assert certs._probe(guard, "http://peer.lan") is None, "plain HTTP has no certificate"


def test_a_provider_past_its_limit_waits_its_window_or_stops_with_the_server():
    """S13.4: a call past the provider's limit waits until its window lets one more through;
    a server stopping meanwhile ends the wait."""
    from moolakata.tasks import ProviderLimits, Stopping

    now = [0.0]
    limits = ProviderLimits(clock=lambda: now[0])
    limits.set("tiingo", [(1, 60.0)])
    waited = []

    class Passing:
        """A stop never set, whose wait lets the clock run on."""

        def wait(self, seconds):
            waited.append(seconds)
            now[0] += seconds
            return False

    limits.acquire("tiingo", Passing())
    limits.acquire("tiingo", Passing())
    assert waited == [60.0], "the second waited the window out"
    stop = threading.Event()
    stop.set()
    with pytest.raises(Stopping):
        limits.acquire("tiingo", stop)


def _ran(tasks, name, *, ended=None):
    """The task asked for and run by a tick, on the tasks' own threads: its last run."""
    from moolakata.dev.waits import eventually

    assert tasks.run_now(name, ended)
    tasks.tick()
    eventually(lambda: tasks.status()[name]["lastFinished"] is not None, what=f"{name} run")
    return tasks._tasks[name].last


def test_a_run_ended_by_a_stop_says_so_and_each_job_waiting_on_it_is_told():
    """S13.8.7: each job that asked for a run is told when it ends, even when another's ending
    fails; a run cut off by the server stopping says so."""
    from moolakata.dev.waits import eventually
    from moolakata.tasks import Stopping

    def stopped(ctx):
        raise Stopping

    tasks = Tasks()
    tasks.register("backups", stopped, None)
    told = []

    def failing(run):
        raise RuntimeError("the job is gone")

    assert tasks.run_now("backups", failing)
    run = _ran(tasks, "backups", ended=told.append)
    eventually(lambda: told, what="the second job told")
    assert told == [run] and run.error == "stopped when the server stopped"
    assert tasks._tasks["backups"].waiting == []
    tasks.stop()


def test_a_tick_passes_over_a_task_still_running():
    tasks = Tasks()
    tasks.register("prices", lambda ctx: None, Every(1))
    tasks._tasks["prices"].running = True
    tasks.tick()
    assert tasks._tasks["prices"].last is None, "never launched twice"
    tasks.stop()


def test_a_failing_tick_is_logged_and_the_runner_goes_on_until_stopped(monkeypatch, caplog):
    import moolakata.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "TICK_SECONDS", 0)
    tasks = Tasks()
    ticks = []

    def tick():
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("a schedule that can't be read")
        tasks._stop.set()

    monkeypatch.setattr(tasks, "tick", tick)
    asyncio.run(tasks.run())
    assert len(ticks) == 2 and "task tick failed" in caplog.text
    tasks.stop()


def test_a_job_that_fails_names_only_its_errors_type():
    """S13.8.7, S13.7.9: a failed job says what kind of error ended it, never its words."""
    from moolakata.dev.waits import eventually

    jobs = Jobs()

    def work(job):
        raise ValueError("account Shaw Checking: 1,234.56")

    job = jobs.start("import", "User_a", work)
    eventually(lambda: job.state == "failed", what="the job failed")
    assert job.error == {"code": "failed", "message": "ValueError"}
    done = jobs.start("import", "User_a", lambda job: ["not a dict"])
    eventually(lambda: done.state == "done", what="the job done")
    assert done.result is None and done.progress == 1.0


def test_a_job_following_a_task_ends_as_its_run_does():
    from moolakata.tasks import TaskRun

    jobs = Jobs()
    failed, done = jobs.create("backup", "User_a"), jobs.create("backup", "User_a")
    jobs.follow(failed)(TaskRun(started=dt.datetime.now(dt.UTC), error="OSError"))
    jobs.follow(done)(TaskRun(started=dt.datetime.now(dt.UTC)))
    assert (failed.state, failed.error) == ("failed", {"code": "failed", "message": "OSError"})
    assert (done.state, done.progress) == ("done", 1.0) and done.finished is not None


def test_a_job_is_kept_a_day_after_it_ends():
    """Jobs are work state kept in memory for a day (schema.md §4.4)."""
    from moolakata import clock

    jobs = Jobs()
    old, running = jobs.create("import", "User_a"), jobs.create("import", "User_a")
    jobs.update(old, state="done")
    try:
        clock.fix(clock.now() + dt.timedelta(days=1, minutes=1))
        jobs.create("import", "User_a")
    finally:
        clock.fix(None)
    assert jobs.get(old.id, "User_a") is None
    assert jobs.get(running.id, "User_a") is running, "never finished: kept"


def test_an_event_reaches_only_its_session_and_a_stream_that_stopped_reading_ends():
    """S12.6: an event for one session goes to its streams alone; a stream whose queue is
    full (a page that stopped reading) is closed, and the browser reconnects."""
    from moolakata.events import Event

    async def scenario():
        broker = Broker()
        broker.bind(asyncio.get_running_loop())
        mine, other = broker.subscribe("User_a", "h1"), broker.subscribe("User_a", "h2")
        assert broker.count() == 2
        broker.end_session("h1", "signed-out")  # from the loop itself: delivered at once
        assert mine.queue.get_nowait() == Event("session", {"state": "signed-out"})
        assert other.queue.empty()
        for _ in range(other.queue.maxsize):
            other.queue.put_nowait(Event("x"))
        broker.publish("prices")
        assert other.closed and not mine.closed
        broker.unsubscribe(other)
        assert broker.count() == 1

    asyncio.run(scenario())


def test_an_event_published_once_the_loop_has_closed_goes_nowhere():
    broker = Broker()
    broker.publish("prices")  # never bound: no loop
    loop = asyncio.new_event_loop()
    broker.bind(loop)
    sub = broker.subscribe("User_a", "h1")
    loop.close()
    broker.publish("prices")
    assert sub.queue.empty()
