// Portfolios (requirements S5.1, S12.2.4): the user's portfolios and those shared with them, with
// All my accounts first.
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Avatar, Failed, Loading, Tile } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { openDialog } from '../components/dialog.js';
import { PortfolioDialog } from './portfolio-dialog.js';

export default function Portfolios() {
  useTitle('Portfolios');
  useGuide('portfolios');
  const { route } = useLocation();
  const res = useList('/portfolios', {}, ['share', 'prices', 'import']);
  const list = /** @type {any[] | null} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!list) return html`<${Loading} lines=${4} />`;
  return html`
    <div class="toolbar"><span class="spacer"></span><button type="button" class="btn primary"
        onClick=${() =>
          openDialog(PortfolioDialog, {}).then((p) => p && route(`/ui/portfolios/${p.id}`))}>
        <${Icon} name="plus" /> New portfolio</button></div>
    <div class="grid g2">${list.map((p) =>
      html`<a class="card" href=${`/ui/portfolios/${p.id}`} style=${{ color: 'inherit' }}>
      <h3><${Tile} group="investing" icon="pie" /><div><div>${p.name}</div><div class="small dim" style=${{
        fontWeight: 400,
      }}>${
        p.implicit
          ? 'Your accounts, and shared ones you count'
          : `${p.accountIds.length} account${p.accountIds.length === 1 ? '' : 's'}`
      }</div></div><span class="spacer"></span>
        ${
        p.access.mine
          ? p.sharedWith
            ? html`<span class="mark" data-tip="Shared by me"><${Icon} name="share" /> ${p.sharedWith}</span>`
            : null
          : html`<span class="mark" data-tip=${`Shared with me by ${p.ownerName} (${
            p.access.writable ? 'write' : 'read'
          })`}><${Avatar} sm name=${p.ownerName}
            image=${p.ownerAvatar} id=${p.ownerId} /><${Icon} name=${
            p.access.writable ? 'pencil' : 'eye'
          } label=${p.access.writable ? 'write' : 'read'} /></span>`
      }</h3>
      <div style=${{
        fontSize: '22px',
        fontWeight: 650,
      }}><${Amt} v=${p.value} cents=${false} /></div></a>`
    )}</div>
  `;
}
