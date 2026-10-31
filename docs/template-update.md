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

 
## Plan integrity and repeated updates

The approval digest binds each change's content hash as well as its path and before/after hashes. Before creating a checkpoint, apply verifies that every create/modify payload matches its recorded after hash and that create/modify/delete records have consistent hash/content fields. A malformed or edited plan is rejected before project files are touched.

If a target no longer matches the plan's recorded before-state, the plan is marked `stale` and cannot be applied again; create a fresh update plan against the current project. After a successful update, the new baseline and `forge.toml` identity become the starting point for the next versioned update. Successive updates therefore continue to use three-way merge against the most recently applied template version.

## Understanding and resolving conflicts

A conflicted update plan includes a `resolution` field for each conflict in both the normal preview and JSON output. It identifies the affected path, explains the conflict category, and suggests a safe manual resolution. Guidance is advisory: Forge does not choose between competing local and upstream content or rewrite the project to clear a conflict.

Typical resolutions are:

- **Content conflict:** reconcile the local and upstream edits in the affected file.
- **Delete/modify:** decide whether the local deletion or upstream modification should win.
- **Modify/delete:** preserve the customization elsewhere or confirm the upstream removal.
- **Add/add:** rename one file or manually combine the two additions.
- **Unowned path collision:** move the user-owned file or change the incoming template path; Forge never overwrites it.

After resolving a conflict, run `forge project update` again. The old conflicted plan remains a record of the original review and is not converted into an approval by editing its output.

## Reviewing the change preview

For template-update plans, `forge integrate preview PLAN_ID` includes a change summary and files grouped by action (create, modify, delete, and manual). The counts include Forge's baseline and project metadata changes as well as template-owned files.

Add `--content` to include concise unified diffs with three lines of context. Before showing a diff, Forge checks that the current file still matches the plan's recorded before-state. If it has drifted, become unreadable, or been replaced by a symlink, the preview labels that state and omits the potentially misleading diff. Previewing never updates the project or changes plan approval state.
