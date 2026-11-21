/// <reference lib="deno.ns" />
// The holdings a corporate action may be recorded on (S2.4.6, S3.10.1), from the positions.
import { equal } from '../kit/tests/assert.js';
import { holdings } from '../app/holdings.js';

const OPEN = [
  { accountId: 'A', accountName: 'Brokerage', instrumentId: 'VTI', symbol: 'VTI', side: 'long' },
  { accountId: 'A', accountName: 'Brokerage', instrumentId: 'XYZ', symbol: 'XYZ', side: 'short' },
  {
    accountId: 'A',
    accountName: 'Brokerage',
    instrumentId: 'P1',
    symbol: 'MSFT 20NOV26 480 P',
    instrumentClass: 'option',
    underlyingId: 'MSFT',
    underlyingSymbol: 'MSFT',
  },
  {
    accountId: 'A',
    accountName: 'Brokerage',
    instrumentId: 'P2',
    symbol: 'MSFT 20NOV26 500 P',
    instrumentClass: 'option',
    underlyingId: 'MSFT',
    underlyingSymbol: 'MSFT',
  },
  {
    accountId: 'A',
    accountName: 'Brokerage',
    instrumentId: 'C1',
    symbol: 'VTI 20NOV26 300 C',
    instrumentClass: 'option',
    underlyingId: 'VTI',
    underlyingSymbol: 'VTI',
  },
  { accountId: 'B', accountName: 'IRA', instrumentId: 'VTI', symbol: 'VTI', side: 'long' },
];
const keys = (/** @type {any[]} */ rows) =>
  rows.map((p) => `${p.accountId}:${p.instrumentId}${p.optionsOnly ? ' (options)' : ''}`);

Deno.test('every stock held, long or short, and never an option itself', () => {
  equal(keys(holdings(OPEN, undefined, 'merger')), ['A:VTI', 'A:XYZ', 'B:VTI']);
});

Deno.test('a split also offers a stock only whose options are held, once', () => {
  equal(keys(holdings(OPEN, undefined, 'split')), [
    'A:VTI',
    'A:XYZ',
    'B:VTI',
    'A:MSFT (options)',
  ]);
});

Deno.test("one account's alone", () => {
  equal(keys(holdings(OPEN, 'B', 'split')), ['B:VTI']);
});
