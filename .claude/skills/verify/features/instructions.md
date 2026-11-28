# Coordinator instructions and follow-up

The coordinator can send an instruction during a running turn and follow up after a worker reports completion. The user receives a result that addresses the new instruction, or sees an explicit, usable path to continue that Dispatch.

## Sub-features

- Queue an instruction during a running turn that subsequently sends `done`.
- Follow up on the same Dispatch after a completion report and confirmed exit.
- Probe `answer` after `done` with a real question ID.

## How to get to it (user POV)

While a worker is reviewing a file, ask it to check one more thing. After its completion report, ask for a follow-up on the same assignment.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" instructions` after launch and doctor.

1. Begin a linked-worktree Dispatch and call `instruct` while turn 1 is running. Record the instruction ID. Have the worker call `done` with a result that omits the requested addition.
2. Process the done event. Probe `instruct` before host exit. Record `turn-ended` and `exited`, then probe `instruct` and `begin` on that Dispatch. Require a follow-up brief in the same session with the original instruction and the follow-up. Finish the heading check and deliver the result. Check `status` separately for the stored message.
3. In a diagnostic Dispatch, create an actual question with `record`, then submit `done` before answering. Probe `answer` with the question ID. Capture the results in `follow-up-probes.json`.

## Gotchas

- `instruct` accepts the running-turn instruction and the follow-ups before and after host exit. The first exit closes the Dispatch. `begin` then opens turn 2 with the same session and the pending instructions in the brief.
- In the diagnostic Dispatch, `answer` exits 1 for the open question once `done` is recorded. The [coordinator guide](../../../../plugin/references/team-up.md) uses `instruct` for new work after completion. See `follow-up-probes.json` for both paths.
- The diagnostic that sends both `record` and `done` tests rejection against a known question. Follow the guide's one-terminal-path rule in normal turns.
