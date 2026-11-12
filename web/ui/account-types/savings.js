// The Savings account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'savings',
  label: 'Savings',
  group: 'banking',
  icon: 'bank',
  hint: 'Bank · interest',
  investing: false,
  contributions: false,
};
