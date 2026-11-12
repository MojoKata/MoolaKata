// The crypto exchange account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'crypto-exchange',
  label: 'Crypto exchange',
  group: 'crypto',
  icon: 'coin',
  hint: 'CSV export, statements',
  investing: true,
  contributions: false,
};
