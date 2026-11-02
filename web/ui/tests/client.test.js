/// <reference lib="deno.ns" />
// A route outside the save that would move a filed year's gains (requirements S2.8.2): the
// client asks once, and sends the request again confirmed only if the person agrees.
import { api, CONFIRM_HEADER, whenClosedYear } from '../api/client.js';
import { equal } from './assert.js';

/** @param {{ status: number, body: any }[]} answers */
function serving(answers) {
  /** @type {{ headers: Record<string, string> }[]} */
  const sent = [];
  globalThis.fetch = /** @type {any} */ ((/** @type {string} */ _url, /** @type {any} */ init) => {
    sent.push({ headers: init.headers });
    const a = answers.shift() || { status: 500, body: {} };
    return Promise.resolve(new Response(JSON.stringify(a.body), { status: a.status }));
  });
  return sent;
}

const REFUSED = {
  status: 409,
  body: { code: 'closed-year', detail: 'This changes the realized gains of 2025…', years: [2025] },
};

Deno.test('a refusal for a filed year is asked, and sent again confirmed on yes', async () => {
  const sent = serving([REFUSED, { status: 200, body: { ok: true } }]);
  /** @type {any[]} */
  const asked = [];
  whenClosedYear((p) => {
    asked.push(p);
    return Promise.resolve(true);
  });
  const got = await api.post('/tax-books/TaxBk_1/accept', {});
  equal(got, { ok: true });
  equal(asked.map((p) => p.years), [[2025]]);
  equal(sent.map((s) => s.headers[CONFIRM_HEADER] || null), [null, 'closed-year']);
});

Deno.test('on no, nothing is sent again and the refusal stands', async () => {
  const sent = serving([REFUSED]);
  whenClosedYear(() => Promise.resolve(false));
  let code = null;
  try {
    await api.post('/tax-books/TaxBk_1/accept', {});
  } catch (e) {
    code = /** @type {any} */ (e).code;
  }
  equal(code, 'closed-year');
  equal(sent.length, 1);
});
