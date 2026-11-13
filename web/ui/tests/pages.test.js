/// <reference lib="deno.ns" />
// The page of the record an id names (S12.18.6.2), which the kit's lists link to.
import { pageOf } from '../app/pages.js';
import { equal } from '../kit/tests/assert.js';

Deno.test('a reference reads as a link to its record page where its kind has one', () => {
  const id = (/** @type {string} */ p) => `${p}_01jbx3h7yq0000000000000000`;
  equal(
    ['Acct', 'Bdgt', 'Portf', 'Prjct'].map((p) => pageOf(id(p))),
    [
      `/ui/accounts/${id('Acct')}`,
      `/ui/budgets/${id('Bdgt')}/month`,
      `/ui/portfolios/${id('Portf')}`,
      `/ui/projections/${id('Prjct')}`,
    ],
  );
  equal(['Cat', 'Persn', 'User'].map((p) => pageOf(id(p))), [null, null, null]);
  equal([null, '', 'Checking', 'monthly'].map(pageOf), [null, null, null, null]);
});
