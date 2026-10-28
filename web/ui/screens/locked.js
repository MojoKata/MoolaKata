// The locked screen (requirements S13.6, S15.4.3): the server has started and holds no key
// until an admin enters the recovery phrase here; with no keyring at all, a new server's
// welcome takes its place (new-server.js, S15.4.4). The phrase is the authentication: nobody
// can sign in before the database is open. A re-encryption the unlock brings runs before the
// server serves, its progress shown here (S15.7.2).
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { loadSession, lostChanges } from '../store/session.js';
import { AuthCard } from '../components/auth.js';
import { Field, FormError } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import NewServer from './new-server.js';

const STAGES = /** @type {Record<string, string>} */ ({
  starting: 'Starting',
  backup: 'A verified backup first',
  database: 'The database',
  secrets: 'The secrets',
  receipts: 'Receipt files',
  copies: 'The copies on this host',
  done: 'Done',
});

export default function Locked() {
  const [words, setWords] = useState('');
  const [shown, setShown] = useState(false);
  const [lock, setLock] = useState(/** @type {any} */ (null));
  const poll = async () => {
    const s = await api.get('/unlock');
    setLock(s);
    if (!s.locked) await loadSession();
    return s;
  };
  useEffect(() => {
    poll().catch(() => {});
  }, []);
  // While a re-encryption runs, the server answers its progress until it serves.
  useEffect(() => {
    if (!lock?.reencrypting) return;
    const t = setTimeout(() => poll().catch(() => {}), 1000);
    return () => clearTimeout(t);
  }, [lock]);
  const unlock = useSubmit(async () => {
    const s = await api.post('/unlock', { phrase: words });
    setWords('');
    setLock(s);
    if (!s.locked) await loadSession();
  });
  if (lock?.uninitialised) return html`<${NewServer} refresh=${poll} />`;
  if (lock?.reencrypting) {
    const r = lock.reencrypting;
    const pct = r.total ? Math.round((r.done / r.total) * 100) : 0;
    return html`
      <${AuthCard} title="MoolaKata is re-encrypting" guide="locked"
        sub="The phrase opened the keyring. The data is being rewritten under a new data key before the server serves; this takes a few minutes.">
        <div class="list-item"><span class="grow">${STAGES[r.stage] || r.stage}</span>${r.total
          ? `${r.done.toLocaleString()} of ${r.total.toLocaleString()}`
          : ''}</div>
        <div role="progressbar" aria-label="Re-encryption progress" aria-valuenow=${pct}
          aria-valuemin="0" aria-valuemax="100" style=${{
            height: '8px',
            borderRadius: '4px',
            background: 'var(--bg-3)',
            overflow: 'hidden',
            margin: '8px 0',
          }}>
          <div style=${{ width: `${pct}%`, height: '100%', background: 'var(--accent)' }}></div>
        </div>
        <p class="small dim" style=${{ marginTop: '12px' }}>Sign-in opens when it is done; <code
          >/healthz</code> answers <code>re-encrypting</code> meanwhile.</p>
        </${AuthCard}>
    `;
  }
  return html`
    <${AuthCard} title="MoolaKata is locked" guide="locked"
      sub=${(lostChanges.value ? "Changes you hadn't saved were lost. " : '') +
        'The server started and holds no key. An admin enters the recovery phrase to open it; everyone signs in after that.'}>
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        unlock.run().catch(() => {});
      }}>
        <${Field} label="Recovery phrase" id="recovery-phrase"
          hint="The 12 words from the recovery sheet, in order. Four letters of each are enough.">
          <span class="pw" id="recovery-phrase-box"><input class="in" id="f-recovery-phrase"
              type=${shown ? 'text' : 'password'} value=${words} required
              autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck=${false}
              data-1p-ignore data-lpignore="true"
              onInput=${(/** @type {any} */ ev) => setWords(ev.currentTarget.value)} /><button
              type="button" class="icon-btn" aria-pressed=${shown ? 'true' : 'false'}
              aria-label=${shown ? 'Hide the phrase' : 'Show the phrase'}
              onClick=${() => setShown(!shown)}><${Icon} name=${shown
                ? 'eye-off'
                : 'eye'} /></button></span>
          </${Field}>
          ${lock?.error
            ? html`<div class="notice small bad" role="status">The last unlock couldn't finish:
              ${lock.error}</div>`
            : null}
          <${FormError} error=${unlock.error} />
          <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
            disabled=${unlock.busy}>${unlock.busy ? 'Opening…' : 'Unlock'}</button>
          <p class="small dim" style=${{ marginTop: '12px' }}>Or on the host: <code
            >docker compose exec moolakata moolakata keys unlock</code>. The server locks
            again at every restart; nothing of the phrase is kept.</p>
          </form>
          </${AuthCard}>
  `;
}
