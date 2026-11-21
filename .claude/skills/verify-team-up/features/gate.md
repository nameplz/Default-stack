# Decision gate before a merge-dependent Task

A Task that depends on a merge becomes reservable only after its prerequisite is merged and the user approves the decision gate. A rejection keeps the Task blocked.

## Sub-features

- Block reservation while the prerequisite is unmerged.
- Block reservation while the gate has no decision.
- Admit the approved Task and keep the rejected Task blocked after the merge.

## How to get to it (user POV)

Ask the coordinator to stage a rollout after a prerequisite merges into `main`. Give one gate an approval and give the other a REJECT decision.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" gate` after launch and doctor.

1. Open a Run with `--base main` and two slots. Create a prerequisite and two dependent Tasks with `--after-merge` and distinct `--gate` names. Require `reserve --task` to return `null` for the blocked Task.
2. Verify the candidate revision in the linked worktree. Report `done`, process the event, and record a successful exit. Approve the first gate and confirm its Task still cannot be reserved.
3. Fast-forward the disposable `main` to the candidate. Prove ancestry with `git merge-base --is-ancestor`. Record `merged --base main --commit <sha>` and confirm the undecided Task still cannot be reserved.
4. Record `gate <run> rollout-reject --decision reject`. Reserve the rejected and approved Tasks by ID. Require `null` for the rejected Task and a Dispatch for the approved Task. Check `gate-reservations.json` and `status.json`.

## Gotchas

- After the merge, both an undecided gate and an explicit `reject` keep the Task blocked. `gate-reservations.json` records `null` for the rejected Task and a Dispatch for the approved Task.
- Use two gates so approval and rejection have independent decisions. Leave a second slot available when probing the approved control.
