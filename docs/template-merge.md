# Three-way template merge

Template updates must use a three-way merge rather than replacing generated
files. The merge base is the exact template content last applied to the
project; the local side is the current project file; and the incoming side is
the newly rendered template.

`app_forge.templates.merge` provides deterministic, filesystem-independent
primitives for this operation:

- `merge_text(base, local, incoming)` combines non-overlapping line edits.
  Identical edits are accepted once. Overlapping edits and competing insertions
  are returned as conflicts; no partial merged text is returned.
- `merge_file_maps(base, local, incoming)` applies the same rule to a complete
  template file map and handles independent additions, deletions, and
  delete-versus-modify conflicts.

The merge functions never read or write project files. Callers remain
responsible for obtaining a trusted baseline, validating paths, presenting
conflicts for approval, and applying a clean result transactionally. In
particular, a caller must not substitute a file hash for the baseline content:
three-way merging requires the original text.
