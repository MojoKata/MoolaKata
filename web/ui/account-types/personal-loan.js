// The Personal loan account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'personal-loan',
  label: 'Personal loan',
  group: 'liabilities',
  icon: 'card',
  hint: 'Liability with terms',
  investing: false,
  contributions: false,
  loan: true,
};
