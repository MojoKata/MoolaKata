// The self-custody wallet account type (requirements S1.1, S1.6): bitcoin read from its
// extended public keys or addresses, never a private key or seed phrase.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'crypto-wallet',
  label: 'Self-custody wallet',
  group: 'crypto',
  icon: 'wallet',
  hint: 'Address or xpub only',
  investing: true,
  contributions: false,
  wallet: true,
};
