"""Ed25519 component attestations (G-17).

Signatures bind the component identity and sealed artifact digest. Private keys are
never copied into the catalog; public keys are pinned in the local trust store.
"""
from __future__ import annotations

import base64
import json
import os
import tomllib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app_forge.domain.errors import SecurityBlock, ValidationFailure

ATTESTATION_FILE = "attestation.json"
_FORMAT = "app-forge-ed25519-v1"


def _payload(component_id: str, version: str, digest: str, key_id: str) -> bytes:
    return json.dumps({"format": _FORMAT, "component": component_id, "version": version,
                       "digest": digest, "key_id": key_id}, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def generate_keypair(private_path: Path, public_path: Path, *, key_id: str) -> dict:
    if not key_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in key_id):
        raise ValidationFailure("key id must contain only letters, digits, '.', '_' or '-'")
    private_path, public_path = Path(private_path), Path(public_path)
    if private_path.exists() or public_path.exists():
        raise ValidationFailure("refusing to overwrite an existing key")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption())
    public_bytes = key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo)
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(private_bytes)
    public_path.write_bytes(public_bytes)
    return {"key_id": key_id, "private_key": str(private_path), "public_key": str(public_path)}


def sign_component(version_dir: Path, private_path: Path, *, key_id: str) -> Path:
    version_dir, private_path = Path(version_dir), Path(private_path)
    manifest = tomllib.loads((version_dir / "component.toml").read_text(encoding="utf-8"))
    component = manifest.get("component", {})
    from app_forge.catalog.registry import compute_artifact_digest
    digest = compute_artifact_digest(version_dir)
    declared = manifest.get("provenance", {}).get("digest")
    if digest != declared:
        raise SecurityBlock("cannot sign an artifact whose sealed digest does not match")
    try:
        key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise ValidationFailure(f"cannot load Ed25519 private key: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValidationFailure("private key must be Ed25519")
    payload = _payload(component["id"], component["version"], digest, key_id)
    document = {"format": _FORMAT, "component": component["id"], "version": component["version"],
                "digest": digest, "key_id": key_id,
                "signature": base64.b64encode(key.sign(payload)).decode("ascii")}
    out = version_dir / ATTESTATION_FILE
    out.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return out


def verify_component(version_dir: Path, trusted_keys: Path) -> dict:
    version_dir, trusted_keys = Path(version_dir), Path(trusted_keys)
    attestation = version_dir / ATTESTATION_FILE
    if not attestation.is_file():
        return {"status": "unsigned", "key_id": None}
    try:
        doc = json.loads(attestation.read_text(encoding="utf-8"))
        manifest = tomllib.loads((version_dir / "component.toml").read_text(encoding="utf-8"))
        component = manifest["component"]
        from app_forge.catalog.registry import compute_artifact_digest
        digest = compute_artifact_digest(version_dir)
        if doc.get("format") != _FORMAT or doc.get("component") != component.get("id") or doc.get("version") != component.get("version"):
            raise SecurityBlock("component attestation identity does not match its manifest")
        if doc.get("digest") != digest or doc.get("digest") != manifest.get("provenance", {}).get("digest"):
            raise SecurityBlock("component attestation digest does not match the sealed artifact")
        key_id = doc.get("key_id")
        if not isinstance(key_id, str) or not key_id or Path(key_id).name != key_id:
            raise SecurityBlock("invalid attestation key id")
        key_path = trusted_keys / f"{key_id}.pub"
        if not key_path.is_file():
            raise SecurityBlock(f"component is signed by untrusted key {key_id!r}")
        key = serialization.load_pem_public_key(key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise SecurityBlock("trusted key is not Ed25519")
        signature = base64.b64decode(doc["signature"], validate=True)
        key.verify(signature, _payload(component["id"], component["version"], digest, key_id))
    except InvalidSignature as exc:
        raise SecurityBlock("component signature verification failed") from exc
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise SecurityBlock(f"invalid component attestation: {exc}") from exc
    return {"status": "verified", "key_id": key_id, "digest": digest}
