// What the browser remembers about how the page looks (requirements S17.3.7): theme, sidebar,
// help pane, the tour's width, page size, privacy mode and the tax book in view. Nothing else is
// kept in the browser but the tour open in a tab (store/tour.js).
import { effect, signal } from '@preact/signals';

/**
 * @template T
 * @param {string} key
 * @param {T} fallback
 */
function stored(key, fallback) {
  let start = fallback;
  try {
    const raw = localStorage.getItem('mk-' + key);
    if (raw !== null) start = JSON.parse(raw);
  } catch {
    // a private window, or storage switched off: the default
  }
  const s = signal(start);
  effect(() => {
    try {
      localStorage.setItem('mk-' + key, JSON.stringify(s.value));
    } catch {
      // nothing to do
    }
  });
  return s;
}

/** @type {import('@preact/signals').Signal<'dark' | 'light' | 'system'>} */
export const theme = stored('theme', /** @type {'dark' | 'light' | 'system'} */ ('dark'));
export const collapsed = stored('sidebar-collapsed', false);
export const helpOpen = stored('help-open', true);
export const helpWidth = stored('help-width', 360);
export const tourWidth = stored('tour-width', 340);
export const pageSize = stored('page-size', 100);
export const privacy = stored('privacy', false);
/** The tax book the Taxes screen shows, by id. */
export const book = stored('tax-book', /** @type {string | null} */ (null));

/** Apply the theme to the page; "system" follows prefers-color-scheme. */
export function applyTheme() {
  const t = theme.value === 'system'
    ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
    : theme.value;
  document.documentElement.dataset.theme = t;
}
