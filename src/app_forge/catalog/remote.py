"""Explicit online catalog refresh with bounded downloads and pre-install verification."""
from __future__ import annotations

import hashlib
import json
import tempfile
import tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from app_forge.catalog.authoring import _extract_safely, add_to_catalog, validate_component_dir
from app_forge.catalog.attestation import verify_component
from app_forge.domain.errors import SecurityBlock, Unavailable, ValidationFailure

MAX_INDEX_BYTES = 1_048_576
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
TIMEOUT_SECONDS = 15


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValidationFailure(f"catalog URL must be an absolute HTTPS URL: {url!r}")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValidationFailure("catalog URLs must not contain credentials or fragments")
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SecurityBlock("catalog sources must use HTTPS (HTTP is allowed only for loopback test servers)")
    return parsed.scheme, parsed.hostname.lower(), parsed.port


def _download(url: str, limit: int, expected_origin: tuple[str, str, int | None]) -> bytes:
    if _origin(url) != expected_origin:
        raise SecurityBlock("catalog artifact URL must use the same origin as its index")
    try:
        with urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            if _origin(response.geturl()) != expected_origin:
                raise SecurityBlock("catalog server redirected to a different origin")
            length = response.headers.get("Content-Length")
            if length and int(length) > limit:
                raise ValidationFailure("catalog response exceeds the configured size limit")
            payload = response.read(limit + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise Unavailable(f"catalog download failed: {exc}") from None
    if len(payload) > limit:
        raise ValidationFailure("catalog response exceeds the configured size limit")
    return payload


def refresh_catalog(sources: list[str], catalog_root: Path, trusted_keys: Path,
                    unsigned_policy: str = "deny") -> dict:
    """Fetch each configured index, verify archive hashes and component attestations, then import."""
    if not sources:
        raise ValidationFailure("no catalog sources are configured")
    imported: list[dict] = []
    for source in sources:
        origin = _origin(source)
        index_bytes = _download(source, MAX_INDEX_BYTES, origin)
        try:
            index = json.loads(index_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValidationFailure(f"catalog index from {source} is not valid JSON") from None
        if not isinstance(index, dict) or index.get("schema_version") != 1 or not isinstance(index.get("components"), list):
            raise ValidationFailure(f"catalog index from {source} has an unsupported schema")
        with tempfile.TemporaryDirectory(prefix="forge-catalog-") as tmp:
            staged: list[tuple[Path, str]] = []
            # Validate every artifact before importing any of them.
            for position, item in enumerate(index["components"]):
                if not isinstance(item, dict):
                    raise ValidationFailure("catalog index component entries must be objects")
                component_id, version = item.get("id"), item.get("version")
                artifact_url, expected = item.get("url"), item.get("sha256")
                if not all(isinstance(x, str) and x for x in (component_id, version, artifact_url, expected)):
                    raise ValidationFailure("catalog entries require id, version, url and sha256 strings")
                if len(expected) != 71 or not expected.startswith("sha256:") or any(
                    c not in "0123456789abcdef" for c in expected[7:]
                ):
                    raise ValidationFailure(f"invalid archive SHA-256 for {component_id}@{version}")
                absolute_url = urljoin(source, artifact_url)
                payload = _download(absolute_url, MAX_ARTIFACT_BYTES, origin)
                actual = "sha256:" + hashlib.sha256(payload).hexdigest()
                if actual != expected:
                    raise SecurityBlock(f"catalog archive digest mismatch for {component_id}@{version}")
                archive = Path(tmp) / f"artifact-{position}.zip"
                archive.write_bytes(payload)
                extracted = _extract_safely(archive, Path(tmp) / f"extract-{position}")
                report = validate_component_dir(extracted)
                if not report["ok"]:
                    raise ValidationFailure("remote component failed validation", details=report["problems"])
                manifest = tomllib.loads((extracted / "component.toml").read_text(encoding="utf-8"))
                identity = manifest.get("component", {})
                if identity.get("id") != component_id or identity.get("version") != version:
                    raise SecurityBlock("catalog index identity does not match component manifest")
                signature = verify_component(extracted, trusted_keys)
                if signature["status"] == "unsigned" and unsigned_policy == "deny":
                    raise SecurityBlock("unsigned component rejected by unsigned_component_policy=deny")
                if unsigned_policy not in ("allow", "warn", "deny"):
                    raise ValidationFailure("unsigned_policy must be allow, warn, or deny")
                staged.append((archive, f"{component_id}@{version}"))
            for archive, expected_identity in staged:
                result = add_to_catalog(archive, catalog_root, trusted_keys=trusted_keys,
                                        unsigned_policy=unsigned_policy)
                if result["added"] != expected_identity:
                    raise SecurityBlock("catalog index identity does not match the signed component artifact")
                imported.append({"source": source, **result})
    return {"refreshed": len(imported), "imported": imported}
