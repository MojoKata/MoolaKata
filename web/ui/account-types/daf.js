// The donor-advised fund account type (requirements S1.1, S7.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'daf',
  label: 'Donor-advised fund',
  group: 'giving',
  icon: 'heart',
  hint: 'Giving',
  investing: true,
  contributions: false,
};
