// A new server's welcome (requirements S12.14.1, S15.4.4): its master key, shown once as a
// recovery phrase to write down, then three of its words typed back. Every visit shows a new
// phrase; only the one confirmed becomes the key, and the admin's account follows (S10.1.2).
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { date } from '../kit/format.js';
import { loadSession } from '../store/session.js';
import { AuthCard } from '../components/auth.js';
import { errAt, Field, FormError, Input } from '../kit/fields.js';
import { Icon } from '../kit/icon.js';

const WIDE = { width: '100%', justifyContent: 'center' };

/** @param {{ refresh: () => Promise<any> }} p */
export default function NewServer({ refresh }) {
  const [step, setStep] = useState('welcome'); // welcome, phrase, check
  const [offer, setOffer] = useState(/** @type {any} */ (null));
  const [typed, setTyped] = useState(/** @type {Record<string, string>} */ ({}));
  const show = useSubmit(async () => {
    setOffer(await api.post('/welcome/phrase'));
    setTyped({});
    setStep('phrase');
  });
  const make = useSubmit(async () => {
    try {
      await api.post('/welcome/key', { token: offer.token, words: typed });
    } catch (e) {
      // Made meanwhile, here or on the host: the page becomes the locked screen.
      if (/** @type {any} */ (e)?.code === 'initialised') await refresh();
      throw e;
    }
    await loadSession(); // nobody is signed in yet: the admin's account comes next
  });

  if (step === 'welcome' || !offer) {
    return html`
      <${AuthCard} title="Welcome to MoolaKata" guide="new-server"
        sub="This server is new. Two steps make it yours: its master key, then your account.">
        <p class="small" style=${{ marginTop: 0 }}>Everything MoolaKata keeps is encrypted under one
          <b> master key</b>, which is a <b>recovery phrase</b> of 12 words. You write it down;
          nothing keeps it for you. MoolaKata asks for it after every restart, and nobody can
          recover it if it's lost.</p>
        <p class="small dim">Have paper and a pen ready. Two copies in two places, one of them
          offline, is the rule.</p>
        <${FormError} error=${show.error} />
        <button type="button" class="btn primary" style=${WIDE} disabled=${show.busy}
          onClick=${() => show.run().catch(() => {})}>Show my recovery phrase</button>
        </${AuthCard}>
    `;
  }
  if (step === 'phrase') {
    return html`
      <${AuthCard} title="Your recovery phrase" guide="new-server"
        sub="Write these 12 words on paper, in order. They're shown here once.">
        <ol class="phrase" aria-label="The recovery phrase">${offer.words.map((
          /** @type {string} */ w,
        ) => html`<li><b>${w}</b></li>`)}</ol>
        <div class="small dim">Fingerprint <code>${offer.fingerprint}</code> · ${offer
          .serverName} · ${date(offer.made)}</div>
        <div class="notice small mt">
          <${Icon} name="alert" />
          <div>A reload, or another browser,
          shows other words: only the ones you confirm next become the key.</div>
        </div>
        <button type="button" class="btn primary mt" style=${WIDE}
          onClick=${() => setStep('check')}>I've written them down</button>
        </${AuthCard}>
    `;
  }
  const gone = /** @type {any} */ (make.error)?.code === 'phrase-gone';
  return html`
    <${AuthCard} title="Check what you wrote" guide="new-server"
      sub="Type three of the words from your sheet.">
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        make.run().catch(() => {});
      }}>
        ${offer.check.map((/** @type {number} */ n) =>
          html`
            <${Field} label=${`Word ${n}`} id=${`word-${n}`} help="words-back"
              error=${errAt(make.error, `word${n}`)}>
              <${Input} value=${typed[n] || ''} onInput=${(/** @type {string} */ v) =>
                setTyped({ ...typed, [n]: v })} autocomplete="off" autocapitalize="none"
                autocorrect="off" spellcheck=${false} required />
              </${Field}>
          `
        )}
        <p class="small dim" style=${{ marginTop: 0 }}>Four letters of each are enough.</p>
        <${FormError} error=${make.error} shown=${offer.check.map((/** @type {number} */ n) =>
          `word${n}`
        )} />
        ${gone
          ? html`
            <button type="button" class="btn primary" style=${WIDE} disabled=${show.busy}
              onClick=${() => show.run().catch(() => {})}>Show a new phrase</button>
          `
          : html`<div class="row"><button type="button" class="btn"
            onClick=${() => setStep('phrase')}>Back</button><span class="spacer"></span><button
            class="btn primary" disabled=${make.busy}>${
            make.busy ? 'Making the key…' : 'Make the key'
          }</button></div>`}
        </form>
      </${AuthCard}>
  `;
}
