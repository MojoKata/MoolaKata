// The 457(b) account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: '457b',
  label: '457(b)',
  group: 'retirement',
  icon: 'retire',
  hint: 'Employer plan',
  investing: true,
  contributions: true,
};
