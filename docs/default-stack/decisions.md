# Decisions

## 확정

| 결정 | 근거 |
|---|---|
| Claude Code·Codex 호환 플러그인, 마켓플레이스 배포 | 두 도구를 모두 사용하고 공유할 예정 |
| 모든 스킬은 명시 호출 전용 | 워크플로 단계를 사용자가 직접 통제 |
| 기본 문서 경로는 `docs/default-stack/`, 기존 문서가 있으면 그것을 우선 재사용 | 중복 문서와 불필요한 구조 변경 방지 |
| coffee-chat은 정형 인터뷰가 아닌 자유 대화 | 정리되지 않은 생각을 맥락과 함께 탐색 ([영감](https://x.com/karpathy/status/2079610838143623371?s=20), voice는 제외) |
| 아이디어 상태를 확정 / 후보 / 미결정 / 폐기로 구분 | 탐색 중인 생각과 결정을 섞지 않기 위해 |
| 플러그인 본체는 `plugin/` 하위, 마켓플레이스·README·LICENSE·설계 문서는 저장소 루트 ([구조](work/plugin-structure.md)) | 배포 대상과 저장소 메타 분리 |
| 매니페스트는 `plugin/plugin.json`(Codex)과 `plugin/.claude-plugin/plugin.json`(Claude Code) 두 개, `skills/`는 공유. 플러그인 `name`은 `default-stack` | Claude Code는 `.claude-plugin/`만 읽음. Codex CLI 0.164.0이 루트 `plugin.json`으로 설치·스킬 등록하는 것을 확인 ([Claude](https://code.claude.com/docs/en/plugins-reference), [Codex](https://developers.openai.com/plugins/build/plugins)) |
| `SKILL.md` frontmatter에 `disable-model-invocation: true`를 그대로 둠 | Codex CLI 0.164.0이 모르는 frontmatter를 경고 없이 무시함을 확인 |
| 스킬에서 공통 문서는 `../../references/<name>.md` 상대경로로 참조. `${CLAUDE_PLUGIN_ROOT}` 등 변수는 쓰지 않음 | Codex는 SKILL.md 절대경로를 모델에 제공하고 `references/`도 설치본에 복사됨. 스킬 본문의 변수는 치환하지 않음 (Codex CLI 0.164.0에서 확인). Claude Code 2.1.312에서도 스킬 기준 상대경로로 바로 읽음을 확인 |
| 마켓플레이스는 `.claude-plugin/marketplace.json`과 `.agents/plugins/marketplace.json` 두 개, 둘 다 `./plugin`을 가리킴 | 각 도구 전용 형식으로 따로 관리. Codex 공식 위치는 `.agents/plugins/` |
| 명시 호출 전용: Claude Code는 `SKILL.md` frontmatter `disable-model-invocation: true`, Codex는 `skills/<name>/agents/openai.yaml`의 `policy.allow_implicit_invocation: false` | 각 도구의 공식 설정 ([Codex skills](https://learn.chatgpt.com/docs/build-skills)). 호출은 Claude `/default-stack:<skill>`, Codex `$` 멘션 (등록 이름 `default-stack:<skill>`) |
| 작성자 `nameplz`(GitHub), MIT 라이선스, 스킬·references 지침은 영어 | 마켓플레이스 공유. 대화와 생성 문서는 사용자 언어 |
| `SKILL.md`는 호출 조건과 역할만, 실행 절차는 `references/`에. 공통 규칙은 한 문서를 여러 스킬이 참조 | 같은 규칙을 두 곳에 쓰지 않음 |
| coffee-chat 외 기존 스킬(whats-wrong, shall-we, is-it-ok, just-do-it) 제거 | 구현·검증·전달은 apply-stack이 만든 verify 기반과 ship-it이 맡음 |
| `commands/`, `agents/`, `hooks/` 미사용. 스킬만으로 구성 | OpenAI 제출 시 비호환 항목 ([가이드](https://developers.openai.com/plugins/guides/submit-claude-plugin.md)) |
| Lauren Tan 방식 설정(`apply-stack`)과 PR 전달(`ship-it`)을 이 플러그인에 포함. 이전 이름 apply-lauren | 아이디어→구현 흐름과 저장소 검증 기반을 한 플러그인으로 관리 |
| pstack은 의존성으로만 둠. 스킬을 복사하지 않고 설치본의 `SKILL.md`를 읽어 따름 (`references/pstack.md`) | 복사하면 pstack 업데이트가 끊김. Claude Code 공식판과 Codex 포팅판의 경로가 달라 매번 최신 버전 폴더를 찾음 |
| 기본 브랜치에는 PR로만 반영. 필수 검사 `verify`만 통과하면 리뷰 없이 자동 병합 | Lauren 방식: 검사가 게이트, 사람 리뷰는 병목. 필수 검사 없는 자동 병합은 즉시 병합이므로 ship-it이 먼저 확인 |
| 형식 검증(`formal`)과 릴리스별 탐색(`explore`)을 apply-stack 기반 위의 별도 스킬로 둠. explore는 버그마다 PR 하나, 실행당 PR 최대 5개 | 기반(verify, 검증 스킬, 자동 병합)이 있어야 동작. 버그를 묶으면 되돌리기 어려움 |
| 반복 지적 규칙은 hook이 아니라 apply-stack이 프로젝트 `AGENTS.md`에 넣음 | `hooks/` 미사용 원칙 유지. 규칙이 저장소와 함께 이동 |
| `team-up` 코디네이터는 Claude 데스크톱 앱 Code 탭, Claude Code CLI, 대화형 Codex CLI, 사용자가 직접 시작한 대화형 agy에서 지원. Codex 데스크톱 앱·App Server 코디네이터는 미검증·미지원. Claude·Codex 워커별 Git worktree 배정, Run·Task·Dispatch 상태는 SQLite에 기록 | 지원 호스트에서 로컬 워커 조율과 진행 상태 보존 |
| 상태 DB는 `~/.local/state/default-stack/team-up/<repo-id>.db`. `git rev-parse --path-format=absolute --git-common-dir` 결과의 `realpath`를 해시해 `<repo-id>`를 구함. `init`에서 Git common dir을 DB에 저장하고 worktree 검사에 사용 | Codex 샌드박스가 `.git`을 보호함. 메인 체크아웃과 linked worktree에서 같은 ID를 확인. `--db`를 지정하면 다른 디렉터리에서도 같은 저장소의 worktree를 검사. [DB 쓰기 검증](research/team-up-db-write.md) |
| Codex 워커는 지정된 worktree에서 `codex exec --json`으로 시작. `thread.started`의 ID와 worktree를 기록하고 같은 worktree에서 해당 ID로 `codex exec resume` 실행. ID 기록을 놓쳤으면 `turn-ended`나 `waiting`에서 현재 턴의 저장된 JSONL로 빈 세션 ID를 채움. 시작·재개에 `-s workspace-write --add-dir <state dir>` 적용 | [Codex 실행 방식](research/chatgpt-desktop-app.md), [DB 쓰기 검증](research/team-up-db-write.md) |
| 데스크톱 코디네이터는 사용자 턴에서 Claude 워커 배정 시 사이드 세션 우선. 알림이나 다른 세션 메시지로 시작된 턴에서는 사이드 세션 시작 불가. 자동 후속 배정은 worktree 서브에이전트 또는 `codex exec` 사용. CLI Claude 워커 시작·재개 시 `--allowedTools`에 브리프의 따옴표 없는 Python·스크립트 접두사, `Edit only` 경로, `Verify`와 `Diff`의 정확한 명령을 지정. Bash 호출당 명령 하나를 실행. 샌드박스 사용 시 `sandbox.filesystem.allowWrite`에 상태 디렉터리 추가. 워커는 작업을 막는 거부를 질문으로 기록하고 코디네이터는 매 턴 `permission_denials`와 DB 기록 확인 | 데스크톱 사이드 세션·worktree 서브에이전트의 DB 쓰기 확인. `claude -p`는 도구 사용이 거부돼도 종료 코드 0 가능. [후보 실험·호스트 검증](research/team-up-candidate-exp.md), [DB 쓰기 검증](research/team-up-db-write.md) |
| `skills/team-up/scripts/`에 Python 표준 라이브러리만 쓰는 스크립트 포함. 스킬 문서는 상대경로로 참조, 코디네이터는 스킬 위치에서 계산한 실행 경로를 워커 브리프에 명시. 워커에게 스크립트로 DB를 갱신하도록 지시 | 스킬 내부에 실행 절차 배포. `--add-dir`는 디렉터리 쓰기 권한 부여, 스크립트 사용은 워커 지침 |
| 코디네이터만 DB를 초기화하고 WAL 모드와 스키마를 설정. 워커는 연결 직후 `busy_timeout`을 설정하고 기존 저널 모드를 유지 | 새 DB에서 동시에 WAL 모드로 전환하자 `database is locked`로 250행 중 200행만 기록. 코디네이터가 먼저 초기화한 뒤 3회 모두 250행 기록 ([DB 쓰기 검증](research/team-up-db-write.md)) |
| `team-up`에 기존 명시 호출 정책 적용. 전환 시 사용자 환경의 `~/.agents/skills/orchestration` 스텁 비활성화. Dispatch를 받은 워커는 브리프에 지정된 명령 실행 | 자연어 위임 요청으로 기존 Orca 스텁이 실행되는 경로 제거 |
| Run별 Task 의존성과 사용자 결정 게이트 저장. 선행 작업·게이트·가용 슬롯 확인과 Dispatch 예약을 하나의 `BEGIN IMMEDIATE` 트랜잭션으로 처리한 뒤 워커 시작. 부분 유일 인덱스로 Task당 열린 Dispatch 하나만 허용. 브리프에 Task·Dispatch ID, 목표, 수정 범위, 완료 증거 명시 | 중복 배정 방지와 재개 시 배정 범위 복원. [OSS 조사](research/team-up-oss.md) |
| 질문·답변·후속 지시는 Dispatch에 연결해 DB에 기록. 워커는 질문 기록 후 턴 종료, 답변 수신 후 같은 worktree에서 같은 스레드로 재개. Codex 시작과 재개에 `-s workspace-write --add-dir <state dir>` 재지정. 같은 턴 대기가 필요할 때만 자체 기한을 둔 셸 `ask` 또는 App Server Plan 모드의 차단형 질문 사용 | 동일 스레드 재개·DB 쓰기와 두 가지 같은 턴 응답 경로 확인. Codex 셸 도구의 최대 대기 시간은 미검증. [후보 실험](research/team-up-candidate-exp.md) |
| `done --evidence`로 성공·실패, 결과 전문, 검증 명령·종료 코드·결과 위치 기록. Claude·Codex 워커는 검증 직후 편집 범위의 Git diff를 수집해 `diff`에 원문을 기록. 추적 파일은 `HEAD`와 비교하고 새 미추적 파일은 `git diff --no-index`로 `/dev/null`과 파일별 비교. 코디네이터는 워커 종료 후 worktree에서 diff를 대조하고 스테이징·커밋·전달 담당. 코디네이터는 시작·턴 종료·프로세스 종료·Task 완료를 구분. 완료 보고 없이 끝난 배정은 미완료 처리, 질문만 남긴 정상 턴은 답변 대기로 복구 | 완료 보고와 실행 종료의 독립 판정. [OSS 조사](research/team-up-oss.md) |
| 상태 전이와 이벤트를 DB에 함께 커밋. Claude 데스크톱 코디네이터는 백그라운드 `wait`로 새 턴 시작. 실행 중인 Claude Code CLI 코디네이터는 `wait`로 미처리 이벤트 조회, 종료한 경우 `claude -p --resume`으로 Run을 명시 재개. Codex CLI 코디네이터는 턴 안에서 `wait`와 워커 셸 핸들 폴링을 번갈아 실행하고, 종료한 경우 `codex resume <thread-id>`로 Run을 명시 재개(`--last` 미사용). agy 코디네이터는 워커를 백그라운드 셸 작업으로 실행하고 `wait --timeout`과 저장된 핸들로 폴링하며, 종료한 경우 사용자가 `agy --conversation <id>`로 명시 재개. 재개 시 워커 생존 상태와 미결 질문 확인, 이후 선행 조건을 충족한 Task 배정 | 데스크톱 자동 깨우기와 `claude -p --resume` 문맥 복원 확인. Claude·Codex CLI 자동 깨우기, Codex 셸 세션의 코디네이터 종료 후 생존, agy 자동 깨우기(백그라운드 작업 깨우기·타이머·`/swarm`·`acp`)는 미검증. [후보 실험·호스트 검증](research/team-up-candidate-exp.md), [agy 실험](research/team-up-agy-exp.md), [OSS 조사](research/team-up-oss.md) |
| team-up 소유 워커에 중지 요청, heartbeat 만료 시 생존 상태 재확인. 워커 종료를 확인한 뒤에만 재시도와 슬롯 재배정. 종료 미확인 상태에서는 정리도 보류. 재시도에 `retry_of`와 시도 번호 기록, 활성 Dispatch의 보고만 수락. 같은 체인의 시작 실패 3회에서 자동 재시도 중단. 배정 포기는 사용자 요청으로 기록하고 워커 생존 상태는 계속 확인 | 중복 워커와 재시도 루프 방지. [OSS 조사](research/team-up-oss.md) |
| 사용자 인수 또는 keep-open 표시가 있는 세션·worktree 보존. team-up 소유 worktree는 경로·브랜치 일치와 워커 종료를 확인하고 미커밋 변경·미전달 결과·보존 요청이 없을 때 정리. DB는 명시적 삭제 요청까지 보존 | 사용자 작업과 재개 기록 보호. 외부 Codex 스레드의 데스크톱 실시간 인수는 미검증. [OSS 조사](research/team-up-oss.md) |
| team-up은 브랜치와 커밋 또는 diff, 검증 증거 전달. PR 전달은 사용자의 `ship-it` 명시 호출로 진행, 기본 브랜치 반영은 필수 `verify` 통과 후 진행. 병합이 선행 조건인 Task는 지정 기본 브랜치 반영을 확인한 뒤 시작 | 워커 완료와 기본 브랜치 반영을 별도 상태로 관리. [OSS 조사](research/team-up-oss.md) |
| 첫 구현 범위는 로컬 단일 Git 저장소와 team-up이 시작한 워커. 원격 실행·페더레이션·봇, 그룹 주소, 별도 전달 영수증, 기존 터미널 주입, 여러 Run 동시 감시는 범위에서 제외 | 단일 머신의 작업·질문·복구 기록은 SQLite와 Dispatch별 메시지로 보존. [OSS 조사](research/team-up-oss.md) |
| 현재 턴 번호와 일치하는 워커 보고만 수락 | 재개 전 턴의 늦은 보고가 현재 상태를 바꾸지 못하게 함 |
| 이벤트 커서는 `ack`로 저장. `wait`는 워커의 `question`, `done` 또는 시간 초과에 반환. 코디네이터의 `turn-ended`와 `exited`는 커서에 반영. 워커 종료는 호스트 작업의 완료 알림으로 확인 | 재시작 시 미확인 질문과 완료 보고를 다시 읽고 코디네이터가 직접 남긴 보고로 인한 깨우기를 방지 |
| 현재 턴의 실행 핸들이 없으면 `turn-ended`와 `exited`는 stderr에 경고하고 보고를 저장. `exited --start-failed`는 경고 생략 | `started` 누락을 알리면서 호스트에서 확인한 종료를 기록하고 슬롯을 해제할 수 있게 함 |
| 답변을 기다리는 Dispatch도 슬롯을 유지 | 사용자 결정 |
| 게이트 결정은 `approve`와 `reject`만 허용. 설명은 `--note`에 저장. 거절된 Task는 명시적으로 재승인할 때까지 예약 불가 | 같은 Task와 의존성을 유지하면서 사용자 결정을 다시 받을 수 있음. 승인 뒤에는 작업이 이미 시작됐을 수 있어 결정을 뒤집지 않음 |
| 실행 중 받은 지시는 그 턴의 `done` 이후에도 대기. 종료 확인 뒤 `begin`으로 같은 Dispatch, 세션, 체크아웃에서 새 턴 시작. 현재 턴의 완료 증거와 이전 턴 기록을 각각 보존. 완료된 턴의 미응답 질문은 `answer`로 닫지 않고 후속 요청은 `instruct`로 기록 | 슬롯과 worktree를 다시 확보하고 새 증거를 요구. 이전 턴의 늦은 보고나 답변이 새 턴을 바꾸지 못함 |
| `reserve --review-main`은 기본 체크아웃의 경로와 브랜치를 기록. Codex는 상태 디렉터리만 쓰도록 권한 프로필 적용. Claude는 Bash 샌드박스로 체크아웃 쓰기를 차단하고 상태 디렉터리 쓰기를 허용. 두 호스트 모두 재개에 같은 제한 적용. 코디네이터는 워커가 보고한 명령을 JSONL·도구 로그로 확인 | 사용자 미커밋 변경을 그 자리에서 읽고 질문 후 같은 세션에서 리뷰. 리뷰는 `changed_code: false`로 보고하고 기본 체크아웃은 정리 대상에서 제외. Claude의 `--db` 허가 접두사는 뒤 인자를 막지 못해 샌드박스 필수. Codex 워커는 실행하지 않은 명령의 실패를 보고함. [호스트 옵션 확인](research/team-up-candidate-exp.md) |
| 스키마 v3의 `init`은 기존 v2 DB를 보존하고 새 `--db` 경로를 요구 | v2의 자유 텍스트 게이트를 승인이나 거절로 자동 해석할 수 없음 |
| 시작 3회 실패 후 사용자 지시가 있을 때만 `retry --override`로 한 번 재시도 | 재시도 루프를 막고 예외 사용을 기록 |
| 영향받는 SQLite 버전이면 `init`과 `status` 출력에 WAL-reset 경고 표시 | 초기화는 허용하고 수정된 Python 빌드 사용을 안내. [SQLite 문서](https://www.sqlite.org/wal.html#the_wal_reset_bug) |
| Codex CLI 코디네이터는 대상 저장소에서 `codex -C "$repo" -s workspace-write --add-dir "$state_dir" -a on-request`로 실행하며 기존 DB 라이프사이클과 명령을 그대로 사용. Git 메타데이터 쓰기(`git worktree add/remove`, 스테이징, 커밋)와 워커 실행(`codex exec`, `claude -p`, 메인 체크아웃 리뷰 포함)은 샌드박스 밖 승인(`on-request`)으로 실행하되 워커 자체 샌드박스·`--allowedTools` 플래그는 유지하고 `--dangerously-bypass-approvals-and-sandbox`는 미사용. 워커는 장기 셸 세션(`exec_command`와 빈 `write_stdin` 폴링)으로 추적해 실제 종료 코드 확인 후 `exited` 기록. 턴 종료 후 재개 시 저장된 PID·시작 식별자와 출력·종료 파일로 생존 확인, 미확인 시 슬롯 유지 | `workspace-write`가 `.git`을 보호하고 네트워크를 차단하며 자식 프로세스가 부모 샌드박스를 상속하므로 권한 승격 필요. Codex는 자동 깨우기가 없고 데스크톱 사이드 세션·`Agent(isolation: worktree)`를 쓸 수 없음. 셸 세션 생존, 최대 셸 대기 시간, Codex 데스크톱·App Server 코디네이터, 자동 깨우기는 미검증 |
| `agy` 워커 지원 중단. 새 Task 생성·배정·재시도·새 턴 시작을 차단하고 자동 배정에서 기존 agy Task 제외. 사용자가 직접 시작하는 대화형 agy 코디네이터는 유지 | [Antigravity 약관 §6](https://antigravity.google/terms)과 [FAQ](https://antigravity.google/docs/faq)는 개인용 Google 계정 인증으로 외부 에이전트가 agy를 워커로 호출하는 용도를 제한. team-up은 인증 방식을 구분하지 않으므로 모든 agy 워커를 차단 |
| 기존 v4의 agy Task·Dispatch·이벤트·결과 보존. 조회와 중단 요청, 실제 종료 확인 후 `exited`, 결과 전달·정리는 허용. `stop`은 요청 기록이며 실제 종료는 호스트에서 확인. 남은 작업은 기존 워커 종료 확인 후 Claude·Codex Task로 새로 계획하며 자동 변환하지 않음 | 과거 이력과 미전달 결과를 보존하고 새 실행만 차단. v4 도입 당시 실행 실험은 [과거 agy 실험](research/team-up-agy-exp.md)에 보존 |
| `init`은 스키마 v3 DB를 제자리에서 v4로 마이그레이션하고, v3 DB에 다른 명령을 실행하면 `init` 실행을 안내. v2 이하 DB는 기존과 같이 새 `--db` 경로 요구 | 사용자 선택: 기존 Run 이력을 보존하면서 v4로 전환. 당시 추가한 `agy` 워커 유형은 과거 기록 호환용으로 유지 |
| Claude 워커용 `done --evidence-file <path>` 플래그 추가 및 해당 명령 접두사 허용 | Claude print 모드가 `--evidence "$(cat file)"` 명령 치환을 거부함 |

## 후보

| 항목 | 메모 |
|---|---|
| 속성 기반 UI 테스트 | 무작위 입력 아래 불변 조건 확인 |
| 성능 기준선 | 시작·입력·전환 시간 회귀 시 CI 실패, pstack `benchmark-checklist` |
| 지표 리포트 | 되돌림 비율, 검증 토큰 비중, PR 병합 시간 |
| 정기 점검 | `maintain-verification-skill`, `correct` 주기 실행 |
