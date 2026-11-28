# Ask, answer, and resume

A worker asks which file to review. The coordinator records the answer and resumes the same Dispatch in the same worktree and session.

## Sub-features

- Wake on a worker question and acknowledge the cursor.
- Keep the saved session while the worker waits for an answer.
- Finish the review in a new turn of that Dispatch.

## How to get to it (user POV)

Give the worker an assignment that needs clarification. When the coordinator presents the worker's question, answer it and ask the worker to continue.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" questions` after launch and doctor.

1. Reserve the linked worktree and call `begin` and `started`. Run worker `record` with the turn and question.
2. Read the question event with `wait` and acknowledge it with `ack`. Call `turn-ended` and `exited --code 0`. Require phase `waiting`.
3. Call `answer` with the question ID. Call `begin` on the same Dispatch. Require turn 2, the original session and worktree, and the answer in the brief. Call `started` with the same session and the new turn handle.
4. Verify the requested file, call worker `done`, process its event, and confirm successful exit. Capture the two turns and answer in the transcript and final status.

## Gotchas

- This recipe covers `record` and next-turn resume. The guide's blocking `ask` path waits inside the same turn and needs a separate drive.
- The saved session ID in this recipe proves the CLI's session continuity. Live host resume remains a separate check.
