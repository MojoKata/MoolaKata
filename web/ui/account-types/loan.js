// The Other loan account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'loan',
  label: 'Other loan',
  group: 'liabilities',
  icon: 'card',
  hint: 'Any other loan',
  investing: false,
  contributions: false,
  loan: true,
};
