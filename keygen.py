"""
keygen.py
=========
One-time script to generate the server's X25519 keypair for E2E sync encryption.

Run ONCE during initial setup or key rotation:
    python keygen.py

Output:
  - Prints the base64-encoded private key  → add to Django settings as SYNC_E2E_PRIVATE_KEY
  - Prints the base64-encoded public key   → paste into sync/crypto.py as SERVER_PUBLIC_KEY_B64
  - Writes keys/server_private.b64 and keys/server_public.b64 for safekeeping

SECURITY RULES:
  ✗ Never commit server_private.b64 or SYNC_E2E_PRIVATE_KEY to version control
  ✗ Never share the private key with anyone
  ✓ The PUBLIC key is safe to embed in the desktop client binary
  ✓ Store the private key in an environment variable or a secrets manager (Vault, AWS SSM, etc.)
  ✓ Back up the private key securely — if lost you must rotate and redeploy all clients

Key rotation procedure:
  1. Run this script again to generate a new keypair
  2. Update SYNC_E2E_PRIVATE_KEY in Django settings and deploy the server first
  3. Update SERVER_PUBLIC_KEY_B64 in sync/crypto.py and ship a new desktop build
  4. Once all clients have updated, old sessions (using old key) will fail gracefully
     with HTTP 400 E2E_DECRYPT_FAILED prompting users to update
"""

import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)


def generate_keypair():
    priv = X25519PrivateKey.generate()
    pub  = priv.public_key()

    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes  = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)

    priv_b64 = base64.b64encode(priv_bytes).decode()
    pub_b64  = base64.b64encode(pub_bytes).decode()

    return priv_b64, pub_b64


def main():
    print("=" * 60)
    print("PrimeBooks E2E Sync — X25519 Keypair Generator")
    print("=" * 60)

    priv_b64, pub_b64 = generate_keypair()

    # Save to files
    keys_dir = Path("keys")
    keys_dir.mkdir(exist_ok=True)

    priv_file = keys_dir / "server_private.b64"
    pub_file  = keys_dir / "server_public.b64"

    priv_file.write_text(priv_b64)
    pub_file.write_text(pub_b64)

    # Restrict private key file permissions on Unix
    if sys.platform != "win32":
        os.chmod(priv_file, 0o600)
        os.chmod(keys_dir, 0o700)

    print()
    print("✓ Keypair generated successfully.")
    print()
    print("─" * 60)
    print("PRIVATE KEY  (add to Django settings as SYNC_E2E_PRIVATE_KEY)")
    print("─" * 60)
    print(f"SYNC_E2E_PRIVATE_KEY = \"{priv_b64}\"")
    print()
    print("─" * 60)
    print("PUBLIC KEY  (paste into sync/crypto.py as SERVER_PUBLIC_KEY_B64)")
    print("─" * 60)
    print(f"SERVER_PUBLIC_KEY_B64: str = \"{pub_b64}\"")
    print()
    print("─" * 60)
    print("Files written:")
    print(f"  {priv_file.resolve()}  ← KEEP SECRET")
    print(f"  {pub_file.resolve()}   ← safe to share")
    print()
    print("⚠  Add keys/ to .gitignore immediately:")
    print("   echo 'keys/' >> .gitignore")
    print("─" * 60)


if __name__ == "__main__":
    main()