// Sign in (requirements S10.1.1), its code when two-step sign-in is on (S10.1.6), Forgot
// password? (S10.1.5), Sign up when an admin opened it (S10.1.4), and the account-is-disabled
// screen with its request to be made active again (S10.1.7).
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { ended, lostChanges, setSession } from '../store/session.js';
import { AuthCard } from '../components/auth.js';
import { errAt, Field, FormError, Input, Select } from '../components/fields.js';

export default function SignIn() {
  const { path, route } = useLocation();
  const [mode, setMode] = useState(ended.value === 'disabled' ? 'disabled' : 'signin');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [sent, setSent] = useState(false);
  const [twoStep, setTwoStep] = useState('');
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState(false);
  const [signupOpen, setSignupOpen] = useState(/** @type {any} */ (null));
  const [form, setForm] = useState({
    displayName: '',
    username: '',
    email: '',
    password: '',
    sex: '',
  });
  useEffect(() => {
    api.get('/signup').then(setSignupOpen, () => {});
  }, []);
  const signedIn = (/** @type {any} */ info) => {
    ended.value = '';
    setSession(info);
    if (path === '/ui/signin') route('/ui/', true);
  };
  const signIn = useSubmit(async () => {
    try {
      const info = await api.post('/session', { login, password });
      if (info?.twoStepToken) {
        setTwoStep(info.twoStepToken);
        setCode('');
        setMode('code');
        return;
      }
      signedIn(info);
    } catch (e) {
      if (/** @type {any} */ (e).code === 'account-disabled') setMode('disabled');
      throw e;
    }
  });
  const second = useSubmit(async () => {
    try {
      signedIn(await api.post('/session/two-step', { token: twoStep, code }));
    } catch (e) {
      if (/** @type {any} */ (e).code === 'two-step-expired') {
        setPassword('');
        setMode('signin');
      }
      throw e;
    }
  });
  const signUp = useSubmit(async () => {
    await api.post('/signup', form);
    setSent(true);
  });
  const forgot = useSubmit(async () => {
    await api.post('/password-reset', { login });
    setSent(true);
  });
  const reactivate = useSubmit(async () => {
    await api.post('/reactivation-requests', { login, password });
    setSent(true);
  });

  if (mode === 'forgot') {
    return html`
      <${AuthCard} title="Forgot password" guide="signin"
        sub="We'll email a link to choose a new password. It works once, for an hour.">
            ${sent
              ? html`
                <div class="notice" role="status">If ${login} has an account here, an email is on its way.</div>
                <p><button type="button" class="linklike" onClick=${() =>
                  setMode('signin')}>Back to sign in</button></p>
              `
              : html`
                <form onSubmit=${(/** @type {Event} */ e) => {
                  e.preventDefault();
                  forgot.run().catch(() => {});
                }}>
                  <${Field} label="Username or email">
                    <${Input} value=${login} onInput=${setLogin}
                      autocomplete="username" required />
                    </${Field}>
                    <${FormError} error=${forgot.error} />
                    <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
                      disabled=${forgot.busy}>Send the link</button>
                    <div
                      class="toolbar mt"><button type="button" class="linklike" onClick=${() =>
                        setMode('signin')}>Back to sign in</button></div>
                    </form>
              `}
          </${AuthCard}>
    `;
  }

  if (mode === 'signup') {
    const set = (/** @type {string} */ k) => (/** @type {string} */ v) =>
      setForm({ ...form, [k]: v });
    const domains = signupOpen?.domains || [];
    return html`
      <${AuthCard} title="Ask for an account" guide="signup"
        sub="An admin approves each request. First, confirm your email from the link we send.">
        ${sent
          ? html`
            <div class="notice"
              role="status">If ${form
                .email} can ask for an account, a link to confirm it is on its way.
              It works for a day.</div>
          `
          : html`
            <form onSubmit=${(/** @type {Event} */ e) => {
              e.preventDefault();
              signUp.run().catch(() => {});
            }}>
              <${Field} label="Your name" id="display-name" error=${errAt(
                signUp.error,
                'displayName',
              )}>
                <${Input} value=${form.displayName} onInput=${set(
                  'displayName',
                )} autocomplete="name" required />
                </${Field}>
                <${Field} label="Sex" error=${errAt(signUp.error, 'sex')}>
                  <${Select} value=${form.sex} onChange=${set('sex')} options=${[
                    ['', 'Choose…'],
                    ['female', 'Female'],
                    ['male', 'Male'],
                  ]} />
                  </${Field}>
                  <${Field} label="Email address" id="email" error=${errAt(signUp.error, 'email')}
                    hint=${domains.length ? 'Addresses at ' + domains.join(', ') + '.' : undefined}>
                    <${Input} type="email" value=${form.email} onInput=${set(
                      'email',
                    )} autocomplete="email"
                      required />
                    </${Field}>
                    <${Field} label="Username" error=${errAt(signUp.error, 'username')}
                      hint="What you'll sign in with: lowercase letters, digits, dots, dashes or underscores.">
                      <${Input} value=${form.username} onInput=${set(
                        'username',
                      )} autocomplete="username" required />
                      </${Field}>
                      <${Field} label="Password" error=${errAt(signUp.error, 'password')}
                        hint="At least 12 characters; not a common password.">
                        <${Input} type="password" value=${form.password} onInput=${set('password')}
                          autocomplete="new-password" required />
                        </${Field}>
                        <${FormError} error=${signUp.error} shown=${[
                          'displayName',
                          'sex',
                          'email',
                          'username',
                          'password',
                        ]} />
                        <button class="btn primary" style=${{
                          width: '100%',
                          justifyContent: 'center',
                        }}
                          disabled=${signUp.busy}>Ask for an account</button>
                        </form>
          `}
        <div class="toolbar mt"><button type="button" class="linklike" onClick=${() => {
          setSent(false);
          setMode('signin');
        }}>Back to sign in</button></div>
      </${AuthCard}>
    `;
  }

  if (mode === 'code') {
    return html`
      <${AuthCard} title="Two-step sign-in" guide="signin"
        sub=${recovery
          ? 'Type one of your recovery codes. Each works once.'
          : 'Type the six-digit code your authenticator app shows for MoolaKata.'}>
        <form onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          second.run().catch(() => {});
        }}>
          <${Field} label=${recovery ? 'Recovery code' : 'Code'} error=${errAt(
            second.error,
            'code',
          )}>
            <${Input} value=${code} onInput=${setCode} required
              inputmode=${recovery ? 'text' : 'numeric'}
              autocomplete=${recovery ? 'off' : 'one-time-code'} />
            </${Field}>
            <${FormError} error=${second.error} shown=${['code']} />
            <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
              disabled=${second.busy}>Sign in</button>
            </form>
            <div
              class="toolbar mt"><button type="button" class="linklike" onClick=${() => {
                setRecovery(!recovery);
                setCode('');
                second.setError(null);
              }}>${recovery ? 'Use a code from the app' : 'Use a recovery code'}</button>
          <span class="grow"></span>
          <button type="button" class="linklike" onClick=${() => {
            setPassword('');
            setRecovery(false);
            setMode('signin');
          }}>Back to sign in</button></div>
            </${AuthCard}>
    `;
  }

  if (mode === 'disabled') {
    return html`
      <${AuthCard} title="This account is disabled" guide="signin"
        sub="An admin switched it off. You can ask them to make it active again, once a week.">
            ${sent
              ? html`<div class="notice" role="status">If that is a disabled account here, the admins will
                see your request.</div>`
              : html`
                <form onSubmit=${(/** @type {Event} */ e) => {
                  e.preventDefault();
                  reactivate.run().catch(() => {});
                }}>
                  <${Field} label="Username or email">
                    <${Input} value=${login} onInput=${setLogin}
                      autocomplete="username" />
                    </${Field}>
                    <${Field} label="Password">
                      <${Input} type="password" value=${password}
                        onInput=${setPassword} autocomplete="current-password" />
                      </${Field}>
                      <${FormError} error=${reactivate.error} />
                      <button class="btn primary" style=${{
                        width: '100%',
                        justifyContent: 'center',
                      }}
                        disabled=${reactivate.busy}>Ask to be made active again</button>
                      </form>
              `}
            <div class="toolbar mt"><button type="button" class="linklike" onClick=${() => {
              setSent(false);
              setMode('signin');
            }}>Back to sign in</button></div>
          </${AuthCard}>
    `;
  }

  return html`
    <${AuthCard} title="Sign in" guide="signin"
      sub=${(lostChanges.value ? "Changes you hadn't saved were lost. " : '') +
        (ended.value === 'expired'
          ? 'Your session ended. Sign in again.'
          : "Your household's finances, on your own server.")}>
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        signIn.run().catch(() => {});
      }}>
        <${Field} label="Username or email" error=${errAt(signIn.error, 'login')}>
          <${Input} value=${login} onInput=${setLogin} autocomplete="username" required />
          </${Field}>
          <${Field} label="Password">
            <${Input} type="password" value=${password} onInput=${setPassword}
              autocomplete="current-password" required />
            </${Field}>
            <${FormError} error=${signIn.error} shown=${['login']} />
            <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
              disabled=${signIn.busy}>Sign in</button>
            </form>
            <div
              class="toolbar mt"><button type="button" class="linklike" onClick=${() => {
                setSent(false);
                setMode('forgot');
              }}>Forgot password?</button>${signupOpen?.open
                ? html`
                  <span class="grow"></span><button type="button" class="linklike"
                    onClick=${() => {
                      setSent(false);
                      setMode('signup');
                    }}>Sign up</button>
                `
                : null}</div>
            </${AuthCard}>
  `;
}
