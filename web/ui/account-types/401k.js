// The 401(k) account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: '401k',
  label: '401(k)',
  group: 'retirement',
  icon: 'retire',
  hint: 'Employer plan, match',
  investing: true,
  contributions: true,
};
