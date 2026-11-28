# apply-stack

Goal: block repeated mistakes with structure and checks instead of instructions, have agents run the app and keep evidence, and let changes merge on their own once the checks pass. Build the completion criteria at the end in this repository and show each one with a real run.

## 1. Survey (before changing anything)

- Check that this is a git repository and whether the working tree has uncommitted changes. Leave the user's changes alone and mention them.
- Find the language, package manager, task runner (`package.json` scripts, `Makefile`, `justfile`, `pyproject.toml`, ...), existing lint, type checks, tests and CI, and how the app runs.
- Find the GitHub remote and default branch (`gh repo view --json nameWithOwner,defaultBranchRef,visibility`).
- If there is no runnable user surface (UI, CLI, TUI, API), skip step 3 and say so.
- Show the findings as a short table, then continue.

## 2. One verify command and CI

- Bundle the existing checks into one `verify` command in the repository's own task runner. Reuse an equivalent command if one exists. Don't bring in a new tool for a few lines.
- It must exit non-zero on any violation. Raise warn-only rules that should block to errors.
- Include runtime checks in `verify` when they are fast. Put slow ones in a separate command such as `verify:ui` and write in the agent rules when to run it.
- CI runs that one command and nothing else (on GitHub, `.github/workflows/verify.yml`, job name `verify`), on pull requests only. Branch protection requires the branch to be up to date, so a second run after merge would repeat the same check. Match runtime versions to the local pins.

## 3. Verification skill and feature map

- Follow pstack `create-verification-skill`, with the output fixed at `.claude/skills/verify/` (folder name `verify`).
- Start the feature map with 3-5 real user features.
- Run one feature end to end for real, and check the evidence survives cleanup. Keep evidence outside the repository or in an ignored path.
- Ask the user before sending input to a paid model or external service.
- If the harness only tests committed HEAD, tell the user.
- Link it for Codex: `mkdir -p .agents/skills && ln -sfn ../../.claude/skills/verify .agents/skills/verify`.

If a verification skill already exists, don't make a new one. Follow pstack `maintain-verification-skill`.

## 4. Recurring mistakes as checks

- Follow pstack `correct`. Pick one or two kinds of mistake that recur at least twice in git history, reverts or reviews.
- Choose the earliest means that works: structure, then types, then a lint or CI check, then a behavior test.
- Run the new check against the real past mistake (reproduce the commit temporarily or as a fixture) and show it fails, then show it passes on the current code.
- If there is no evidence of a recurring mistake, don't invent one. Report "no evidence".

Also add these two checks to `verify` when the repository doesn't have them. Their messages name the fix.

| Check | How |
|---|---|
| Architecture boundaries | Prefer structure (separate packages, `internal/`, visibility) first. Otherwise use the ecosystem's tool: dependency-cruiser or `no-restricted-imports` (JS/TS), import-linter (Python), depguard (Go). Encode only boundaries the code already keeps or that a past mistake crossed |
| No comments | Fail on comments in source, except tool directives (lint, type, coverage), license headers, shebangs and generated files. Message: remove the comment and move the reason into a name, type, test or commit message. If existing code has many comments, enforce on lines changed against the merge base instead of rewriting everything, and say which you chose. pstack `no-comments` reviews the existing ones |

## 5. Auto-merge on the required check

Changes reach the default branch only through pull requests that merge themselves when `verify` passes.

These change GitHub settings. Show the commands and get the user's approval before running them. Do this before the pull request that adds CI, not after it: the required check can be set before the job has ever run, and that pull request's own run of `verify` is the first proof of the gate.

First read what protects the default branch now. Never replace settings that are already there. Also list open pull requests (`gh pr list --state open`): their branches lack the new workflow, so once `verify` is required they cannot merge until they are updated from the default branch. Show that list with the approval request.

```sh
gh api repos/<owner>/<repo>/branches/<default>/protection   # classic protection, 404 if none
gh api repos/<owner>/<repo>/rules/branches/<default>        # rulesets that apply to the branch
```

Then make one change, depending on what you found:

| Current state | Change |
|---|---|
| A ruleset governs the branch | Add `verify` to its `required_status_checks` rule (or add that rule) in the ruleset. Leave classic protection alone |
| Classic protection with required status checks | `gh api -X POST repos/<owner>/<repo>/branches/<default>/protection/required_status_checks/contexts -f 'contexts[]=verify'` |
| Classic protection without status checks | `PUT .../protection` with the current settings read above, plus `required_status_checks: {"strict": true, "contexts": ["verify"]}`. Show the user the before and after JSON |
| No protection | `PUT .../protection` with `{"required_status_checks":{"strict":true,"contexts":["verify"]},"enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null}` |

Then `gh repo edit --enable-auto-merge --delete-branch-on-merge`.

- The context name must match the job name in `.github/workflows/verify.yml` exactly. A mismatched name is never reported, so every pull request waits forever.
- Confirm afterwards that everything read in the first step is still there and `verify` is now required.
- If branch protection isn't available (a private repository on a free plan), stop this step and tell the user. Auto-merge without a required check merges immediately.

## 6. Agent rules

Keep `AGENTS.md` as the source of truth, with:

- One line: run `<verify command>` before calling a change done; CI runs the same command.
- Deliver through a pull request with the `ship-it` skill. Never push to the default branch.
- Where the verification skill lives (`.claude/skills/verify/`, linked from `.agents/skills/verify`).
- Repeated corrections: when the user corrects you, check your saved feedback (memory in Claude Code; `~/.codex/corrections.md` in Codex, `~/.gemini/corrections.md` in agy, appending `date | repo | correction`). If the same correction is already there, say it is a repeat and suggest pstack `correct`. Run it only after the user agrees.
- The table `| Rule | Enforced by | Past mistake it catches |`, with commit hashes where there are any.

`CLAUDE.md` imports it with one line, `@AGENTS.md`. If `CLAUDE.md` exists, keep its content and add the import. Don't copy the same text into both files.

## 7. Finish

- Run `verify` again from scratch and confirm it passes.
- Report the completion criteria as a table with evidence (command output, file paths):
  1. verify command
  2. CI running the same command
  3. verification skill and feature map, with run evidence
  4. at least one recurring mistake blocked by a check, plus boundary and comment checks
  5. auto-merge gated on the required `verify` check
  6. rule-to-enforcement table
- Don't commit. Show the changed files. Suggest `ship-it` to deliver them. That pull request's CI run is the first run of `verify` under the required check; confirm it passes there.

## Don't

- Formal verification and per-release exploration. They run on this foundation with `formal` and `explore`.
- Weaken tests or verification journeys to make them pass. Report a failure as a failure.
- Add a rule to `AGENTS.md` as prose only when it can be automated.
