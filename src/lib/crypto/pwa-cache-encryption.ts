/**
 * Client-Side Field-Level Encryption for PWA IndexedDB Cache (MUC 3.1).
 *
 * Implements Misuse Case 3.1 Mitigation:
 * Prevents physical cache dump attacks on lost or stolen mobile devices
 * by encrypting sensitive customer PII (TIN, Ghana Card, Phone, Address)
 * using WebCrypto AES-GCM (256-bit key, 96-bit random IV).
 */

export interface EncryptedPayload {
  ciphertext: string; // Base64 encoded ciphertext + GCM auth tag
  iv: string; // Base64 encoded 96-bit IV
  version: "v1";
}

export interface CustomerCacheRecord {
  id: string;
  organizationId: string;
  name: string;
  tin: string;
  ghanaCardNumber: string;
  billingAddress: string;
  phone: string;
  email: string;
}

export interface EncryptedCustomerCacheRecord {
  id: string;
  organizationId: string;
  name: string; // May remain searchable in UI or encrypted per policy
  encryptedData: EncryptedPayload;
  isEncrypted: true;
}

/**
 * Helper to convert Uint8Array to Base64 string.
 */
function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Helper to convert Base64 string to Uint8Array.
 */
function base64ToUint8Array(base64: string): Uint8Array {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Derives a 256-bit AES-GCM CryptoKey from a session passphrase or device secret using PBKDF2.
 */
export async function deriveCacheKey(
  passphraseOrSecret: string,
  salt: Uint8Array = new TextEncoder().encode("magebooks-pwa-cache-salt")
): Promise<CryptoKey> {
  const cryptoObj = globalThis.crypto;
  if (!cryptoObj?.subtle) {
    throw new Error("WebCrypto API is not supported in this runtime environment.");
  }

  const keyMaterial = await cryptoObj.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphraseOrSecret),
    { name: "PBKDF2" },
    false,
    ["deriveKey"]
  );

  return await cryptoObj.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt as BufferSource,
      iterations: 100_000,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

/**
 * Encrypts arbitrary plaintext string using AES-GCM with a fresh random 96-bit IV.
 */
export async function encryptSensitivePayload(
  plaintext: string,
  key: CryptoKey
): Promise<EncryptedPayload> {
  const cryptoObj = globalThis.crypto;
  const iv = cryptoObj.getRandomValues(new Uint8Array(12));
  const encodedPlaintext = new TextEncoder().encode(plaintext);

  const encryptedBuffer = await cryptoObj.subtle.encrypt(
    {
      name: "AES-GCM",
      iv: iv as BufferSource,
    },
    key,
    encodedPlaintext
  );

  return {
    ciphertext: uint8ArrayToBase64(new Uint8Array(encryptedBuffer)),
    iv: uint8ArrayToBase64(iv),
    version: "v1",
  };
}

/**
 * Decrypts an AES-GCM EncryptedPayload and validates authentication tag integrity.
 */
export async function decryptSensitivePayload(
  payload: EncryptedPayload,
  key: CryptoKey
): Promise<string> {
  const cryptoObj = globalThis.crypto;
  const iv = base64ToUint8Array(payload.iv);
  const ciphertext = base64ToUint8Array(payload.ciphertext);

  const decryptedBuffer = await cryptoObj.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: iv as BufferSource,
    },
    key,
    ciphertext as BufferSource
  );

  return new TextDecoder().decode(decryptedBuffer);
}

/**
 * Encrypts sensitive PII fields of a customer record before storing in local IndexedDB (MUC 3.1).
 */
export async function encryptCustomerCacheRecord(
  customer: CustomerCacheRecord,
  key: CryptoKey
): Promise<EncryptedCustomerCacheRecord> {
  const sensitivePII = JSON.stringify({
    tin: customer.tin,
    ghanaCardNumber: customer.ghanaCardNumber,
    billingAddress: customer.billingAddress,
    phone: customer.phone,
    email: customer.email,
  });

  const encryptedData = await encryptSensitivePayload(sensitivePII, key);

  return {
    id: customer.id,
    organizationId: customer.organizationId,
    name: customer.name,
    encryptedData,
    isEncrypted: true,
  };
}

/**
 * Decrypts a customer record from local IndexedDB cache into full plaintext structure.
 */
export async function decryptCustomerCacheRecord(
  cachedRecord: EncryptedCustomerCacheRecord,
  key: CryptoKey
): Promise<CustomerCacheRecord> {
  const decryptedPIIString = await decryptSensitivePayload(
    cachedRecord.encryptedData,
    key
  );
  const pii = JSON.parse(decryptedPIIString);

  return {
    id: cachedRecord.id,
    organizationId: cachedRecord.organizationId,
    name: cachedRecord.name,
    tin: pii.tin ?? "",
    ghanaCardNumber: pii.ghanaCardNumber ?? "",
    billingAddress: pii.billingAddress ?? "",
    phone: pii.phone ?? "",
    email: pii.email ?? "",
  };
}
