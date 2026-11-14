// The live stream (requirements S12.6): one EventSource per page. It carries what changed, never
// data; a screen whose data changed reloads it through its usual routes.
import { signal } from '@preact/signals';
import { version } from './config.js';
import { api } from '../api/client.js';
import { toast } from '../kit/toast.js';
import { parseJson } from '../kit/dec.js';

/** A counter per kind of change; screens subscribe by reading it. */
export const changes = signal(/** @type {Record<string, number>} */ ({}));
/** The navigation's counts, from the server. */
export const badges = signal(/** @type {Record<string, number>} */ ({}));
/** True once the server says it runs another version than this page (S12.1.4). */
export const updated = signal(false);

/** @type {EventSource | null} */
let source = null;
/** @type {(state: string) => void} */
let onEnded = () => {};

/** @param {string} kind */
function bump(kind) {
  changes.value = { ...changes.value, [kind]: (changes.value[kind] || 0) + 1 };
}

/** The navigation's counts again, after something that changes them. */
export function refreshBadges() {
  api.get('/badges').then((b) => (badges.value = b), () => {});
}

/** @param {(state: string) => void} ended */
export function connect(ended) {
  onEnded = ended;
  if (source) return;
  source = new EventSource('/ui/api/events');
  source.addEventListener('hello', (e) => {
    const data = parseJson(/** @type {MessageEvent} */ (e).data);
    if (data.version && data.version !== version) updated.value = true;
    badges.value = data.badges || {};
  });
  for (
    const kind of [
      'prices',
      'import',
      'share',
      'job',
      'activity',
      'task',
      'signup',
      'alert',
      'receipt',
      'category',
      'saved',
    ]
  ) {
    source.addEventListener(kind, () => bump(kind));
  }
  // A new alert shows at once, with its count on the badge (S12.11.4). The event names no
  // alert (S12.6): the newest is read through the API.
  source.addEventListener('alert', () => {
    api.get('/alerts').then((/** @type {any} */ r) => {
      const a = r?.open?.[0];
      toast(a ? `New alert: ${a.title}` : 'A new alert');
    }).catch(() => toast('A new alert'));
  });
  for (const kind of ['alert', 'badges', 'signup']) {
    source.addEventListener(kind, refreshBadges);
  }
  source.addEventListener('session', (e) => {
    const data = parseJson(/** @type {MessageEvent} */ (e).data);
    disconnect();
    onEnded(data.state);
  });
  source.onerror = () => {
    // The browser reconnects by itself; a closed session shows on the next request.
  };
}

export function disconnect() {
  source?.close();
  source = null;
}
