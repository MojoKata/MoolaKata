// The Payment app account type (requirements S1.1): Venmo, PayPal, Cash App and the like; its
// fields, icon and help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'payment-app',
  label: 'Payment app',
  group: 'banking',
  icon: 'card',
  hint: 'Venmo, PayPal, Cash App',
  investing: false,
  reconcilable: true,
  contributions: false,
};
