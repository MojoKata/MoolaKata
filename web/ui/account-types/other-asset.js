// The other asset account type (requirements S1.1, S1.10): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'other-asset',
  label: 'Other asset',
  group: 'physical-assets',
  icon: 'gem',
  hint: 'Valued as you say',
  investing: false,
  contributions: false,
  physical: 'valuations',
};
