// The precious metals account type (requirements S1.1, S1.10): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'precious-metals',
  label: 'Precious metals',
  group: 'physical-assets',
  icon: 'gem',
  hint: 'Valued at spot',
  investing: false,
  contributions: false,
  physical: 'spot',
};
