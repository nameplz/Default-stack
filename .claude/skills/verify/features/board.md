# Run board and fix-turn occupancy

The coordinator reads a grouped, read-only view of a Run. An active PR fix turn moves its Task from merging to in progress and uses a Run slot.

## Sub-features

- Read the same Task groups from `board <run>` and `board <run> --json`.
- See a ready Task marked queued and a blocked Task show its prerequisite.
- Use the HTML header and a reservation probe to verify slot occupancy during a fix turn.

## How to get to it (user POV)

Ask for the state of the Run while a PR is failing checks, then ask a worker to fix the failure and check the board again.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" board` after launch and doctor.

1. Create delivered, review, queued, gated, and merge-dependent work. Check the completed Dispatch first appears under review before delivery.
2. Register the delivered PR with the sandbox fake `gh` and sync failing checks. Require the Task to appear under merging and the HTML header to show `0/1`.
3. Instruct and start the fix in turn 2 of the same Dispatch and session. Compare text headings and Task IDs with JSON, require exclusive group membership, and check `1/1` in HTML. Probe reservation of the queued Task and require `null`.
4. Compare `status` before and after the board reads. Check `board-snapshots.json`, `board.txt`, `board-idle.html`, and `board-fixing.html`.

## Gotchas

- The slot count appears in the HTML header. Text and JSON expose Task grouping.
- Grouping and occupancy are implemented in [the CLI](../../../../plugin/skills/team-up/scripts/team_up.py#L1488) and [slot accounting](../../../../plugin/skills/team-up/scripts/team_up.py#L837). See [the coordinator guide](../../../../plugin/references/team-up.md#L298).
