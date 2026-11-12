// The vehicle account type (requirements S1.1, S1.10): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'vehicle',
  label: 'Vehicle',
  group: 'physical-assets',
  icon: 'car',
  hint: 'Depreciates',
  investing: false,
  contributions: false,
  physical: 'depreciation',
};
