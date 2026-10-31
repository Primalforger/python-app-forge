# Project template updates

`forge project update PATH [--template ID@VERSION]` creates a read-only, reviewable three-way update plan for a project created from a Forge template. If omitted, the newest installed version of the project's existing template ID is selected.

The plan compares `.forge/template-baseline.json` (the last pristine template snapshot), current project files, and the incoming rendered template. Independent local edits are preserved; overlapping edits, delete/modify cases, and collisions with files not owned by the prior template are reported as plan conflicts. Forge metadata and the stored baseline are advanced only by applying an approved plan.

Use the normal integration lifecycle:

1. `forge project update PATH [--template ID@VERSION]`
2. Review with `forge integrate preview PLAN_ID --content`
3. `forge integrate approve PLAN_ID --by NAME`
4. `forge integrate apply PLAN_ID`

Adopted projects and projects without a valid baseline are not eligible. This increment plans template-owned files; component contributions remain separately owned.

## Safety and recovery

The update plan is still subject to apply-time drift checks: every changed path must match its recorded pre-update hash when the approved plan is applied. If any target has changed since planning, apply stops before the first write and asks for a new plan.

Apply creates a checkpoint before writing. If a write is interrupted, Forge restores only files whose current bytes still match the exact post-write hash recorded in the checkpoint. Files changed independently after the interruption are preserved and reported for manual review. Recovery validates backup content hashes and refuses to write through symlink targets. A complete rollback marks the plan `rolled_back`; incomplete recovery marks it `partially_recovered`.

The merge policy also covers independent upstream additions and removals, local deletion versus upstream modification, local modification versus upstream deletion, and collisions where an incoming template path is already occupied by an unowned project file. Conflicts remain reviewable but cannot be approved.
