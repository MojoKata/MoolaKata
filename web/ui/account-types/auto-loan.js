// The Auto loan account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'auto-loan',
  label: 'Auto loan',
  group: 'liabilities',
  icon: 'car',
  hint: 'Liability with terms',
  investing: false,
  contributions: false,
  loan: true,
};
