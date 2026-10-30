// Importing a file into an account (requirements S1.3.2–S1.3.3): OFX, QFX or CSV, or a
// statement (a PDF or a photo of one) read on the server and checked before it is saved. A CSV
// from an institution seen for the first time asks for its columns, then remembers them.
import { useEffect, useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { changes } from '../app/stream.js';
import { cents, date, fromCents, money } from '../app/format.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { TransactionDialog } from './transaction-dialog.js';
import { useDialogGuide } from '../components/help.js';
import { errAt, Field, FormError, Input, Select } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import { toast } from '../components/toast.js';

/**
 * Wait for a job to finish: the live stream says when, and a slow poll covers a lost event.
 * @param {string} id
 */
async function finished(id) {
  for (let i = 0; i < 600; i++) {
    const job = await api.get(`/jobs/${id}`);
    if (job.state === 'done' || job.state === 'failed') return job;
    await new Promise((r) => setTimeout(r, i < 10 ? 200 : 1000));
  }
  throw new Error('The import is taking too long; it carries on, and its result shows later.');
}

// The columns a mapping names; the last five, a trade history's, only for an account that holds
// instruments (S1.3.2).
const COLUMNS = /** @type {[string, string, string, boolean?][]} */ ([
  ['date', 'Date column', 'The posting or trade date.'],
  ['payee', 'Description column', 'The payee, merchant or description.'],
  ['amount', 'Amount column', 'One column with + for money in and − for money out.'],
  ['debit', 'Debit column', 'If money out has its own column.'],
  ['credit', 'Credit column', 'If money in has its own column.'],
  ['balance', 'Running balance column', 'Optional: every row then checks the balance.'],
  ['memo', 'Memo column', 'Optional.'],
  ['id', 'Transaction id column', "Optional: the institution's own id for each row."],
  ['action', 'Action column', 'What each row is: a buy, a sale, a dividend, a transfer.', true],
  ['symbol', 'Symbol column', 'The ticker, fund symbol or coin traded.', true],
  ['quantity', 'Quantity column', 'Shares or coins.', true],
  ['price', 'Price column', 'Optional: the price per share or coin.', true],
  ['fees', 'Fees column', 'Optional: commission, fees or spread.', true],
]);

/** @param {{ close: (v?: any) => void, accounts: any[], accountId?: string }} p */
export function ImportDialog({ close, accounts, accountId }) {
  useDialogGuide('dialog-import');
  const writable = accounts.filter((a) => a.level !== 'read');
  const [target, setTarget] = useState(accountId || writable[0]?.id || '');
  const [file, setFile] = useState(/** @type {File | null} */ (null));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {any} */ (null));
  const [result, setResult] = useState(/** @type {any} */ (null));
  const [mapping, setMapping] = useState(/** @type {any} */ (null));
  const [review, setReview] = useState(/** @type {any} */ (null));
  // A statement kept as it is, without its lines (S1.3.3.6): asked for, or offered when its
  // lines can't be read.
  const [keeping, setKeeping] = useState(false);
  const [kept, setKept] = useState(/** @type {any} */ (null));
  // The upload the server holds for this dialog, let go as soon as the dialog closes
  // (S13.7.6) rather than when it expires.
  const held = useRef(/** @type {string | null} */ (null));
  held.current = mapping?.uploadId || review?.uploadId || kept?.uploadId || error?.uploadId ||
    null;
  useEffect(() => () => {
    if (held.current) api.del(`/imports/${held.current}`).catch(() => {});
  }, []);

  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const path = keeping ? `/accounts/${target}/statements/keep` : `/accounts/${target}/imports`;
      const job = await finished((await api.upload(path, file)).id);
      if (job.state === 'failed') setError({ ...job.error });
      else if (job.result.keep) setKept(job.result);
      else if (job.result.needsMapping) setMapping(job.result);
      else if (job.result.parts) setReview({ ...job.result, at: 0 });
      else if (job.result.kind === 'brokerage') {
        setReview({
          ...job.result,
          activity: job.result.activity.map((/** @type {any} */ r) => ({
            ...r,
            include: !r.notRead && !r.ignored,
          })),
        });
      } else if (job.result.needsReview) {
        setReview({
          ...job.result,
          rows: job.result.rows.map((/** @type {any} */ r) => ({
            ...r,
            include: r.present || !r.ignored,
          })),
          accept: false,
        });
      } else setResult(job.result);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const applyMapping = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await finished(
        (await api.post(`/imports/${mapping.uploadId}/mapping`, {
          mapping: mapping.mapping,
          save: true,
        })).id,
      );
      if (job.state === 'failed') setError({ message: job.error.message });
      else {
        setMapping(null);
        setResult(job.result);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (result) changes.value = { ...changes.value, import: (changes.value.import || 0) + 1 };
  }, [result]);

  if (result) {
    return html`<${Dialog} title="Imported" close=${close} footer=${html`
      <button type="button"
        class="btn primary" onClick=${() => {
          toast(`${result.added} new transactions`);
          close(result);
        }}>Done</button>
    `}>
      <div class="kv">
        <div><div class="k">New</div><div class="v">${result.added}</div></div>
        <div><div class="k">Already here</div><div class="v">${result.matched}</div></div>
        <div><div class="k">Changed since last time</div><div class="v">${result.changed}</div></div>
        <div><div class="k">Transfers matched</div><div class="v">${result.transfers}</div></div>
      </div>
      <p class="small dim">Covers ${date(result.coveredFrom)} to ${
      date(result.coveredTo)
    }. Importing the
        same file again adds nothing.</p>
      ${result.warnings.map((/** @type {string} */ w) => html`<div class="notice warn">${w}</div>`)}
    </${Dialog}>`;
  }

  if (kept) return html`<${KeepReview} kept=${kept} close=${close} />`;

  if (review?.kind === 'brokerage') {
    return html`
      <${BrokerageReview} review=${review} setReview=${setReview} close=${close}
        accounts=${accounts} done=${(/** @type {any} */ r) => {
          setReview(null);
          setResult(r);
        }} />
    `;
  }

  if (review?.parts) {
    return html`<${PartsReview} review=${review} setReview=${setReview} close=${close} />`;
  }

  if (review) {
    return html`
      <${StatementReview} review=${review} setReview=${setReview} close=${close}
        done=${(/** @type {any} */ r) => {
          setReview(null);
          setResult(r);
        }} />
    `;
  }

  if (mapping) {
    const headers = [['', '(none)'], ...mapping.headers.map((/** @type {string} */ h) => [h, h])];
    const m = mapping.mapping;
    const set = (/** @type {string} */ k) => (/** @type {string} */ v) =>
      setMapping({ ...mapping, mapping: { ...m, [k]: v || null } });
    return html`
      <${Dialog} title="Which columns are which?" wide close=${close}
        onSubmit=${applyMapping} note="Saved for the next file from this institution."
        footer=${html`<button class="btn primary" disabled=${busy}>Import</button>`}>
        <p class="small dim" style=${{
          marginTop: 0,
        }}>A CSV from this institution for the first time.
              Check the columns MoolaKata guessed.</p>
        <div class="split-form">
              ${COLUMNS.filter(([, , , trade]) => !trade || mapping.trades).map((
                [k, label, hint],
              ) =>
                html`
                  <${Field} label=${label} id=${'map-' + k} hint=${hint}
                    error=${errAt(error, 'mapping.' + k)}>
                    <${Select} value=${m[k] || ''} onChange=${set(k)}
                      options=${headers} />
                    </${Field}>
                `
              )}
              <${Field} label="Date format" id="map-date-format" hint="As the file writes its dates."
                error=${errAt(error, 'mapping.dateFormat')}><${Input} value=${m.dateFormat || ''}
                onInput=${set('dateFormat')} placeholder="%m/%d/%Y" /></${Field}>
              <${Field} label="Spending is positive" id="map-negate"
                hint="Card exports often show purchases as positive amounts."><${Select}
                value=${m.negateAmounts ? 'yes' : 'no'} onChange=${(/** @type {string} */ v) =>
                  setMapping({ ...mapping, mapping: { ...m, negateAmounts: v === 'yes' } })}
                options=${[['no', 'No'], ['yes', 'Yes: flip the signs']]} /></${Field}>
            </div>
            ${mapping.trailer
              ? html`
                <p
                  class="small dim">${mapping.trailer} line${mapping.trailer === 1
                    ? ''
                    : 's'} below the rows ${mapping.trailer === 1
                    ? 'was'
                    : 'were'} left out: notes, not rows.</p>
              `
              : null}
            <div class="table-wrap"><table class="t"><caption class="sr-only">The file's first rows</caption>
              <thead><tr>${mapping.headers.map((/** @type {string} */ h) =>
                html`<th>${h}</th>`
              )}</tr></thead>
              <tbody>${mapping.sample.slice(0, 5).map((/** @type {string[]} */ r) =>
                html`<tr>${r.map((c) => html`<td class="small">${c}</td>`)}</tr>`
              )}</tbody></table></div>
            <${FormError} error=${error} shown=${COLUMNS.map(([k]) => 'mapping.' + k).concat([
              'mapping.dateFormat',
            ])} />
          </${Dialog}>
    `;
  }

  const empty = error?.code === 'statement-empty' || error?.code === 'brokerage-photo'
    ? error
    : null;
  return html`
    <${Dialog} title=${keeping ? 'Keep a statement' : 'Import transactions'} close=${close}
      onSubmit=${start}
      note=${keeping
        ? 'Kept on the account as it is, named by its period. Its lines aren’t read.'
        : "OFX, QFX or CSV, or a statement (PDF or photo). Re-importing adds only what's new."}
      footer=${html`<button class="btn primary" disabled=${busy || !file || !target}>${
        busy ? 'Reading…' : keeping ? 'Next' : 'Import'
      }</button>`}>
      <${Field} label="Into account" id="into-account">
        <${Select} value=${target} onChange=${setTarget}
          options=${writable.map((a) => [a.id, a.name])} />
        </${Field}>
        <${Field} label="File"
          hint="Downloaded from your bank or broker, or a statement: its PDF, or a photo."><input class="in" type="file"
          accept=".ofx,.qfx,.csv,.txt,.pdf,.jpg,.jpeg,.png,.webp,.heic" onChange=${(
            /** @type {any} */ e,
          ) => setFile(e.currentTarget.files?.[0] || null)} /></${Field}>
        ${file
          ? html`<p class="small dim"><${Icon} name="upload" /> ${file.name} · ${
            Math.ceil(
              file.size / 1024,
            )
          } KB</p>`
          : null}
        ${empty
          ? html`
            <div class="notice warn" role="alert">
              <${Icon} name="alert" />
              <div>${empty
                .message} <button type="button" class="btn sm" onClick=${() =>
                setKept({
                  uploadId: empty.uploadId,
                  fileName: empty.fileName,
                  periodStart: empty.periodStart,
                  periodEnd: empty.periodEnd,
                  read: true,
                  accountId: target,
                })}>Keep it without reading</button></div>
            </div>
          `
          : html`<${FormError} error=${error} />`}
        ${keeping ? null : html`
          <p
            class="small"><a href="#" data-help="keep-without-reading" onClick=${(
              /** @type {Event} */ e,
            ) => {
              e.preventDefault();
              setKeeping(true);
            }}>Keep a statement without reading it</a>: for the record, such as one from an
                      account kept current from OFX.</p>
        `}
      </${Dialog}>
  `;
}

/**
 * A statement kept on its account as it is (S1.3.3.6): its period, read where it could be,
 * checked, and the file kept as a receipt named by it.
 * @param {{ kept: any, close: (v?: any) => void }} p
 */
function KeepReview({ kept, close }) {
  useDialogGuide('dialog-statement-keep');
  const [f, setF] = useState({
    periodStart: kept.periodStart || '',
    periodEnd: kept.periodEnd || '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {any} */ (null));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.post(`/imports/${kept.uploadId}/keep`, f);
      changes.value = { ...changes.value, import: (changes.value.import || 0) + 1 };
      toast('Statement kept on the account');
      close(job.result);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return html`
    <${Dialog} title="Keep the statement" close=${close} onSubmit=${save}
      footer=${html`<button class="btn primary" disabled=${busy}>Keep it</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>${kept.fileName}${kept.institution
        ? ` · ${kept.institution}`
        : ''}</p>
      <div class="row">
        <${Field} label="Period from" id="period-start" error=${errAt(error, 'periodStart')}
          hint=${kept.periodStart ? 'Read from the statement.' : ''}>
          <${Input} type="date" value=${f.periodStart} onInput=${(/** @type {string} */ v) =>
            setF({ ...f, periodStart: v })} required />
          </${Field}>
          <${Field} label="Period to" id="period-end" error=${errAt(error, 'periodEnd')}>
            <${Input} type="date" value=${f.periodEnd} onInput=${(/** @type {string} */ v) =>
              setF({ ...f, periodEnd: v })} required />
            </${Field}>
            </div>
            <p class="small dim">Its lines aren't added. It counts as the account's statement for the
        period, so no alert asks for it.</p>
            <${FormError} error=${error} shown=${['periodStart', 'periodEnd', 'accountId']} />
            </${Dialog}>
  `;
}

/**
 * A statement of several accounts (S1.3.3.5): each part checked in turn, against its own
 * balances, and saved to the account it shows or one chosen, or left out. Nothing is saved
 * until every part is decided.
 * @param {{ review: any, setReview: (v: any) => void, close: (v?: any) => void }} p
 */
function PartsReview({ review, setReview, close }) {
  const part = review.parts[review.at];
  const [current, setCurrent] = useState(() => partReview(review, part));
  useEffect(() => setCurrent(partReview(review, part)), [review.at]);
  const next = (/** @type {any} */ result) => {
    if (result.remaining) setReview({ ...review, at: result.remaining[0] });
    else {
      changes.value = { ...changes.value, import: (changes.value.import || 0) + 1 };
      const n = result.parts.length;
      toast(n ? `Statement saved to ${n} account${n === 1 ? '' : 's'}` : 'Every part left out');
      close(result);
    }
  };
  return html`
    <${StatementReview} key=${review.at} review=${current} setReview=${setCurrent}
      close=${close} done=${next} part=${{ ...part, total: review.parts.length }} />
  `;
}

/** @param {any} review @param {any} part */
function partReview(review, part) {
  return {
    ...review,
    ...part,
    accountId: part.accountId || '',
    rows: part.rows.map((/** @type {any} */ r) => ({ ...r, include: r.present || !r.ignored })),
    accept: false,
  };
}

/** A line's first three words, what "Remember…" proposes to ignore (S1.3.3.4). */
const firstWords = (/** @type {string} */ d) =>
  d.trim().split(/\s+/).slice(0, 3).join(' ').toLowerCase();

/** What the person asked about the lines to ignore: the starts to remember and to forget. */
function ignoring(/** @type {any[]} */ rows) {
  return {
    remember: [...new Set(rows.filter((r) => r.remember).map((r) => r.remember))],
    forget: [...new Set(rows.filter((r) => r.stop).map((r) => r.ignored))],
  };
}

/**
 * A statement line's state at the end of its row (S1.3.3.3, S1.3.3.4): already in the account;
 * caught by a line to ignore, with Stop ignoring; or left out by the person, with Remember…,
 * whose question opens beneath the row (`Asking`).
 * @param {{ r: any, set: (v: any) => void, fresh: any }} p
 */
function LineState({ r, set, fresh }) {
  if (r.present) return html`<span class="pill">already in the account</span>`;
  if (r.ignored && !r.stop) {
    return html`<span class="small dim">Ignored (starts with “${r.ignored}”) · <a href="#"
      onClick=${(/** @type {Event} */ e) => {
      e.preventDefault();
      set({ stop: true, include: true });
    }}>Stop ignoring</a></span>`;
  }
  if (r.include) return fresh;
  if (r.remember) {
    return html`<span class="pill">Ignored next time <button type="button" class="linklike"
      aria-label="Don't ignore it next time" onClick=${() =>
      set({ remember: null })}>✕</button></span>`;
  }
  return r.asking == null
    ? html`<a href="#" class="small dim" onClick=${(/** @type {Event} */ e) => {
      e.preventDefault();
      set({ asking: firstWords(r.description) });
    }}>Remember…</a>`
    : null;
}

/**
 * "Ignore future lines starting with:", beneath the row it asks about.
 * @param {{ r: any, set: (v: any) => void, cols: number }} p
 */
function Asking({ r, set, cols }) {
  if (r.asking == null || r.include || r.present) return null;
  const ok = () => r.asking.trim() && set({ remember: r.asking.trim(), asking: null });
  return html`
    <tr class="asking">
      <td colspan=${cols}>
        <div class="ask-inline" role="group" aria-label="Remember this line">
          <label for=${'ask-' + r.line}>Ignore future lines starting with:</label>
          <input class="in" id=${'ask-' + r.line} value=${r.asking} data-help="remember"
            onInput=${(/** @type {any} */ e) => set({ asking: e.currentTarget.value })}
            onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                ok();
              } else if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                set({ asking: null });
              }
            }} />
          <button type="button" class="btn sm" onClick=${() =>
            set({ asking: null })}>Cancel</button>
          <button type="button" class="btn sm primary" onClick=${ok}>OK</button>
        </div>
      </td>
    </tr>
  `;
}

/**
 * A statement read on the server, to check before anything is saved: its period and balances,
 * and each transaction, which can be corrected or left out. It is saved only when the
 * transactions add up from the opening to the closing balance, or the difference is accepted.
 * @param {{ review: any, setReview: (v: any) => void, close: (v?: any) => void,
 *   done: (r: any) => void, part?: any }} p
 */
function StatementReview({ review, setReview, close, done, part = null }) {
  useDialogGuide(part ? 'dialog-statement-split' : 'dialog-statement');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {any} */ (null));
  const kept = review.rows.filter((/** @type {any} */ r) => r.include);
  const sum = kept.reduce(
    (/** @type {bigint} */ a, /** @type {any} */ r) => a + (cents(r.amount) ?? 0n),
    0n,
  );
  const diff = (cents(review.closing) ?? 0n) - (cents(review.opening) ?? 0n) - sum;
  const set = (/** @type {string} */ k) => (/** @type {string} */ v) =>
    setReview({ ...review, [k]: v });
  const change = (/** @type {number} */ i, /** @type {any} */ v) =>
    setReview({
      ...review,
      rows: review.rows.map((/** @type {any} */ r, /** @type {number} */ j) =>
        i === j ? { ...r, ...v } : r
      ),
    });
  const setRow = (/** @type {number} */ i, /** @type {string} */ k, /** @type {any} */ v) =>
    change(i, { [k]: v });
  const save = async (/** @type {boolean} */ leftOut = false) => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.post(`/imports/${review.uploadId}/statement`, {
        ...(part ? { part: part.index, accountId: review.accountId || null, leftOut } : {}),
        periodStart: review.periodStart,
        periodEnd: review.periodEnd,
        opening: review.opening,
        closing: review.closing,
        acceptDifference: review.accept,
        ...ignoring(review.rows),
        // Each row names the line it was read as, so a corrected description is told from
        // what was read (S1.3.3.4).
        rows: review.rows.map((/** @type {any} */ r, /** @type {number} */ i) => ({
          date: r.date,
          description: r.description,
          amount: r.amount,
          include: r.include,
          line: i,
        })),
      });
      done(job.result);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const fresh = kept.filter((/** @type {any} */ r) => !r.present).length;
  const label = part
    ? `Save part ${part.index + 1}${part.index + 1 < part.total ? ' · next part' : ''}`
    : `Import ${fresh} new`;
  return html`
    <${Dialog} title=${part
      ? `Part ${part.index + 1} of ${part.total}: account ending ${part.last4}`
      : 'Check the statement'} wide close=${close} onSubmit=${() => save(false)}
      note=${review.learned
        ? `Read with what was learned of ${review.institution || 'this institution'}'s statements.`
        : 'What you correct here is remembered for the next statement from this institution.'}
      footer=${html`${
        part
          ? html`
            <button type="button" class="btn" disabled=${busy}
              onClick=${() => save(true)}>Leave this part out</button><span class="spacer"></span>
          `
          : null
      }<button class="btn primary" disabled=${
        busy || (diff !== 0n && !review.accept) || (part && !review.accountId)
      }>${busy ? 'Saving…' : label}</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>${review.fileName} · ${review.method === 'text'
        ? 'read from its text layer'
        : 'read with OCR'}${review.institution ? ` · ${review.institution}` : ''}</p>
      ${part
        ? html`
          <${Field} label="Account" id="part-account" error=${errAt(error, 'accountId')}
            hint=${part.accountId
              ? `Its header shows ${part.header}.`
              : `No account here ends in ${part.last4}: choose one, or leave this part out.`}>
            <${Select} value=${review.accountId} onChange=${set('accountId')} options=${[
              ['', 'Choose…'],
              ...part.candidates.map((/** @type {any} */ a) => [
                a.id,
                a.name + (a.mask ? ` ··${a.mask}` : ''),
              ]),
            ]} />
            </${Field}>
        `
        : null}
      <div class="row">
        <${Field} label="Period from" id="period-start" error=${errAt(error, 'periodStart')}>
          <${Input} type="date" value=${review.periodStart || ''} onInput=${set(
            'periodStart',
          )} required />
          </${Field}>
          <${Field} label="Period to" id="period-end" error=${errAt(error, 'periodEnd')}>
            <${Input} type="date" value=${review.periodEnd || ''} onInput=${set(
              'periodEnd',
            )} required />
            </${Field}>
            <${Field} label="Opening balance" id="opening">
              <${Input} value=${review.opening || ''} onInput=${set(
                'opening',
              )} inputmode="decimal" required />
              </${Field}>
              <${Field} label="Closing balance" id="closing">
          <${Input} value=${review.closing || ''} onInput=${set(
            'closing',
          )} inputmode="decimal" required />
        </${Field}>
      </div>
      <div class="kv">
        <div><div class="k">${kept.length} transactions</div><div class="v amt">${money(
          fromCents(sum),
        )}</div></div>
        <div><div class="k">Adds up</div><div class="v" style=${{
          color: diff === 0n ? 'var(--ok)' : 'var(--deny)',
        }}>${diff === 0n
          ? html`<${Icon} name="check" /> yes`
          : `${money(fromCents(diff))} short`}</div></div>
      </div>
      <div class="table-wrap mt"><table class="t">
        <thead><tr><th></th><th>Date</th><th>Description</th><th class="num">Amount</th><th></th></tr></thead>
        <tbody>${review.rows.map((/** @type {any} */ r, /** @type {number} */ i) =>
          html`
            <tr class=${r.include ? '' : 'dim'}>
              <td><input type="checkbox" checked=${r.include} disabled=${r.present}
                aria-label=${'Import ' + r.description} data-help="include" onChange=${() =>
                  change(i, { include: !r.include, asking: null })} /></td>
              <td class="dim">${date(r.date)}</td>
              <td><input class="in" value=${r
                .description} aria-label="Description" data-help="description"
                          onInput=${(/** @type {any} */ e) =>
                            setRow(i, 'description', e.currentTarget.value)} />${r.confidence < 80
                            ? html`<div class="small ocr"><${Icon} name="info" /> its sign was guessed · check it</div>`
                            : null}</td>
              <td class="num"><input class="in num" value=${r.amount} aria-label="Amount"
                          data-help="amount" style=${{ maxWidth: '120px' }}
                          onInput=${(/** @type {any} */ e) =>
                            setRow(i, 'amount', e.currentTarget.value)} /></td>
              <td>
                <${LineState} r=${{ ...r, line: i }} set=${(/** @type {any} */ v) =>
                  change(i, v)} fresh=${html`<span class="pill info">new</span>`} />
              </td>
            </tr>
            <${Asking} r=${{ ...r, line: i }} cols=${5} set=${(/** @type {any} */ v) =>
              change(i, v)} />
          `
        )}</tbody>
      </table></div>
      ${diff !== 0n
        ? html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="checkbox"
            id="f-accept-difference" checked=${review.accept}
            onChange=${() =>
          setReview({ ...review, accept: !review.accept })} /><span class="grow">Import
            anyway: the Reconcile tab will show the ${
          money(fromCents(diff))
        } it is short</span></label>`
        : null}
      <${FormError} error=${error} shown=${['periodStart', 'periodEnd', 'accountId']} />
    </${Dialog}>
  `;
}

/**
 * A brokerage or plan statement (S1.3.3.8): its summary, whose ending value becomes a value
 * anchor; its positions checked against what is held; and its cash lines, checked against the
 * summary and kept as transactions. Trades aren't read: each opens the trade dialog filled in.
 * @param {{ review: any, setReview: (v: any) => void, close: (v?: any) => void,
 *   done: (r: any) => void, accounts: any[] }} p
 */
function BrokerageReview({ review, setReview, close, done, accounts }) {
  useDialogGuide('dialog-brokerage-statement');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {any} */ (null));
  const sm = review.summary;
  const change = (/** @type {number} */ i, /** @type {any} */ v) =>
    setReview({
      ...review,
      activity: review.activity.map((/** @type {any} */ r, /** @type {number} */ j) =>
        i === j ? { ...r, ...v } : r
      ),
    });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.post(`/imports/${review.uploadId}/brokerage`, {
        periodStart: review.periodStart,
        periodEnd: review.periodEnd,
        endingValue: sm.ending,
        positions: review.positions.map((/** @type {any} */ p) => ({
          label: p.label,
          symbol: p.symbol,
          instrumentId: p.instrumentId,
          quantity: p.quantity,
          price: p.price,
          marketValue: p.marketValue,
          costBasis: p.costBasis,
          cash: p.cash,
        })),
        rows: review.activity.map((/** @type {any} */ r) => ({
          date: r.date,
          description: r.description,
          amount: r.amount,
          kind: r.kind,
          symbol: r.symbol,
          include: r.include && !r.notRead,
        })),
        ...ignoring(review.activity),
      });
      done(job.result);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const trade = (/** @type {any} */ r) => {
    const sold = /\b(sold|sell)\b/i.test(r.description);
    openDialog(TransactionDialog, {
      accounts,
      accountId: review.accountId,
      start: {
        date: r.date,
        kind: /reinvest/i.test(r.description) ? 'reinvest' : sold ? 'sell' : 'buy',
        symbol: r.symbol || '',
        quantity: r.quantity || '',
        price: r.price || '',
        amount: r.amount,
        payee: r.description,
      },
    });
  };
  const figure = (/** @type {string} */ label, /** @type {string | null} */ v) =>
    v == null ? null : html`
      <div>
        <div class="k">${label}</div>
        <div class="v amt">${money(v)}</div>
      </div>
    `;
  const read = /** @type {Record<string, string | null>} */ (review.totals);
  const offBy = ['deposits', 'withdrawals', 'income'].filter((k) =>
    sm[k] != null && read[k] != null && cents(sm[k]) !== cents(read[k])
  );
  return html`
    <${Dialog} title="Check the statement" wide close=${close} onSubmit=${save}
      note=${`What you ask to ignore is remembered for the next statement from ${
        review.institution || 'this institution'
      }.`}
      footer=${html`<button class="btn primary" disabled=${busy}>${
        busy ? 'Saving…' : review.snapshot ? 'Save the holdings' : 'Save the anchor and check'
      }</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>${review
        .fileName} · read from its text layer${review.institution
        ? ` · ${review.institution}`
        : ''} · ${date(review.periodStart)} to ${date(review.periodEnd)}</p>
      <h4 style=${{ margin: '8px 0' }} data-help="summary">Summary</h4>
      <div class="kv">${figure('Starting value', sm.starting)}${figure(
        'Deposits',
        sm.deposits,
      )}${figure('Withdrawals', sm.withdrawals)}${figure('Income', sm.income)}${figure(
        'Change in value',
        sm.change,
      )}${figure('Ending value', sm.ending)}</div>
      <p class="small dim">${review.snapshot
        ? `This account is kept by snapshots: its positions become its holdings on ${
          date(review.periodEnd)
        }.`
        : `The ending value becomes a balance anchor on ${date(review.periodEnd)}.`}</p>
      <h4 style=${{ margin: '12px 0 8px' }} data-help="positions">Positions on ${date(
        review.periodEnd,
      )}</h4>
      <div class="table-wrap"><table class="t">
        <thead><tr><th>Holding</th><th class="num">Statement</th><th class="num">MoolaKata</th><th
          class="num">Market value</th><th></th></tr></thead>
        <tbody>${review.positions.map((/** @type {any} */ p) =>
          html`
            <tr>
              <td><b>${p.symbol || p.label}</b>${p.symbol
                ? html`<div class="small dim">${p.label}</div>`
                : null}</td>
              <td class="num">${p.quantity ?? '—'}</td>
              <td class="num">${p.held ??
                html`<span class="dim">not held</span>`}</td>
              <td class="num">${p.marketValue ? money(p.marketValue) : '—'}</td>
              <td>${p.difference == null
                ? html`<span class="pill">${
                  p.instrumentId || p.cash ? 'checked' : 'not matched'
                }</span>`
                : Number(p.difference) === 0
                ? html`<span class="pill"><${Icon} name="check" /> matches</span>`
                : html`<span class="pill warn">${String(p.difference).replace(/^-/, '')} ${
                  Number(p.difference) > 0 ? 'short' : 'over'
                }</span>`}</td>
            </tr>${p.hint
              ? html`
                <tr>
                  <td colspan="5" class="small"><${Icon} name="alert" /> ${p.symbol ||
                    p.label}: ${p.hint}.</td>
                </tr>
              `
              : null}
          `
        )}</tbody>
      </table></div>
      <h4 style=${{ margin: '12px 0 8px' }} data-help="cash-activity">Cash activity</h4>
      <div class="table-wrap"><table class="t">
        <thead><tr><th></th><th>Date</th><th>Description</th><th class="num">Amount</th><th
          ></th></tr></thead>
        <tbody>${review.activity.map((/** @type {any} */ r, /** @type {number} */ i) =>
          html`
            <tr class=${r.include && !r.notRead ? '' : 'dim'}>
              <td>${r.notRead ? null : html`
                <input type="checkbox" checked=${r.include} disabled=${r.present}
                  aria-label=${'Import ' + r.description} onChange=${() =>
                    change(i, { include: !r.include, asking: null })} />
              `}</td>
              <td class="dim">${date(r.date)}</td>
              <td>${r.description}</td>
              <td class="num">${money(r.amount)}</td>
              <td>${r.notRead
                ? html`<span class="pill warn">not read</span> ${
                  r.kind === 'trade'
                    ? html`<a href="#" onClick=${(/** @type {Event} */ e) => {
                      e.preventDefault();
                      trade(r);
                    }}>enter it as a trade</a>`
                    : html`<span class="small dim">${
                      r.kind.replace('-', ' ')
                    }: enter it by hand</span>`
                }`
                : html`<${LineState} r=${{ ...r, line: 'b' + i }} set=${(
                  /** @type {any} */ v,
                ) => change(i, v)} fresh=${html`<span class="pill info">${r.kind}</span>`} />`}</td>
            </tr>
            <${Asking} r=${{ ...r, line: 'b' + i }} cols=${5} set=${(/** @type {any} */ v) =>
              change(i, v)} />
          `
        )}</tbody>
      </table></div>
      ${offBy.length
        ? html`
          <div class="notice warn mt">
            <${Icon} name="alert" />
            <div>The lines read don't add up
                    to the summary's ${offBy.join(
                      ' and ',
                    )}: a line may not have been read. Check them
                    before saving.</div>
          </div>
        `
        : null}
      <p class="small dim">Lines already in the account are counted and never added twice.
        Trades aren't read: each opens the trade dialog with its figures. The PDF is kept on
        the account.</p>
      <${FormError} error=${error} />
    </${Dialog}>
  `;
}
