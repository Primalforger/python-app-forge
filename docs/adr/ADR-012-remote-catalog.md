# ADR-012: Remote catalog

**Status:** Accepted; implemented by the explicit catalog-refresh workflow.

## Context

Offline operation is a core requirement, but operators also need a controlled way to
consume components published outside the local catalog. Automatically contacting
remote sources would undermine predictable offline behavior and could introduce
unreviewed artifacts.

## Decision

Keep ordinary catalog operations local and make remote access an explicit operator
action. `forge catalog refresh` fetches configured or one-time HTTPS index sources,
preflights the complete index and artifacts, verifies archive hashes and Ed25519
attestations against locally trusted publisher keys, and only then imports accepted
artifacts into the local catalog. Refresh is refused when `offline = true`.

There is no background polling or silent download. The operator controls source
configuration, trusted-key distribution, and the timing of refresh.

## Alternatives considered

- Mandatory remote registry access.
- Background catalog polling.
- Accepting unsigned remote artifacts without verification.

## Consequences

Local search, generation, analysis, and verification remain usable without network
access. Remote refresh is available when explicitly requested and configured.
Invalid signatures, untrusted keys, malformed indexes, and artifact hash mismatches
fail closed. Publisher keys are pinned locally; key distribution, rotation, and
revocation remain operator responsibilities.

## Security implications

A valid signature proves artifact integrity and possession of a trusted private key,
not that component code is safe. This mechanism is not a certificate authority or
transparency log. Components still require trust review and permission scrutiny.

## Migration strategy

Existing local catalogs continue to work. Operators who want remote refresh configure
an HTTPS source and pin its Ed25519 public key before invoking the refresh command.
