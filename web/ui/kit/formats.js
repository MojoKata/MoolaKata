// How the kit's controls draw what depends on the person (requirements S17.3.10.2): the time
// zone a date's "today" is in, and bitcoin in BTC or sats. A control's own `timezone` or
// `bitcoinUnit` wins; else its part of the page's, from `Formats`; else what was set at sign-in.
// As `readonly` and `Reading` do.
import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import { defaultBitcoinUnit, defaultTimezone, today } from './format.js';

/** @typedef {{ timezone?: string, bitcoinUnit?: 'btc' | 'sats' }} FormatsValue */

/** What a part of the page draws by: the app sets it at its root, from the session. */
export const Formats = createContext(/** @type {FormatsValue} */ ({}));

/**
 * The time zone and bitcoin unit a control draws by, and today there.
 * @param {FormatsValue} [own]
 */
export function useFormats(own = {}) {
  const page = useContext(Formats);
  const timezone = own.timezone ?? page.timezone ?? defaultTimezone();
  const bitcoinUnit = own.bitcoinUnit ?? page.bitcoinUnit ?? defaultBitcoinUnit();
  return {
    timezone,
    bitcoinUnit: bitcoinUnit === 'sats' ? 'sats' : 'btc',
    today: () => today(timezone),
  };
}
