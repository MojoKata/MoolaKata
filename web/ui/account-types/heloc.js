// The HELOC account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'heloc',
  label: 'HELOC',
  group: 'liabilities',
  icon: 'home',
  hint: 'Home-equity line of credit',
  investing: false,
  contributions: false,
  loan: true,
};
