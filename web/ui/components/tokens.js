// Profile › Access tokens (requirements S10.9.1): tokens an AI assistant uses to read, never
// change, what you can see through the MCP endpoint. Each is shown once, when it is made.
import { html } from '../app/html.js';
import { useList, useSubmit } from '../app/hooks.js';
import { ago, day } from '../app/format.js';
import { confirmAction } from './confirm.js';
import { Dialog, openDialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { Field, Select } from './fields.js';
import { Failed, Loading } from './bits.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, saveNow, useDraft } from './draft-form.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';

const endpoint = () => `${location.origin}/mcp`;

export function AccessTokens() {
  const res = useList('/profile/tokens');
  const rows = /** @type {any[]} */ (res.data);
  const revoke = useSubmit(async (/** @type {any} */ t) => {
    await saveNow((d) => d.remove(d.load(TokenRec, t)));
    toast(`${t.name}: revoked`);
    res.reload();
  });
  const make = () =>
    openDialog(NewToken, {}).then((made) => {
      if (!made) return;
      res.reload();
      openDialog(TokenShown, { made });
    });
  return html`
    <div class="card" id="access-tokens">
      <h3 data-help="access-tokens">Access tokens<span class="spacer"></span><button class="btn sm"
        onClick=${make}><${Icon} name="plus" /> New token</button></h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>Let an AI assistant read, never change,
        what you can see, through MCP at <code>${endpoint()}</code>.</p>
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !rows
        ? html`<${Loading} lines=${2} />`
        : !rows.length
        ? html`<p class="small dim">None yet.</p>`
        : rows.map((t) =>
          html`
            <div
              class="list-item"><div class="grow"><b>${t.name}</b><div class="small dim">${t
                  .scope === 'all'
                ? 'everything I can see'
                : t.items.map((/** @type {any} */ i) => i.name).join(', ')} · ${t.expired
                ? html`<span class="pill warn">expired</span>`
                : `expires ${day(t.expiresAt)}`} · ${t.lastUsedAt
                ? `last used ${ago(t.lastUsedAt)}`
                : 'never used'}</div></div><button class="btn sm danger" disabled=${revoke.busy}
                        onClick=${async () => {
                          if (
                            !(await confirmAction({
                              title: 'Revoke this token?',
                              yes: 'Yes, revoke',
                            }))
                          ) return;
                          revoke.run(t).catch(() => {});
                        }}>Revoke</button></div>
          `
        )}
    </div>
  `;
}

/** An access token (S10.9.1): made once, its secret in the save's answer alone. */
class TokenRec extends Record {
  /** @override */
  static prefix = 'Token';
  /** @override */
  static fields = FIELDS.TokenRecord;
}

/** @param {{ close: (v?: any) => void }} p */
function NewToken({ close }) {
  useDialogGuide('dialog-new-token');
  const accounts = useList('/accounts');
  const portfolios = useList('/portfolios');
  const f = useDraft((draft) => {
    draft.add(TokenRec, { name: '', scope: 'all', days: 90, items: [] });
  }, []);
  const rec = /** @type {TokenRec | undefined} */ (f.draft?.records[0]);
  const items = [
    ...(/** @type {any[]} */ (accounts.data) || []).map((a) => ({
      kind: 'account',
      id: a.id,
      name: a.name,
    })),
    ...(/** @type {any[]} */ (portfolios.data) || []).map((p) => ({
      kind: 'portfolio',
      id: p.id,
      name: `${p.name} (portfolio)`,
    })),
  ];
  const chosen = /** @type {any[]} */ (rec?.get('items') || []);
  const has = (/** @type {any} */ i) => chosen.some((x) => x.kind === i.kind && x.id === i.id);
  const pick = (/** @type {any} */ i, /** @type {boolean} */ on) =>
    rec?.set(
      'items',
      on
        ? [...chosen, { kind: i.kind, id: i.id }]
        : chosen.filter((x) => !(x.kind === i.kind && x.id === i.id)),
    );
  return html`
    <${DraftDialog} f=${f} title="New access token" close=${close} what="This token"
      label="Create token" saved=${(/** @type {any} */ o) => {
        const { secret, ...token } = o.saved[0].record;
        close({ token, secret });
      }}>
      <p class="small dim" style=${{ marginTop: 0 }}>For an AI assistant or another tool that
        speaks MCP. It can read, never change, and only what you choose here.</p>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Token name" placeholder="Claude on my laptop" />
          <${Field} label="Can read" error=${rec.error('scope') || rec.error('items')}
            hint="Never secrets, Settings or linked households.">
            <${Select} value=${rec.get('scope')} onChange=${(/** @type {string} */ v) =>
              rec.set('scope', v)} options=${[
              ['all', 'Everything I can see'],
              ['chosen', 'Chosen items…'],
            ]} />
          </${Field}>
          ${rec.get('scope') === 'chosen'
            ? html`<div class="field" data-help="chosen-items" style=${{
              maxHeight: '220px',
              overflow: 'auto',
            }}>${
              items.map((i) =>
                html`<label class="list-item" style=${{ cursor: 'pointer' }}><input
                  type="checkbox" checked=${has(i)} onChange=${(/** @type {any} */ ev) =>
                  pick(i, ev.currentTarget.checked)} /><span class="grow">${i.name}</span></label>`
              )
            }</div>`
            : null}
          <${RecField} rec=${rec} name="days" label="Expires" options=${[
            ['30', 'In 30 days'],
            ['90', 'In 90 days'],
            ['365', 'In a year'],
          ]} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** @param {{ close: (v?: any) => void, made: any }} p */
function TokenShown({ close, made }) {
  useDialogGuide('dialog-token-shown');
  return html`
    <${Dialog} title="Your new access token" close=${close} onSubmit=${() => close(true)}
      note="It is shown once and can't be shown again."
      footer=${html`
        <button type="button" class="btn" onClick=${() =>
          navigator.clipboard?.writeText(made.secret).then(() => toast('Copied'))}>Copy</button>
        <button class="btn primary">Done</button>
      `}>
      <div class="notice" style=${{ marginBottom: '12px' }}>
        <${Icon} name="alert" />
        <div>Copy it
        now. Anyone with it can read what it can until it expires or you revoke it.</div>
      </div>
      <div class="field"
        data-help="token"><label>Token</label><code class="mono" style=${{
          display: 'block',
          padding: '10px 12px',
          background: 'var(--bg-3)',
          borderRadius: '8px',
        }}>${made.secret}</code></div>
      <p class="small dim">Use it with the MCP endpoint <code>${endpoint()}</code>, as a bearer
        token: <code>Authorization: Bearer mkt_…</code>.</p>
      </${Dialog}>
  `;
}
