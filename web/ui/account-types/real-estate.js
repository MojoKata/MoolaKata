// The real estate account type (requirements S1.1, S1.10): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'real-estate',
  label: 'Real estate',
  group: 'physical-assets',
  icon: 'home',
  hint: 'Property, improvements',
  investing: false,
  contributions: false,
  physical: 'valuations',
};
