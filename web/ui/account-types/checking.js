// The Checking account type (requirements S1.1): its fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'checking',
  label: 'Checking',
  group: 'banking',
  icon: 'bank',
  hint: 'Bank · OFX, QFX, CSV',
  investing: false,
  contributions: false,
};
