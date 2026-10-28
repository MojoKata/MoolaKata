// The browser's side of /ui/api (requirements S13.8): JSON in and out, problem+json errors with
// each refusal at its field, If-Match versions, and Idempotency-Key on creates.

import { parseJson } from '../app/dec.js';

/** A refusal from the server, with the field each part of it belongs to. */
export class ApiError extends Error {
  /**
   * @param {number} status
   * @param {any} body
   */
  constructor(status, body) {
    super(body?.detail || body?.title || `HTTP ${status}`);
    this.status = status;
    this.code = body?.code || 'error';
    /** @type {{ field: string | null, code: string, message: string }[]} */
    this.errors = body?.errors || [];
    this.current = body?.current;
    this.errorId = body?.errorId;
    /** The problem as sent, with anything else it carries (a clash's person). */
    this.body = body;
  }

  /**
   * The message for one field, or for the form when none names it.
   * @param {string | null} field
   */
  at(field) {
    const e = this.errors.find((x) => x.field === field);
    return e ? e.message : null;
  }
}

/**
 * A linked household's window (requirements S12.10) reads only what that household shared with
 * you: each GET of a screen's API path is answered from its copy, as its source worked it out.
 * @type {string | null}
 */
let linked = null;
/** @param {string | null} linkId */
export function readLinked(linkId) {
  linked = linkId;
}
const OWN = /^\/(linked|session|events|prices\/status|profile|badges)/;

/** Called when a request finds no session: the frame goes to sign-in. */
let onSignedOut = (/** @type {string} */ _code) => {};
/** @param {(code: string) => void} fn */
export function whenSignedOut(fn) {
  onSignedOut = fn;
}

/**
 * @param {string} method
 * @param {string} path
 * @param {{ body?: any, version?: number, params?: Record<string, any>, idempotent?: boolean | string,
 *   form?: FormData }} [opts]
 */
async function call(method, path, opts = {}) {
  // A placeholder base: only the path and query are sent, so this works without an origin.
  const url = new URL('/ui/api' + path, 'https://moolakata.invalid');
  for (const [k, v] of Object.entries(opts.params || {})) {
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, String(x)));
    else if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }
  /** @type {Record<string, string>} */
  const headers = { Accept: 'application/json' };
  let body;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  if (linked && method === 'GET' && !OWN.test(path)) {
    const inner = url.pathname.slice('/ui/api'.length) + url.search;
    url.pathname = `/ui/api/linked/${linked}/doc`;
    url.search = '?' + new URLSearchParams({ path: inner });
  }
  if (opts.version !== undefined) headers['If-Match'] = `"${opts.version}"`;
  if (opts.idempotent) {
    // A key of the caller's (a draft's retry keeps its own, S13.8.8), or a new one.
    headers['Idempotency-Key'] = typeof opts.idempotent === 'string'
      ? opts.idempotent
      : crypto.randomUUID();
  }
  const r = await fetch(url.pathname + url.search, {
    method,
    headers,
    body,
    credentials: 'same-origin',
  });
  if (r.status === 204 || r.status === 201 && r.headers.get('content-length') === '0') {
    return null;
  }
  const text = await r.text();
  const data = text ? parseJson(text) : null;
  if (!r.ok) {
    const err = new ApiError(r.status, data);
    if (r.status === 401 && !path.startsWith('/session')) onSignedOut(err.code);
    throw err;
  }
  return data;
}

export const api = {
  /** @param {string} path @param {Record<string, any>} [params] */
  get: (path, params) => call('GET', path, { params }),
  /** @param {string} path @param {any} [body] @param {{ idempotent?: boolean | string, version?: number, params?: Record<string, any> }} [o] */
  post: (path, body, o = {}) => call('POST', path, { body, ...o }),
  /** @param {string} path @param {any} body @param {number} [version] @param {Record<string, any>} [params] */
  put: (path, body, version, params) => call('PUT', path, { body, version, params }),
  /** @param {string} path @param {any} body @param {number} [version] @param {Record<string, any>} [params] */
  patch: (path, body, version, params) => call('PATCH', path, { body, version, params }),
  /** @param {string} path @param {number} [version] @param {Record<string, any>} [params] @param {any} [body] */
  del: (path, version, params, body) => call('DELETE', path, { version, params, body }),
  /** @param {string} path @param {File} file */
  upload: (path, file) => {
    const form = new FormData();
    form.append('file', file);
    return call('POST', path, { form });
  },
};
