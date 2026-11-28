# Coordinate a run with team-up

Use one coordinator for one active Run in one local Git repository. Start only workers owned by the Run. Keep their execution handles and SQLite records so you can recover after a coordinator restart.

Use `claude` or `codex` for new Tasks. agy remains available as an interactive coordinator that the user starts directly.

## Identify the host and open the Run

1. In the Claude desktop app's Code tab, use the host's side-session tools when they are available. Note whether the current turn came from the user or a background notification. In the Claude Code CLI, use shell jobs for external workers. In an interactive Codex CLI session, follow the [Codex coordinator procedure](#codex-coordinator). In an interactive agy session, follow the [agy coordinator procedure](#agy-coordinator).
2. Use Python 3 with the SQLite WAL-reset fix for the coordinator and worker commands. For Claude workers, use the same executable in the Bash allow rule. `init` and `status` warn if the current Python uses an affected version. The fix is in SQLite 3.51.3 and later, with backports starting at 3.44.6 and 3.50.7 on their respective branches. [SQLite's WAL-reset notes](https://www.sqlite.org/wal.html#the_wal_reset_bug)
3. Resolve `scripts/team_up.py` relative to the installed `SKILL.md`. Set `script` to its absolute path and `python` to the selected Python executable. Run `init` from the target repository before any worker connects. Keep the absolute DB path returned by `init`. Set `db` to that path and `state_dir` to its parent. Give each worker the same DB path. Worktree checks use the Git common directory saved at `init`, so with an absolute `--db` path they work from any directory.
4. On pickup, reuse the saved DB path and open the existing Run with `status <run-id>`. Reconcile its worker handles, worktrees, unprocessed events, and pending questions before reserving anything. The DB path defaults to `~/.local/state/default-stack/team-up/<repo-id>.db`. The ID is the first 16 hex digits of the SHA-256 of the real path returned by `git rev-parse --path-format=absolute --git-common-dir`.
5. For a new Run, use `run-create --goal <goal> --slots <count>`. Keep its ID for pickup. Set `--base <ref>` when a dependency requires a merge into a designated branch. Use `task-create` to record each Task's worker type, goal, editable paths, and required completion evidence. Create prerequisites first. Use `--after` for a completion dependency and `--after-merge` for a merge dependency. Add any user decision gate with `--gate <name>`. Record the user's decision with `gate` before dispatching dependent work.

Use the local script's `--help` for command arguments. The examples put `--db` before the subcommand. Replace the shell variables and example values with the actual Run values. Replace the example `python3` with the selected executable if you use a different one.

Run `init` to upgrade a schema v3 or v4 DB to v5 in place. For schema v2 and older, run `init` with a new absolute `--db` path. Keep the old DB for its Run history.

### Existing agy records

agy worker dispatch is no longer supported. Google's [Antigravity Terms of Service §6](https://antigravity.google/terms) and [FAQ](https://antigravity.google/docs/faq) prohibit third-party agent orchestration with consumer sign-in. team-up does not inspect authentication, so it blocks agy workers for all authentication types.

Schema v5 preserves saved agy Tasks, Dispatches, events, and evidence. team-up blocks new agy Tasks, reservations, retries, turns, answers, and instructions. Automatic reservation skips saved agy Tasks. If the Dispatch is `running` or `turn-ended` and has no recorded runtime, team-up also rejects `register` and `started`. Use `status <run-id>` to inspect Tasks, Dispatches with completion evidence, dependencies, and messages. Use `wait <run-id> --timeout 0` to read unacknowledged `question` and `done` events.

Use `stop <dispatch-id>` to close a reservation that never began. For a begun Dispatch, record `stop` and ask the host to terminate that exact worker if it is still live. Keep the slot and worktree while liveness is unknown, even if the Dispatch has no runtime handle. After confirming shutdown, record `exited <dispatch-id> --turn <turn> --code <exit-code> --stopped`. If the worker exited on its own and no stop was requested, reconcile the actual exit with `exited`. Preserve saved results and follow the usual [delivery and cleanup checks](#deliver-and-clean-up).

After confirming that the old worker has shut down or never started, recover unfinished work in the same Run.

1. Create a Claude or Codex Task with `task-create` for the remaining work. Carry over the applicable prerequisites and gates. Copy any unconsumed instruction text shown by `status` into the replacement Task's `--goal`.
2. If you transferred instructions, record `abandon <dispatch-id> --reason "Moved pending instructions to Task <new-task-id>"` on the old Dispatch. For a completed Dispatch with confirmed exit and recorded delivery, this lets `cleanup <run-id>` list the worktree when the other cleanup checks pass.
3. In `status`, find blocked Tasks whose `dependencies` reference the old prerequisite ID. Recreate those Tasks in prerequisite order, including any downstream Tasks blocked by them. For each recreated Task, pass the replacement prerequisite IDs to `--after` or `--after-merge` according to the original dependency. Carry over any unaffected prerequisites and gates. Preserve the original Tasks and Dispatches for history.
4. Reserve the new Task IDs as they become ready. A completion dependency needs a successful result from the replacement prerequisite. A merge dependency also needs a recorded `merged` for that prerequisite after its changes reach the Run's base branch.

### Codex coordinator

Start an interactive Codex CLI session in the target repository. Use the absolute directory that will hold the Run DB as `state_dir`.

```sh
codex -C "$repo" -s workspace-write --add-dir "$state_dir" -a on-request
```

Use the same DB commands as the Claude hosts. Open the Run with `init`, `run-create`, and `task-create`. Dispatch workers with `reserve`, `begin`, and `started`. Track work with `wait`, `ack`, `status`, `turn-ended`, and `exited`. Finish with `delivered` and `cleanup`.

The coordinator's `workspace-write` sandbox protects the Git directory and blocks network access. Use the `on-request` approval prompt to run Git metadata writes outside the sandbox, including `git worktree add`, `git worktree remove`, staging, and commits. Request the same escalation for `codex exec` and `claude -p` launches and resumes. A worker launched inside the coordinator's sandbox inherits its restrictions and can fail on authentication, network access, or session writes.

Use the [Codex worker commands](#codex-worker) with `-s workspace-write --add-dir "$state_dir"`. For Claude workers, use the [Claude CLI commands](#claude-worker) with `--output-format json` and the Task's `--allowedTools` rules. Resume Claude with its saved session ID and check `permission_denials` after each turn. Side sessions and `Agent` with `isolation: worktree` are available only in the Claude desktop app's Code tab.

Start each worker with a short yield in the unified shell tool `exec_command` and save its session handle. Save the worker PID and its process start identity, plus the paths to its output and exit-status files. Poll each handle with an empty `write_stdin` call. Alternate polling with `wait <run-id> --timeout 30` during the active turn. After each return, reconcile questions, `done` reports, and exits, then pass the returned cursor to `ack`. While you have the handle, record `exited` only after it reports the actual exit code. Worker completion does not start a new Codex coordinator turn.

Keep the coordinator turn active until running workers exit when possible. If you must end the turn, save the coordinator's thread ID. Resume that exact thread with the same repository, sandbox, state directory, and approval flags.

```sh
codex resume -C "$repo" -s workspace-write --add-dir "$state_dir" -a on-request \
  "$coordinator_thread_id" "Pick up Run $run_id using DB $db"
```

Pass the absolute DB path in the prompt. Use the saved thread ID every time and avoid `--last`. Treat shell-session handles as unavailable after a coordinator restart. Check `status` and verify each worker using its saved PID and process start identity. Read its saved output and exit-status files to reconcile reports and confirmed exits. Keep the slot reserved while liveness is unknown.

### agy coordinator

Use an interactive agy session started directly by the user in the main checkout of the target repository.

```sh
agy
```

Use the same DB commands as the Claude and Codex hosts. Open the Run with `init`, `run-create`, and `task-create`. Dispatch workers with `reserve`, `begin`, and `started`. Track work with `wait`, `ack`, `status`, `turn-ended`, and `exited`. Finish with `delivered` and `cleanup`.

Use Codex or Claude workers from an agy coordinator, following their sections below. Side sessions and `Agent` with `isolation: worktree` are available only in the Claude desktop app's Code tab.

Launch workers as background shell jobs. Save each worker's execution handle, PID and process start identity, and output and exit-status file paths. Poll with `wait <run-id> --timeout 30` and the saved handles. After each return, reconcile questions, `done` reports, and exits, then pass the returned cursor to `ack`. Record `exited` only after confirming the actual exit code. There is no host notification; worker completion does not start a new coordinator turn.

Keep the coordinator turn active while workers run when possible. If you end the turn, save the coordinator's conversation ID and have the user resume it explicitly.

```sh
agy --conversation "$coordinator_conversation_id"
```

Name the Run ID and absolute DB path when picking up. On restart, check `status`, verify each worker using its saved PID and process start identity, and read its saved output and exit-status files to reconcile reports and confirmed exits. Keep the slot reserved while liveness is unknown.

## Record a gate decision

Map a clear user approval to `gate <run-id> <name> --decision approve` and a clear rejection to `--decision reject`. Put the user's explanation in `--note <text>`. Ask for clarification if the answer gives neither decision. Leave the gate undecided while you wait.

A rejected Task stays blocked. If the user later approves the same gate, record `--decision approve` and check the Task's other prerequisites before reserving. This lets the user revisit a decision without recreating Tasks or dependencies. Approval is final for that gate because dependent work may already have started.

## Reserve before launching

Use `reserve <run-id>` to check Task dependencies, decision gates, and slot capacity. Use `--task <task-id>` when selecting a specific Task. The command returns `null` and exits with code 0 if no slot or eligible Task is available. Launch only when the command returns a Dispatch. Keep its Task ID, Dispatch ID, and attempt number.

Use a distinct linked worktree and branch for each worker that edits. For CLI workers and desktop side sessions, reserve the intended path and branch with `--worktree` and `--branch`. Create that worktree from the appropriate base revision and verify it against `git worktree list --porcelain`. For a host-created worktree, use `register` to record the assigned path and branch as soon as they become available. Use the [main checkout review procedure](#review-the-live-patch-in-the-main-checkout) when a Task needs the user's uncommitted changes.

Call `begin <dispatch-id>` immediately before starting or resuming the worker. Use the returned turn in the brief and in later host reports. Use `started --runtime <handle>` to save the process or tool handle. For a PID, include its process start identity. Save `--session <id>` when the host returns it. If the coordinator stops before recording the handle, leave the slot reserved until you can establish whether the worker started. Use a background shell-tool job or another host-owned handle that can observe the process exit. Save each worker's output under the state directory with the Dispatch ID and turn in the filename.

### Worker brief

Give each worker a filled-in brief. Include the exact commands with concrete paths and IDs.

Use `note <run-id> <text>` as coordinator to record decisions, conventions, and pitfalls that apply across Tasks. Use `status <run-id>` to read all notes. Paste the `notes` text returned by `begin` into the brief for each turn. It contains the latest notes first and marks truncation at 4 KiB.

```text
Run: <run ID>
Task: <task ID>
Dispatch: <dispatch ID>
Turn: <turn number>
Worktree and branch: <absolute worktree path and branch>
Goal: <deliverable>
Run notes: <notes from begin>
Edit only: <paths>
Verify: <exact commands, one per shell call, and expected evidence>
Diff: <exact read-only Git commands for the editable paths>
State DB: <absolute DB path>
Python: <selected executable>
Script: <absolute script path used in the commands>

Run each supplied command in its own shell call from the assigned worktree.
Report the step count once you have a plan. Send one progress line whenever the step changes.
Keep the command prefix exactly as supplied. If a required tool call is denied,
record a question naming the denied tool and path or command. Record any blocking
question once and end the turn.
Finish with a done report containing the full result and verification evidence.
If you changed code, run the supplied Git commands after verification and copy
the Git patch output verbatim into the evidence's diff field. If you edit again,
rerun verification and capture the new patch.
Leave Git staging, commits, and delivery to the coordinator.
```

For Claude, use unquoted Python, script, and DB paths with no spaces or shell metacharacters. If a path needs quoting, use a shell-safe wrapper or symlink path to the same executable, script, or DB. Use the exact same Python and script prefix in the Claude Bash allow rule. Give Claude one command per Bash call. Leave out `cd`, `&&`, and pipes. For Codex, quote paths as needed for its shell.

Supply a status command and a diff against `HEAD` scoped to the Task's editable paths. For each planned new file, supply a separate `git diff --no-index` command against `/dev/null`. Exit code 1 from that command means it found differences. If the worker needs a diff command for another untracked file, have it record a question with the path. Check the path against the Task's edit scope before adding the command to the follow-up brief. Omit the `Diff` line for read-only Tasks.

Use the following commands as examples for the brief. Replace the evidence JSON with the worker's full result. Use `status: "failure"` for a failed result. Use `changed_code: false` for a result with no code changes.

```sh
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db heartbeat 12 --turn 1
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db progress 12 --turn 1 --step 1/3 'Inspect the existing migration'
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db record 12 --turn 1 'Which path should I use?'
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db done 12 --turn 1 --evidence '{"status":"success","result":"Full result with test output","verification":[{"command":"/usr/bin/python3 -m unittest","exit_code":0,"location":"completion report result"}],"changed_code":true,"diff":"<Git patch output encoded as a JSON string>"}'
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db done 12 --turn 1 --evidence-file /var/tmp/team-up/evidence-12-t1.json
```

Use `progress <dispatch-id> --turn N [--step k/n] <text>` during the active running turn. Use `1 <= k <= n` and at most 200 characters of text. Omit `--step` to keep the reported step and total. Each report refreshes the heartbeat and records a `progress` event. `wait` continues waiting for an actionable event or its timeout. `begin` clears the prior turn's progress.

Use one terminal path per turn. A worker that records a blocking question ends the turn instead of running `done`. Preserve the worker log and Git patch before cleanup.

### Codex worker

From a coordinator-owned background job, run the command below. Save the JSONL stream and the exit status separately. Read `thread.started` as the stream arrives and save its `thread_id` with the worktree and execution handle.

```sh
codex exec --json -C "$worktree" -s workspace-write --add-dir "$state_dir" - < "$brief_file"
```

For a follow-up, wait for the current process to exit and verify the recorded worktree and branch. Use the exact saved thread ID. Reapply both sandbox flags.

```sh
codex exec -C "$worktree" -s workspace-write --add-dir "$state_dir" \
  resume --json "$thread_id" - < "$brief_file"
```

Record `turn.completed` or `turn.failed` with `turn-ended` when observed. After the host confirms process exit, call `exited` with the actual exit code. Check the DB for a `done` report before treating the Task as complete.

If you missed the thread ID and the Dispatch is `turn-ended`, `waiting`, or closed with a completion report, read `thread.started` from the saved JSONL. Fill the missing ID for the current turn with `started <dispatch-id> --turn <turn> --session <thread-id>` before resuming.

### Claude worker

- On a user turn in the Claude desktop app's Code tab, prefer the host's `start_session` side session in the prepared worktree. Store its session ID. On a question, confirm that the current turn is idle before recording its exit and keep the session open for the answer. Send the follow-up to that exact session. When the Dispatch finishes, use the host's session state and stop controls to verify shutdown before releasing the slot. For a preserved session, confirm that team-up's execution has ended and leave the idle session open.
- On a notification or session-message turn in the Claude desktop app's Code tab, use `Agent` with `isolation: worktree` or start a Codex worker for a compatible Task. Use the host-returned Agent ID and worktree. If the host discards a worktree or offers no way to resume the same Agent, report that blocker and confirm shutdown before considering a retry. On these turns a desktop side-session card needs a user action to start.
- For a Claude CLI worker, set `python` and `script` to the exact unquoted paths in the brief. Build the `--allowedTools` list from the worker's DB command prefix, the Task's `Edit only` paths, and its `Verify` and `Diff` commands. Add one exact `Bash(<command>)` rule for each supplied command under `Verify` and `Diff`. Claude print mode denies `--evidence "$(cat file)"`; give Claude workers `done <id> --turn <turn> --evidence-file <path>` and allow that exact command prefix. Leave out edit and diff rules for read-only Tasks. If Claude's Bash sandbox is enabled, include the absolute state directory in `sandbox.filesystem.allowWrite` on launch and resume. Save the returned `session_id`.

In `claude -p`, `--allowedTools` accepts path-scoped `Edit` rules that cover both `Edit` and `Write`. Use paths relative to the worker's worktree, such as `Edit(./src/**)`. For an absolute path, use `Edit(//path/to/worktree/src/**)`. [Print-mode allow rules](https://code.claude.com/docs/en/headless#create-a-commit) [File permission patterns](https://code.claude.com/docs/en/permissions#read-and-edit)

For a Task with `Edit only: greet.py, test_greet.py` and `Verify: /usr/bin/python3 -m unittest`, give the worker the commands below. Each line is a separate Bash call. Run the last two commands only for the respective files listed as untracked (`??`) by status.

```sh
/usr/bin/python3 -m unittest
git --no-optional-locks status --short --untracked-files=all -- greet.py test_greet.py
git --no-pager diff --no-ext-diff --no-textconv --binary HEAD -- greet.py test_greet.py
git --no-pager diff --no-index --no-ext-diff --no-textconv --binary -- /dev/null greet.py
git --no-pager diff --no-index --no-ext-diff --no-textconv --binary -- /dev/null test_greet.py
```

Use these rules in Bash or Zsh.

```sh
allowed_tools=(
  "Bash($python $script:*)"
  "Edit(./greet.py)"
  "Edit(./test_greet.py)"
  "Bash(/usr/bin/python3 -m unittest)"
  "Bash(git --no-optional-locks status --short --untracked-files=all -- greet.py test_greet.py)"
  "Bash(git --no-pager diff --no-ext-diff --no-textconv --binary HEAD -- greet.py test_greet.py)"
  "Bash(git --no-pager diff --no-index --no-ext-diff --no-textconv --binary -- /dev/null greet.py)"
  "Bash(git --no-pager diff --no-index --no-ext-diff --no-textconv --binary -- /dev/null test_greet.py)"
)
(
  cd "$worktree" || exit
  claude -p --output-format json \
    --allowedTools "${allowed_tools[@]}" -- "$brief"
)
```

Resume in the same worktree. Reapply the rules for the follow-up brief.

```sh
(
  cd "$worktree" || exit
  claude -p --output-format json --resume "$session_id" \
    --allowedTools "${allowed_tools[@]}" -- "$brief"
)
```

After each turn, the coordinator must check JSON `permission_denials` and the corresponding DB writes, even if Claude exits with code 0. A denial that blocks the Task becomes a worker question. If the denial also prevents the worker from recording its question, use the saved JSON to identify the blocker. Preserve the JSON output in the worker log and resolve the permission issue before resuming.

## Review the live patch in the main checkout

Reserve a read-only Task with `reserve <run-id> --task <task-id> --review-main --worktree "$review_checkout" --branch "$review_branch"`. Use the primary checkout's absolute physical path and current branch. Set `state_dir` to a dedicated directory outside any Git checkout, with no overlap with the review checkout or its Git directory. Use an absolute DB path in that directory and save the brief and worker logs there.

Use CLI workers for this placement on every coordinator host. From a Codex coordinator, request escalation for the launch and resume commands below with their review permissions intact. Give the worker `git -C "$review_checkout" --no-optional-locks status --short --untracked-files=all` and `git -C "$review_checkout" --no-pager diff --no-ext-diff --no-textconv --binary HEAD` with concrete paths in the brief. Tell the worker to read the live files and report findings with `changed_code: false`. Use `record` for a blocking question and the same session ID for the next turn.

For Codex CLI 0.170.0, set a permission profile on both launches. It grants read access and gives SQLite write access to the state directory, including its WAL and shared-memory files. The built-in `read-only` mode blocks the DB write. Start Codex from the state directory so it does not load the review checkout's project configuration. [Codex permission profiles](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/src/config/permissions.rs)

```sh
review_profile=$("$python" -c '
import json, sys
state_dir = json.dumps(sys.argv[1], ensure_ascii=False)
print("permissions.team-up-review.filesystem={\":root\"=\"read\", " + state_dir + "=\"write\"}")
' "$state_dir")
codex_review=(
  --ignore-user-config --ignore-rules --skip-git-repo-check -C "$state_dir"
  -c 'approval_policy="never"'
  -c 'default_permissions="team-up-review"'
  -c "$review_profile"
)
codex exec "${codex_review[@]}" --json - < "$brief_file"
codex exec "${codex_review[@]}" resume --json "$thread_id" - < "$brief_file"
```

For Claude Code 2.1.330, supply the Bash sandbox settings inline. Use `denyWrite` for the checkout and Git common directory and `allowWrite` for the state directory. Limit built-in tools to Bash and file reads and load no MCP servers. The example assumes shell-safe paths in the Bash allow rules. Use the same shell-safe path spelling in the brief. The Bash sandbox must be available on the host. [Claude Bash sandbox settings](https://code.claude.com/docs/en/sandboxing)

```sh
review_git_dir=$(git -C "$review_checkout" rev-parse --path-format=absolute --git-common-dir)
review_settings=$("$python" -c '
import json, sys
print(json.dumps({"sandbox": {
    "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
    "autoAllowBashIfSandboxed": False,
    "filesystem": {"denyWrite": sys.argv[1:3], "allowWrite": [sys.argv[3]]},
}}))
' "$review_checkout" "$review_git_dir" "$state_dir")
claude_review=(
  -p --output-format json --restricted --tools 'Bash,Read,Glob,Grep'
  --permission-mode dontAsk --setting-sources '' --settings "$review_settings" --strict-mcp-config
  --allowedTools
  "Bash($python $script --db $db:*)"
  "Bash(git -C $review_checkout --no-optional-locks status --short --untracked-files=all)"
  "Bash(git -C $review_checkout --no-pager diff --no-ext-diff --no-textconv --binary HEAD)"
)
(
  cd "$review_checkout" || exit
  claude "${claude_review[@]}" -- "$brief"
)
(
  cd "$review_checkout" || exit
  claude --resume "$session_id" "${claude_review[@]}" -- "$brief"
)
```

Use the same sandbox rules for each resumed turn. If the required sandbox or tool permissions are unavailable, stop the review and report the blocker. The Bash allow rules are not a write boundary: a later `--db` argument matches the DB rule, so only the sandbox keeps writes out of the checkout. Treat a worker's report of what it ran as unverified and check the command and exit code in the Codex JSONL or the Claude tool log. Compare the working-tree status and patch around delivery. Deliver the findings and verification evidence and record `delivered`. The main checkout is excluded from `cleanup`.

## Process questions and wake events

For ordinary questions, the worker uses `record` and ends the turn. Present unresolved questions to the user. Save the answer with `answer` and include it in the follow-up brief. Use `instruct` to store other follow-up instructions against the same Dispatch before sending them. Resume the same session and worktree after confirming that the previous turn has ended. Include the new turn number in worker commands. A Dispatch waiting for an answer still owns its slot.

Use `instruct <dispatch-id> <text>` to queue instructions during a turn, after `done`, or after confirmed exit. Instructions added during a turn remain pending when that turn reports `done`. To follow up on a completed Dispatch, record its exit with `exited` and call `begin <dispatch-id>` when a slot is available. Use the same session and checkout. Include the pending instructions from `messages` with `kind: "instruction"` and `consumed: 0`, along with the new turn number. A completion in a later turn marks the instructions from its brief consumed. Use the new completion report for delivery. The `completion-followed-up` event retains the previous report.

An unanswered question from a turn that reported `done` is stale and `answer` refuses it. If the user wants the answer acted on, restate it as an `instruct` follow-up. Keep a completed worktree available if a follow-up is pending. For a Dispatch you cannot resume, report the reason and use the stored instructions to brief any replacement.

Use `ask --timeout <seconds>` only when the worker must continue in the same turn. Poll the existing shell job. If the command exits with code 124, end the turn and leave the question in the DB for the next turn. If a host already provides an App Server Plan-mode connection, its blocking `item/tool/requestUserInput` is another same-turn path. Keep the question and answer in the Dispatch record. Use the shell or next-turn workflow for regular `codex exec`.

`wait` returns on a worker `question` or `done` event, or on timeout. Confirm exit through the worker's host notification or by polling its shell session. `turn-ended` and `exited` stay in the DB as coordinator reports and advance the cursor without triggering a wake. Read current state on each return. Process pending questions and reports, reconcile exits, then reserve ready Tasks. Pass the returned cursor to `ack` after processing, even if the event list is empty. A restart can replay unacknowledged actionable events.

If the current turn has no runtime handle, `turn-ended` and `exited` warn on stderr and still save the report. This lets you record a confirmed exit after a missed `started`. An `exited --start-failed` report has no runtime warning.

If worker activity is still expected in the Claude desktop app's Code tab, start `wait <run-id> --timeout 30` as a background Bash job and end the turn. The job's completion wakes the coordinator. In an active CLI coordinator, poll with `wait <run-id> --timeout 30` and reconcile after each return. If the CLI coordinator exits, resume its saved session and name the absolute DB path and Run ID in the prompt. Use `claude -p --resume <coordinator-session-id>` for Claude Code CLI. For Codex CLI, follow the [Codex coordinator pickup procedure](#codex-coordinator). For agy, follow the [agy coordinator pickup procedure](#agy-coordinator).

## Follow up on pull requests

1. Record delivery, then register the open PR with `pr-open <dispatch-id> --number <number>`. The default policy is `hold`. Use `--policy manual` when the user plans to merge. A matching glob in the coordinator checkout's `.github/merge-policy` forces `hold`. Put one glob per line and start comment lines with `#`.
2. Use `wait <run-id> --sync-prs 15` to poll GitHub. Check failures and conflicts wake the coordinator. Read the other PR events on the next wake or timeout. GitHub's merged state records the merge for Tasks that depend on it.
3. For a failure or conflict, queue an `instruct` on the same Dispatch. If the PR is armed, run `gh pr merge <number> --disable-auto` and then `pr-sync <run-id>`. Call `begin` after the worker exits and a slot frees up. Resume the saved session and publish the reviewed fix. After three fix rounds, bring the remaining failure or conflict to the user. The board puts it under 내 차례.
4. When the user explicitly approves auto-merge, create a new gate dedicated to that PR, such as `merge-pr-<number>`. Record approval with `gate <run-id> <name> --decision approve`, then run `pr-policy <task-id> auto --gate <name>`. Confirm the target branch requires the `verify` check before using `pr-arm <task-id>`. Use `pr-policy <task-id> hold` or `manual` to record a change in the user's decision. Never merge with `--admin`.

GitHub can merge an armed PR between polls. If other actors can push to an armed PR, enforce paths requiring approval in GitHub branch protection. Use `hold` for merge queues unless GitHub enforces the same policy, since disabling auto-merge does not remove a queued PR.

## Report progress with the board

When you report progress to the user, run `board <run-id>` and show its output as is. It is read-only and places each Task in one group: 내 차례 (unanswered questions, undecided gates, three start failures), 진행 중 (open Dispatches and ready Tasks marked 대기열), 검토 대기, 머지 중, 막힘 (with `←` naming what the Task waits on), and 완료. Lead with the 내 차례 items. Use `board <run-id> --json` when you need the same groups as data, and `status` when you need the raw records.

Running Dispatches show their reported step and text, worktree diff stats, last update time, and a stall marker after 10 minutes without a heartbeat or progress report. The coordinator counts changes against `HEAD` and includes untracked files. Binary files contribute zero lines.

Running entries in `board --json` include `progress_text`, `progress_step`, `progress_total`, and `progress_at`. Unreported values are `null`. `last_update_at` is the latest heartbeat or progress timestamp in UTC, and `stalled` is a boolean. `diff_stats` contains `files`, `added`, and `deleted`, or is `null` when the worktree is unavailable.

## Stop or retry

- Treat an overdue heartbeat as a prompt to inspect the saved handle and start identity. Check the host or supervisor for current liveness. Keep the slot and worktree reserved while liveness is unknown.
- Use `stop` to record a request. Ask the host to stop only the worker owned by that Dispatch. After confirmed termination, record `exited --stopped` with the current turn and exit code. If the user abandons an assignment, use `abandon --reason` and continue checking the worker until shutdown is confirmed.
- If launch fails, use `exited --start-failed` after confirming there is no live worker. Use `retry` on a failed or incomplete Dispatch only after confirmed termination. The new Dispatch records the previous ID as `retry_of` and increments the attempt number. For linked placements, give the replacement a new worktree and preserve any undelivered work in the old worktree. For a main checkout review, leave out the worktree options to reuse the recorded placement and apply the review permissions again. Defer retries for permission or installation failures until the cause changes.
- After three start failures for a Task, report the cause to the user. Use `retry <dispatch-id> --override` only when the user confirms the cause has changed and instructs you to retry. The override allows one attempt and records a `retry-override` event.
- A turn event or process exit alone does not complete a Task. A normal turn that records a question stays available for an answer. A worker that exits without a report or a resumable question leaves the Task incomplete.

## Deliver and clean up

1. After confirming worker exit, read the completion report and check the branch and verification evidence. Check the full worktree status against the Task's edit scope. For working-tree changes, rerun the brief's Git commands and compare their patch output with the worker's report before staging. Deliver the branch, commit or diff, and verification evidence to the user and record delivery. For PR delivery, hand off to [ship-it](ship-it.md) when the user invokes it. For a merge dependency, confirm the required `verify` check passed and the specified default branch contains the needed change before recording the merge.
2. Use `takeover` or `keep-open` before handing control to the user. Preserve the session and worktree in either case. Once the user takes over, stop sending instructions to the worker. Keep tracking the active turn until the host confirms it ended.
3. Use `cleanup` to list linked worktree candidates with confirmed exit and recorded delivery. Pending instructions block cleanup until consumed or the Dispatch is abandoned. Retain worktrees without a report for manual reconciliation. Before removing a candidate, confirm team-up ownership and worker exit. Recheck the recorded path and branch against Git. Check `git status --porcelain --untracked-files=all` in the worktree and confirm all results are delivered. Skip any worktree with changes, an unknown worker state, or a preservation request. If the host already removed the worktree, reconcile that with Git instead of substituting another path.
4. Use regular `git worktree remove` after the checks pass. Preserve the branch, durable evidence, and DB. Delete the DB only on an explicit user request.

## Limits

Run on a single machine in one local repository. Keep the coordinator's watch scoped to one Run. Coordination in the Codex Desktop app and Codex App Server is unverified and unsupported. Codex shell-session survival across coordinator exit, maximum Codex shell wait, CLI background `wait` auto-wake, and live desktop takeover of external Codex threads remain unverified. agy auto-wake (background task wake, timers, `/swarm`, and `agy acp`) is unverified. In agy, Auto mode without `--sandbox` can bypass the command sandbox. Independent worker limits and WAL lock wait with dozens of workers also remain unverified. For the Orca migration, the user controls when to disable `~/.agents/skills/orchestration`.
