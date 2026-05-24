# fleet_platform/services/ssh_keypair.py
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_DEFAULT_KRI_DIR = Path.home() / ".kri"
_DEFAULT_PRIV = _DEFAULT_KRI_DIR / "id_rsa"
_DEFAULT_PUB  = _DEFAULT_KRI_DIR / "id_rsa.pub"


def ensure_controller_keypair(
    priv_path=None,
    pub_path=None,
) -> tuple[str, str]:
    priv_path = Path(priv_path) if priv_path else _DEFAULT_PRIV
    pub_path  = Path(pub_path)  if pub_path  else _DEFAULT_PUB
    priv_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    if not priv_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        priv_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_openssh = key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        priv_path.write_bytes(priv_pem)
        priv_path.chmod(0o600)
        pub_path.write_bytes(pub_openssh + b"\n")
        pub_path.chmod(0o644)

    pubkey = pub_path.read_text().strip()
    return str(priv_path), pubkey


def get_controller_pubkey(pub_path=None) -> str | None:
    pub_path = Path(pub_path) if pub_path else _DEFAULT_PUB
    if not pub_path.exists():
        return None
    return pub_path.read_text().strip()
