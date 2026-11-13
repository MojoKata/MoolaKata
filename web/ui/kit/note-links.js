// A note's links (requirements S12.18.15): an address on the web, http or https only, or a page
// of MoolaKata itself, kept without its server so it opens on any server that shows the note (a
// linked household's copy included).

/** The longest address a link keeps. */
export const LINK_MAX = 2000;

/**
 * A server MoolaKata answers at: its origin and where its pages start (`/ui/`).
 * @typedef {{ origin: string, base: string }} Own
 */

/**
 * What a typed or pasted address is: a page of this MoolaKata, an address on the web, or why it
 * is neither. A bare `www.` name is taken as https. An address of this server that isn't one of
 * its pages (its files, its API) is refused.
 * @param {string} text
 * @param {Own[]} [own]
 * @returns {{ page: string } | { href: string } | { error: string }}
 */
export function readHref(text, own = []) {
  const t = String(text ?? '').trim();
  if (!t) return { error: 'Type an address, such as https://example.com.' };
  if (t.length > LINK_MAX) {
    return { error: `At most ${LINK_MAX.toLocaleString('en-US')} characters.` };
  }
  const typed = /^www\./i.test(t) ? `https://${t}` : t;
  /** @type {URL} */
  let url;
  try {
    url = new URL(typed);
  } catch {
    return { error: 'Type a whole address, starting https://.' };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { error: 'Only http and https addresses.' };
  }
  if (url.username || url.password) {
    return { error: 'An address with a password in it is refused.' };
  }
  if (!url.hostname) return { error: 'Type a whole address, starting https://.' };
  const mine = own.find((o) => o.origin === url.origin);
  if (mine) {
    if (!url.pathname.startsWith(mine.base)) return { error: 'Not a page of MoolaKata.' };
    const page = url.pathname.slice(mine.base.length) + url.search + url.hash;
    // A linked household's window is this server's own; the page there is the copy's.
    if (page.startsWith('linked/')) return { href: url.href };
    return isPage(page) ? { page } : { error: 'Not a page of MoolaKata.' };
  }
  return { href: url.href };
}

/**
 * Whether text names a page inside MoolaKata, as a note keeps one: a screen and the path under
 * it, a query and a part, with no server, no `..`, and not the app's own files.
 * @param {unknown} page
 */
export function isPage(page) {
  return typeof page === 'string' && page.length > 0 && page.length <= LINK_MAX &&
    /^[a-z][a-z0-9-]*(\/[A-Za-z0-9_.~-]+)*\/?(\?[^#\s]*)?(#\S*)?$/.test(page) &&
    !/(^|\/)\.\.?(\/|$|\?|#)/.test(page) && !/^(v|linked|api)(\/|$)/.test(page);
}

/** Whether text is an address on the web a note may keep. @param {unknown} href */
export function isHref(href) {
  if (typeof href !== 'string' || href.length > LINK_MAX) return false;
  const r = readHref(href);
  return 'href' in r && r.href === href;
}

/**
 * Where a bare address typed into a note ends, if the text before the caret ends with one: a
 * word starting http://, https:// or www., closing punctuation left out.
 * @param {string} before  the text before the space just typed
 * @returns {string | null}
 */
export function trailingAddress(before) {
  const m = /(?:^|\s)((?:https?:\/\/|www\.)\S+)$/i.exec(before);
  if (!m) return null;
  return m[1].replace(/[.,;:!?)\]'"]+$/, '') || null;
}
