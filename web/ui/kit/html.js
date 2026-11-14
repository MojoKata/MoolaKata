// JSX-like templates with HTM, bound to Preact's h(); no build step and no eval.
import htm from 'htm';
import { h } from 'preact';

/** @type {(strings: TemplateStringsArray, ...values: any[]) => any} */
export const html = htm.bind(h);
