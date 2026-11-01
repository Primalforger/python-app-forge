# Online component catalogs

Forge remains local-first. Ordinary catalog scans, component searches, project generation and
verification never contact a network source. Online refresh is an explicit operator action and
is refused while `offline = true`.

## Configure a source

Add the index URL to `$FORGE_HOME/settings.toml`:

```toml
offline = false
catalog_sources = [
  "https://catalog.example.org/index.json",
]
unsigned_component_policy = "deny"
```

You must also pin the publisher's Ed25519 public key:

```sh
forge trust add publisher.pub --key-id publisher-release
```

Then refresh explicitly:

```sh
forge catalog refresh
```

A one-time source can be supplied without editing settings:

```sh
forge catalog refresh --source https://catalog.example.org/index.json
```

Repeat `--source` to refresh more than one index. The command downloads each index and its
artifacts only when invoked. It does not enable background polling.

## Index format

The index is UTF-8 JSON with schema version 1. Each artifact must be a ZIP produced by
`forge component pack`, contain a valid component manifest, and carry a valid detached
attestation from a locally trusted key.

```json
{
  "schema_version": 1,
  "components": [
    {
      "id": "acme.reporting",
      "version": "1.2.0",
      "url": "artifacts/acme.reporting-1.2.0.zip",
      "sha256": "sha256:REPLACE_WITH_64_LOWERCASE_HEX_DIGITS"
    }
  ]
}
```

The archive digest is SHA-256 over the exact downloaded ZIP bytes. The index and artifact
must share an origin. Sources must use HTTPS; plain HTTP is permitted only for loopback
development/test servers. Downloads have fixed size limits and timeouts.

## Acceptance and failure behavior

Before importing a source's artifacts, Forge downloads and preflights the complete index:
archive hashes, ZIP paths, component manifest/digest, index identity, and Ed25519 attestation
are checked. A mismatch or an untrusted signing key blocks the refresh. The normal unsigned
component policy still applies. Accepted artifacts are copied into the local user catalog;
the existing immutable-version rule prevents overwriting an installed version.

This is publisher-key pinning, not a certificate authority or transparency log. Operators
remain responsible for distributing, rotating and revoking trusted keys and for reviewing
component permissions. A valid signature proves integrity and possession of a trusted key,
not that component code is safe.
