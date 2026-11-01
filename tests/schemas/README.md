# Pinned SBOM validation schemas

These test fixtures are the published JSON Schemas for CycloneDX 1.5 and SPDX 2.3:

- CycloneDX: `https://github.com/CycloneDX/specification/blob/master/schema/bom-1.5.schema.json` (Apache-2.0; schema declares its own licence in its header).
- SPDX: `https://github.com/spdx/spdx-spec/blob/v2.3/schemas/spdx-schema.json` (SPDX 2.3 release schema).

They are vendored so tests run offline and validate generated documents against the standards' schemas. Update them only as part of an explicit format-version change or upstream schema refresh.
