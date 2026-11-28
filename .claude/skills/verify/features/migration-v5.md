# Upgrade a v4 database to v5

The coordinator runs `init` on the existing v4 DB to keep Run history and make schema v5 features available.

## Sub-features

- See an upgrade instruction when opening v4 data with the current CLI.
- Upgrade in place and repeat `init` safely.
- Resume a preserved Dispatch and receive a v5 note.

## How to get to it (user POV)

Reopen a repository with an existing v4 State DB after upgrading the plugin. Initialize the same DB path and continue a waiting Dispatch.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" migration-v5` after launch and doctor.

1. Use the historical v4 CLI from the fetched history to create a second DB with a Run, Task, and waiting Dispatch that has a saved session and question.
2. Run current `status` against the v4 DB and require the upgrade instruction. Run current `init` on that path and compare old records and new v5 defaults.
3. Add a Run note, answer the preserved question, and resume the same Dispatch in turn 2. Check repeat `init` and database integrity. Inspect `migration.json`.

## Gotchas

- The fixture comes from the historical CLI at `c94b299`. The launch DB remains available for doctor.
- See [version checks and migration](../../../../plugin/skills/team-up/scripts/team_up.py#L256) and [the coordinator guide](../../../../plugin/references/team-up.md#L17).
