# S17.4. Charts

4. **Charts.** The constraints come from S17.3: an ES module the import map can point
   at, vendored with no bundler, working under `script-src 'self'` and `style-src 'self'`
   with no `eval` and no injected `<style>`, colours from `tokens.css`, both themes, and a
   size that is fine if it loads only with the chart screens. Three candidates are worth
   considering:

   | | **Apache ECharts** 5/6 (Apache-2.0) | **uPlot** (MIT) | **Lightweight Charts** (TradingView, Apache-2.0) |
   | --- | --- | --- | --- |
   | Size (gzip) | ~330 KB full ESM build; ~150 KB hand-picked, but picking needs a bundler, so we'd vendor the full file | ~20 KB | ~45 KB |
   | Charts we need | **all**: line/area with range zoom, donut, **treemap**, **Sankey** (cash flow), candlesticks, stacked bars, Monte Carlo fan (stacked bands), markers | line/area/bars, bands for the fan, markers; **no** donut, treemap or Sankey: we'd draw those as our own SVG | financial time series only: line, area, candles, histogram, markers for trades; **no** donut, treemap, Sankey, fan |
   | Rendering | canvas or **SVG** (switchable; SVG suits theming and print) | canvas | canvas |
   | Performance | good to ~100k points | best by far: millions of points | very good, built for price series |
   | Theming | registered themes, built from our CSS variables at run time | CSS file plus options | options |
   | CSP | clean (sets inline styles only through the DOM, which `style-src` allows) | clean; ships its own CSS file, served as ours | clean |
   | Accessibility | ARIA description generation built in | none | none |
   | Catch | size; a large API surface | we write and maintain the non-time-series charts | **requires a TradingView attribution link on the chart**; only covers prices |

   **Apache ECharts**, lazily imported by the chart screens through a small
   `app/charts/` wrapper (theme from tokens, table-view toggle, number formatting). Sign-in and
   the first screen's budget (S17.3.4: under 150 KB) stay unaffected. It is the only one
   of the three that covers every chart in S5–S7 without code of our own. **uPlot** is the
   choice if size and a minimal surface matter more than coverage, at the cost of a few
   hundred lines of our own SVG for donut, treemap and Sankey. **Lightweight Charts** is
   best kept as a possible *addition* for the holding-detail price chart, not the base.
   Chart.js (MIT, ~70 KB) was considered: it is wide enough except for treemap and Sankey
   (plugins), but its time axis needs a separate date-adapter dependency and its ESM build
   imports a further package. It offers less than ECharts for little size saved.

   The mockup draws its charts with small hand-written SVG functions, so it stays one small
   file and doesn't pre-empt this choice.
