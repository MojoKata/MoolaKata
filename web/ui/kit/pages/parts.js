// What every page of the ui-kit is made of (requirements S17.3.10.4): a control's states side by
// side, each in a card with a line saying what it last reported to its caller; and, beside
// them, its keys and its props, for a reader without the code.
import { useState } from 'preact/hooks';
import { html } from '../html.js';

/**
 * What a demo reports: the value its control last gave, and a setter that records it.
 * @template T @param {T} first
 * @returns {[T, (v: T) => void, string]}
 */
export function useReport(first) {
  const [v, set] = useState(first);
  const [line, setLine] = useState('nothing yet');
  return [v, (/** @type {T} */ x) => {
    set(x);
    setLine(show(x));
  }, line];
}

/** A value as the report line shows it. @param {any} x */
export function show(x) {
  if (x === null || x === undefined) return 'null';
  if (typeof x === 'bigint') return `${x}n`;
  if (typeof x === 'string') return JSON.stringify(x);
  return JSON.stringify(x, (_, v) => (typeof v === 'bigint' ? `${v}n` : v));
}

/**
 * One state of a control: its name, the control, and what it reported.
 * @param {{ id: string, title: string, note?: any, report?: string, children: any }} p
 */
export function Demo({ id, title, note, report, children }) {
  return html`
    <section class="demo" id=${'demo-' + id} data-demo=${id}>
      <h3>${title}</h3>
      ${note ? html`<p class="small dim">${note}</p>` : null}
      <div class="demo-body">${children}</div>
      ${report !== undefined
        ? html`<div class="report small" data-report=${id}>Reported: <code>${report}</code></div>`
        : null}
    </section>
  `;
}

/**
 * A page of the kit: its name, what it is, its states, its keys and its props.
 * @param {{ title: string, about: any, keys?: [string, string][],
 *   props?: [string, string, string][], children: any }} p
 */
export function Page({ title, about, keys, props, children }) {
  return html`
    <article class="kit-page">
      <h1>${title}</h1>
      <p class="about">${about}</p>
      <div class="demos">${children}</div>
      ${keys?.length
        ? html`
          <h2>Keys</h2>
          <table class="t kit-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Does</th>
              </tr>
            </thead>
            <tbody>${keys.map(([k, d]) =>
              html`
                <tr>
                  <td><kbd>${k}</kbd></td>
                  <td>${d}</td>
                </tr>
              `
            )}</tbody>
          </table>
        `
        : null}
      ${props?.length
        ? html`
          <h2>Props</h2>
          <table class="t kit-table">
            <thead>
              <tr>
                <th>Prop</th>
                <th>Type</th>
                <th>Means</th>
              </tr>
            </thead>
            <tbody>${props.map(([n, t, d]) =>
              html`
                <tr>
                  <td><code>${n}</code></td>
                  <td><code>${t}</code></td>
                  <td>${d}</td>
                </tr>
              `
            )}</tbody>
          </table>
        `
        : null}
    </article>
  `;
}
