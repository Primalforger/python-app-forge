"""Offline SBOM generation and conservative component licence-policy checks."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from app_forge.domain.errors import ValidationFailure


def _pypi_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    if not normalized or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        raise ValidationFailure(f"Invalid Python package name in inventory: {name!r}")
    return normalized


def _inventory_components(inventory: dict) -> list[dict]:
    components = []
    for item in inventory.get("components", []):
        name = str(item.get("id", "")).strip()
        version = str(item.get("version", "")).strip()
        if not name or not version:
            raise ValidationFailure("Installed component inventory entries require id and version")
        components.append({
            "name": name, "version": version, "license": str(item.get("license") or "NOASSERTION"),
            "publisher": str(item.get("publisher") or "NOASSERTION"),
            "purl": f"pkg:generic/{name}@{version}",
            "type": "library",
        })
    for dependency in sorted(set(inventory.get("python_dependencies", []))):
        name = _pypi_name(str(dependency))
        components.append({
            "name": name, "version": "UNKNOWN", "license": "NOASSERTION",
            "publisher": "NOASSERTION", "purl": f"pkg:pypi/{name}", "type": "library",
        })
    return sorted(components, key=lambda item: (item["purl"], item["version"]))


def build_cyclonedx(inventory: dict) -> dict:
    components = _inventory_components(inventory)
    seed = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    serial = uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(seed.encode()).hexdigest())
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": str(inventory.get("project") or "unknown-project"),
                "version": "UNKNOWN",
            }
        },
        "components": [
            {
                "type": item["type"],
                "bom-ref": item["purl"],
                "name": item["name"],
                "version": item["version"],
                "publisher": item["publisher"],
                "licenses": ([{"license": {"id": item["license"]}}]
                             if item["license"] not in ("", "unknown", "NOASSERTION")
                             else []),
                "purl": item["purl"],
            }
            for item in components
        ],
    }


def build_spdx(inventory: dict) -> dict:
    components = _inventory_components(inventory)
    seed = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    namespace = f"https://spdx.org/spdxdocs/{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"
    packages = []
    relationships = []
    for index, item in enumerate(components, start=1):
        spdx_id = f"SPDXRef-Package-{index}"
        packages.append({
            "name": item["name"],
            "SPDXID": spdx_id,
            "versionInfo": item["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": item["license"] if item["license"] not in ("", "unknown") else "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": item["purl"],
            }],
        })
        relationships.append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": spdx_id,
        })
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": str(inventory.get("project") or "unknown-project"),
        "documentNamespace": namespace,
        "creationInfo": {"creators": ["Tool: python-app-forge"], "created": inventory.get("generated_at", "1970-01-01T00:00:00Z")},
        "packages": packages,
        "relationships": relationships,
    }


def check_license_policy(inventory: dict, denied: list[str] | None = None) -> dict:
    denied_set = {value.strip().lower() for value in (denied or []) if value.strip()}
    if any(not value for value in (denied or [])):
        raise ValidationFailure("Denied licence identifiers must be non-empty")
    findings = []
    unknown = []
    for component in inventory.get("components", []):
        license_id = str(component.get("license") or "").strip()
        entry = {"component": component.get("id"), "version": component.get("version"),
                 "license": license_id or "unknown"}
        if not license_id or license_id.lower().startswith("unknown"):
            unknown.append(entry)
        elif license_id.lower() in denied_set:
            findings.append({**entry, "status": "denied"})
    for dependency in inventory.get("python_dependencies", []):
        unknown.append({"component": dependency, "version": "UNKNOWN", "license": "unknown",
                        "reason": "project dependency licence metadata is not available from declared requirements"})
    return {
        "policy": {"denied_licenses": sorted(denied_set)},
        "checked_components": len(inventory.get("components", [])),
        "findings": findings,
        "unknown": unknown,
        "ok": not findings,
        "disclaimer": "A clean result is not a legal opinion. Unknown licence metadata is not treated as approved.",
    }
