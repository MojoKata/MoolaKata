// The Mortgage account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'mortgage',
  label: 'Mortgage',
  group: 'liabilities',
  icon: 'home',
  hint: 'Liability with terms',
  investing: false,
  contributions: false,
  loan: true,
};
