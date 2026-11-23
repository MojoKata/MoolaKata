/// <reference lib="deno.ns" />
// Landed money spread among the reserves held where it landed (S7.10.5).
import { spreadByBalance } from '../app/reserves.js';
import { equal } from '../kit/tests/assert.js';

/** @param {(string | number)[]} balances */
const held = (balances) => balances.map((balance) => ({ balance: String(balance) }));

Deno.test('landed money is spread by balance, the last taking what rounding leaves', () => {
  equal(spreadByBalance('100.00', held(['300.00', '100.00'])), ['75.00', '25.00']);
  equal(spreadByBalance('100.00', held(['1.00', '1.00', '1.00'])), ['33.33', '33.33', '33.34']);
  // A reserve overdrawn counts as holding nothing.
  equal(spreadByBalance('50.00', held(['-20.00', '200.00'])), ['0.00', '50.00']);
});

Deno.test('spread among reserves that hold nothing, it is split evenly', () => {
  equal(spreadByBalance('100.00', held(['0.00', '0.00'])), ['50.00', '50.00']);
  equal(spreadByBalance('100.00', held(['0', '-5.00', '0'])), ['33.33', '33.33', '33.34']);
  equal(spreadByBalance('41.20', held(['0.00'])), ['41.20']);
});
