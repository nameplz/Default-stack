# Coordinate a run with team-up

Use one Claude coordinator for one active Run in one local Git repository. Start only workers owned by the Run. Keep their execution handles and SQLite records so you can recover after a coordinator restart.

## Identify the host and open the Run

1. In the Claude desktop app's Code tab, use the host's side-session tools when they are available. Note whether the current turn came from the user or a background notification. In the Claude Code CLI, use shell jobs for external workers. If the host is Codex, direct the user to Claude Code.
2. Use Python 3 with the SQLite WAL-reset fix for the coordinator, worker commands, and Claude Bash allow rule. `init` and `status` warn if the current Python uses an affected version. The fix is in SQLite 3.51.3 and later, with backports starting at 3.44.6 and 3.50.7 on their respective branches. [SQLite's WAL-reset notes](https://www.sqlite.org/wal.html#the_wal_reset_bug)
3. Resolve `scripts/team_up.py` relative to the installed `SKILL.md`. Set `script` to its absolute path and `python` to the selected Python executable. Run `init` from the target repository before any worker connects. Keep the absolute DB path returned by `init`. Set `db` to that path and `state_dir` to its parent. Give each worker the same DB path. Worktree checks use the Git common directory saved at `init`, so with an absolute `--db` path they work from any directory.
4. On pickup, reuse the saved DB path and open the existing Run with `status <run-id>`. Reconcile its worker handles, worktrees, unprocessed events, and pending questions before reserving anything. The DB path defaults to `~/.local/state/default-stack/team-up/<repo-id>.db`. The ID is the first 16 hex digits of the SHA-256 of the real path returned by `git rev-parse --path-format=absolute --git-common-dir`.
5. For a new Run, use `run-create --goal <goal> --slots <count>`. Keep its ID for pickup. Set `--base <ref>` when a dependency requires a merge into a designated branch. Use `task-create` to record each Task's worker type, goal, editable paths, and required completion evidence. Create prerequisites first. Use `--after` for a completion dependency and `--after-merge` for a merge dependency. Add any user decision gate with `--gate <name>`. Record the user's decision with `gate` before dispatching dependent work.

Use the local script's `--help` for command arguments. The examples put `--db` before the subcommand. Replace the shell variables and example values with the actual Run values. Replace the example `python3` with the selected executable if you use a different one.

## Reserve before launching

Use `reserve <run-id>` to check Task dependencies, decision gates, and slot capacity. Use `--task <task-id>` when selecting a specific Task. The command returns `null` and exits with code 0 if no slot or eligible Task is available. Launch only when the command returns a Dispatch. Keep its Task ID, Dispatch ID, and attempt number.

Use a distinct worktree and branch for each worker. For CLI workers and desktop side sessions, reserve the intended path and branch with `--worktree` and `--branch`. Create that worktree from the appropriate base revision and verify it against `git worktree list --porcelain`. For a host-created worktree, use `register` to record the assigned path and branch as soon as they become available.

Call `begin <dispatch-id>` immediately before starting or resuming the worker. Use the returned turn in the brief and in later host reports. Use `started --runtime <handle>` to save the process or tool handle. For a PID, include its process start identity. Save `--session <id>` when the host returns it. If the coordinator stops before recording the handle, leave the slot reserved until you can establish whether the worker started. Use a background shell-tool job or another host-owned handle that can observe the process exit. Save each worker's output under the state directory with the Dispatch ID and turn in the filename.

### Worker brief

Give each worker a filled-in brief. Include the exact commands with concrete paths and IDs.

```text
Run: <run ID>
Task: <task ID>
Dispatch: <dispatch ID>
Turn: <turn number>
Worktree and branch: <absolute worktree path and branch>
Goal: <deliverable>
Edit only: <paths>
Verify: <exact commands, one per Bash call, and expected evidence>
State DB: <absolute DB path>
Python: <selected executable>
Script: <absolute script path used in the commands>

Run each supplied command in its own Bash call from the assigned worktree.
Keep the command prefix exactly as supplied. If a required tool call is denied,
record a question naming the denied tool and path or command. Record any blocking
question once and end the turn.
Finish with a done report containing the full result and verification evidence.
Include the commit or exact diff you verified if you changed code.
Leave Git staging, commits, and delivery to the coordinator.
```

For Claude, use unquoted Python, script, and DB paths with no spaces or shell metacharacters. If a path needs quoting, use a shell-safe wrapper or symlink path to the same executable, script, or DB. Use the exact same Python and script prefix in the Claude Bash allow rule. Give Claude one command per Bash call. Leave out `cd`, `&&`, and pipes. For Codex, quote paths as needed for its shell.

Use the following commands as examples for the brief. Replace the evidence JSON with the worker's full result. Use `status: "failure"` for a failed result. Use `changed_code: false` for a result with no code changes.

```sh
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db heartbeat 12 --turn 1
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db record 12 --turn 1 'Which path should I use?'
/opt/python/bin/python3 /opt/team-up/team_up.py --db /var/tmp/team-up/state.db done 12 --turn 1 --evidence '{"status":"success","result":"Full result","verification":[{"command":"make verify","exit_code":0,"location":"artifacts/verify.log"}],"changed_code":true,"diff":"artifacts/task.patch"}'
```

Use one terminal path per turn. A worker that records a blocking question ends the turn instead of running `done`. Store referenced logs and diffs at paths the coordinator can read and preserve before cleanup.

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

If you missed the thread ID and the Dispatch is `turn-ended` or `waiting`, read `thread.started` from the saved JSONL. Fill the missing ID for the current turn with `started <dispatch-id> --turn <turn> --session <thread-id>` before resuming.

### Claude worker

- On a desktop user turn, prefer the host's `start_session` side session in the prepared worktree. Store its session ID. On a question, confirm that the current turn is idle before recording its exit and keep the session open for the answer. Send the follow-up to that exact session. When the Dispatch finishes, use the host's session state and stop controls to verify shutdown before releasing the slot. For a preserved session, confirm that team-up's execution has ended and leave the idle session open.
- On a desktop notification or session-message turn, use `Agent` with `isolation: worktree` or start a Codex worker for a compatible Task. Use the host-returned Agent ID and worktree. If the host discards a worktree or offers no way to resume the same Agent, report that blocker and confirm shutdown before considering a retry. On these turns a desktop side-session card needs a user action to start.
- From the CLI, set `python` and `script` to the exact unquoted paths in the brief. Build the `--allowedTools` list from the worker's DB command prefix, the Task's `Edit only` paths, and its `Verify` commands. Add one exact `Bash(<command>)` rule per verification command. Leave out edit rules for read-only Tasks. If Claude's Bash sandbox is enabled, include the absolute state directory in `sandbox.filesystem.allowWrite` on launch and resume. Save the returned `session_id`.

In `claude -p`, `--allowedTools` accepts path-scoped `Edit` rules that cover both `Edit` and `Write`. Use paths relative to the worker's worktree, such as `Edit(./src/**)`. For an absolute path, use `Edit(//path/to/worktree/src/**)`. [Print-mode allow rules](https://code.claude.com/docs/en/headless#create-a-commit) [File permission patterns](https://code.claude.com/docs/en/permissions#read-and-edit)

For a Task that allows edits under `src/` and `artifacts/` and lists `make verify` on its `Verify` line, use these rules in Bash or Zsh.

```sh
allowed_tools=("Bash($python $script:*)" "Edit(./src/**)" "Edit(./artifacts/**)" "Bash(make verify)")
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

## Process questions and wake events

For ordinary questions, the worker uses `record` and ends the turn. Present unresolved questions to the user. Save the answer with `answer` and include it in the follow-up brief. Use `instruct` to store other follow-up instructions against the same Dispatch before sending them. Resume the same session and worktree after confirming that the previous turn has ended. Include the new turn number in worker commands. A Dispatch waiting for an answer still owns its slot.

Use `ask --timeout <seconds>` only when the worker must continue in the same turn. Poll the existing shell job. If the command exits with code 124, end the turn and leave the question in the DB for the next turn. If a host already provides an App Server Plan-mode connection, its blocking `item/tool/requestUserInput` is another same-turn path. Keep the question and answer in the Dispatch record. Use the shell or next-turn workflow for regular `codex exec`.

`wait` returns on a worker `question` or `done` event, or on timeout. Use the worker job's host completion notification to learn of exit and record `exited`. `turn-ended` and `exited` stay in the DB as coordinator reports and advance the cursor without triggering a wake. Read current state on each return. Process pending questions and reports, reconcile exits, then reserve ready Tasks. Pass the returned cursor to `ack` after processing, even if the event list is empty. A restart can replay unacknowledged actionable events.

If the current turn has no runtime handle, `turn-ended` and `exited` warn on stderr and still save the report. This lets you record a confirmed exit after a missed `started`. An `exited --start-failed` report has no runtime warning.

If worker activity is still expected, start `wait <run-id> --timeout 30` as a background Bash job on desktop and end the turn. The job's completion wakes the coordinator. In an active CLI coordinator, call `wait` to poll events and reconcile at the deadline. If the CLI coordinator has exited, explicitly resume it with `claude -p --resume <coordinator-session-id>` and identify the Run in the prompt.

## Stop or retry

- Treat an overdue heartbeat as a prompt to inspect the saved handle and start identity. Check the host or supervisor for current liveness. Keep the slot and worktree reserved while liveness is unknown.
- Use `stop` to record a request. Ask the host to stop only the worker owned by that Dispatch. After confirmed termination, record `exited --stopped` with the current turn and exit code. If the user abandons an assignment, use `abandon --reason` and continue checking the worker until shutdown is confirmed.
- If launch fails, use `exited --start-failed` after confirming there is no live worker. Use `retry` on a failed or incomplete Dispatch only after confirmed termination. The new Dispatch records the previous ID as `retry_of` and increments the attempt number. Give the replacement a new worktree and preserve any undelivered work in the old checkout. Defer retries for permission or installation failures until the cause changes.
- After three start failures for a Task, report the cause to the user. Use `retry <dispatch-id> --override` only when the user confirms the cause has changed and instructs you to retry. The override allows one attempt and records a `retry-override` event.
- A turn event or process exit alone does not complete a Task. A normal turn that records a question stays available for an answer. A worker that exits without a report or a resumable question leaves the Task incomplete.

## Deliver and clean up

1. Read the completion report and verify its branch, commit or diff, and evidence. Deliver those items to the user and record delivery. For PR delivery, hand off to [ship-it](ship-it.md) when the user invokes it. For a merge dependency, confirm the required `verify` check passed and the specified default branch contains the needed change before recording the merge.
2. Use `takeover` or `keep-open` before handing control to the user. Preserve the session and worktree in either case. Once the user takes over, stop sending instructions to the worker. Keep tracking the active turn until the host confirms it ended.
3. Use `cleanup` to list candidates with confirmed exit and recorded delivery. Retain worktrees without a report for manual reconciliation. Before removing a candidate, confirm team-up ownership and worker exit. Recheck the recorded path and branch against Git. Check `git status --porcelain --untracked-files=all` in the worktree and confirm all results are delivered. Skip any worktree with changes, an unknown worker state, or a preservation request. If the host already removed the worktree, reconcile that with Git instead of substituting another path.
4. Use regular `git worktree remove` after the checks pass. Preserve the branch, durable evidence, and DB. Delete the DB only on an explicit user request.

## Limits

Run on a single machine in one local repository. Keep the coordinator's watch scoped to one Run. Codex is a worker host. CLI background `wait` auto-wake, the maximum Codex shell-tool wait, and live desktop takeover of external Codex threads remain unverified. Independent worker limits and WAL lock wait with dozens of workers also remain unverified. For the Orca migration, the user controls when to disable `~/.agents/skills/orchestration`.
