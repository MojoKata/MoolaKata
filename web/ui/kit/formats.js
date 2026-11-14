// How what depends on the person is drawn (requirements S17.3.10.2): the time zone moments and
// "today" are in, and bitcoin in BTC or sats. A control's own `timezone` or `bitcoinUnit` wins;
// else its part of the page's, from `Formats`; else the defaults. As `readonly` and `Reading`
// do. No module state: two parts of a page may draw by different ones.
import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import {
  bitcoin,
  day,
  DEFAULT_BITCOIN_UNIT,
  DEFAULT_TIMEZONE,
  moment,
  thisYear,
  today,
} from './format.js';

/** @typedef {{ timezone?: string, bitcoinUnit?: 'btc' | 'sats' }} FormatsValue */

/** What a part of the page draws by: the app sets it at its root, from the session. */
export const Formats = createContext(/** @type {FormatsValue} */ ({}));

/**
 * The format functions that depend on the person, bound to a time zone and bitcoin unit, with
 * the defaults for what is not given. For code outside a component, from the component that
 * builds it.
 * @param {FormatsValue} [given]
 */
export function formatsFor(given = {}) {
  const timezone = given.timezone || DEFAULT_TIMEZONE;
  const bitcoinUnit = /** @type {'btc' | 'sats'} */ (
    given.bitcoinUnit === 'sats' ? 'sats' : DEFAULT_BITCOIN_UNIT
  );
  return {
    timezone,
    bitcoinUnit,
    /** "Oct 12, 2026, 2:05 PM" in the zone. @param {string | null | undefined} iso */
    moment: (iso) => moment(iso, timezone),
    /** "Oct 12, 2026": the moment's day in the zone. @param {string | null | undefined} iso */
    day: (iso) => day(iso, timezone),
    /** Today in the zone, "2026-10-12". */
    today: () => today(timezone),
    /** This year in the zone. */
    thisYear: () => thisYear(timezone),
    /**
     * "0.12345678 BTC" or "12,345,678 sats", from BTC or, with `fromSats`, whole sats.
     * @param {import('./dec.js').Dec | string | number | null | undefined} s
     * @param {boolean} [fromSats]
     */
    bitcoin: (s, fromSats = false) => bitcoin(s, bitcoinUnit, fromSats),
  };
}

/** @typedef {ReturnType<typeof formatsFor>} Fmt */

/**
 * The format functions a component draws by: its own time zone or bitcoin unit, else its part
 * of the page's.
 * @param {FormatsValue} [own]
 */
export function useFormats(own = {}) {
  const page = useContext(Formats);
  return formatsFor({
    timezone: own.timezone ?? page.timezone,
    bitcoinUnit: own.bitcoinUnit ?? page.bitcoinUnit,
  });
}
