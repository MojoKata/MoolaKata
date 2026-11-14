/// <reference lib="deno.ns" />
// The warnings that show only while their condition holds (requirements R3.12), at each data
// point of their condition.
import { ackNeeded, birthYearDiffers, keptUnderSeven, transferLotsLine } from '../app/warnings.js';
import { Dec } from '../kit/dec.js';
import { equal } from '../kit/tests/assert.js';

Deno.test('a written acknowledgement is needed from $250, read exactly (S8.9)', () => {
  const amounts = [null, undefined, '', '0', '249.99', '250', '250.00', '250.01', '1000000000.00'];
  equal(amounts.map(ackNeeded), [false, false, false, false, false, true, true, true, true]);
  // As the record holds it once read: a Dec, at its own places.
  equal(
    ['249.999', '249.99', '250.000', '250'].map((x) => ackNeeded(Dec.parse(x))),
    [false, false, true, true],
  );
  equal([249, 250].map(ackNeeded), [false, true], 'a whole number');
});

Deno.test('receipts kept under 7 years warn; a blank and 7 or more do not (S14.10.1.1)', () => {
  equal([null, undefined, 0, 1, 6, 7, 8].map(keptUnderSeven), [
    false,
    false,
    true,
    true,
    true,
    false,
    false,
  ]);
});

Deno.test('the lots moved in say what is missing: none typed, or a cost (S2.2)', () => {
  const none =
    'None typed: one lot whose day bought is missing, its term unknown until you add it.';
  const basis = 'Marked basis missing until you add it.';
  /** @param {string | null} costBasis */
  const lot = (costBasis) => ({ acquiredOn: '2024-03-01', quantity: '5', costBasis });
  equal(transferLotsLine([]), none);
  equal(transferLotsLine([lot(null)]), basis);
  equal(transferLotsLine([lot('')]), basis);
  equal(transferLotsLine([{ acquiredOn: null, quantity: null }]), basis, 'no cost basis key');
  equal(transferLotsLine([lot('1200.00'), lot(null)]), basis, 'one of several');
  equal(transferLotsLine([lot('1200.00')]), null);
  equal(transferLotsLine([lot('1200.00'), lot('0')]), null, 'a cost of 0 is a cost');
  equal(transferLotsLine([{ costBasis: Dec.parse('2400.00') }]), null, 'a cost as read');
});

Deno.test('the birth year differs only for A Different Person beside one here (S10.10.3)', () => {
  const emma = { id: 'Prsn_1', name: 'Emma Griffin' };
  /** @type {[unknown, boolean, boolean | null | undefined, boolean][]} */
  const cases = [
    [null, false, false, false],
    [null, false, true, false],
    [null, true, false, false],
    [null, true, true, false],
    [emma, false, false, false],
    [emma, false, true, true],
    [emma, true, false, false],
    [emma, true, true, false],
    [emma, false, null, false],
    [emma, false, undefined, false],
  ];
  for (const [clash, using, different, shown] of cases) {
    equal(
      birthYearDiffers(clash, using, different),
      shown,
      JSON.stringify([clash, using, different]),
    );
  }
});
