// The Credit card account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'credit-card',
  label: 'Credit card',
  group: 'liabilities',
  icon: 'card',
  hint: 'Liability',
  investing: false,
  contributions: false,
};
