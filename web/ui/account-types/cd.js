// The CD account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'cd',
  label: 'CD',
  group: 'banking',
  icon: 'bank',
  hint: 'Certificate of deposit',
  investing: false,
  contributions: false,
};
