// The HSA account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'hsa',
  label: 'HSA',
  group: 'retirement',
  icon: 'retire',
  hint: 'Health savings',
  investing: true,
  contributions: true,
};
