// The frame (requirements S12.1, S12.2): drawn once around every signed-in screen from one list
// of navigation entries; no screen draws or changes it.
import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { dev, mockup, version } from '../app/config.js';
import { ago, initials } from '../app/format.js';
import { badges, changes, updated } from '../app/stream.js';
import { api } from '../api/client.js';
import { saveTheme, session } from '../store/session.js';
import { applyTheme, collapsed, helpOpen, privacy, theme } from '../store/prefs.js';
import { Icon } from './icon.js';
import { Avatar } from './bits.js';
import { openMenu } from './menu.js';
import { HelpCorner, HelpPane } from './help.js';
import { TourPane } from './tour.js';
import { tour } from '../store/tour.js';

/** The screen's title and crumbs, set by each screen with useTitle(). */
export const title = signal(
  /** @type {{ text: string, crumbs?: [string, string][] }} */ ({
    text: '',
  }),
);

/**
 * @param {string} text
 * @param {[string, string][]} [crumbs]  (label, href) before the title
 */
export function useTitle(text, crumbs) {
  useEffect(() => {
    title.value = { text, crumbs };
    document.title = text ? `${text} · MoolaKata` : 'MoolaKata';
  }, [text, JSON.stringify(crumbs || [])]);
}

/** The navigation, in its order (S12.2); only the screens this release has. */
export const NAV = [
  { href: '/ui/', label: 'Dashboard', icon: 'dashboard', match: /^\/ui\/?$/ },
  { href: '/ui/accounts', label: 'Accounts', icon: 'bank', match: /^\/ui\/accounts/ },
  { href: '/ui/transactions', label: 'Transactions', icon: 'tx', match: /^\/ui\/transactions/ },
  { href: '/ui/portfolios', label: 'Portfolios', icon: 'pie', match: /^\/ui\/portfolios/ },
  { href: '/ui/positions', label: 'Positions', icon: 'candles', match: /^\/ui\/positions/ },
  { href: '/ui/budgets', label: 'Budgets', icon: 'target', match: /^\/ui\/budgets/ },
  { href: '/ui/projections', label: 'Projections', icon: 'trend', match: /^\/ui\/projections/ },
  { href: '/ui/gifts', label: 'Gifts', icon: 'gift', match: /^\/ui\/gifts/ },
  { href: '/ui/giving', label: 'Giving', icon: 'heart', match: /^\/ui\/giving/ },
  { href: '/ui/taxes', label: 'Taxes', icon: 'tax', match: /^\/ui\/taxes/ },
  { href: '/ui/receipts', label: 'Receipts', icon: 'receipt', match: /^\/ui\/receipts/ },
  { href: '/ui/activity', label: 'Activity', icon: 'pulse', match: /^\/ui\/activity/ },
  { href: '/ui/alerts', label: 'Alerts', icon: 'bell', match: /^\/ui\/alerts/ },
];
export const ADMIN_NAV = [
  { href: '/ui/users', label: 'Users and Groups', icon: 'users', match: /^\/ui\/users/ },
  { href: '/ui/settings', label: 'Settings', icon: 'sliders', match: /^\/ui\/settings/ },
];

const THEMES = /** @type {const} */ ({
  dark: { next: 'light', icon: 'moon', label: 'Theme: dark' },
  light: { next: 'system', icon: 'bulb', label: 'Theme: light' },
  system: { next: 'dark', icon: 'palette', label: "Theme: the system's" },
});

/** @param {{ house: any }} p */
function HouseholdAvatar({ house }) {
  const av = house.avatar || {};
  if (av.kind === 'image') {
    return html`<span class="brand-av"><img src=${av.image} alt="" /></span>`;
  }
  return html`<span class="brand-av" style=${{ background: av.color || '#3b7a57' }}>${
    av.initials ||
    initials(house.name)
  }</span>`;
}

function PriceStatus() {
  const s = useApiLite('/prices/status', ['prices']);
  if (!s) return null;
  const when = s.lastRefresh ? ago(s.lastRefresh) : 'no prices yet';
  return html`<div class="price-status" data-tip=${
    s.stale
      ? 'Some prices are older than they should be'
      : 'Daily closes: prices are delayed, never live'
  }>
    <span class=${'dot' + (s.stale ? ' stale' : '')} aria-hidden="true"></span><span
      class="txt">Prices ${when}</span><span class="sr-only">${s.stale ? ' (stale)' : ''}</span>
  </div>`;
}

/**
 * A small loader for the frame's own figures.
 * @param {string} path
 * @param {string[]} kinds
 */
function useApiLite(path, kinds) {
  const sig = useApiLite.cache[path] ??= signal(null);
  const seen = kinds.map((k) => changes.value[k] || 0).join(',');
  useEffect(() => {
    api.get(path).then((v) => (sig.value = v), () => {});
  }, [seen]);
  return sig.value;
}
/** @type {Record<string, any>} */
useApiLite.cache = {};

/** @param {{ children: any, onSignOut: () => void }} p */
export function Frame({ children, onSignOut }) {
  const { path, route } = useLocation();
  const s = session.value;
  const me = s.user;
  const nav = me.admin ? [...NAV, ...ADMIN_NAV] : NAV;
  const t = title.value;
  const themeNow = THEMES[theme.value] || THEMES.dark;
  // The households that share something with you (S12.10.1): none, and the avatar opens nothing.
  const linked =
    /** @type {any[] | null} */ (useApiLite('/linked', ['share', 'links'])?.items ?? null);

  useEffect(() => {
    document.body.classList.toggle('privacy', privacy.value);
  }, [privacy.value]);

  const userMenu = (/** @type {MouseEvent} */ e) =>
    openMenu(e, [
      { label: 'Profile', onSelect: () => route('/ui/profile') },
      { label: 'Sign out', onSelect: onSignOut },
    ]);

  return html`<div class=${
    'app' + (collapsed.value ? ' collapsed' : '') +
    (helpOpen.value ? ' help-open' : '') + (tour.value ? ' touring' : '')
  }>
    <aside class="side" aria-label="Navigation">
      <div class="brand">
        ${
    linked?.length
      ? html`
        <button type="button" class="linklike" aria-haspopup="menu" aria-label="Linked households"
          data-tip="Linked households" onClick=${(/** @type {MouseEvent} */ e) =>
            openMenu(
              e,
              linked.map((/** @type {any} */ h) => ({
                label: h.name,
                href: `/ui/linked/${h.linkId}/`,
                target: `mk-linked-${h.linkId}`,
                content: html`<${HouseholdAvatar} house=${h} /><span><b>${h.name}</b><div
            class="small dim">${h.items} item${h.items === 1 ? '' : 's'} shared with you · synced ${
                  ago(h.syncedAt)
                }</div></span>`,
              })),
            )}><${HouseholdAvatar} house=${s.household} /></button>
      `
      : html`<${HouseholdAvatar} house=${s.household} />`
  }
        <div class="brand-text"><div class="brand-name">${s.household.name}</div>
          <div class="brand-ver">MoolaKata ${version} ${
    mockup
      ? html`<button type="button" class="pill-mock" aria-haspopup="menu" onClick=${(
        /** @type {MouseEvent} */ e,
      ) => {
        const at = /** @type {HTMLElement} */ (e.currentTarget);
        import('../mockup/menu.js').then((m) => m.openMockMenu(at, nav, route));
      }}>MOCK</button>`
      : dev
      ? html`<span class="pill-dev" data-tip="Dev mode: the rules are the same as production">DEV</span>`
      : null
  }</div></div>
      </div>
      ${
    updated.value
      ? html`<button type="button" class="pill-update" onClick=${() =>
        location.reload()}>MoolaKata was updated: reload</button>`
      : null
  }
      <button type="button" class="collapse-btn" aria-label=${
    collapsed.value ? 'Open the sidebar' : 'Collapse the sidebar'
  } aria-expanded=${collapsed.value ? 'false' : 'true'}
        onClick=${() => (collapsed.value = !collapsed.value)}><${Icon} name="chev" /></button>
      <nav>${
    nav.map((n) => {
      const active = n.match.test(path);
      const count = badges.value[n.label.toLowerCase()];
      return html`
        <a class=${'nav-item' + (active ? ' active' : '')} href=${n.href}
          aria-current=${active ? 'page' : undefined} data-tip=${collapsed.value
            ? n.label
            : undefined}>
                  <${Icon} name=${n.icon} /><span class="nav-label">${n.label}</span>${' '}
                  ${count ? html`<span class="nav-badge">${count}</span>` : null}</a>
      `;
    })
  }</nav>
      <div class="user-tile">
        <${Avatar} name=${me.displayName} image=${me.avatar} id=${me.id} />
        <button type="button" class="user-text linklike" style=${{
    color: 'inherit',
    textAlign: 'left',
  }}
          aria-haspopup="menu" onClick=${userMenu}><b>${me.displayName}</b><span>${me.username}</span></button>
        <button type="button" class="icon-btn" aria-label=${themeNow.label} data-tip=${themeNow.label}
          onClick=${() => {
    theme.value = /** @type {any} */ (themeNow.next);
    applyTheme();
    saveTheme(themeNow.next);
  }}><${Icon} name=${themeNow.icon} /></button>
      </div>
    </aside>
    <main id="main">
      ${helpOpen.value ? null : html`<${HelpCorner} />`}
      <div class="topbar">
        <h1>${
    (t.crumbs || []).map(([l, href]) =>
      html`<a class="crumb" href=${href}>${l}</a><span class="crumb" aria-hidden="true">›</span>`
    )
  }<span>${t.text}</span></h1>
        <${PriceStatus} />
        <button type="button" class="icon-btn" aria-pressed=${privacy.value ? 'true' : 'false'}
          aria-label=${privacy.value ? 'Show amounts' : 'Hide amounts (privacy mode)'}
          data-tip=${privacy.value ? 'Show amounts' : 'Hide amounts'}
          onClick=${() => (privacy.value = !privacy.value)}><${Icon} name=${
    privacy.value ? 'eye-off' : 'eye'
  } /></button>
      </div>
      <div class="content">${children}</div>
    </main>
    <${TourPane} />
    ${helpOpen.value ? html`<${HelpPane} />` : null}
  </div>`;
}
