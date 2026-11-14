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
import { Attention } from '../kit/state.js';

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
      <${AuthCard} title="Welcome to MoolaKata" guide="new-server">
        <${FormError} error=${show.error} />
        <button type="button" class="btn primary" style=${WIDE} disabled=${show.busy}
          onClick=${() => show.run().catch(() => {})}>Show My Recovery Phrase</button>
        </${AuthCard}>
    `;
  }
  if (step === 'phrase') {
    return html`
      <${AuthCard} title="Your Recovery Phrase" guide="new-server"
        sub="They're shown here once.">
        <ol class="phrase" aria-label="The recovery phrase">${offer.words.map((
          /** @type {string} */ w,
        ) => html`<li><b>${w}</b></li>`)}</ol>
        <div class="small dim">Fingerprint <code>${offer.fingerprint}</code> · ${offer
          .serverName} · ${date(offer.made)}</div>
        <div class="mt">
          <${Attention} icon=${html`<${Icon} name="alert" />`}>A reload shows other
          words</${Attention}></div>
        <button type="button" class="btn primary mt" style=${WIDE}
          onClick=${() => setStep('check')}>I've Written Them Down</button>
        </${AuthCard}>
    `;
  }
  const gone = /** @type {any} */ (make.error)?.code === 'phrase-gone';
  return html`
    <${AuthCard} title="Check What You Wrote" guide="new-server">
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
        <${FormError} error=${make.error} shown=${offer.check.map((/** @type {number} */ n) =>
          `word${n}`
        )} />
        ${gone
          ? html`
            <button type="button" class="btn primary" style=${WIDE} disabled=${show.busy}
              onClick=${() => show.run().catch(() => {})}>Show a New Phrase</button>
          `
          : html`<div class="row"><button type="button" class="btn"
            onClick=${() => setStep('phrase')}>Back</button><span class="spacer"></span><button
            class="btn primary" disabled=${make.busy}>${
            make.busy ? 'Making the Key…' : 'Make the Key'
          }</button></div>`}
        </form>
      </${AuthCard}>
  `;
}
