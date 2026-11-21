# Review uncommitted changes in the main checkout

A coordinator assigns a read-only review of the user's live, uncommitted patch. If the reviewer asks a question, the coordinator resumes that session against the same patch and delivers the findings. The user's checkout retains the original patch.

## Sub-features

- Place the Dispatch where the uncommitted patch is visible.
- Record and answer a question, then resume the same reviewer.
- Deliver the review and confirm the live patch is unchanged.

## How to get to it (user POV)

With a dirty main checkout, ask the coordinator, “Have Codex review this and report back.” Answer the reviewer's clarifying question.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" review-main` after launch and doctor.

1. Add an uncommitted line to the disposable main checkout and record its patch. Confirm the linked worktree has a clean patch.
2. Reserve with `reserve --review-main --worktree <main-checkout> --branch main`. Call `begin` and `started`, then confirm registration with the same checkout and branch.
3. From the main checkout, confirm the worker role can read the patch. Call `record`, process the question event, and record the turn end and exit. Require a waiting Dispatch with a session. Publish the answer and call `begin` on the same Dispatch.
4. Require the same session to enter turn 2. Reread the patch, report and deliver the review, and compare the original patch with the final patch. Use `placement-probes.json`, `status.json`, and both patch files as evidence.

## Gotchas

- `--review-main` records the checkout so `begin` can resume the same session after the answer. `placement-probes.json` records both turns, and the two saved patches match byte for byte after delivery. The shell-role journey checks placement and DB behavior. Live worker sandbox enforcement requires a separate host run.
- Use the live patch. A clean linked worktree omits the uncommitted change, and a copied patch exercises a different placement workflow.
