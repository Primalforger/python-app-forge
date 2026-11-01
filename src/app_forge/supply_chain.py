"""Offline SBOM generation and conservative component licence-policy checks."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from urllib.parse import quote
from typing import Any

from app_forge.domain.errors import ValidationFailure


_UNKNOWN = {"", "unknown", "noassertion", "none", "n/a"}
_LICENSE_OPERATORS = re.compile(r"\b(?:AND|OR|WITH)\b|[()]")
_NAME = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", re.IGNORECASE)


def _pypi_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
        raise ValidationFailure(f"Invalid Python package name in inventory: {name!r}")
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _inventory_components(inventory: dict) -> list[dict]:
    """Normalize and validate inventory data before serializing either SBOM format."""
    if not isinstance(inventory, dict):
        raise ValidationFailure("Supply-chain inventory must be an object")
    raw_components = inventory.get("components", [])
    raw_dependencies = inventory.get("python_dependencies", [])
    if not isinstance(raw_components, list) or not isinstance(raw_dependencies, list):
        raise ValidationFailure("Inventory components and python_dependencies must be arrays")

    components: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_components):
        if not isinstance(item, dict):
            raise ValidationFailure(f"Inventory components[{index}] must be an object")
        name, version = item.get("id"), item.get("version")
        if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
            raise ValidationFailure(f"Inventory components[{index}] requires non-empty id and version")
        name, version = name.strip(), version.strip()
        license_id = item.get("license") or "NOASSERTION"
        publisher = item.get("publisher") or "NOASSERTION"
        if not isinstance(license_id, str) or not isinstance(publisher, str):
            raise ValidationFailure(f"Inventory components[{index}] licence and publisher must be strings")
        purl = f"pkg:generic/{quote(name, safe='.-_~')}@{quote(version, safe='.-_~')}"
        if purl in seen:
            raise ValidationFailure(f"Duplicate inventory component: {name}@{version}")
        seen.add(purl)
        components.append({
            "name": name, "version": version, "license": license_id.strip() or "NOASSERTION",
            "publisher": publisher.strip() or "NOASSERTION", "purl": purl, "type": "library",
        })

    dependency_names: set[str] = set()
    for dependency in raw_dependencies:
        name = _pypi_name(dependency)
        if name in dependency_names:
            continue
        dependency_names.add(name)
        purl = f"pkg:pypi/{quote(name, safe='.-_~')}"
        if purl not in seen:
            components.append({
                "name": name, "version": "UNKNOWN", "license": "NOASSERTION",
                "publisher": "NOASSERTION", "purl": purl, "type": "library",
            })
            seen.add(purl)
    return sorted(components, key=lambda item: (item["purl"], item["version"]))


def _license_is_expression(value: str) -> bool:
    return bool(_LICENSE_OPERATORS.search(value))


def _cyclonedx_licenses(value: str) -> list[dict]:
    if value.strip().lower() in _UNKNOWN:
        return []
    if _license_is_expression(value):
        return [{"expression": value}]
    return [{"license": {"id": value}}]


def build_cyclonedx(inventory: dict) -> dict:
    components = _inventory_components(inventory)
    seed = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    serial = uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(seed.encode()).hexdigest())
    project = inventory.get("project") or "unknown-project"
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": str(project), "version": "UNKNOWN"}},
        "components": [
            {
                "type": item["type"], "bom-ref": item["purl"], "name": item["name"],
                "version": item["version"], "publisher": item["publisher"],
                "licenses": _cyclonedx_licenses(item["license"]), "purl": item["purl"],
            }
            for item in components
        ],
    }


def build_spdx(inventory: dict) -> dict:
    components = _inventory_components(inventory)
    seed = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    namespace = f"https://spdx.org/spdxdocs/{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"
    packages, relationships = [], []
    for index, item in enumerate(components, start=1):
        license_value = item["license"]
        if license_value.strip().lower() in _UNKNOWN:
            license_value = "NOASSERTION"
        spdx_id = f"SPDXRef-Package-{index}"
        packages.append({
            "name": item["name"], "SPDXID": spdx_id, "versionInfo": item["version"],
            "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION", "licenseDeclared": license_value,
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                "referenceLocator": item["purl"],
            }],
        })
        relationships.append({
            "spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
            "relatedSpdxElement": spdx_id,
        })
    generated = inventory.get("generated_at", "1970-01-01T00:00:00Z")
    if not isinstance(generated, str):
        raise ValidationFailure("Inventory generated_at must be an ISO-8601 timestamp")
    try:
        datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationFailure("Inventory generated_at must be an ISO-8601 timestamp") from None
    return {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT", "name": str(inventory.get("project") or "unknown-project"),
        "documentNamespace": namespace,
        "creationInfo": {"creators": ["Tool: python-app-forge"], "created": generated},
        "packages": packages, "relationships": relationships,
    }


def check_license_policy(inventory: dict, denied: list[str] | None = None) -> dict:
    components = inventory.get("components", []) if isinstance(inventory, dict) else None
    dependencies = inventory.get("python_dependencies", []) if isinstance(inventory, dict) else None
    if not isinstance(components, list) or not isinstance(dependencies, list):
        raise ValidationFailure("Inventory components and python_dependencies must be arrays")
    if any(not isinstance(value, str) or not value.strip() for value in (denied or [])):
        raise ValidationFailure("Denied licence identifiers must be non-empty strings")
    denied_set = {value.strip().casefold() for value in (denied or [])}
    findings, unknown = [], []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ValidationFailure(f"Inventory components[{index}] must be an object")
        name, version = component.get("id"), component.get("version", "UNKNOWN")
        license_id = component.get("license")
        if not isinstance(name, str) or not name.strip():
            raise ValidationFailure(f"Inventory components[{index}] requires a non-empty id")
        if not isinstance(license_id, str) or license_id.strip().casefold() in _UNKNOWN:
            unknown.append({"component": name, "version": version, "license": "unknown"})
            continue
        expression_tokens = re.split(r"\s+(?:AND|OR|WITH)\s+|[()]", license_id, flags=re.IGNORECASE)
        matched = sorted({token.strip().casefold() for token in expression_tokens if token.strip()} & denied_set)
        if matched:
            findings.append({"component": name, "version": version, "license": license_id, "status": "denied",
                             "matched_denied_licenses": matched})
    for dependency in dependencies:
        name = _pypi_name(dependency)
        unknown.append({
            "component": name, "version": "UNKNOWN", "license": "unknown",
            "reason": "project dependency licence metadata is not available from declared requirements",
        })
    return {
        "policy": {"denied_licenses": sorted(denied_set)},
        "checked_components": len(components), "findings": findings, "unknown": unknown,
        "ok": not findings,
        "disclaimer": "A clean result is not a legal opinion. Unknown licence metadata is not treated as approved.",
    }


def generate_sboms(inventory: dict, formats: tuple[str, ...] = ("cyclonedx", "spdx")) -> dict[str, dict]:
    """Build requested SBOM documents using the validated project inventory.

    The returned mapping preserves the caller's format order. Each document is
    deterministic for an identical inventory; timestamps and other metadata
    must therefore be supplied by the caller rather than inferred here.
    """
    if isinstance(formats, (str, bytes)) or not isinstance(formats, (list, tuple)):
        raise ValidationFailure("SBOM formats must be a list or tuple of format names")
    builders = {"cyclonedx": build_cyclonedx, "spdx": build_spdx}
    if not formats:
        raise ValidationFailure("At least one SBOM format must be requested")
    if any(not isinstance(name, str) or name not in builders for name in formats):
        raise ValidationFailure("SBOM formats must contain only 'cyclonedx' and/or 'spdx'")
    if len(set(formats)) != len(formats):
        raise ValidationFailure("SBOM formats must not contain duplicates")
    return {name: builders[name](inventory) for name in formats}


def serialize_sbom(document: dict) -> str:
    """Serialize an SBOM as stable UTF-8-ready canonical JSON with a final newline."""
    if not isinstance(document, dict):
        raise ValidationFailure("SBOM document must be an object")
    try:
        return json.dumps(
            document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise ValidationFailure(f"SBOM document is not valid JSON data: {exc}") from None
