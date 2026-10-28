// Leaving a screen's form that holds changes (requirements S12.15.6): a link followed in the
// app, Back, or leaving the page asks first. Installed once, before the router, so that on Back
// it hears the address change ahead of the router: listeners on the window run in the order
// they were added.

/**
 * A screen's form: whether it holds changes, its name for the question, the question itself
 * (resolving to whether to discard), and how to move on.
 * @typedef {{ has: () => boolean, where: string, ask: (where: string) => Promise<boolean>,
 *   route: (url: string) => void }} Guarded
 */

/** @type {Set<Guarded>} */
const guarded = new Set();

/** Guard a screen's form while it is shown; returns what takes the guard off. @param {Guarded} form */
export function guardForm(form) {
  guarded.add(form);
  return () => guarded.delete(form);
}

/** The first of the screen's forms that holds changes. */
const changed = () => [...guarded].find((g) => g.has());

/** Whether a screen's form holds changes: they are lost if the session ends now. */
export function formChanges() {
  return !!changed();
}

let installed = false;

export function installGuard() {
  if (installed) return;
  installed = true;
  let asking = false;
  const here = () => location.pathname + location.search;
  let at = here();
  /** @param {Guarded} form @param {string} url */
  const ask = (form, url) => {
    if (asking) return;
    asking = true;
    form.ask(form.where).then((discard) => {
      asking = false;
      if (!discard) return;
      guarded.clear();
      form.route(url);
    });
  };
  addEventListener('click', (e) => {
    const form = changed();
    if (!form) {
      setTimeout(() => (at = here()));
      return;
    }
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    const a = /** @type {HTMLAnchorElement | undefined} */ (e.composedPath().find((x) =>
      /** @type {any} */ (x).nodeName === 'A' && /** @type {any} */ (x).href
    ));
    if (!a || a.origin !== location.origin || a.target || a.download) {
      return;
    }
    const url = a.href.replace(location.origin, '');
    if (url === here() || url.startsWith('#')) {
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    ask(form, url);
  }, true);
  addEventListener('popstate', (e) => {
    const form = changed();
    // A dialog's own entry coming and going leaves the address where it was.
    if (!form || here() === at) {
      at = here();
      return;
    }
    // Back has moved the address already: put it back, then ask.
    const wanted = here();
    e.stopImmediatePropagation();
    history.pushState(null, '', at);
    ask(form, wanted);
  });
  addEventListener('beforeunload', (e) => {
    if (changed()) e.preventDefault();
  });
}
