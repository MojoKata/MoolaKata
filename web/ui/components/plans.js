// The projections built on one portfolio or one account (requirements S6.8.2): shown on its
// own page, beside the Projections screen.
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { Empty } from '../kit/state.js';

const TONE =
  /** @type {Record<string, string>} */ ({ 'on track': 'ok', ahead: 'ok', behind: 'warn' });

/**
 * @param {{ kind: 'portfolio' | 'account', id: string, all?: boolean }} p  all: scenarios too
 */
export function PlansFor({ kind, id, all = false }) {
  const res = useList('/projections', {}, ['share']);
  const rows = (/** @type {any[]} */ (res.data) || []).filter((r) =>
    (all || r.active) &&
    (kind === 'portfolio'
      ? r.builtOn.kind === 'portfolio' && r.builtOn.id === id
      : r.builtOn.kind === 'accounts' && r.builtOn.ids?.length === 1 && r.builtOn.ids[0] === id)
  );
  if (!rows.length) {
    return all ? html`<${Empty}>No projection built on it yet</${Empty}>` : null;
  }
  return html`
    <div class="card"><h3>${all ? 'Projections' : 'Plan'}</h3>
      ${rows.map((r) =>
        html`<a class="list-item" href=${`/ui/projections/${r.id}`} style=${{ color: 'inherit' }}>
          <div class="grow"><span class="row-name">${r.name}</span> ${
          r.active
            ? html`<span class=${'pill ' + (TONE[r.status] || '')}>${
              r.status && r.status !== 'untracked' ? r.status : 'active'
            }</span>`
            : html`<span class="pill">scenario</span>`
        }<div class="row-more">${r.headline}</div></div></a>`
      )}
    </div>
  `;
}
