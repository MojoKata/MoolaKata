// What the page was served with: the app's version and whether this is dev mode.
const meta = (/** @type {string} */ name) =>
  document.querySelector(`meta[name="${name}"]`)?.getAttribute('content') ?? '';

export const version = meta('mk-version');
export const dev = meta('mk-dev') === '1';
/** The generated mockup (S12.9): the app on recorded answers, with the MOCK pill. */
export const mockup = meta('mk-mockup') === '1';
/** Where the app's own files are: versioned, cached for a year in a release (S17.3.5). */
export const base = `/ui/v/${version}`;
/** Whether the help guides' screenshots are here (S12.7.5): without them a guide shows none. */
export const shots = meta('mk-shots') === '1';
/** Where the help guides and their screenshots are; the generated mockup points elsewhere. */
export const guides = meta('mk-guides') || `${base}/guides`;
