// The Brokerage account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'brokerage',
  label: 'Brokerage',
  group: 'investing',
  icon: 'candles',
  hint: 'Stocks, ETFs, funds',
  investing: true,
  contributions: false,
};
