# ship-it

Deliver the current change as a pull request. Use hold mode if the Task's policy is `hold` or `manual`, the user asks to merge it themselves or to keep auto-merge off, or any changed path matches a glob in `.github/merge-policy`. Read one glob per line and ignore comment lines starting with `#`.

## Preconditions

- Outside hold mode, confirm auto-merge is enabled and the default branch requires the `verify` check (`gh api repos/<owner>/<repo>/branches/<default>/protection/required_status_checks`). If either precondition fails, stop and point to `apply-stack`. Without a required check, auto-merge can merge immediately.
- Run the repository's `verify` command locally. Fix failures before opening the pull request.

## Steps

1. If you are on the default branch, create a branch for this change. Keep one change per pull request.
2. Commit following the repository's conventions.
3. Push the branch. Never push to the default branch.
4. Open the pull request with `gh pr create`. The body says what changed and why, the `verify` result, and, when behavior changed, evidence from the verification skill (transcripts, screenshots). For a team-up Task, record delivery and register the PR using [team-up's PR procedure](team-up.md#follow-up-on-pull-requests).
5. In hold mode, skip this step. For a team-up Task, use `pr-arm` only after the user approves the `auto` policy. For other PRs, turn on auto-merge with `gh pr merge --auto --squash` or the merge method the repository allows.
6. For a team-up Task, watch with `wait --sync-prs` and use the same Dispatch for fixes. For other PRs, watch with `gh pr checks <pr> --watch`.
   - If a check fails, read the log with `gh run view <run> --log-failed`. Fix the root cause and run `verify`. Disable auto-merge before pushing a fix to an armed PR. Check the new PR paths against the merge policy before requesting auto-merge again. pstack `fix-ci` covers check failures where it exists.
   - If the branch is behind, disable auto-merge before running `gh pr update-branch <pr>`.
   - Conflicts: resolve them, keeping both sides' intent. pstack `fix-merge-conflicts` covers this where it exists.
7. Stop after three fix rounds and report what still fails. In hold mode, report “ready for the user's merge” once checks pass and the PR is ready to merge.

## Never

- Merge with `--admin`, disable or remove required checks, or change branch protection.
- Skip, delete or loosen tests or checks to get green.
- Force-push to the default branch.

## Report

The pull request URL, whether it merged, and the merge commit. If it hasn't merged, say what it is waiting on.
