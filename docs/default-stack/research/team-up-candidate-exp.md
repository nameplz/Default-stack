# team-up 후보 실험

Codex 워커가 질문을 SQLite에 남기고 턴을 끝낸 뒤 같은 worktree와 세션에서 답변을 받아 재개하는 경로가 동작했다. 재개할 때도 `-s workspace-write --add-dir "$D"`를 지정해야 상태 DB에 쓸 수 있었다. 같은 턴에는 Codex 셸의 대기 프로세스를 폴링하거나 App Server Plan 모드의 차단형 질문 RPC에 응답할 수 있었다. Default 모드에서는 기능 플래그를 켰을 때 비차단 질문에 즉시 답해 같은 턴을 완료했다. SQLite `wait`는 별도 프로세스가 쓴 질문과 완료를 5회 모두 1초 안에 감지했다. 종료된 Claude 코디네이터의 문맥 재개와 호스트의 자동 깨우기는 추가 확인이 필요하다. Claude CLI 워커의 DB 쓰기는 Bash 허가를 명시했을 때 성공했다.

## 실험 결과

2026-11-21 KST. macOS, Codex CLI 0.170.0, Claude Code 2.1.330, 임시 Git 저장소의 첫 커밋 `253830e`와 linked worktree 두 개. 아래 명령의 변수와 프롬프트는 다음 절에 적었다. 시간은 프로세스 경과 시간이며, A1 답변 지연은 질문 행을 쓰기 직전부터 `answer` 실행을 시작할 때까지다.

| 실험 | 명령 | 기대 | 실제 | 통과/실패 |
|---|---|---|---|---|
| A1 · 30초 | `codex exec -m gpt-6.2-sol -C "$W" -s workspace-write --add-dir "$D" --json "$P30"`, `python3 "$T" wait --timeout 5`, `python3 "$T" answer 12 answer-585300` | 질문 ID 12 감지 후 30초에 응답, 같은 턴 완료 | `wait` exit 0, 0.074초. 30.005초에 답변 시작. `answer` exit 0, 0.074초. `ask` exit 0, 출력 `12`와 `answer-585300`. 같은 턴이 이 토큰을 반환했고 CLI exit 0, 39.388초. | 통과 |
| A1 · 5분 | `codex exec -m gpt-6.2-sol -C "$W" -s workspace-write --add-dir "$D" --json "$P300"`, `python3 "$T" wait --timeout 5`, `python3 "$T" answer 7 answer-long-514607` | 질문 ID 7 감지 후 300초에 응답, 같은 턴 완료 | `wait` exit 0, 0.076초. 300.059초에 답변 시작. `answer`와 `ask` 모두 exit 0. `ask`는 `7`과 `answer-long-514607`를 출력했다. 같은 턴이 이 토큰을 반환하고 308.236초에 완료됐다. CLI exit 0은 macOS의 종료 상태로 확인했다. | 통과 |
| A2 · 질문 기록 | `codex exec -m gpt-6.2-sol -C "$W" -s workspace-write --add-dir "$D" --json "$P2"`, `python3 "$T" answer 8 reply-431973` | DB에 질문을 남기고 턴 종료 | CLI exit 0, 8.396초. `record` exit 0, 질문 ID 8. 최종 메시지 `QUESTION_RECORDED`. `thread.started`에서 ID를 받았다. `answer` exit 0, 0.075초. | 통과 |
| A2 · 권한 플래그 생략 | `codex exec resume --json "$THREAD" "$PBARE"` | 문맥 복원과 기존 쓰기 권한 상속 여부 확인 | CLI exit 0, 9.225초. `context-372015`와 `reply-431973`을 반환했다. `done`은 `attempt to write a readonly database`, exit 1. 완료 행 없음. | 문맥 통과, 쓰기 실패 |
| A2 · 권한 재지정 | `codex exec -m gpt-6.2-sol -C "$W" -s workspace-write --add-dir "$D" resume --json "$THREAD" "$PFLAGS"` | 문맥 복원과 DB 쓰기 | CLI exit 0, 8.920초. 같은 토큰과 답변을 반환했다. `done` exit 0, DB의 완료 행 ID 9. | 통과 |
| A3 · Default | `codex app-server --listen stdio://`, `turn/start`의 `collaborationMode.mode=default` | 차단형 질문 RPC 수신과 응답 | 4.418초에 `item/completed`의 `agentMessage`로 질문과 선택지를 받았다. `delivery=async`. 90초 동안 차단형 RPC와 `turn/completed`는 관측되지 않았다. stdin을 닫은 뒤 프로세스 exit 0, 90.043초. | 차단형 왕복 실패 |
| A3 · Default + 기능 플래그 | `codex app-server --listen stdio:// --enable default_mode_request_user_input`, `mode=default` | RPC 수신 여부와 같은 턴 응답 확인 | RPC는 4.267초에 `isBlocking=false`로 왔다. 즉시 `Green`을 답하자 같은 턴이 `Green`으로 완료됐다. 프로세스 exit 0, 6.652초. 지연 답변은 이 모드에서 시험하지 않았다. | 즉시 왕복 통과, 차단형 대기 미검증 |
| A3 · Plan | 같은 stdio 명령, `collaborationMode.mode=plan` | 차단형 질문 RPC 수신과 응답 | 두 번 모두 `item/tool/requestUserInput`의 `isBlocking=true` 수신. 요청 ID `0`에 `Green`을 답하자 같은 턴이 `Green`을 출력하고 `turn/completed`를 보냈다. RPC는 4.527초와 6.150초, 프로세스 exit 0은 5.901초와 9.963초. | 통과 2/2 |
| B1 · 프로세스 간 깨우기 | 별도 프로세스의 `python3 "$T" wait --timeout 3`와 `done` 3회, `ask` 2회 | 쓰고 1초 안에 해당 이벤트로 `wait` 종료 | 5회 모두 `wait`와 writer exit 0. 이벤트 ID 1–5. 쓰기 직전부터 `wait` 종료 관측까지 41.3, 43.5, 40.5, 44.0, 42.4ms. 중앙값 42.4ms. 질문 두 건은 `pong`으로 풀었고 `answer`도 둘 다 exit 0. | 통과 5/5 |
| B2 · Claude 재개 | `claude -p --model haiku --output-format json --setting-sources '' --strict-mcp-config`로 시작 후 같은 옵션에 `--resume aa849183-91d0-4a5d-90e7-dc80bdfb8412` | 이전 토큰 `lotus-323315` 회상 | 첫 턴 `READY`, exit 0, 2.510초. 기존 프로필 쓰기를 막은 조건에서 두 번째 명령은 `No conversation found with session ID`, exit 1, 0.774초. | 이 환경에서 실패, 호스트 확인 필요 |
| B2 · Claude 재개 (재실행) | 코디네이터가 샌드박스 없이 `claude -p --model haiku --output-format json` 후 `--resume <session_id>` | 이전 토큰 회상 | 두 번째 턴이 `lotus-323315`를 반환, 같은 `session_id`, exit 0. 첫 실행의 실패는 프로필 쓰기를 막은 실험 샌드박스 때문 | 통과 |
| C · Bash 허가 | `claude -p --model haiku --output-format json --setting-sources '' --strict-mcp-config --no-session-persistence --allowedTools "Bash(python3 $T:*)" -- "$PALLOW"` | linked worktree에서 `done` 기록 | exit 0, 4.926초. `permission_denials=[]`. 출력 `10`과 DB의 `C-allow / ok / fixture` 행 일치. | 통과 |
| C · acceptEdits | 같은 명령에서 `--allowedTools`를 빼고 `--permission-mode acceptEdits -- "$PACCEPT"` 사용 | Bash 승인 필요로 차단 | exit 0, 5.667초. `permission_denials`에 Bash 1건, `This command requires approval`. `C-accept` 행 없음. | 통과 |

## 재현 명령

```sh
R='/private/tmp/claude-501/-Users-yuhyeon-Library-Application-Support-Claude-scratch-workspaces-af7e6153-8a66-4e46-af31-1d7699cbc6be-0bf26451-ff20-4e4a-816f-11423330cc8b-scratch-2026-11-21-e11e16/0d02762e-13ba-4b78-9772-f7329fe6b8bb/scratchpad/team-up-exp2'
D='/Users/yuhyeon/.local/state/default-stack-test'
T="$R/tu.py"
W="$R/wt-a"
THREAD='01a1fcc4-ea63-73b2-8c5c-d63840cb41a0'
P30="Run exactly once: python3 $T ask A1-30-verified 'Which token?'. Wait for the answer in the same turn (poll the existing tool session if needed). Use the answer verbatim as your final message. Do not answer before the command returns."
P300="Run exactly once: python3 $T ask A1-300-retry 'Which token?'. Wait for the answer in the same turn (poll the existing tool session if needed). Use the answer verbatim as your final message. Do not answer before the command returns."
P2="Remember context-372015. Run exactly python3 $T record A2 'Which token?'. End your turn with QUESTION_RECORDED, omitting the memorized token."
PBARE="The answer is reply-431973. Run exactly python3 $T done A2-bare ok reply-431973. In your final message give the memorized context token and answer."
PFLAGS="The answer is reply-431973. Run exactly python3 $T done A2-flags ok reply-431973. In your final message give the memorized context token and answer."
PALLOW="Run this exact Bash command once: python3 $T done C-allow ok fixture. Report result briefly."
PACCEPT="Run this exact Bash command once: python3 $T done C-accept ok fixture. Report result briefly."
python3 "$T" init
```

`init`은 작업자 실행 전에 WAL과 스키마를 적용했다. 질문, 완료 이벤트와 답변은 별도 행에 기록했고 연결마다 `busy_timeout=3000`을 설정했다. `ask`는 질문 트랜잭션을 커밋하고 50ms마다 답변을 조회했다. 기한 365초가 지나면 exit 124로 끝나게 했다. A2의 `record`는 같은 질문 행을 쓰고 즉시 반환한다. `wait`는 50ms마다 미확인 완료 또는 답변 없는 미확인 질문을 찾아 같은 트랜잭션에서 확인 표시를 남기고 JSON으로 출력했다.

A2의 두 재개는 cwd를 `"$W"`로 두고 같은 스레드 ID를 썼다. Codex 프로필과 임시 파일은 실험 디렉터리 안에 격리했다. B1은 `wait`가 `ready`를 출력한 뒤 아래 writer를 순서대로 실행했다. 쓰기 시각과 종료 관측 시각에는 같은 Python 3.13의 단조 시계를 사용했다.

```sh
python3 "$T" done B1-1 ok fixture
python3 "$T" ask B1-2 ping --timeout 5
python3 "$T" answer 2 pong
python3 "$T" done B1-3 ok fixture
python3 "$T" ask B1-4 ping --timeout 5
python3 "$T" answer 4 pong
python3 "$T" done B1-5 ok fixture
```

B2와 C는 cwd를 `"$R/wt-b"`로 두고 명령 앞에 `sandbox-exec -f "$R/claude-write.sb"`를 붙였다. 프로필은 파일 쓰기를 `"$R"`, `"$D"`, `/dev/null`로 제한했다. `TMPDIR`, `CLAUDE_CODE_TMPDIR`, `CLAUDE_TMPDIR`는 `"$R/isolated-tmp"`를 사용했다. B2는 첫 명령에 `'Remember lotus-323315. Reply only READY.'`, 재개 명령에 `'What exact token did I ask you to remember? Reply only with it.'`를 전달했다.

### App Server 메시지

`codex app-server generate-json-schema --experimental --out "$R/schema"`는 exit 0이었다. `ServerRequest.json`에 `item/tool/requestUserInput`이 있고, 응답은 `ToolRequestUserInputResponse.json`의 `answers` 형식을 따른다. 실험은 아래 순서로 stdio에서 한 줄씩 교환했다. `WT`와 `THREAD_ID`에는 각각 `"$W"`와 `thread/start`의 반환값을 넣었다. Default 실험은 `mode`만 `default`로 바꿨다.

```jsonl
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"team-up-exp","version":"0.1"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized"}
{"id":2,"method":"thread/start","params":{"cwd":"WT","model":"gpt-6.2-sol","sandbox":"workspace-write","approvalPolicy":"never","ephemeral":true}}
{"id":3,"method":"turn/start","params":{"threadId":"THREAD_ID","input":[{"type":"text","text":"Use request_user_input to ask 'Which color?' with options Blue and Green. Wait for the reply, then output only the selected color."}],"collaborationMode":{"mode":"plan","settings":{"model":"gpt-6.2-sol"}}}}
{"id":0,"result":{"answers":{"color":{"answers":["Green"]}}}}
```

마지막 줄은 서버가 보낸 요청 ID와 질문 ID를 그대로 사용한 응답이다. 서버는 `serverRequest/resolved` 후 같은 `turnId`로 완료를 알렸다. `codex exec`는 `turn/start`의 `collaborationMode=plan`을 지정하는 옵션을 노출하지 않는다. [기존 Codex 실행 방식 조사](chatgpt-desktop-app.md)

### 계측과 실행 제한

A1에서 셸 실행은 `yield_time_ms=1000`으로 시작해 세션 ID를 반환했다. 워커는 같은 세션을 `write_stdin`으로 다시 조회했다. 5분 실험의 조회는 회당 최대 60초 대기를 요청했다. 이 시간은 각 조회가 제어권을 돌려주는 간격이다. 셸 프로세스는 최소 300.059초 생존했고 Codex가 종료하지 않았다. `ask`의 자체 기한은 365초이며 Codex 도구의 절대 상한은 이번 실험에서 도달하지 않았다.

- 첫 Codex 실행은 연결 제한으로 `workspace routing discovery failed`가 나며 exit 1이었다. 위 표는 연결이 열린 재실행의 기록이다.
- 첫 A1 감독 프로세스는 macOS 시스템 Python 3.9의 프로세스별 `monotonic()`을 워커 Python 3.13의 시각과 비교해 답변 타이머를 늦췄다. Python 3.13 감독 프로세스가 질문 ID 6에 312.146초 후 `answer-late-192502`를 전달하자 원래 턴이 그 답변으로 완료됐다. 그 턴은 321.463초였다. 30초와 5분 판정에는 같은 시계를 사용한 답변 지연을 썼다.
- Claude 임시 프로필에서는 `Not logged in`으로 모델 호출 전에 종료됐다. 키체인에서 OAuth 값을 직접 전달하는 시도는 자동 승인 검토가 자격 증명 접근 위험을 이유로 거부해 실행되지 않았다. 이후 CLI 기본 인증을 그대로 사용하고 파일 쓰기를 실험 경로에 제한했다. C의 첫 허가 실행은 셸 임시 디렉터리의 `mkdir`에서 차단됐다. 임시 디렉터리를 실험 경로로 지정한 뒤 C를 재실행했다. B2의 세션 저장은 기존 프로필 경로가 필요해 호스트 재확인이 남았다.

## 결정 행 권고

| 행 | 권장 문구 |
|---|---|
| 질문과 후속 지시 | 질문과 답변을 Dispatch에 연결해 DB에 저장한다. 워커는 질문을 기록한 뒤 턴을 종료한다. 답변을 받으면 저장된 스레드 ID로 같은 worktree에서 재개한다. Codex 시작과 재개에 `-s workspace-write --add-dir <state dir>`를 적용한다. 같은 턴 대기가 필요한 경우 자체 기한을 둔 셸 세션을 폴링하거나 App Server Plan 모드의 차단형 질문 RPC에 답한다. |
| 코디네이터 깨우기와 재개 | CLI에서 실행 중인 코디네이터는 `wait`로 미처리 질문·완료 이벤트를 받아 DB에서 Run을 이어간다. 턴을 이미 종료한 코디네이터는 Run을 명시적으로 재개하고 워커 생존 여부와 미결 질문부터 확인한다. `claude -p --resume`의 문맥 복원은 코디네이터 재실행(B2 재실행)으로 확인했다. 데스크톱 앱의 종료 턴 자동 깨우기는 H3으로 확인했다. |
| Claude 워커 DB 쓰기 | linked worktree의 `claude -p` 워커에는 `--allowedTools "Bash(python3 <team-up 스크립트>:*)"`를 지정한다. 쓰기 샌드박스가 켜져 있으면 상태 디렉터리를 허가하고, JSON `permission_denials`와 DB 행을 확인한다. `acceptEdits`만 지정하면 Bash 쓰기 명령이 거부될 수 있다. 데스크톱 사이드 세션과 앱 서브에이전트의 DB 쓰기는 H1·H2로 확인했다. [기존 DB 쓰기 검증](team-up-db-write.md) |

## 호스트 검증 (코디네이터 직접 실행)

2026-11-21, Claude 데스크톱 앱 Code 탭. 코디네이터가 WAL로 초기화한 테스트 DB(`~/.local/state/default-stack-test/host.db`)에 각 워커가 stdlib 스크립트로 완료 행을 썼다. 권한 모드는 auto.

| 실험 | 방법 | 실제 | 결과 |
|---|---|---|---|
| H1 · 앱 서브에이전트 | Agent 도구, `isolation: worktree`, Haiku | `.claude/worktrees/agent-…`에서 실행, git common dir은 메인 `.git`. 완료 행 기록, 코디네이터가 조회. 변경 없는 worktree는 종료 후 자동 정리 | 통과 |
| H2 · 데스크톱 사이드 세션 | `start_session`, 별도 worktree, Haiku. 20초 뒤 완료 행 기록 | 완료 행 기록 | 통과 |
| H3 · 종료 턴 자동 깨우기 | 코디네이터가 `wait`를 백그라운드 Bash로 띄우고 턴 종료 | H2의 쓰기 후 164ms에 `wait`가 종료, 앱이 코디네이터를 새 턴으로 깨움 | 통과 |

제약: 앱 알림이나 다른 세션의 메시지로 시작된 턴에서는 코디네이터가 사이드 세션을 직접 시작할 수 없고 제안 카드만 올릴 수 있다. 사용자가 시작하거나 사용자 턴에서 시작해야 한다. CLI 코디네이터의 백그라운드 `wait` 깨우기는 이번에 시험하지 않았다.
