// The tour open in this browser tab (requirements S12.17.2): kept for the tab, through a reload,
// until it is closed or the session ends; never shared with another tab or device.
import { effect, signal } from '@preact/signals';

/**
 * A tour: its kind, what it is about, and what it found when it started (a step done since
 * stays, ticked).
 * @typedef {{ kind: 'uses', catId: string, start?: Record<string, number> }} Tour
 */

const KEY = 'mk-tour';

function read() {
  try {
    return /** @type {Tour | null} */ (JSON.parse(sessionStorage.getItem(KEY) || 'null'));
  } catch {
    return null; // storage switched off, or what it held unreadable: no tour
  }
}

/** @type {import('@preact/signals').Signal<Tour | null>} */
export const tour = signal(read());

effect(() => {
  try {
    if (tour.value) sessionStorage.setItem(KEY, JSON.stringify(tour.value));
    else sessionStorage.removeItem(KEY);
  } catch {
    // nothing to do: it lasts as long as the page
  }
});

/** Start a tour; one is open at a time, so it closes any other. @param {Tour} t */
export function startTour(t) {
  tour.value = t;
}

export function endTour() {
  tour.value = null;
}
