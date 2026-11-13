// The account groups (S1.1): each one's icon, its name, and its tile.
import { html } from '../app/html.js';
import { Icon } from '../kit/icon.js';

export const GROUP_ICONS = {
  banking: 'bank',
  investing: 'candles',
  retirement: 'retire',
  education: 'grad',
  crypto: 'coin',
  giving: 'heart',
  liabilities: 'card',
  'physical-assets': 'gem',
};
export const GROUP_LABELS = {
  banking: 'Banking',
  investing: 'Investing',
  retirement: 'Retirement',
  education: 'Education',
  crypto: 'Crypto',
  giving: 'Giving',
  liabilities: 'Liabilities',
  'physical-assets': 'Physical assets',
};
const TILE =
  /** @type {Record<string, string>} */ ({ liabilities: 'liability', 'physical-assets': 'other' });

/** @param {{ group: string, icon?: string }} p */
export function Tile({ group, icon }) {
  const g = /** @type {Record<string, string>} */ (GROUP_ICONS);
  return html`
    <div class=${`tile t-${TILE[group] || group}`}>
      <${Icon} name=${icon || g[group] || 'bank'} />
    </div>
  `;
}
