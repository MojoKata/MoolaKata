// Making or changing a portfolio (requirements S5.1): its name, accounts and benchmark.
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useList } from '../app/hooks.js';
import { useDialogGuide } from '../components/help.js';
import { Record } from '../app/draft.js';
import { DraftDialog, RecField, useDraft } from '../components/draft-form.js';
import { FIELDS } from '../api/fields.js';
import { toast } from '../components/toast.js';

export const BENCHMARKS = /** @type {[string, string][]} */ ([
  ['VT', 'VT (world stocks)'],
  ['SPY', 'SPY (US large companies)'],
  ['60-40', '60/40: VT and BND'],
]);

/** A portfolio (S5.1), as its dialog's draft edits it. */
class PortfolioRec extends Record {
  /** @override */
  static prefix = 'Portf';
  /** @override */
  static fields = FIELDS.PortfolioRecord;
  /** @override */
  static defaults = { accountIds: [], benchmark: 'VT' };
}

/** @param {{ close: (v?: any) => void, portfolio?: any }} p */
export function PortfolioDialog({ close, portfolio }) {
  useDialogGuide('dialog-portfolio');
  const accounts = useList('/accounts');
  const f = useDraft(async (draft) => {
    if (portfolio) draft.load(PortfolioRec, await api.get(`/portfolios/${portfolio.id}`));
    else draft.add(PortfolioRec, { name: '' });
  }, [portfolio?.id]);
  const rec = /** @type {PortfolioRec | undefined} */ (f.draft?.records[0]);
  const list = /** @type {any[]} */ (accounts.data) || [];
  // Only the owner chooses the accounts (S5.1): what a portfolio covers is a setting.
  const owner = !portfolio || portfolio.access.configurable;
  const ids = new Set(/** @type {string[]} */ (rec?.get('accountIds') || []));
  return html`
    <${DraftDialog} f=${f} title=${portfolio ? 'Portfolio' : 'New portfolio'} close=${close}
      what="This portfolio" saved=${(/** @type {any} */ o) => {
        toast('Saved');
        close(o.saved[0]?.record || true);
      }}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name" />
          ${owner
            ? html`
              <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
                <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Accounts</legend>
                ${list.map((a) =>
                  html`<label class="list-item" style=${{ cursor: 'pointer' }}><input
                    type="checkbox" checked=${ids.has(a.id)} onChange=${() => {
                    const next = new Set(ids);
                    next.has(a.id) ? next.delete(a.id) : next.add(a.id);
                    rec.set('accountIds', [...next]);
                  }} /><span class="grow">${a.name} <span class="small dim">${
                    a.institution || ''
                  }</span></span>${
                    !a.access.mine ? html`<span class="pill">shared</span>` : null
                  }</label>`
                )}
                ${rec.error('accountIds')
                  ? html`<div class="err">${rec.error('accountIds')}</div>`
                  : null}
              </fieldset>
            `
            : null}
          <${RecField} rec=${rec} name="benchmark" label="Benchmark" options=${BENCHMARKS}
            hint="What Performance compares it with, given the same money at the same times." />
        `
        : null}
    </${DraftDialog}>
  `;
}
