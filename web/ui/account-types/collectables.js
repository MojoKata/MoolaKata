// The collectables account type (requirements S1.1, S1.10): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'collectables',
  label: 'Collectables',
  group: 'physical-assets',
  icon: 'star',
  hint: 'Appraised items',
  investing: false,
  contributions: false,
  physical: 'valuations',
};
