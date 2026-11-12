// The Roth IRA account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'roth-ira',
  label: 'Roth IRA',
  group: 'retirement',
  icon: 'retire',
  hint: 'Tax-free',
  investing: true,
  contributions: true,
};
