/// <reference lib="deno.ns" />
// What the charts hand the chart wrapper (requirements S17.4): its table view, its legend and the
// ECharts option it draws, read off the wrapper's props without drawing anything.
import { equal } from '../kit/tests/assert.js';
import { BarChart, FlowChart, ModelsChart } from '../charts/chart.js';

/** The theme's tokens: one it doesn't hold reads as blank, as getComputedStyle gives it. */
const TOKENS = /** @type {Record<string, string>} */ ({ '--c1': '#c1', '--fg': '#fg' });
const t = (/** @type {string} */ name) => TOKENS[name] || '';

/** The wrapper's props for a chart. @param {any} vnode */
const props = (vnode) => /** @type {any} */ (vnode).props;

// The day after which a path is drawn: where the price history ends, about 2026.5.
const LAST = '2026-07-02';

/** @typedef {{ model: string, path: [number, number][] }} Row */
const HISTORY = /** @type {[string, string][]} */ ([
  ['2024-12-31', '95000.5'],
  ['2025-06-30', '107000'],
  [LAST, '64000'],
]);

Deno.test("Compare models' price labels: billions, millions, thousands and plain dollars", () => {
  const { option } = props(ModelsChart({ rows: [], history: HISTORY, names: {} }));
  const label = option(t).yAxis.axisLabel.formatter;
  equal(
    [2.5e9, 1e9, 3.44e6, 1e6, 85_400, 1e3, 512.4, 999.4].map(label),
    ['$2.5B', '$1.0B', '$3.4M', '$1.0M', '$85K', '$1K', '$512', '$999'],
  );
});

Deno.test("Compare models' table: a year with no close or no path point is blank", () => {
  const rows = /** @type {Row[]} */ ([
    { model: 'ark', path: [[2026, 64000], [2027, 150000], [2028, 1.2e6]] },
    { model: 'new', path: [[2026, 64000], [2028, 2.5e9]] },
  ]);
  const p = props(ModelsChart({ rows, history: HISTORY, names: { ark: 'ARK Invest' } }));
  equal(p.rows, [
    ['2024', '$95K', '', ''],
    ['2025', '$107K', '', ''],
    ['2026', '$64K', '$64K', '$64K'],
    ['2027', '', '$150K', ''],
    ['2028', '', '$1.2M', '$2.5B'],
  ]);
  // A model with no name of its own goes by its id, in the legend, the table and the chart.
  equal(p.head, ['Year', 'Price history', 'ARK Invest', 'new']);
  equal(p.legend, [['Price history', '--fg'], ['ARK Invest', '--c1'], ['new', '--c5']]);
  const o = p.option(t);
  equal(o.series.map((/** @type {any} */ s) => s.name), ['Price history', 'ARK Invest', 'new']);
  // Every path starts where the history ends, and the axis runs to its last year's point.
  const end = o.series[0].data.at(-1)[0];
  equal(o.series.slice(1).map((/** @type {any} */ s) => s.data[0][0]), [end, end]);
  equal([o.xAxis.min, o.xAxis.max], [2024, 2028 + (end - 2026)]);
});

Deno.test('Compare models with no price history: the paths are drawn from their own years', () => {
  const rows = /** @type {Row[]} */ ([{ model: 'ark', path: [[2026, 64000], [2027, 150000]] }]);
  const p = props(ModelsChart({ rows, history: [], names: { ark: 'ARK Invest' } }));
  equal(p.rows, [['2026', '', '$64K'], ['2027', '', '$150K']]);
  const o = p.option(t);
  equal(o.series[0].data, []);
  equal(o.series[1].data, [[2026, 64000], [2027, 150000]]);
  equal([o.xAxis.min, o.xAxis.max], [2026, 2027]);
});

Deno.test('Compare models with nothing to draw: no rows, and the axis is left to ECharts', () => {
  const p = props(ModelsChart({ rows: [], history: [], names: {} }));
  equal(p.rows, []);
  const o = p.option(t);
  equal([o.xAxis.min, o.xAxis.max], [undefined, undefined]);
});

Deno.test("a bar's colour the theme doesn't hold is drawn as given", () => {
  const series = [
    { name: 'Planned', color: '#808080', values: ['10'] },
    { name: 'Actual', color: '--c1', values: ['12'] },
  ];
  const { option } = props(BarChart({ label: 'Spending', periods: ['Jan'], series }));
  equal(
    option(t).series.map((/** @type {any} */ s) => s.itemStyle.color),
    ['#808080', '#c1'],
  );
});

Deno.test('with no income, each spending flow is drawn at its own amount', () => {
  const uses = [{ name: 'Rent', amount: '1200' }, { name: 'Food', amount: '300' }];
  const { option } = props(FlowChart({ label: 'Cash flow', sources: [], uses }));
  equal(
    option(t).series[0].links.map((/** @type {any} */ l) => [l.target, l.value]),
    [['Rent', 1200], ['Food', 300]],
  );
});
