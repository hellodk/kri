#!/usr/bin/env python3
"""Secret rotation script — re-encrypts all stored secrets under a new JWT_SECRET.

This script handles the rotation of the JWT_SECRET by:
1. Decrypting all node and group secrets using the old JWT_SECRET
2. Re-encrypting them with the new JWT_SECRET
3. Validating the re-encryption succeeded
4. Running in dry-run mode by default; use --commit to write changes

Usage:
    OLD_JWT_SECRET=old_key NEW_JWT_SECRET=new_key python3 scripts/rotate_secrets.py
    OLD_JWT_SECRET=old_key NEW_JWT_SECRET=new_key python3 scripts/rotate_secrets.py --commit

The --commit flag is required to actually write changes. Without it, runs in dry-run mode.

Warning: Rotating JWT_SECRET without re-encrypting stored node/group secrets makes
all stored credentials unrecoverable. Always use this script.
"""
import os
import sys
import argparse
import base64
import hashlib
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def make_fernet_key(secret: str) -> bytes:
    """Derive a Fernet key from a JWT_SECRET string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def main():
    parser = argparse.ArgumentParser(
        description="Rotate kri JWT_SECRET for stored encrypted secrets"
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write changes to database (default: dry-run)",
    )
    args = parser.parse_args()

    old_secret = os.environ.get("OLD_JWT_SECRET")
    new_secret = os.environ.get("NEW_JWT_SECRET")

    if not old_secret or not new_secret:
        print("ERROR: Set OLD_JWT_SECRET and NEW_JWT_SECRET environment variables")
        sys.exit(1)

    if old_secret == new_secret:
        print("ERROR: OLD_JWT_SECRET and NEW_JWT_SECRET are identical")
        sys.exit(1)

    print(f"Mode: {'COMMIT' if args.commit else 'DRY-RUN'}")
    print("Connecting to database...")

    # Import here after path setup
    from cryptography.fernet import Fernet, InvalidToken
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from fleet_platform.db.session import get_sync_db
    from fleet_platform.models.node_secret import NodeSecret
    from fleet_platform.models.group_secret import GroupSecret

    old_key = make_fernet_key(old_secret)
    new_key = make_fernet_key(new_secret)

    old_fernet = Fernet(old_key)
    new_fernet = Fernet(new_key)

    rotated = 0
    failed = 0
    failed_items = []

    try:
        with get_sync_db() as db:
            # Rotate node secrets
            print("\nRotating NodeSecrets...")
            node_secrets = db.execute(select(NodeSecret)).scalars().all()
            for ns in node_secrets:
                try:
                    plaintext = old_fernet.decrypt(ns.encrypted_value.encode()).decode()
                    new_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
                    if args.commit:
                        ns.encrypted_value = new_encrypted
                    rotated += 1
                    print(f"  ✓ node secret {ns.id} ({ns.key}): OK")
                except InvalidToken:
                    print(
                        f"  ✗ node secret {ns.id} ({ns.key}): FAILED (wrong key or corrupted)"
                    )
                    failed_items.append(f"node_secret:{ns.id}")
                    failed += 1
                except Exception as e:
                    print(f"  ✗ node secret {ns.id} ({ns.key}): ERROR ({e})")
                    failed_items.append(f"node_secret:{ns.id}")
                    failed += 1

            # Rotate group secrets
            print("\nRotating GroupSecrets...")
            group_secrets = db.execute(select(GroupSecret)).scalars().all()
            for gs in group_secrets:
                try:
                    plaintext = old_fernet.decrypt(gs.encrypted_value.encode()).decode()
                    new_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
                    if args.commit:
                        gs.encrypted_value = new_encrypted
                    rotated += 1
                    print(f"  ✓ group secret {gs.id} ({gs.key}): OK")
                except InvalidToken:
                    print(
                        f"  ✗ group secret {gs.id} ({gs.key}): FAILED (wrong key or corrupted)"
                    )
                    failed_items.append(f"group_secret:{gs.id}")
                    failed += 1
                except Exception as e:
                    print(f"  ✗ group secret {gs.id} ({gs.key}): ERROR ({e})")
                    failed_items.append(f"group_secret:{gs.id}")
                    failed += 1

            if args.commit:
                if failed == 0:
                    db.commit()
                    print(f"\n✓ COMMITTED: {rotated} secrets re-encrypted")
                    sys.exit(0)
                else:
                    db.rollback()
                    print(f"\n✗ ROLLED BACK: {failed} failures. No changes made.")
                    print("\nFailed items:")
                    for item in failed_items:
                        print(f"  - {item}")
                    sys.exit(1)
            else:
                print(f"\nDry-run complete: {rotated} rotatable, {failed} would fail")
                if failed > 0:
                    print("\nFailed items that would block rotation:")
                    for item in failed_items:
                        print(f"  - {item}")
                    print(
                        "\nFix the corrupted/unreadable secrets before rotating, or investigate"
                    )
                    sys.exit(1)
                else:
                    print("Re-run with --commit to apply changes")
                    sys.exit(0)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
