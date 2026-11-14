// The generated mockup's MOCK pill (requirements S12.9): it jumps to any screen, opens the
// dialogs, switches between the sample users, and changes state (stale prices, a locked or new
// server, privacy mode).
import { openMenu } from '../kit/menu.js';
import { privacy } from '../store/prefs.js';

/** (label, screen, the button that opens it): reached as a person would, through the screen. */
const DIALOGS = [
  ['New account', '/ui/accounts', 'New Account'],
  ['Import', '/ui/accounts', 'Import'],
  ['Add a transaction', '/ui/transactions', 'Add'],
  ['New portfolio', '/ui/portfolios', 'New Portfolio'],
  ['New user', '/ui/users', 'New User', true],
  ['New group', '/ui/users', 'New Group', true],
  ['Add a price source', '/ui/settings/prices', 'Add a Source', true],
  ['Verify key', '/ui/settings/keys', 'Verify Key', true],
];

/**
 * Open a screen, then press the button with this label once it is there and enabled.
 * @param {(url: string) => void} route
 * @param {string} path
 * @param {string} label
 */
function press(route, path, label) {
  route(path);
  let tries = 0;
  const look = () => {
    const button = [...document.querySelectorAll('.content button')].find((b) =>
      b.textContent?.trim() === label && !(/** @type {HTMLButtonElement} */ (b).disabled)
    );
    if (button) /** @type {HTMLElement} */ (button).click();
    else if (tries++ < 50) setTimeout(look, 100);
  };
  setTimeout(look, 100);
}

/**
 * @param {HTMLElement} at  the pill
 * @param {{ href: string, label: string }[]} nav  the signed-in user's navigation
 * @param {(url: string) => void} route
 */
export function openMockMenu(at, nav, route) {
  const mock = /** @type {any} */ (globalThis).mkMockup;
  const admin = nav.some((n) => n.href === '/ui/settings');
  openMenu(/** @type {any} */ ({ currentTarget: at }), [
    { head: true, label: 'Screens' },
    ...[...nav, { href: '/ui/profile', label: 'Profile' }].map((n) => ({
      label: n.label,
      onSelect: () => route(n.href),
    })),
    { head: true, label: 'Dialogs' },
    ...DIALOGS.filter((d) => admin || !d[3]).map(([label, path, button]) => ({
      label: String(label),
      onSelect: () => press(route, String(path), String(button)),
    })),
    { head: true, label: 'Signed in as' },
    ...mock.users.map((/** @type {{ username: string, name: string }} */ u) => ({
      label: u.name,
      on: u.username === mock.user,
      onSelect: () => mock.signInAs(u.username),
    })),
    { head: true, label: 'State' },
    { label: 'Prices stale', on: mock.stale, onSelect: () => mock.setStale(!mock.stale) },
    {
      label: 'Server locked (after a restart)',
      on: mock.locked,
      onSelect: () => mock.setLocked(!mock.locked),
    },
    {
      label: 'New server (the welcome)',
      on: mock.fresh,
      onSelect: () => mock.setFresh(!mock.fresh),
    },
    { label: 'Privacy mode', on: privacy.value, onSelect: () => (privacy.value = !privacy.value) },
  ]);
}
