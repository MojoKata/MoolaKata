// The 529 plan account type (requirements S1.1, S1.8): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: '529',
  label: '529 plan',
  group: 'education',
  icon: 'grad',
  hint: 'College savings',
  investing: true,
  contributions: false,
  education: true,
};
