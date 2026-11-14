// Alerts (requirements S12.11): open ones first, newest first, then those resolved in the last
// 90 days. Opening the screen marks them seen, which clears the badge.
import { useEffect } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi } from '../app/hooks.js';
import { refreshBadges } from '../app/stream.js';
import { moment } from '../kit/format.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Empty, Failed, Loading } from '../kit/bits.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';

const EMAILS = /** @type {Record<string, string>} */ ({
  each: 'each alert',
  daily: 'a daily summary',
  none: 'none',
});

export default function Alerts() {
  useTitle('Alerts');
  useGuide('alerts');
  const res = useApi('/alerts', {}, ['alert']);
  const d = /** @type {any} */ (res.data);
  const unseen = d ? d.open.filter((/** @type {any} */ a) => !a.seen).length : 0;
  useEffect(() => {
    if (unseen) api.post('/alerts/seen').then(refreshBadges, () => {});
  }, [unseen]);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!d) return html`<${Loading} lines=${5} />`;
  const dismiss = (/** @type {any} */ a) =>
    api.post(`/alerts/${a.id}/dismiss`).then(() => {
      toast('Dismissed for you');
      res.reload();
    }, (e) => toast(e.message));
  const row = (/** @type {any} */ a) =>
    html`
      <div class="list-item" style=${{ alignItems: 'flex-start' }}>
        <div class=${'tile ' + (a.resolvedAt ? 't-other' : 't-liability')}><${Icon} name=${a
          .icon} /></div>
        <div class="grow"><b>${a.title}</b>
          <div class="small dim">${a.about ? a.about + ' · ' : ''}opened ${moment(a.openedAt)}${a
              .resolvedAt
            ? ` · resolved ${moment(a.resolvedAt)}${a.resolution ? ': ' + a.resolution : ''}`
            : ''}</div></div>
        ${a.resolvedAt
          ? html`<span class="pill ok">resolved</span>`
          : html`${
            a.link ? html`<a class="btn sm" href=${a.link}>${a.fix || 'See It'}</a>` : null
          }<button type="button" class="btn sm" onClick=${() => dismiss(a)}>Dismiss</button>`}
      </div>
    `;
  return html`
    <div class="card"><h3>Open</h3>
      ${d.open.length ? d.open.map(row) : html`<${Empty}>Nothing needs you</${Empty}>`}</div>
    <div class="card mt"><h3>Resolved<span class="spacer"></span><span class="small dim"
      style=${{ fontWeight: 400 }}>kept 90 days</span></h3>
      ${d.resolved.length
        ? d.resolved.map(row)
        : html`<${Empty}>None in the last 90 days</${Empty}>`}</div>
    <p class="small dim">Emails: ${EMAILS[d.emails] || d.emails} · change it in <a
      href="/ui/profile">Profile</a>.</p>
  `;
}
