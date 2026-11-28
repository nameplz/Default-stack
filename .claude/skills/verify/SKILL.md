---
name: verify
description: Verify the team-up coordinator and worker CLI in a disposable Git repository. Use for team-up behavior changes, lifecycle regressions, or reports about dispatch, gates, resume, delivery, and cleanup.
---

# Verify team-up

Use the real [team-up CLI](../../../plugin/skills/team-up/scripts/team_up.py) and follow the [coordinator guide](../../../plugin/references/team-up.md). Read the [feature map](features/README.md) to select a journey.

## Launch

Run from the repository root in a POSIX shell. The helper uses Git and Python 3. The default verification interpreter is `/usr/bin/python3`. If it is unavailable or the CLI warns about SQLite, set `VERIFY_TEAM_UP_PYTHON` to an absolute path to a Python with the SQLite fix required by the guide.

```sh
helper=.claude/skills/verify/scripts/sandbox.py
evidence=$(mktemp -d /tmp/verify-team-up-evidence.XXXXXX)
sandbox=$("$helper" launch "$evidence")
```

Launch creates a new Git repository at the current revision's first parent and adds a linked worktree on branch `worker`. The current revision is available as `FETCH_HEAD` for the merge journey. The first parent must contain `README.md`. Launch calls `init` with an absolute `--db` inside the sandbox. The printed path identifies the sandbox. Run doctor before driving it.

## Doctor

```sh
"$helper" doctor "$sandbox"
```

Require exit 0 and `"ready": true`. Doctor checks the CLI source hash, Python and SQLite version, Git common directory, linked worktree, database identity, schema version, and integrity. It reads an idle DB and logs diagnostics in the evidence directory.

## Drive

Read the chosen [feature recipe](features/README.md). Start a fresh sandbox and evidence directory for each journey.

```sh
"$helper" drive "$sandbox" lifecycle
```

Use the drive argument from the [feature map](features/README.md). Exit 0 means PASS, exit 1 means a user-facing check is FAILING, and exit 2 means the helper could not finish. Rerun doctor after a failed drive and inspect the transcript before classifying it. Clean up after each attempt.

The helper runs the coordinator commands as CLI subprocesses in the disposable repository. It runs worker commands as separate CLI subprocesses in the assigned checkout. Runtime handles and session IDs identify shell-role turns. An optional live Claude Code, Codex CLI, or user-started interactive agy coordinator run with Claude Code or Codex workers requires a separate verification pass covering host launch, permissions, notifications or shell-handle polling, and real session resume.

The board and PR follow-up journeys use a local fake `gh` on the sandbox's PATH. The migration journey also creates a separate v4 DB with the historical CLI from the fetched Git history.

## Evidence

Keep the directory printed by `mktemp`. Record its path and the journey name in the result.

- `commands.jsonl` records each command, working directory, stdout, stderr, and exit code.
- `status.json`, `events.json`, and `messages.json` show the CLI's final view and stored effects. The SQLite dump is read-only.
- `git-state.json` records worktree placement, branch refs, and file status. Review and delivery journeys also save the Git patches.
- `verdict.json` shows the checks that determined the outcome. See each recipe for its extra JSON, text, and HTML artifacts.

Use the CLI responses and observed Git effects as the proof. Use the DB event dump to explain what was recorded. Correlate the IDs across actions, events, and final state. Record a failed expected outcome in the feature's Gotchas with the command and observed result.

## Cleanup

```sh
"$helper" cleanup "$sandbox"
test ! -e "$sandbox"
test -s "$evidence/commands.jsonl"
test -s "$evidence/cleanup.json"
```

The helper deletes its disposable repository, linked worktree, and DB. Keep the separate evidence directory and check that the transcript, verdict, and every journey-specific artifact survived. The app's `cleanup <run>` command lists delivery candidates. The lifecycle journey checks that list and exercises ordinary Git worktree removal before sandbox teardown.

## Helpers

[Executable sandbox.py](scripts/sandbox.py) owns the `launch`, `doctor`, `drive`, and `cleanup` invocations above. Use `commands.jsonl` to replay individual commands while the sandbox exists.
