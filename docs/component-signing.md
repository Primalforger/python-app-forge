# Component signing and attestation (G-17)

App Forge supports Ed25519 detached signatures for component artifacts. The manifest's
sealed SHA-256 digest covers both `component.toml` and `files/`; the detached
`attestation.json` binds that digest to the component ID, version, and signing key ID.
It is included in packed component archives but is not itself part of the artifact digest.

## Create and trust a signing key

```sh
forge trust keygen release-2026 --private-out ~/.app_forge/keys/release-2026.pem --public-out release-2026.pub
forge trust add release-2026.pub --key-id release-2026
```

Keep the private key offline or in a dedicated secrets manager. Never place it in a
component directory or source repository. The public key is copied to
`$FORGE_HOME/trusted-keys/release-2026.pub`.

## Sign, pack, and install

```sh
forge component seal ./catalog/acme.example/1.2.0
forge component sign ./catalog/acme.example/1.2.0 --key ~/.app_forge/keys/release-2026.pem --key-id release-2026
forge component pack ./catalog/acme.example/1.2.0 --out acme-example-1.2.0.zip
forge catalog add acme-example-1.2.0.zip
```

A signature is checked against the local trusted-key store when the catalog is scanned,
before a component can be selected for an installation plan. A changed manifest or
payload invalidates the sealed digest and therefore the signature. Unknown signing keys
and invalid signatures are quarantined; they are never treated as unsigned artifacts.

## Unsigned compatibility policy

Set `unsigned_component_policy` in `$FORGE_HOME/settings.toml`:

- `allow`: accept unsigned artifacts without a warning.
- `warn` (default): preserve compatibility and mark unsigned entries with a warning.
- `deny`: quarantine unsigned artifacts.

The policy applies to all catalog roots, including built-in and user catalogs. Existing
unsigned built-ins remain usable under the default `warn` policy. A deployment that
chooses `deny` must ensure every component it needs has a trusted signature.

This is local key pinning, not a public certificate authority or online transparency
log. Key distribution, rotation, revocation, and private-key custody remain operator
responsibilities. Signatures prove possession of a trusted private key and artifact
integrity; they do not prove that the component is safe.
