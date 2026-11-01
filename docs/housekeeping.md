# Local data retention and housekeeping

Run `forge gc` to preview expired local state. It does not delete anything unless
`--apply` is supplied:

```bash
forge gc
forge --json gc
forge gc --apply
```

Retention defaults are intentionally conservative:

| Data | Default | Eligibility |
|---|---:|---|
| Plans | 30 days | Terminal plans only; planned and approved plans are retained |
| Checkpoints | 30 days | Old checkpoints for terminal plans and old orphan checkpoints |
| Evidence | 365 days | Evidence rows older than the configured age |
| Operation history | 365 days | Completed operations older than the configured age |

Configure the periods in `$FORGE_HOME/settings.toml`:

```toml
[retention]
plan_retention_days = 30
checkpoint_retention_days = 30
evidence_retention_days = 365
operation_retention_days = 365
```

Values must be whole days from 1 through 36500. Evidence and completed operation history
are pruned transactionally in SQLite. Pending plans are never eligible. Checkpoints are
retained for pending plans even when their directory is old. Orphan checkpoint directories
are eligible only after the checkpoint retention period.

The preview includes candidate identifiers/counts, protected pending plans and any malformed
plan or filesystem errors. Review it before applying. This is local housekeeping, not a backup:
retain independent project backups and evidence exports when long-term retention is required.
