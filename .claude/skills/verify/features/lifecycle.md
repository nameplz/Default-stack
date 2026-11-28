# Single Dispatch lifecycle

The coordinator receives a verified patch, observes worker exit, delivers the patch, and removes a clean worktree.

## Sub-features

- Reserve and start one Dispatch with the recorded linked worktree and branch.
- Receive and acknowledge the worker's completion report.
- Compare the report with Git, deliver the patch, and remove the clean worktree.

## How to get to it (user POV)

Ask the coordinator to assign one code change to a worker and deliver the result with verification evidence.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" lifecycle` after launch and doctor.

1. Run `run-create` and `task-create` with scope `README.md`. Reserve with `--task`, `--worktree`, and `--branch`. Check `git worktree list --porcelain`, then call `begin` and `started` for turn 1.
2. From the worker checkout, call `heartbeat`, append the fixture line, verify it, and capture scoped Git status and the binary patch against `HEAD`. Call `done --turn 1 --evidence` with the verification and exact patch.
3. Process the `done` event from `wait --timeout 0` and `ack` its cursor. Call `turn-ended` and `exited --code 0`. Require a successful closed Dispatch.
4. Check the full Git status and compare the recorded patch with Git. Save `delivered.patch` and call `delivered`. Require `cleanup <run>` to skip the dirty checkout.
5. Restore the delivered fixture change and require `cleanup <run>` to list the clean Dispatch. Remove the worktree with `git worktree remove`. Confirm the directory and candidate are gone and the branch still exists.

## Gotchas

- The fixture patch is delivered as a file. Restore the fixture only after you save and compare that patch.
- The final `cleanup <run>` output and Git worktree list prove removal. The sandbox cleanup receipt separately proves the evidence survived teardown.
