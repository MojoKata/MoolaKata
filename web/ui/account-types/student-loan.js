// The Student loan account type (requirements S1.1, S1.9): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'student-loan',
  label: 'Student loan',
  group: 'liabilities',
  icon: 'grad',
  hint: 'Liability with terms',
  investing: false,
  contributions: false,
  loan: true,
};
