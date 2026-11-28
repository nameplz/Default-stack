# Shared Run notes

The coordinator records decisions with `note <run> <text>`. Each new turn receives a Run-scoped note snapshot with the latest notes first.

## Sub-features

- Record notes and see the Run's note version advance in schema v5.
- Read the updated snapshot when a Dispatch resumes.
- Keep notes scoped to their Run and retain full text in `status`.

## How to get to it (user POV)

Ask the coordinator to write down a convention for the Run. Update it while a worker is active, then ask the worker to continue after a question.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" run-notes` after launch and doctor.

1. Add a note and start a Dispatch. Add another note during the turn. Check the Run advances while the active Dispatch keeps its original note version.
2. Record and answer a question, then resume. Require the new brief to include the two notes newest first and carry the new version.
3. Add a long UTF-8 note and start a later Dispatch. Verify the brief is at most 4 KiB with the truncation marker and full notes remain in `status`. Use a second Run to check isolation. Inspect `notes-briefs.json` and `status.json`.

## Gotchas

- The size limit counts UTF-8 bytes in the brief. The database retains full notes.
- See [note storage and brief formatting](../../../../plugin/skills/team-up/scripts/team_up.py#L383) and [the coordinator guide](../../../../plugin/references/team-up.md#L99).
