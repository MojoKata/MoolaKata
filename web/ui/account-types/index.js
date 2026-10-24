// Every account type this release has, in the New account dialog's order (requirements S1.1).
// One module per type holds its label, group, icon and which tabs and fields it has; its help
// part is guides/account-<type>.md.
import t0 from './checking.js';
import t1 from './savings.js';
import t2 from './money-market.js';
import t3 from './cd.js';
import t4 from './credit-card.js';
import t5 from './brokerage.js';
import t6 from './ira.js';
import t7 from './roth-ira.js';
import t8 from './401k.js';
import t9 from './403b.js';
import t10 from './457b.js';
import t11 from './hsa.js';
import t25 from './crypto-exchange.js';
import t26 from './crypto-wallet.js';
import t12 from './mortgage.js';
import t13 from './heloc.js';
import t14 from './auto-loan.js';
import t15 from './student-loan.js';
import t16 from './personal-loan.js';
import t17 from './loan.js';
import t18 from './precious-metals.js';
import t19 from './collectables.js';
import t20 from './real-estate.js';
import t21 from './vehicle.js';
import t22 from './other-asset.js';
import t23 from './529.js';
import t24 from './daf.js';
import t27 from './cash.js';
import t28 from './payment-app.js';

/**
 * @typedef {Object} AccountType
 * @property {string} type
 * @property {string} label
 * @property {string} group
 * @property {string} icon
 * @property {string} hint
 * @property {boolean} investing  has Holdings, a lot method and trades
 * @property {boolean} reconcilable  has a Reconcile tab
 * @property {boolean} contributions  records contribution years and sources
 * @property {boolean} [loan]  has terms, a schedule and a payoff planner (S1.9)
 * @property {boolean} [education]  a 529 plan: its plan, contributions, withdrawals and goal (S1.8)
 * @property {boolean} [wallet]  a self-custody wallet: its keys and addresses (S1.6)
 * @property {string} [physical]  holds items (S1.10), valued this way unless one says otherwise
 */

/** @type {AccountType[]} */
export const TYPES = [
  t0,
  t1,
  t2,
  t3,
  t27,
  t28,
  t4,
  t5,
  t6,
  t7,
  t8,
  t9,
  t10,
  t11,
  t25,
  t26,
  t12,
  t13,
  t14,
  t15,
  t16,
  t17,
  t18,
  t19,
  t20,
  t21,
  t22,
  t23,
  t24,
];

/** @type {Record<string, AccountType>} */
export const BY_TYPE = Object.fromEntries(TYPES.map((t) => [t.type, t]));
