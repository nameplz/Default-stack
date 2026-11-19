# ship-it

Deliver the current change as a pull request with auto-merge on. It merges as soon as the required checks pass. No human review is waited for.

## Preconditions

- Auto-merge is enabled and the default branch requires the `verify` check (`gh api repos/<owner>/<repo>/branches/<default>/protection/required_status_checks`). If not, stop and point to `apply-stack`: without a required check, auto-merge merges immediately.
- Run the repository's `verify` command locally. Fix failures before opening the pull request.

## Steps

1. If you are on the default branch, create a branch for this change. Keep one change per pull request.
2. Commit following the repository's conventions.
3. Push the branch. Never push to the default branch.
4. Open the pull request with `gh pr create`. The body says what changed and why, the `verify` result, and, when behavior changed, evidence from the verification skill (transcripts, screenshots).
5. Turn on auto-merge with `gh pr merge --auto --squash`, or the merge method the repository allows.
6. Watch with `gh pr checks <pr> --watch`.
   - A check fails: read the log (`gh run view <run> --log-failed`), fix the root cause, run `verify`, push. pstack `fix-ci` covers this where it exists.
   - The branch is behind: `gh pr update-branch <pr>`.
   - Conflicts: resolve them, keeping both sides' intent. pstack `fix-merge-conflicts` covers this where it exists.
7. Stop after 3 fix rounds and report what still fails.

## Never

- Merge with `--admin`, disable or remove required checks, or change branch protection.
- Skip, delete or loosen tests or checks to get green.
- Force-push to the default branch.

## Report

The pull request URL, whether it merged, and the merge commit. If it hasn't merged, say what it is waiting on.
