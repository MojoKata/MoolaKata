"""When a page driven by Playwright has settled: the browser tests (requirements S17.5.8) and the
generated mockup's crawl (S12.9) wait for it before they move on, so each leaves a screen in the
same state every run and nothing the screen asked for is cut off."""

# TRACK_FETCHES, run in each page before its own scripts, counts the requests in flight until
# their bodies are read or they fail (a screen left behind aborts its own); SETTLED holds once
# none has been for 150 ms (time for a screen to start what it fetches next), no Loading
# placeholder shows, and each chart has drawn (ECharts loads on first use and draws its SVG into
# the box). The page's open event stream is not a fetch, so it never counts.
TRACK_FETCHES = """(() => {
  let pending = 0;
  let quiet = 0;
  const fetch0 = window.fetch.bind(window);
  window.__mkSettled = () => pending === 0 && performance.now() - quiet > 150;
  window.fetch = (...args) => {
    pending++;
    const answer = fetch0(...args);
    answer.then((r) => r.clone().arrayBuffer()).catch(() => {}).finally(() =>
      setTimeout(() => {
        pending--;
        quiet = performance.now();
      }, 0)
    );
    return answer;
  };
})();"""
# A function, not an expression: the app's CSP refuses eval.
SETTLED = """() => (!window.__mkSettled || window.__mkSettled())
  && !document.querySelector('[aria-busy="true"]')
  && [...document.querySelectorAll('.chart-box')].every((b) => b.querySelector('svg'))"""
