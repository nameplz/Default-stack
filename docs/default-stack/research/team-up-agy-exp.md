# agy as a team-up worker — experiment log

Historical record of the 2026-11-24 experiments. team-up no longer supports agy workers; the commands and recommendations below are preserved as experiment history, not current execution guidance. See the [current decision](../decisions.md).

agy 1.5.16 (`agy --version`, exit 0), macOS, 2026-11-24.

Scratch area: `/Users/yuhyeon/.local/state/default-stack/team-up/r3-agy-exp` (`$E`).
- `$E/repo`: a disposable Git repo with one commit. It is the agy cwd for every run below.
- `$E/state`: experiment DBs.
- `$E/out/<name>.{out,err,rc}`: raw stdout, stderr and exit code of each run.

Wrappers: each one runs `cd $E/repo`, then agy, with stdout and stderr redirected to `$E/out/<name>.*`. Each command below is shown in the form agy actually received.
- `run.sh <name> ARGS`: runs `agy ARGS < /dev/null`.
- `runarg.sh <name> FILE ARGS`: runs `agy ARGS -p "$(cat FILE)"`.
- `runin.sh <name> FILE ARGS`: runs `agy ARGS < FILE`.

## 1. Output formats and exit codes

### `--output-format json`: one object
```
agy -p "Reply with exactly: PONG" --output-format json --print-timeout 180s      # run.sh q1json
```
Exit 0.
```
{"conversation_id":"8342a1cb-…","status":"SUCCESS","response":"PONG\n","duration_seconds":3.58,"num_turns":1,"usage":{"input_tokens":17564,"output_tokens":25,"thinking_tokens":22,"cache_read_tokens":0,"total_tokens":17589}}
```
- Fields on success: `conversation_id`, `status`, `response`, `duration_seconds`, `num_turns`, `usage{input_tokens,output_tokens,thinking_tokens,cache_read_tokens,total_tokens}`.
- Fields on error (q2emptytext, q1timeout): `error` and `finished_reason` are added (`"error"`, `"print_timeout"`).
- Field on a permission denial (q4defmode, see §4): `denied_actions[{action,display_name}]` is added.

### `--output-format stream-json`: NDJSON
```
agy -p "List the files in the current directory using a shell command, then reply DONE." --output-format stream-json --print-timeout 180s   # run.sh q1stream
```
Exit 0. Excerpt, with the tools list trimmed:
```
{"event":"init","conversation_id":"3a1358e9-…","init":{"cwd":"…/r3-agy-exp/repo","tools":[…],"permission_mode":"request-review"}}
{"event":"step_update","step_update":{"conversation_id":"3a1358e9-…","step_index":0,"state":"DONE","step_type":"user_input"}}
{"event":"step_update","step_update":{…,"step_index":2,"state":"ACTIVE","step_type":"tool","tool_name":"run_command","tool_info":{"name":"run_command","parameters":{"CommandLine":"ls"}}}}
{"event":"step_update","step_update":{…,"state":"DONE","step_type":"tool","tool_name":"run_command","duration_seconds":0.26,"tool_info":{…,"output":"…Command exited with code 0.\n\nCommand output:\nREADME.md\r\n"}}}
{"event":"step_update","step_update":{…,"step_index":3,"state":"ACTIVE","step_type":"agent_response","text_delta":"DONE"}}
{"event":"result","result":{"conversation_id":"3a1358e9-…","status":"SUCCESS","response":"DONE\n","duration_seconds":10.38,"num_turns":1,"usage":{…}}}
```
- Top-level event names: `init`, `step_update`, `result`. Each line carries one payload key that matches its event name.
- `init` keys: `cwd`, `tools`, `permission_mode`.
- `step_update` keys:
  - `conversation_id`, `step_index`
  - `state` (`ACTIVE`, `DONE`, `ERROR`)
  - `step_type`, with values seen: `user_input`, `agent_response`, `tool`, `system_message`
  - `tool_name`, `tool_info{name,parameters,output|error}`, `text_delta`, `duration_seconds`, `usage`
- The conversation ID is the top-level `conversation_id` on the first line (`init`). It is repeated in every `step_update` and in `result`.
- The final answer is `result.response`; status is `result.status`. With `--input-format stream-json`, one `result` line is emitted per input message (§2).
- `init.permission_mode` read `"request-review"` in every run, including `--mode accept-edits` and `--settings {"agentMode":""}` (q4ae, q4defmode). It does not reflect the effective mode.

### Exit codes
| Case | Command | Exit | Observed |
|---|---|---|---|
| Success | q1json above | 0 | `"status":"SUCCESS"` |
| Unknown flag | `agy -p "hi" --output-format json --no-such-flag` (run.sh q1badflag) | **2** | stderr: `flags provided but not defined: -no-such-flag` + usage |
| Missing `-p` value | `agy --output-format json --print-timeout 180s -p` (runin.sh q2plast) | **2** | `flag needs an argument: -p` |
| `-p` swallowed a flag | `agy -p --output-format json …` (runin.sh q2noarg) | **2** | `Error: -p took "--output-format" as its prompt…` |
| Bad `--output-format` value | `agy -p "hi" --output-format xml` (run.sh q1badfmt) | **0** | Silently fell back to text: `Hi! How can I help you today?` |
| Empty prompt | `agy -p= --output-format json …` (runin.sh q2emptytext) | 1 | `"status":"ERROR","error":"Error: empty prompt…","finished_reason":"error"` |
| Backend failure at start | runarg.sh q3set (first try, started concurrently with another run) | 1 | `"error":"failed to start conversation: backend returned an empty conversation id"` |
| `--print-timeout` expiry | `agy -p "Run the shell command: sleep 60 ; then reply SLEPT" --output-format stream-json --print-timeout 5s` (run.sh q1timeout) | **3** | below |

The timeout run's `result` line and stderr:
```
{"event":"result","result":{…,"status":"ERROR","response":"","error":"print timeout after 5s with the turn still in progress; the response is partial",…,"finished_reason":"print_timeout"}}
stderr: [agy] print timeout after 5s with turn in progress; returning partial output
        AGY_ERROR: {"short_error":"print timeout …","status":"DEADLINE_EXCEEDED","retryable":false,"reason":"print_timeout"}
```
The process listing taken afterwards (`ps -axo pid,ppid,etime,command | grep -E "agy|sleep 60|language_server"`, exit 0) showed no CLI `agy` process and no `sleep 60`. It showed only the pre-existing Antigravity.app processes, which were 1h12m old.

## 2. Passing the brief

| Attempt | Command | Exit | Result |
|---|---|---|---|
| `-p -` + stdin | `agy -p - --output-format json … < brief.txt` (runin.sh q2dash) | 0 | `"response":"How can I help you today?\n"`: the literal `-` was the prompt and **stdin was ignored** |
| `-p=` + text stdin | `agy -p= --output-format json … < brief.txt` (runin.sh q2emptytext) | 1 | `Error: empty prompt`: text stdin is **not read** |
| Multi-line argv | `agy --output-format json --print-timeout 180s -p "$(cat brief.txt)"` (runarg.sh q2argv) | 0 | `"response":"MAPLE-42\n"`: all three lines were honored |
| NDJSON stdin | `agy -p= --input-format stream-json --output-format stream-json --print-timeout 180s < brief.ndjson` (runin.sh q2ndjson) | 0 | Two turns in one conversation: `"response":"MAPLE-42\n"` then `"response":"MAPLE\n"`, `"num_turns":2` |

`brief.txt` holds three lines: codeword MAPLE, number 42, and "reply `<codeword>-<number>`".

The NDJSON message schema was found by probing:
- `{"event":"bogus"}` gave stderr `warning: ignoring unsupported stream input message event "bogus"` and exit 0 (q2probe).
- `{"type":"user",…}` gave `stream input message is missing the "event" field` and exit 1 (first q2ndjson).
- `{"event":"user","text":…}` gave `stream input "user" message is missing the "message" field` and exit 1 (q2probe2).

The working line is:
```json
{"event":"user","message":{"role":"user","content":"line 1\nline 2"}}
```
`-p` always needs a value. With `--input-format stream-json` use `-p=` (empty). A bare trailing `-p` exits 2.

**Cleanest way to pass a multi-line brief:** `agy … -p "$(cat brief.md)"`. NDJSON stdin works too, but the brief must be JSON-escaped, and the process keeps reading stdin for further turns.

## 3. Resume

```
agy --sandbox --add-dir $E/state --mode accept-edits --output-format json --print-timeout 180s \
    -p "$(cat secret.txt)"            # runarg.sh q3set; brief: remember ZEBRA-7731, reply STORED
```
Exit 0: `{"conversation_id":"79dee396-598f-4787-b0aa-bfe11f1866c7","status":"SUCCESS","response":"STORED\n",…}`
```
agy --conversation 79dee396-598f-4787-b0aa-bfe11f1866c7 -p "What was the secret token? Reply with just the token." \
    --output-format stream-json --print-timeout 180s        # run.sh q3resume
```
Exit 0. The first line is `{"event":"init","conversation_id":"79dee396-…",…}`, and the result is `"response":"ZEBRA-7731\n","num_turns":2`.

- Context persists, and the ID stays the same.
- `--output-format` is per-invocation: q3set used json, and the resume printed stream-json because it asked for it.

Flag persistence:
- **`--add-dir` / `--sandbox` are not persisted.** q5b ran with `--sandbox --add-dir $E/state` and could write `$E/state/exp-sb-in.db`. That conversation was resumed without flags (runarg.sh q3noflags: `agy --conversation 02a63f61-… --output-format stream-json --print-timeout 180s -p "<init exp-resume-noflags.db>"`, exit 0). The tool output was `Command exited with code 1 … team-up: [Errno 1] Operation not permitted: '…/r3-agy-exp/state'`, the same failure as a fresh run without `--add-dir` (q5e).
- **`--settings` / mode are not persisted.** Conversation `ad1a5aaa-…` ran under `--settings set-default.json` (`{"agentMode":""}`), where `write_file` was denied (q4defmode). It was resumed without `--settings` (runarg.sh q3mode, exit 0). The response was `"OK\n"`, and `repo/resume_mode.txt` was created.
- Conclusion: repeat `--add-dir`, `--sandbox`, `--mode`, `--settings` and `--output-format` on every resume. All of them are session flags ("for the current CLI session" / "for this session only, never saved" in `agy --help`).

## 4. Permissions in print mode (no `--dangerously-skip-permissions`)

The headless default is **Auto mode**. The changelog says "headless `-p` runs, now start in Auto" (`agy changelog | grep …`, exit 0, line 193).

| Run | Flags | In-cwd new file via `write_file` | Shell command | Other |
|---|---|---|---|---|
| q4default | none (Auto) | allowed (`edit_tool.txt` created) | allowed (`shell.txt`, `python3 -c` printed `2`) | `edit_file` replacing a line in `$E/outside.txt` (outside workspace, not a VCS repo) was **also allowed**: the file read `changed line` |
| q4defmode | `--settings '{"agentMode":""}'` (Default mode) | denied | not executed (tool `DONE` with no `output`; `shell.txt` mtime unchanged) | `edit_file` outside: tool `DONE`, but `outside.txt` was unchanged (`original line`) |
| q4allow | Default + `permissions.allow:["write_file(<repo>/**)","command(echo)","command(/usr/bin/python3)"]` | denied: the glob form did not match | not executed (no `allow_shell.txt`) | — |
| q4allow2 | Default + `permissions.allow:["write_file(<repo>)","write_file(<repo>/allow2_tool.txt)","command(*)"]` | allowed, including `allow2_other.txt`, so the **directory form matches files under it** | allowed (`allow2_shell.txt`) | — |
| q4ae | `--mode accept-edits` + Default | allowed (`ae_tool.txt`) | **denied**: `permission check failed for unsandboxed "echo shell-ok > ae_shell.txt": user denied permission to run command` | — |
| q4deny | Auto + `permissions.deny:["command(echo)","write_file(<repo>/deny_tool.txt)"]` | denied: `Permission denied for write_file(…deny_tool.txt). Matches user-configured deny rule.` | `command(echo)` deny did **not** block `echo deny-test > deny_shell.txt` (the file was created) | — |

Every command had the form `agy <flags> --output-format stream-json --print-timeout 180s -p "$(cat permN.txt)"` (runarg.sh), and every run exited **0**.

How a denial appears (q4defmode, exit 0):
```
{"event":"step_update","step_update":{…,"state":"ERROR","step_type":"tool","tool_name":"write_file",…,"error":{"type":"TOOL_ERROR","message":"permission check failed for write_file \"…/edit_tool.txt\": user denied permission for write_file(…)\nDo not attempt to circumvent this denial…"}}}
{"event":"result","result":{…,"status":"SUCCESS","response":"",…,"denied_actions":[{"action":"write_file","display_name":"Edit"}]}}
stderr: jetski: no output produced — a tool required the "write_file" permission that headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under permissions.allow in settings.json (e.g. write_file(<target>)). …
```
- A denial is **not** a non-zero exit. `status` stays `SUCCESS`, and `response` may be empty.
- Detect denials by checking `result.denied_actions`, `step_update.state=="ERROR"` with a `permission check failed` message, or an empty `response`.
- In q4defmode, only `write_file` was listed in `denied_actions`. The shell step and the outside-workspace edit also did not take effect, yet they reported `DONE` with no output. **Verify side effects on disk rather than trusting tool `state`.**
- An explicit deny-rule hit (q4deny) produced a tool `ERROR` but **no** `denied_actions` entry.

`--settings` accepts a file path (or inline JSON). Keys confirmed to take effect:
- `agentMode` (`""` = Default)
- `permissions.allow` / `permissions.deny`, with rule forms `write_file(<dir-or-file>)` and `command(*)`

Forms that had no effect: `write_file(<dir>/**)` and `command(echo)` (as allow in Default, and as deny in Auto). No test checked whether unknown keys are rejected: `set-bogus.json` was written but not run.

## 5. Sandbox + SQLite state DB

Prompt in every case: "Run exactly this one shell command…: `/usr/bin/python3 <script> --db $E/state/<db> init`". Each command had the form `agy <flags> --output-format stream-json --print-timeout 180s -p "$(cat q5X.txt)"` (runarg.sh), and every agy exit was 0. The table lists the inner command results.

| Run | Flags | Script location | Inner exit | Observed |
|---|---|---|---|---|
| q5a | `--sandbox --add-dir $E/state` | outside workspace (`~/Documents/…/team_up.py`) | **2** | `can't open file '…/team_up.py': [Errno 1] Operation not permitted` plus a `There were sandbox errors … BypassSandbox` hint. The agent did not retry. |
| q5b | `--sandbox --add-dir $E/state` | copy in `$E/repo` | 0 | `{"db":"…/exp-sb-in.db","schema_version":3,"sqlite_version":"3.54.0","journal_mode":"wal"}`; `ls` shows `exp-sb-in.db`, `-shm` (32768 B), `-wal` (0 B) |
| q5c | `--add-dir $E/state` (no `--sandbox`) | outside | first 2 (same `Operation not permitted`), then 0 | The agent retried on its own, and Auto mode's review approved leaving the sandbox; `exp-nosb-out.db{,-shm,-wal}` was created. |
| q5d | `--add-dir $E/state` (no `--sandbox`) | copy in repo | 0 | `journal_mode":"wal"`; `exp-nosb-in.db{,-shm,-wal}` |
| q5e | `--sandbox` (no `--add-dir`) | copy in repo | **1** | `team-up: [Errno 1] Operation not permitted: '…/r3-agy-exp/state'` |
| q5f | `--sandbox --add-dir $E/state --add-dir <script dir>` | outside, but its dir was added | 0 | `journal_mode":"wal"`; `exp-sb-adddir.db` |

- SQLite in WAL mode works inside the sandbox when the DB directory is an `--add-dir`.
- The terminal sandbox blocks **reading** files outside the workspace. The script must be inside the cwd or an `--add-dir`. q5f shows that adding the script's directory is enough.
- Without `--sandbox`, Auto mode still sandboxes commands by default (q5c's first attempt failed the same way). The agent can then escape via `BypassSandbox`, gated by Auto mode's review.
- **Consequence:** the absence of `--sandbox` is not an isolation boundary, and the presence of `--sandbox` is what stops escalation. In q5a/q5b/q5e the agent never escaped the sandbox. Those prompts said "do not bypass" only in q5e/q5f, though, so it is unverified whether `--sandbox` forbids `BypassSandbox` or merely went unused.

## 6. Background process behavior

```
zsh bg2.sh   # cd $E/repo; agy -p "Run the shell command: sleep 12 && echo bg-done ; then reply FINISHED" \
             #   --output-format json --print-timeout 180s > out 2> err < /dev/null &   ; sample descendants every 2s
```
Exit 0. Output excerpt:
```
--- descendants at 14:51:17
55618 55573 /bin/zsh -c sleep 12 && echo bg-done
55619 55618 sleep 12
--- descendants at 14:51:35
55725 55573 /Users/yuhyeon/miniconda3/bin/python3 /Users/yuhyeon/.gemini/config/hooks/notion_logger.py
exit=0
{"conversation_id":"95e19936-…","status":"SUCCESS","response":"Running `sleep 12 && echo bg-done` in the background; waiting for it to finish.\nFINISHED\n",…}
--- descendants seen earlier still alive:
(none)
```
- With `&` and stdout redirected to a file, `agy -p` exited 0 and wrote one JSON object. Commands run as direct `zsh -c` children of agy, and none survived the exit.
- That stderr was empty here is incidental, not a guarantee.
- One leftover came from **the user's own agy hook**, not from agy itself. `~/.gemini/config/hooks/notion_logger.py` spawned a detached `agy --model gemini-3.8-flash-low -p "아래는 Antigravity 세션의 한 턴이다…"` that outlived the worker (it was seen in `pgrep -fl "sleep 12"` after exit). A later `ps -o pid=,ppid=,etime=,stat= -p 55740 55725` (exit 1, no rows) showed it had finished on its own. Expect one extra short-lived `agy` per worker turn in this environment.
- Earlier run bg.sh (`sleep 3`, exit 0) also showed no leftovers.
- Concurrency: par.sh started 3 `agy -p` runs at once. All exited 0 with distinct `conversation_id`s (`PAR1`, `PAR2`, `PAR3`). The single earlier `backend returned an empty conversation id` failure (q3set, exit 1) did not reproduce, so treat it as transient and retry on exit 1 with an empty `conversation_id`.

## 7. Notes for an agy coordinator (mostly unverified)

- **Verified:** in print mode, agy itself moves a long command to the background and is woken when it finishes, inside one turn. In bg2.sh the response was `Running … in the background; waiting for it to finish.\nFINISHED`, and the turn lasted 26.6 s for a 12 s sleep.
- **Verified (help text only):** an interactive mode exists: plain `agy` (TUI), and `-i/--prompt-interactive "<prompt>"` to start a TUI with a first prompt. It can be combined with `--conversation`. `--input-format stream-json` keeps a headless session open across many turns on stdin, which is a possible coordinator driver loop.
- **Unverified, from the changelog only** (`agy changelog | grep -n -i -E "…wake|background|notif…"`, exit 0): the agent has `manage_task`, `wait` and `schedule` tools; timers and background task completions are queued as messages that **wake the agent**; and a `/swarm` board sends "wakeup notifications" to members (line 14). An interactive coordinator could likely use background `run_command` and timers to poll workers without a human prompt. No interactive session was driven in this experiment.
- **Unverified:** `agy acp` (an Agent Client Protocol stdio server) keeps a turn open across background wake-ups (changelog line 33). It could serve as a programmatic coordinator transport.
- Print mode without `--print-timeout` waits for background tasks (changelog line 308). A coordinator should always set `--print-timeout`.

## Historical worker launch/resume commands

```sh
cd "$WORKTREE"
agy --sandbox \
    --add-dir "$STATE_DIR" --add-dir "$SCRIPT_DIR" \
    --settings "$SETTINGS_JSON" \
    --output-format stream-json --print-timeout 1800s \
    -p "$(cat "$BRIEF")" \
    > "$LOG.ndjson" 2> "$LOG.err" < /dev/null &
# conversation id: first line → jq -r 'select(.event=="init").conversation_id'
# final:           last line  → jq 'select(.event=="result").result | {status,response,denied_actions}'
```
`$SETTINGS_JSON` example: `{"permissions":{"allow":["write_file(<worktree>)","command(*)"]}}`. Rules use directory form, not `/**`. Alternatively, use `--mode accept-edits` and accept that shell commands which leave the sandbox are denied.

Resume: repeat **every** flag, because none persist.
```sh
cd "$WORKTREE"
agy --conversation "$CONV_ID" --sandbox \
    --add-dir "$STATE_DIR" --add-dir "$SCRIPT_DIR" \
    --settings "$SETTINGS_JSON" \
    --output-format stream-json --print-timeout 1800s \
    -p "$(cat "$NEXT_BRIEF")" > "$LOG2.ndjson" 2> "$LOG2.err" < /dev/null &
```
Exit handling:
- `0`: read `result.status`, `result.denied_actions` and the on-disk effects.
- `2`: usage error.
- `3`: `--print-timeout` hit (`finished_reason:"print_timeout"`). Resume with the same ID.
- `1` with an empty `conversation_id`: start-up failure. Retry.

## Limits

- Bad enum values are silently accepted (`--output-format xml` exits 0 with text output). Validate flags in the launcher.
- `-p` requires a value, and stdin text is never read as the prompt. A multi-line brief must go in argv, so it is bounded by `ARG_MAX`; the alternative is JSON-escaped NDJSON stdin.
- Permission denials exit 0 with `status:"SUCCESS"`. `denied_actions` is incomplete, and denied shell or outside-workspace steps can report `state:"DONE"`.
- `init.permission_mode` always reads `request-review`, so it cannot be used to confirm the mode.
- The default Auto mode allows edits outside the workspace (a line replacement in a non-VCS file was observed) and lets the agent request `BypassSandbox`. Use `--sandbox` plus explicit rules for workers.
- `command(<word>)` allow and deny rules had no observable effect. Only `command(*)` was confirmed.
- No flag persists across `--conversation`. The launcher must store and replay them.
- In the sandbox, any script or interpreter input outside cwd and the `--add-dir` paths fails with `Operation not permitted`.
- User-level hooks in `~/.gemini/config/hooks` run on every worker turn and may spawn extra `agy` processes.
- One transient start-up failure was seen: `backend returned an empty conversation id`, exit 1.
- §7 interactive coordinator, auto-wake and `/swarm` behavior are unverified beyond the help text and changelog.
