// The generated mockup's backend (requirements S12.9), run before the app: the answers recorded
// from a seeded server for each sample user, the guides, a clock that starts on the day they
// were recorded, and a stream that never sends. Nothing leaves the page. It then loads the app
// from the modules the page carries.
(() => {
  // A long data: URL (an avatar) is kept once in the page, and each answer names it: put back
  // as the answers load, so the app gets what the server sent.
  const blobs = /** @type {string[]} */ (
    JSON.parse(document.getElementById('mk-blobs')?.textContent || '[]')
  );
  // A number with a decimal point stays as its literal (S13.8.2), so each answer is served with
  // the exact digits the server wrote.
  const data = JSON.parse(
    /** @type {HTMLElement} */ (document.getElementById('mk-data')).textContent || '{}',
    /** @type {any} */ (
      /** @param {string} _k @param {unknown} v @param {{ source?: string }} [ctx] */
      (_k, v, ctx) =>
        typeof v === 'number' && ctx?.source && /[.eE]/.test(ctx.source)
          ? /** @type {any} */ (JSON).rawJSON(ctx.source)
          : typeof v === 'string' && v.startsWith('mk-blob:')
          ? blobs[Number(v.slice(8))]
          : v
    ),
  );

  // The day the answers were recorded, so "3 days ago" and the date fields agree with them.
  const RealDate = Date;
  const shift = RealDate.parse(data.now) - RealDate.now();
  class MockDate extends RealDate {
    /** @param {any[]} args */
    constructor(...args) {
      super(.../** @type {[any]} */ (args.length ? args : [RealDate.now() + shift]));
    }
    /** @override */
    static now() {
      return RealDate.now() + shift;
    }
  }
  globalThis.Date = /** @type {any} */ (MockDate);

  // The state the MOCK pill switches with a reload. The browser remembers it, and the address
  // carries it across the reload too ('?user=john&stale=1'), since Chromium can reload a page
  // opened from disk with its storage empty. The address wins.
  const address = new URLSearchParams(location.search);
  const recall = (/** @type {string} */ name) => {
    if (address.has('user')) return address.get(name);
    try {
      return localStorage.getItem('mk-mockup-' + name);
    } catch {
      return null; // no storage: the first user, fresh prices, an unlocked older server
    }
  };
  let user = recall('user') || data.users[0].username;
  if (!data.api[user]) user = data.users[0].username;
  let signedIn = true;
  const stale = recall('stale') === '1';
  // The server locked after a restart (S15.4.3), until the phrase is entered: a state of the
  // mockup's own, since the recorded server was unlocked for the crawl.
  let locked = recall('locked') === '1';
  // A new server (S15.4.4): its welcome, then the first admin's account; also the mockup's own.
  let fresh = recall('fresh') === '1';
  let needsAdmin = false;
  /**
   * Keep the state, with these changes, for the page that comes back.
   * @param {{ user?: string, stale?: boolean, locked?: boolean }} [changes]
   */
  const remember = (changes = {}) => {
    const s = { user, stale, locked, fresh, ...changes };
    const flags = /** @type {const} */ (['stale', 'locked', 'fresh']);
    try {
      localStorage.setItem('mk-mockup-user', s.user);
      for (const f of flags) localStorage.setItem('mk-mockup-' + f, s[f] ? '1' : '0');
    } catch {
      // without storage the address alone carries it
    }
    const q = new URLSearchParams({ user: s.user });
    for (const f of flags) if (s[f]) q.set(f, '1');
    history.replaceState(history.state, '', `?${q}${location.hash}`);
  };
  // The welcome's sample phrase: the same words every time, so the page draws the same.
  const OFFER = {
    token: 'mock-token',
    words: 'harbor velvet pencil orbit lucky tribe canyon modify gallery reward almost shiver'
      .split(' '),
    fingerprint: 'mk-b7ef…5f6d',
    serverName: 'doe-home',
    made: '2026-10-12',
    check: [3, 7, 11],
  };
  const setFresh = (/** @type {boolean} */ on) => {
    fresh = on;
    remember();
  };

  /** A request's key: its path and its query in order, less what only says "now". */
  const keyOf = (/** @type {string} */ url) => {
    const u = new URL(url, 'https://moolakata.invalid');
    const q = [...u.searchParams].filter(([k]) => k !== 'since').sort((a, b) =>
      a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0
    );
    return u.pathname + (q.length ? '?' + new URLSearchParams(q) : '');
  };

  const json = (/** @type {number} */ status, /** @type {any} */ body) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  const missing = (/** @type {string} */ what) =>
    json(404, { title: 'Not in the mockup', detail: `${what} was not recorded.`, code: 'mockup' });

  /**
   * @param {any} input
   * @param {RequestInit} [init]
   */
  globalThis.fetch = (input, init = {}) => {
    const url = String(input);
    const method = (init.method || 'GET').toUpperCase();
    const guide = url.match(/\/guides\/([\w-]+)\.md$/);
    if (guide) {
      const md = data.guides[guide[1]];
      return Promise.resolve(
        md === undefined ? new Response('', { status: 404 }) : new Response(md),
      );
    }
    const key = keyOf(url);
    if (fresh || needsAdmin) {
      let sent = /** @type {any} */ ({});
      try {
        sent = typeof init.body === 'string' ? JSON.parse(init.body) : {};
      } catch {
        // nothing sent
      }
      if (key === '/ui/api/unlock') {
        return Promise.resolve(json(200, {
          locked: fresh,
          uninitialised: fresh,
          needsAdmin,
          fingerprint: fresh ? null : OFFER.fingerprint,
          version: data.version || '',
        }));
      }
      if (key === '/ui/api/welcome/phrase') return Promise.resolve(json(200, OFFER));
      if (key === '/ui/api/welcome/key') {
        const wrong = OFFER.check.filter((n) => {
          const typed = String(sent.words?.[n] || '').trim().toLowerCase();
          const word = OFFER.words[n - 1];
          return !(typed === word || (typed.length >= 4 && word.startsWith(typed)));
        });
        if (wrong.length) {
          return Promise.resolve(json(422, {
            code: 'words-wrong',
            title: 'Not the words shown',
            detail: "Those aren't the words shown: check your sheet.",
            errors: wrong.map((n) => ({
              field: `word${n}`,
              code: 'word-wrong',
              message: 'Not the word shown: check your sheet.',
            })),
          }));
        }
        setFresh(false);
        needsAdmin = true;
        return Promise.resolve(json(200, { locked: false, needsAdmin: true }));
      }
      if (key === '/ui/api/welcome/admin') {
        needsAdmin = false;
        signedIn = true;
        user = data.users.some((/** @type {any} */ u) => u.username === 'admin') ? 'admin' : user;
        return Promise.resolve(json(200, data.api[user]['GET /ui/api/session'].body));
      }
      return Promise.resolve(
        fresh
          ? json(503, { code: 'locked', title: 'Not available', detail: 'MoolaKata is new.' })
          : json(401, { code: 'signed-out' }),
      );
    }
    if (key === '/ui/api/settings/keys/verify' && method === 'POST') {
      return Promise.resolve(
        json(200, { fingerprint: 'mk-b7ef…5f6d', at: new Date().toISOString() }),
      );
    }
    if (key === '/ui/api/unlock') {
      if (method === 'POST') {
        locked = false;
        remember();
      }
      return Promise.resolve(
        json(200, { locked, fingerprint: 'mk-b7ef…5f6d', version: data.version || '' }),
      );
    }
    if (locked && key.startsWith('/ui/api/')) {
      return Promise.resolve(
        json(503, {
          code: 'locked',
          title: 'Not available',
          detail: 'MoolaKata is locked: an admin enters the recovery phrase to open it.',
        }),
      );
    }
    if (key === '/ui/api/session') {
      if (method === 'DELETE') signedIn = false;
      if (method === 'POST') signedIn = true;
      if (!signedIn) return Promise.resolve(json(401, { code: 'signed-out' }));
    }
    if (method === 'GET' || key === '/ui/api/session') {
      const hit = data.api[user]['GET ' + key];
      if (hit && stale && key === '/ui/api/prices/status') {
        return Promise.resolve(json(hit.status, { ...hit.body, stale: true }));
      }
      if (hit?.binary) {
        const bytes = Uint8Array.from(atob(hit.binary), (c) => c.charCodeAt(0));
        return Promise.resolve(
          new Response(bytes, { status: hit.status, headers: { 'Content-Type': hit.type } }),
        );
      }
      return Promise.resolve(hit ? json(hit.status, hit.body) : missing(key));
    }
    // What the crawl worked out (a payoff plan): the same answer for any inputs.
    const worked = data.api[user]['POST ' + key];
    if (method === 'POST' && worked) return Promise.resolve(json(worked.status, worked.body));
    // A change succeeds and changes nothing: the answer echoes what was sent.
    if (method === 'DELETE') return Promise.resolve(json(204, null));
    let body = {};
    try {
      body = typeof init.body === 'string' ? JSON.parse(init.body) : {};
    } catch {
      // a form: an upload
    }
    return Promise.resolve(json(200, { id: 'mock_0', version: 1, ...body }));
  };

  /** The live stream: it says hello with the navigation's counts, then stays quiet. */
  class MockEventSource extends EventTarget {
    /** @param {string} url */
    constructor(url) {
      super();
      this.url = url;
      /** @type {((e: Event) => void) | null} */
      this.onerror = null;
      const hello = data.events[user];
      setTimeout(() =>
        this.dispatchEvent(new MessageEvent('hello', { data: JSON.stringify(hello || {}) }))
      );
    }
    close() {}
  }
  globalThis.EventSource = /** @type {any} */ (MockEventSource);

  /** @type {any} */ (globalThis).mkMockup = {
    users: data.users,
    user,
    stale,
    locked,
    fresh,
    setFresh(/** @type {boolean} */ on) {
      setFresh(on);
      location.reload();
    },
    setLocked(/** @type {boolean} */ on) {
      remember({ locked: on });
      location.reload();
    },
    setStale(/** @type {boolean} */ on) {
      remember({ stale: on });
      location.reload();
    },
    signInAs(/** @type {string} */ name) {
      user = name;
      remember();
      location.reload();
    },
  };

  // The app's modules sit in the page as text. Each gets a blob: address, an import map names
  // them all, and then the app starts.
  /** @type {Record<string, string>} */
  const urls = {};
  for (const s of document.querySelectorAll('script[data-module]')) {
    const name = /** @type {HTMLElement} */ (s).dataset.module || '';
    urls[name] = URL.createObjectURL(new Blob([s.textContent || ''], { type: 'text/javascript' }));
  }
  for (const [name, target] of Object.entries(data.aliases)) urls[name] = urls[target];
  const map = document.createElement('script');
  map.type = 'importmap';
  map.textContent = JSON.stringify({ imports: urls });
  document.head.append(map);
  const main = document.createElement('script');
  main.type = 'module';
  main.textContent = `import '${data.main}';`;
  document.body.append(main);
})();
