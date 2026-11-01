// A receipt (requirements S9): its card in a grid, uploading files, and the dialog that shows
// one with its fields, what it is attached to, and the transactions it may belong to.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { date, day, money } from '../app/format.js';
import { useDialogGuide } from './help.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { Record as Rec } from '../app/draft.js';
import { DraftDialog, RecField, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { TagsField } from './tags.js';
import { confirmAction } from './confirm.js';

export const ACCEPT = 'application/pdf,image/jpeg,image/png,image/webp,image/heic,.heic';
const KIND = /** @type {Record<string, string>} */ ({
  'application/pdf': 'PDF',
  'image/jpeg': 'JPG',
  'image/png': 'PNG',
  'image/webp': 'WebP',
  'image/heic': 'HEIC',
});

/**
 * Uploads files one request each, so a batch works through them; returns what was made.
 * @param {FileList | File[]} list
 */
export async function uploadAll(list) {
  const made = [];
  for (const f of [...list]) {
    try {
      made.push(await api.upload('/receipts', f));
    } catch (e) {
      toast(`${f.name}: ${/** @type {any} */ (e).message}`);
    }
  }
  if (made.length) toast(`Uploaded ${made.length} receipt${made.length === 1 ? '' : 's'}`);
  return made;
}

/**
 * A picture from the API, fetched with the session and shown from memory: thumbnails and
 * photos load the way every other answer does.
 * @param {{ src: string, alt: string, class?: string }} p
 */
export function ApiImg({ src, alt, class: cls }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    let made = '';
    let live = true;
    fetch(src, { credentials: 'same-origin' }).then((r) => (r.ok ? r.blob() : null)).then((b) => {
      if (live && b) setUrl(made = URL.createObjectURL(b));
    }, () => {});
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [src]);
  return url ? html`<img src=${url} alt=${alt} class=${cls} />` : null;
}

/** @param {{ r: any, onOpen: () => void }} p */
export function ReceiptCard({ r, onOpen }) {
  return html`
    <button type="button" class="receipt" onClick=${onOpen} aria-label=${'Receipt ' +
      (r.payee || r.fileName)}>
      <div class="thumb"><span class="pill kind">${KIND[r.mediaType] || ''}</span>
        ${r.hasThumbnail
          ? html`<${ApiImg} src=${`/ui/api/receipts/${r.id}/thumbnail`} alt="" />`
          : html`<div class="paper"><i></i><i style=${{ width: '70%' }}></i><i></i><i style=${{
            width: '50%',
          }}></i></div>`}</div>
      <div class="meta">
        <div class="ellipsis" style=${{ fontWeight: 550 }}>${r.payee ||
          r.fileName}</div>
        <div class="dim">${r.date ? date(r.date) : day(r.uploadedAt)}${r.amount
          ? html`
            ${'\u00a0· '}<span class="amt">${money(r.amount)}</span>
          `
          : ''}</div>
        <div style=${{
          marginTop: '4px',
        }}>${r.readStatus === 'waiting' || r.readStatus === 'reading'
          ? html`<span class="pill info">Reading…</span>`
          : r.readStatus === 'failed'
          ? html`<span class="pill bad">couldn't read it</span>`
          : r.links.length
          ? html`<span class="pill ok">${r.links[0].accountName || r.links[0].label}${
            r.links.length + r.alsoKeptWith > 1 ? ` +${r.links.length + r.alsoKeptWith - 1}` : ''
          }</span>`
          : r.alsoKeptWith
          ? html`<span class="pill ok">kept with ${r.alsoKeptWith} not shared</span>`
          : html`<span class="pill warn">inbox</span>`}</div>
      </div>
    </button>
  `;
}

/** A receipt (S9.8), as its dialog's draft edits it: what was read or typed, and Keep. */
class ReceiptRec extends Rec {
  /** @override */
  static prefix = 'Rcpt';
  /** @override */
  static fields = FIELDS.ReceiptRecord;
}

/** What a receipt is attached to (S9.3): made or taken away, never changed. */
export class ReceiptLinkRec extends Rec {
  /** @override */
  static prefix = 'RcLnk';
  /** @override */
  static fields = FIELDS.ReceiptLinkRecord;
}

/**
 * One receipt: the picture or PDF, its fields, and what it is attached to, a draft saved
 * together: attaching and detaching are its links made and taken away.
 * @param {{ close: (v?: any) => void, id: string }} p
 */
export function ReceiptDialog({ close, id }) {
  useDialogGuide('dialog-receipt');
  const res = useApi(`/receipts/${id}`, {}, ['receipt']);
  const r = /** @type {any} */ (res.data);
  const f = useDraft(async (draft) => {
    const got = await api.get(`/receipts/${id}`);
    draft.load(ReceiptRec, got);
    for (const l of got.links) {
      if (!l.id) continue; // a tax document's file: kept with the document
      const data = { id: l.id, version: l.version, receiptId: id, kind: l.kind, itemId: l.itemId };
      draft.load(ReceiptLinkRec, data);
    }
  }, [id]);
  const rec = /** @type {ReceiptRec | undefined} */ (f.draft?.get(id) ?? undefined);
  // What reading fills in comes into the draft while nothing in it has changed.
  useEffect(() => {
    if (r && rec && !f.draft?.changed && rec.version !== r.version) f.reload();
  }, [r?.version]);
  const again = useSubmit(async () => {
    await api.post(`/receipts/${id}/read`);
    toast('Queued to read again');
    res.reload();
  });
  // The dialog opens once the receipt has come, so its first field takes the focus.
  if (!r || !rec || !f.draft) return null;
  const draft = f.draft;
  const linkRecs = /** @type {ReceiptLinkRec[]} */ (
    draft.records.filter((x) => x instanceof ReceiptLinkRec && !x.removed)
  );
  // What it stays attached to, then what this draft attaches: a match it was offered.
  const kept = r.links.filter((/** @type {any} */ l) =>
    !l.id || linkRecs.some((x) => x.id === l.id)
  );
  const added = linkRecs.filter((x) => x.state === 'new').map((x) => {
    const m = r.matches.find((/** @type {any} */ m) => m.transactionId === x.get('itemId'));
    return { ...m, rec: x, canDetach: true };
  });
  const attach = (/** @type {string} */ tid) =>
    draft.add(ReceiptLinkRec, { receiptId: id, kind: 'transaction', itemId: tid });
  const detach = (/** @type {any} */ l) => {
    const x = l.rec || draft.get(l.id);
    if (x) draft.remove(x);
  };
  const canEdit = r.access.writable;
  const reading = r.readStatus === 'waiting' || r.readStatus === 'reading';
  /** "Read from the receipt" under a field still holding what was read from it. */
  const hint = (/** @type {string} */ field, /** @type {string} */ key) =>
    r.filled.includes(field) && r.suggested[key]
      ? `Read from the receipt · ${r.suggested[key].confidence}% sure`
      : undefined;
  const file = `/ui/api/receipts/${id}/file`;
  return html`
    <${DraftDialog} f=${f} title=${r.fileName} wide close=${close} what="This receipt"
      done=${rec.removed ? 'Receipt deleted' : 'Saved'} hideSave=${!canEdit}
      extra=${({ save }) =>
        r.access.deletable
          ? html`
            <button type="button" class="btn danger" style=${{ marginRight: 'auto' }}
              disabled=${save.busy || r.links.length > 0 || r.alsoKeptWith > 0 ||
                linkRecs.length > 0}
              title=${r.links.length || linkRecs.length
                ? 'Detach it first'
                : r.alsoKeptWith
                ? 'It is kept with something not shared with you'
                : undefined} onClick=${async () => {
                const draft = f.draft;
                if (!draft) return;
                if (!(await confirmAction({ title: 'Delete this receipt?' }))) return;
                draft.remove(rec);
                const o = await save.run().catch(() => null);
                if (o?.status !== 'asks' && o?.status !== 'saved') draft.unremove(rec);
              }}>Delete</button>
          `
          : null}>
      <div class="split" style=${{ alignItems: 'flex-start' }}>
        <div class="receipt-view">
          ${r.filePrunedAt
            ? html`
              <div class="notice" role="note">
                <${Icon} name="info" />
                <div>${r.kept}: its
                            record keeps its amounts, dates and links.</div>
              </div>
            `
            : r.mediaType === 'application/pdf'
            ? html`<a href=${file} target="_blank" rel="noopener" class="pdf-open">
              ${
              r.hasThumbnail
                ? html`
                  <${ApiImg} src=${`/ui/api/receipts/${id}/thumbnail`}
                    alt="The PDF's first page" />
                `
                : null
            }
              <span class="btn sm"><${Icon} name="download" /> Open the PDF</span></a>`
            : html`<a href=${file} target="_blank" rel="noopener" title="Open full size"><${ApiImg}
              src=${file} alt=${'Receipt ' + r.fileName} /></a>`}
          ${r.text
            ? html`
              <details class="mt">
                <summary class="small">Text read from the receipt (searchable)</summary>
                <div class="ocr-text mt">${r.text}</div>
              </details>
            `
            : null}
          <div class="toolbar mt" style=${{
            margin: '8px 0 0',
          }}><span class="small dim">${r.readMethod ===
              'text'
            ? "Read from the PDF's text layer"
            : r.readMethod === 'ocr'
            ? 'Read with OCR'
            : ''}${r.suggested.card ? ` · card ending ${r.suggested.card.value}` : ''}</span>
            <span class="spacer"></span>${canEdit && !reading
              ? html`
                <button type="button" class="btn sm" disabled=${again.busy}
                  onClick=${() =>
                    again.run().catch((e) =>
                      toast(e.message)
                    )}><${Icon} name="refresh" /> Read again</button>
              `
              : null}</div>
          ${r.filePrunedAt ? null : html`
            <${RecField} rec=${rec} name="keep" label="Keep" hint=${rec.get('keep')
              ? 'Kept for ever, whatever its retention.'
              : html`${r.keptSoon ? html`<b>${r.kept}</b>` : r.kept}${
                r.keptWhy ? ` · ${r.keptWhy}` : ''
              }`} disabled=${!canEdit} />
          `}
          <p class="small dim">${KIND[r.mediaType]} · ${(r.size / 1024).toFixed(
            0,
          )} KB · uploaded ${day(r.uploadedAt)}${!r.access.mine ? ` by ${r.ownerName}` : ''}</p>
        </div>
        <div style=${{ flex: '0 1 280px' }}>
          ${reading
            ? html`
              <div class="notice" role="status">
                <${Icon} name="refresh" />
                <div>Reading this receipt on
                            the server. The fields fill in when it's done; you can type them now.</div>
              </div>
            `
            : r.readStatus === 'failed'
            ? html`
              <div class="notice bad" role="status">
                <${Icon} name="alert" />
                <div>Couldn't read it: ${r
                  .readError}. Type the fields by hand.</div>
              </div>
            `
            : null}
          <div class="row">
            <${RecField} rec=${rec} name="date" label="Date" id="receipt-date" type="date"
              hint=${hint('date', 'date')} disabled=${!canEdit} />
            <${RecField} rec=${rec} name="amount" label="Amount" id="receipt-amount"
              hint=${hint('amount', 'total')} disabled=${!canEdit} />
          </div>
          <${RecField} rec=${rec} name="payee" label="Payee" id="receipt-payee"
            hint=${hint('payee', 'merchant')} disabled=${!canEdit} />
          <${RecField} rec=${rec} name="notes" label="Notes" id="receipt-notes"
            disabled=${!canEdit} />
          ${f.draft
            ? html`
              <${TagsField} rec=${rec} draft=${f.draft} id="receipt-tags"
                hint="Yours only, separated by commas." disabled=${!canEdit} />
            `
            : null}
          <h4 class="small dim" data-help="attached-to" id="x-attached-to">Attached to</h4>
          ${kept.length || added.length
            ? [...kept, ...added].map((/** @type {any} */ l) =>
              html`<div class="list-item"><div class="grow small">${
                l.transactionId
                  ? html`
                    ${l.payee || 'Transaction'} · <span class="amt">${money(l.amount)}</span><div
                      class="dim">${l.accountName} · ${date(l.date)}${l.rec
                        ? ' · attached when you save'
                        : ''}</div>
                  `
                  : l.label
              }</div>${
                l.canDetach && canEdit
                  ? html`<button type="button" class="btn sm" onClick=${() =>
                    detach(l)}>Detach</button>`
                  : null
              }</div>`
            )
            : r.alsoKeptWith
            ? null
            : html`<p class="small dim">Nothing yet: it waits in the inbox.</p>`}
          ${r.alsoKeptWith
            ? html`
              <p class="small dim"
                id="x-also-kept">Also kept with ${r.alsoKeptWith} ${r
                    .alsoKeptWith === 1
                  ? 'thing'
                  : 'things'} not shared with you.</p>
            `
            : null}
          ${r.matches.length && !added.length && canEdit
            ? html`
              <div class="notice mt">
                <${Icon} name="clip" />
                <div><b>Attach to</b> ${r.matches[0].payee || 'a transaction'} · ${money(
                  r.matches[0].amount,
                )} · ${date(r.matches[0].date)} · ${r.matches[0].accountName}?
                            <div class="toolbar" style=${{ margin: '8px 0 0' }}>${r.matches.map((
                              /** @type {any} */ m,
                              /** @type {number} */ i,
                            ) =>
                              html`
                                <button type="button" class=${'btn sm' + (i ? '' : ' primary')}
                                  onClick=${() => attach(m.transactionId)}>${i
                                    ? `${m.payee || 'Transaction'} · ${date(m.date)}`
                                    : 'Attach'}</button>
                              `
                            )}</div></div>
              </div>
            `
            : !kept.length && !added.length
            ? html`<p class="small dim">${
              r.amount
                ? 'No transaction of this amount within five days of its date yet. Attach it from the transaction when it arrives.'
                : 'Give it a date and amount to find the transaction it belongs to, or attach it from the transaction itself.'
            }</p>`
            : null}
        </div>
      </div>
      </${DraftDialog}>
  `;
}
