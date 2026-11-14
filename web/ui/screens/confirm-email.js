// Confirming a new email address (requirements S10.1.5): it takes effect only now.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { AuthCard, tokenFromHash } from '../components/auth.js';

export default function ConfirmEmail() {
  const [state, setState] = useState('checking');
  useEffect(() => {
    api.post('/email-change/confirm', { token: tokenFromHash() }).then(
      () => setState('done'),
      () => setState('bad'),
    );
  }, []);
  if (state === 'checking') return null;
  return html`
    <${AuthCard} title=${state === 'done' ? 'Email Address Confirmed' : 'This Link Has Expired'}
      guide="confirm-email" sub=${state === 'done'
        ? 'Your new address is in use from now on.'
        : 'Ask for a new one in Profile.'}>
        <a class="btn primary" href="/ui/">Continue</a></${AuthCard}>
  `;
}
