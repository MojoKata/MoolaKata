// The warnings that show only while their condition holds (requirements R3.12): each condition
// as a pure function of what the screen holds, so the unit tests read every data point without
// a page.
import { Dec, dec } from '../kit/dec.js';

/**
 * Whether a single gift of this amount needs a written acknowledgement: $250 or more (S8.9),
 * read exactly. Nothing typed needs none.
 * @param {Dec | string | number | null | undefined} amount
 */
export function ackNeeded(amount) {
  return amount != null && !dec(amount).lt(Dec.of(250));
}

/**
 * Whether a category's receipts are kept under 7 years, shorter than some IRS audit windows
 * (S14.10.1.1). A blank, which takes the parent's period or keeps them for ever, is not.
 * @param {number | null | undefined} years
 */
export function keptUnderSeven(years) {
  return years != null && years < 7;
}

/**
 * The line under the lots moved in (S2.2, CR3-73): none typed, they arrive as one lot whose day
 * bought is missing; a lot without a cost basis is marked missing until it has one; every lot
 * costed, nothing.
 * @param {{ costBasis?: Dec | string | null, [k: string]: unknown }[]} rows
 * @returns {string | null}
 */
export function transferLotsLine(rows) {
  if (!rows.length) {
    return 'None typed: one lot whose day bought is missing, its term unknown until you add it.';
  }
  if (rows.some((r) => r.costBasis == null || r.costBasis === '')) {
    return 'Marked basis missing until you add it.';
  }
  return null;
}

/**
 * Whether the gift plan's Birthday warns that its year differs from theirs: a person by this
 * name is already here, the plan isn't using them, and it is marked A Different Person (S10.10.3).
 * @param {unknown} clash the person already here by this name, or null
 * @param {boolean} using whether the plan uses them
 * @param {boolean | null | undefined} different whether it is marked A Different Person
 */
export function birthYearDiffers(clash, using, different) {
  return Boolean(clash && !using && different);
}
