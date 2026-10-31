// Credentials sealed for the MoolaKata Connector (requirements S18.7.1,
// docs/connector-protocol.md §4.3): an X25519 sealed box made here, in the browser, with
// WebCrypto, that only the connector's sealing key opens. MoolaKata keeps the box as it is.
//
//   box = ephemeral public key (32) ‖ nonce (12) ‖ AES-256-GCM ciphertext, base64url
//   key = HKDF-SHA256(X25519(ephemeral, sealing key), salt = the Connection's id,
//                     info = "moolakata connector credential")

const LABEL = 'moolakata connector credential';

/** @param {string} s */
export function unb64(s) {
  const pad = s.length % 4 ? '='.repeat(4 - (s.length % 4)) : '';
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad);
  return Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
}

/** @param {Uint8Array} b */
export function b64(b) {
  let bin = '';
  for (const x of b) bin += String.fromCharCode(x);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Whether this browser can seal (X25519 in WebCrypto). */
export async function canSeal() {
  try {
    await crypto.subtle.generateKey({ name: 'X25519' }, false, ['deriveBits']);
    return true;
  } catch {
    return false;
  }
}

const SIGNED = new TextEncoder().encode('moolakata connector sealing key\0');

/**
 * Whether the sealing key is the paired connector's own: signed by the action key whose
 * fingerprint an admin confirmed (S18.4.5). Nothing is sealed to a key that isn't.
 * @param {string} sealingKey base64url
 * @param {string} actionKey base64url, Ed25519
 * @param {string} signature base64url
 */
export async function sealingKeyIsSigned(sealingKey, actionKey, signature) {
  try {
    const key = await crypto.subtle.importKey(
      'raw',
      unb64(actionKey),
      { name: 'Ed25519' },
      false,
      [
        'verify',
      ],
    );
    const sealing = unb64(sealingKey);
    const message = new Uint8Array(SIGNED.length + sealing.length);
    message.set(SIGNED, 0);
    message.set(sealing, SIGNED.length);
    return await crypto.subtle.verify({ name: 'Ed25519' }, key, unb64(signature), message);
  } catch {
    return false;
  }
}

/**
 * Seal `plaintext` to the connector's sealing key for one Connection.
 * @param {string} plaintext
 * @param {string} sealingKey the connector's X25519 public key, base64url
 * @param {string} connectionId
 * @returns {Promise<string>} the box, base64url
 */
export async function seal(plaintext, sealingKey, connectionId) {
  const recipient = await crypto.subtle.importKey(
    'raw',
    unb64(sealingKey),
    { name: 'X25519' },
    false,
    [],
  );
  const once = /** @type {CryptoKeyPair} */ (await crypto.subtle.generateKey(
    { name: 'X25519' },
    true,
    ['deriveBits'],
  ));
  const shared = await crypto.subtle.deriveBits(
    { name: 'X25519', public: recipient },
    once.privateKey,
    256,
  );
  const key = await deriveKey(shared, connectionId);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const sealed = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce },
      key,
      new TextEncoder().encode(plaintext),
    ),
  );
  const pub = new Uint8Array(await crypto.subtle.exportKey('raw', once.publicKey));
  const box = new Uint8Array(32 + 12 + sealed.length);
  box.set(pub, 0);
  box.set(nonce, 32);
  box.set(sealed, 44);
  return b64(box);
}

/**
 * Open a box with the sealing private key: the connector's job, here for the tests.
 * @param {string} box
 * @param {CryptoKey} sealingPrivate
 * @param {string} connectionId
 */
export async function open(box, sealingPrivate, connectionId) {
  const raw = unb64(box);
  const pub = await crypto.subtle.importKey('raw', raw.slice(0, 32), { name: 'X25519' }, false, []);
  const shared = await crypto.subtle.deriveBits(
    { name: 'X25519', public: pub },
    sealingPrivate,
    256,
  );
  const key = await deriveKey(shared, connectionId);
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: raw.slice(32, 44) },
    key,
    raw.slice(44),
  );
  return new TextDecoder().decode(plain);
}

/**
 * @param {ArrayBuffer} shared
 * @param {string} connectionId
 */
async function deriveKey(shared, connectionId) {
  const base = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: new TextEncoder().encode(connectionId),
      info: new TextEncoder().encode(LABEL),
    },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}
