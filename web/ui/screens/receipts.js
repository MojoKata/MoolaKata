// Receipts (requirements S9): drop files to upload them, the inbox of receipts attached to
// nothing yet, search, and a grid of thumbnails that open each receipt.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Chips, Empty, Failed, Loading } from '../kit/bits.js';
import { Icon } from '../kit/icon.js';
import { openDialog } from '../kit/dialog.js';
import { ACCEPT, ReceiptCard, ReceiptDialog, uploadAll } from '../components/receipt.js';

export default function Receipts() {
  useTitle('Receipts');
  useGuide('receipts');
  const [show, setShow] = useState('all');
  const [q, setQ] = useState('');
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const res = useList('/receipts', { show, q: q || undefined }, ['receipt']);
  const rows = /** @type {any[]} */ (res.data);
  const send = async (/** @type {FileList | File[]} */ files) => {
    if (!files.length) return;
    setBusy(true);
    const made = await uploadAll(files);
    setBusy(false);
    res.reload();
    if (made.length === 1) openDialog(ReceiptDialog, { id: made[0].id }).then(res.reload);
  };
  return html`
    <label class=${'drop' + (over ? ' over' : '')} for="f-receipt-files"
      onDragOver=${(/** @type {DragEvent} */ e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave=${() => setOver(false)}
      onDrop=${(/** @type {DragEvent} */ e) => {
        e.preventDefault();
        setOver(false);
        send(e.dataTransfer?.files || []);
      }}>
      <${Icon} name="upload" />
      <div style=${{ marginTop: '6px' }}><b>${busy
        ? 'Uploading…'
        : 'Drop PDFs or photos here'}</b>, or click to choose.</div>
      <div
        class="small">PDF, JPEG, PNG, WebP, HEIC (iPhone photos) · kept encrypted on this server</div>
      <input id="f-receipt-files" class="sr-only" type="file" multiple accept=${ACCEPT}
        onChange=${(/** @type {any} */ e) => {
          send(e.currentTarget.files);
          e.currentTarget.value = '';
        }} />
    </label>
    <div class="toolbar mt">
      <${Chips} label="Show" value=${show} onChange=${setShow}
        options=${[['all', 'All'], ['inbox', 'Inbox']]} />
      ${rows?.some((r) => r.readStatus === 'waiting' || r.readStatus === 'reading')
        ? html`<span class="pill info">${
          rows.filter((r) => r.readStatus === 'waiting' || r.readStatus === 'reading').length
        } being read</span>`
        : null}<span class="spacer"></span>
      <input class="in" style=${{ maxWidth: '280px' }} id="f-search" value=${q}
        placeholder="Search the receipts' text, payee, amount…" aria-label="Search receipts"
        onInput=${(/** @type {any} */ e) => setQ(e.currentTarget.value)} />
    </div>
    ${res.error
      ? html`<${Failed} error=${res.error} />`
      : !rows
      ? html`<${Loading} lines=${4} />`
      : !rows.length
      ? html`<${Empty}>${
        show === 'inbox' ? 'The inbox is empty' : q ? 'No receipt matches' : 'No receipts yet'
      }</${Empty}>`
      : html`<div class="receipts mt">${
        rows.map((r) =>
          html`<${ReceiptCard} r=${r} onOpen=${() =>
            openDialog(ReceiptDialog, { id: r.id }).then(res.reload)} />`
        )
      }</div>`}
  `;
}
