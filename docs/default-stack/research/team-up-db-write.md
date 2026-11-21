# team-up 상태 DB 쓰기 검증

2026-11-21 · macOS (Darwin 27.2) · Codex CLI 0.170.0 · Claude Code 2.1.330

계획한 위치 `~/.local/state/default-stack/team-up/<repo-id>.db`는 Codex 워커와 Claude 워커 둘 다 linked worktree에서 쓸 수 있다. 단, 각 워커에 경로 허가를 명시해야 한다. Codex는 `-s workspace-write --add-dir <state dir>`가 필요하고, 없으면 DB를 열지 못한다. `claude -p`는 비대화 모드라 승인 프롬프트가 없으므로 `--allowedTools "Bash(python3 <team-up 스크립트>:*)"`가 필요하다. Claude Bash 샌드박스를 켠 경우에는 `sandbox.filesystem.allowWrite`에 state dir을 추가로 넣어야 한다. 동시 쓰기는 WAL에서 문제없지만, 새 DB를 여러 프로세스가 동시에 WAL로 전환하면 `database is locked`가 난다. 코디네이터가 DB를 먼저 초기화해야 한다.

## 실험

테스트 위치: 임시 repo(`main` + linked worktree `wt-a`), state dir `~/.local/state/default-stack/team-up-test/`. 쓰기 스크립트는 stdlib `sqlite3`만 쓴다.

| 실험 | 명령 | 기대 | 실제 | 결과 |
|---|---|---|---|---|
| 1. Codex, 허가 있음 | `codex exec -C wt-a -s workspace-write --add-dir $D "python3 tu.py $D/x.db 실행"` | 쓰기 성공 | `count 1`, exit 0. 정상 종료 후 `-wal`/`-shm`은 정리되어 `x.db`만 남음 | 통과 |
| 2. Codex, 대조군 | 1과 같되 `--add-dir` 없음 | 실패 | `sqlite3.OperationalError: unable to open database file`, exit 1 | 통과 (예상대로 차단) |
| 3a. Codex 샌드박스 동시 쓰기 (초기화 없음) | `codex exec … --add-dir $D` 안에서 `tu.py` 5개 병렬 × 50행 | 250 | 200. 한 프로세스가 `PRAGMA journal_mode=WAL`에서 `database is locked`로 종료 | 실패 |
| 3b. 같은 조건, 수정 스크립트 | 코디네이터가 `tu2.py … init`으로 WAL·스키마를 먼저 만든 뒤, 같은 샌드박스에서 5 × 50을 3회 | 250 ×3 | `count 250 wal` ×3 | 통과 |
| 4a. Claude, 허가 있음 | cwd `wt-a`, `claude -p --model haiku --allowedTools "Bash(python3 tu2.py:*)" --output-format json` | 쓰기 성공 | `count 1 wal`, `permission_denials: []` | 통과 |
| 4b. Claude, 대조군 | 4a와 같되 `--allowedTools` 없음 | 권한 거부 | exit 0이지만 명령 미실행, `permission_denials`에 Bash 1건 | 통과 (예상대로 차단) |
| 5a. Claude 샌드박스, 경로 미허가 | 4a + `--settings '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false}}'` | 차단 | `unable to open database file`, 행 증가 없음 | 통과 (예상대로 차단) |
| 5b. Claude 샌드박스, 경로 허가 | 5a + `"filesystem":{"allowWrite":["$D"]}` | 쓰기 성공 | `count 2 wal` | 통과 |
| 6. repo-id 안정성 | `git rev-parse --path-format=absolute --git-common-dir` → sha256 앞 16자, main/`wt-a`/`wt-a/`에서 각각 | 동일 | 세 곳 모두 `…/main/.git` → `a8ad8d0bf07c3662` | 통과 |

참고: 3a·3b의 stderr에 나온 `zsh: nice(5) failed: operation not permitted`는 샌드박스에서 백그라운드 작업을 띄울 때 나오는 경고로, 결과와 무관하다. 5a·5b는 사용자 설정 파일을 건드리지 않고 `--settings` JSON으로 한 번만 켰다.

## team-up에 필요한 변경

- **초기화는 코디네이터만 한다.** 코디네이터가 run 시작 시 DB를 만들고 `PRAGMA journal_mode=WAL`과 스키마를 적용한다. 워커 쪽 스크립트는 연결 직후 `PRAGMA busy_timeout`을 먼저 설정하고, journal mode를 바꾸거나 스키마를 만들지 않는다.
- **Codex 워커 실행 인자:** `codex exec -C <worktree> -s workspace-write --add-dir ~/.local/state/default-stack/team-up`.
- **`claude -p` 워커 실행 인자:** `--allowedTools "Bash(python3 <plugin>/skills/team-up/scripts/<script>:*)"`. 사용자가 Claude 샌드박스를 쓰면 `--settings`로 `sandbox.filesystem.allowWrite`에 state dir을 넣는다. 허가가 빠지면 exit 0으로 끝나므로 종료 코드가 아니라 JSON의 `permission_denials`나 DB 기록으로 실패를 판정한다.
- **repo-id:** 해시 전에 경로를 정규화한다(`realpath`). 이번 실험에서는 세 위치 모두 같은 값이 나왔지만, macOS의 `/tmp` → `/private/tmp`처럼 심볼릭 링크가 있는 경로에서 코디네이터와 워커가 서로 다른 문자열을 넘기면 값이 달라질 수 있다.
- **확인하지 못한 것:** 데스크톱 앱 사이드 세션 워커(같은 Claude Code 권한 체계를 쓸 것으로 보이나 직접 실행하지 않음), 워커 수가 수십 개일 때의 잠금 대기 시간.
