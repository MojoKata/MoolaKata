// Who is signed in, and the household, from GET /ui/api/session.
import { signal } from '@preact/signals';
import { api } from '../api/client.js';
import { setBitcoinUnit, setZone } from '../app/format.js';

/** @type {import('@preact/signals').Signal<any>} */
export const session = signal(null);
/**
 * Why there is no session: 'signed-out', 'expired', 'disabled', 'locked' (the server waits
 * for its recovery phrase, or a new one for its welcome, S15.4), 'needs-admin' (unlocked with
 * no users: the welcome's last step, S10.1.2), or '' while loading.
 */
/** A session that ended, or a server that locked, while a dialog held changes: they were lost,
 * and the sign-in or locked screen says so (S12.15.6). */
export const lostChanges = signal(false);
export const ended = signal('');

export async function loadSession() {
  try {
    const info = await api.get('/session');
    session.value = info;
    setZone(info.user.zone);
    setBitcoinUnit(info.user.bitcoinUnit);
    ended.value = '';
    return info;
  } catch (e) {
    session.value = null;
    ended.value = /** @type {any} */ (e)?.code === 'locked'
      ? 'locked'
      : (await needsAdmin())
      ? 'needs-admin'
      : 'signed-out';
    return null;
  }
}

/** Whether the server is open with no users yet, so its first admin is to be set up. */
async function needsAdmin() {
  try {
    return Boolean((await api.get('/unlock')).needsAdmin);
  } catch {
    return false;
  }
}

/** @param {any} info */
export function setSession(info) {
  session.value = info;
  if (info) {
    setZone(info.user.zone);
    setBitcoinUnit(info.user.bitcoinUnit);
  }
}

/**
 * Keep the theme with the profile too, so a new browser starts with it.
 * @param {string} theme
 */
export async function saveTheme(theme) {
  try {
    const profile = await api.get('/profile');
    if (profile.theme !== theme) await api.patch('/profile', { theme }, profile.version);
  } catch {
    // the browser still remembers it
  }
}
