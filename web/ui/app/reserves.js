// Landed money given to the reserves held where it landed (requirements S7.10.5).
import { Dec, dec } from '../kit/dec.js';

/**
 * An amount spread among reserves by their balances, the last taking what rounding leaves;
 * evenly when none has a balance.
 * @param {string} amount @param {any[]} reserves @returns {string[]}
 */
export function spreadByBalance(amount, reserves) {
  const weights = reserves.map((r) => (dec(r.balance).gt(0) ? dec(r.balance) : dec(0)));
  const total = Dec.sum(weights);
  let left = dec(amount);
  return reserves.map((_, i) => {
    if (i === reserves.length - 1) return String(left);
    const share = total.isZero()
      ? dec(amount).div(reserves.length, 2)
      : dec(amount).mul(weights[i]).div(total, 2);
    left = left.sub(share);
    return String(share);
  });
}
