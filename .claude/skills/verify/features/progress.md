# Worker progress and stalled status

A worker reports progress during an active turn. The board shows the latest report, changes in the assigned worktree, and whether updates have stalled.

## Sub-features

- Send `progress <dispatch> --turn N [--step k/n] <text>`.
- Read progress fields, last update, and worktree diff stats from the board.
- Observe a stall after ten minutes without updates and clear it with a heartbeat.

## How to get to it (user POV)

Ask the coordinator for progress while a worker edits a file. Check for the stall marker when the worker has been quiet.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" progress` after launch and doctor.

1. Start the worker and verify initially empty progress fields. Report step `2/4`, update the text without a step, and probe an incorrect turn number.
2. Modify a tracked file and add untracked text and binary files. Require three changed files, four added lines, and one deleted line.
3. Set both saved update timestamps to a past time in the disposable DB to cross the ten-minute threshold. Require `stalled: true` in JSON and the text stall marker. Send a heartbeat and require the flag to clear. Check `progress-snapshots.json` and `progress-stalled.txt`.

## Gotchas

- Binary files count as files and contribute zero lines. An omitted step preserves the last reported step.
- See [progress updates](../../../../plugin/skills/team-up/scripts/team_up.py#L1182), [diff stats](../../../../plugin/skills/team-up/scripts/team_up.py#L1438), and [the coordinator guide](../../../../plugin/references/team-up.md#L300).
