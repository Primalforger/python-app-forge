# Changelog and release notes

The `app_forge.changelog` module provides dependency-free release-note tooling.
It does not inspect Git history or execute Git commands; callers can pass commit
messages from their own source-control integration.

## Parse Conventional Commits

`parse_conventional_commit(message)` accepts a Conventional Commit subject,
optional scope, optional breaking marker (`!`), and a `BREAKING CHANGE:`
or `BREAKING-CHANGE:` footer. A trailing issue reference (`#123` or
`GH-123`) is retained separately. Non-conventional subjects fail explicitly.

## Render and create release notes

Use `ReleaseChange` values with `render_release_notes(version, changes,
release_date=...)` to render stable Markdown grouped into breaking changes,
features, fixes, performance and other changes. Release versions use semantic
version syntax; dates use ISO `YYYY-MM-DD`. Breaking changes appear in their
own section and are not duplicated in their ordinary category.

`create_release_notes(directory, version, changes, ...)` writes
`VERSION.md` using exclusive creation. Existing notes are never overwritten.
The library has no runtime dependencies and does not infer release versions,
dates, or change descriptions.
