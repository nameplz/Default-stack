# team-up 설계에 참고할 오픈소스 오케스트레이터

oh-my-symphony의 SQLite 배정권과 Git 검증, Gas Town의 영속 메시지와 알림, Agent Orchestrator의 결과 보고와 Nimbalyst의 부모 세션 알림을 team-up 설계와 비교했다. team-up은 단일 저장소의 SQLite에 배정·질문·검증 결과를 기록하는 현재 범위를 유지하고, 준비 작업 조회와 배정을 한 트랜잭션으로 묶는 편이 좋다. 질문은 DB 기록 후 같은 세션의 다음 턴에서 처리하고, 알림을 놓쳤을 때는 DB 조회로 복구한다. 배정권 만료는 워커 생존을 다시 확인할 신호로 사용한다. 워커의 완료 보고, 실제 종료, PR 병합은 각각 기록한다.

## 비교 대상

표의 항목과 **확인** 표시는 공식 소스·문서·릴리스 또는 이슈 본문을 읽어 확인한 내용이다. 이슈는 보고된 사례로 표시한다. **미검증**은 소스에서 해당 경로를 확인하지 못했거나 team-up 호스트에서 종단 간 확인이 남았다는 뜻이다. 최근 활동은 2026-11-21 조회 기준이며 날짜는 UTC다. 권고는 비교 결과를 team-up에 적용한 판단이다. 번호는 비교 요청의 순서를 따르며 2번은 결정 문서의 완료 보고 행, 3번은 질문 행, 4번은 깨우기 행에 해당한다. [결정 문서](../decisions.md)

| 프로젝트 | 라이선스 | 최근 활동 | 에이전트 | 워커 실행 | 상태 저장 |
|---|---|---|---|---|---|
| [oh-my-symphony][oms] | [Apache-2.0][oms-license] | [v0.29.0, 2026-10-28][oms-release] | Claude Code·Codex·Gemini·Pi 등, ACP 프로필 | 이슈별 branch/worktree. Codex는 stdio App Server, Claude는 턴마다 `claude -p --output-format stream-json`과 세션 ID로 재개. Python 3.12+, Git, PyYAML·httpx·watchdog·aiohttp·Textual 등. [실행 참조][oms-ref] · [의존성][oms-deps] | Markdown 카드 또는 Linear/Jira와 로컬 WAL SQLite. `runs`에 이슈·세션·PID·만료, `issue_flags`에 재시도·일시중지, 별도 `run_events`·`artifacts`·`approvals` 테이블. [DDL][oms-db] |
| [Gas Town][gt] | [MIT][gt-license] | [main 커밋, 2026-11-12][gt-commit] | Claude Code·Codex·Gemini·OpenCode·Copilot 등 | 역할별 대화형 tmux 세션. `gt sling`이 작업을 polecat의 worktree에 배정. Git·tmux·Beads·Dolt 및 Go로 만든 `gt` 사용. [설치·런타임][gt] | Beads의 로컬 Dolt DB에 작업·의존성·메일·병합 요청. `bd ready`로 차단 이유를 확인하고 `--claim`으로 배정. [영속 저장 방식][bd] |
| [Agent Orchestrator][ao] | [Apache-2.0][ao-license] | [main 커밋, 2026-11-21][ao-commit] | Claude Code·Codex 외 35개 이상을 공식 README에 명시 | Go 데몬이 Task별 브랜치와 worktree를 관리. TUI는 PTY/ConPTY 또는 tmux, Chat은 제공자 프로토콜 또는 ACP. [실행 구조][ao-arch] | 로컬 SQLite. `sessions`에 런타임 핸들·제공자 세션 ID·컨트롤러 세대·활동 상태, 별도 PR·CI·리뷰·알림·`change_log` 기록. [스키마][ao-arch] |
| [Nimbalyst][nim] | [MIT][nim-license] | [main 커밋, 2026-11-21][nim-commit] | Claude Code·Codex, OpenCode·GitHub Copilot(alpha) | Electron 앱이 작업 경로를 에이전트 제공자에 전달. Codex는 App Server. [앱 구성][nim-oss] · [권한 매핑][nim-perm] | 공식 소개의 PGLite와 소스의 SQLite 전환 경로. SQLite DDL에 `ai_sessions`, `worktrees`, `session_files`, `ai_agent_messages`와 PR 연결. **미검증** · 설치판별 기본 DB. [SQLite DDL][nim-db] · [PR 연결 DDL][nim-pr] |
| [LiteQueue][lq] | [MIT][lq-license] | [0.14, 2026-07-31][lq-release] | 호출자가 제공하는 워커 | Python 3.12+ 프로세스에서 `pop()` 호출. 별도 브로커나 런타임 의존성 없음. [패키지][lq-release] | 로컬 SQLite `Queue`에 메시지 ID·상태·시간·`claim_id`·`idempotency_key`. [claim 스키마][lq-claim] |
| [Huey][huey] | [MIT][huey-license] | [3.5.4, 2026-11-01][huey-release] | 등록한 Python 함수 | consumer가 프로세스·스레드·greenlet으로 실행. `SqliteHuey`의 기본 SQLite 경로는 표준 `sqlite3` 사용. [패키지][huey-release] · [consumer][huey-guide] | 로컬 SQLite의 큐·스케줄·결과 저장소. [저장 코드][huey-store] |

**확인 · 선정 메모.** Vibe Kanban은 Apache-2.0이며 2026-11-15 릴리스가 있다. 회사가 4월에 원격 서비스를 종료하고 로컬 워크스페이스의 커뮤니티 유지로 전환한다고 공지했다. 이번 표에서는 질문과 완료 보고 방식을 확인할 수 있는 Agent Orchestrator와 Nimbalyst를 우선했다. Claude Squad와 CCManager는 대화형 tmux·PTY 세션 관리가 중심이다. uzi의 확인된 최근 커밋은 2025-06-04다. Claude Flow는 Ruflo로 이전했으며, 공개 README는 메모리와 페더레이션을 포함한 범용 에이전트 오케스트레이션을 다룬다. [Vibe Kanban 릴리스][vibe-release] · [운영 전환 공지][vibe-sunset] · [Claude Squad](https://github.com/smtg-ai/claude-squad) · [CCManager](https://github.com/kbwo/ccmanager) · [uzi 커밋](https://github.com/devflowinc/uzi/commit/421685f65d66180152fb5f63128111ec12566ea5) · [Ruflo](https://github.com/ruvnet/ruflo)

**확인 · 큐 범위.** LiteQueue와 Huey의 호출 계약은 큐 메시지와 Python 함수다. Worktree 인수, 에이전트 질문·Codex `exec`, PR·사용자 결정 게이트는 호출자가 관리한다. Oban Lite는 예정 시간이 된 재시도를 활성화하고 종료 기록을 별도 정리한다. 선택 구성인 Lifeline은 오래된 실행을 시간으로 판정해 재배정하고, 시도 한도에 도달하면 폐기 상태로 기록한다. 실제로 실행 중인 작업도 다시 배정할 수 있다고 문서에 명시한다. [LiteQueue API][lq-release] · [Huey 가이드][huey-guide] · [Oban Lite 엔진][oban-lite] · [Lifeline][oban-rescue]

## 1. Task 의존성과 사용자 결정 게이트

- **확인** · oh-my-symphony는 카드의 `blocked_by`를 해석해 배정 순서를 정한다. `Human Review` 카드는 운영자가 확인할 수 있다. Gas Town의 Beads는 `bd ready --explain`으로 차단 사유를 보여 주고 `--claim`으로 원자적으로 가져간다. `human` 게이트는 수동 결정, `gh:pr` 게이트는 PR 이벤트를 기다린다. [스케줄러][oms-scheduler] · [운영자 확인][oms-ref] · [Beads 준비 작업][bd] · [게이트 사용례][bd-gates]
- **확인** · Agent Orchestrator는 작업 분해와 워커 시작을 조율하고 같은 자동화의 실행 중첩을 막는다. Nimbalyst는 부모 세션별 자식 실행 용량을 예약하며 입력 대기 카드를 표시한다. **미검증** · 두 프로젝트에서 Task DAG의 선행 완료 여부로 자동 배정하는 전체 경로. LiteQueue는 준비 메시지를 꺼내며 Huey는 함수 파이프라인을 지원한다. [자동화][ao-auto] · [세션 계층][nim-life] · [LiteQueue API][lq-release] · [Huey 가이드][huey-guide]
- **권고 · 변경** · Run 단위 의존성·결정 게이트와 현재 브리프 필드를 유지한다. 선행 조건과 슬롯을 읽고 활성 Dispatch를 만드는 일을 짧은 `BEGIN IMMEDIATE` 하나로 묶는다. 같은 Task에 열린 Dispatch가 하나만 있도록 부분 유일 인덱스를 둔다. 질문 때문에 프로세스가 끝난 Dispatch는 슬롯을 반환하고 Task에 대한 배정권을 유지한다. 순환 의존성과 존재하지 않는 선행 ID는 등록 시 거절한다. [SQLite 트랜잭션](https://sqlite.org/lang_transaction.html) · [부분 인덱스](https://sqlite.org/partialindex.html) · [oh-my-symphony 배정권][oms-reg]

## 2. 완료, 실패, 결과 증거

- **확인** · oh-my-symphony는 백엔드 턴 이벤트와 작업 카드 상태를 따로 읽고, 설정된 검증 명령이 실패하면 카드를 이전 단계로 되돌려 실패 내용을 남긴다. Gas Town은 `gt done`에서 브랜치와 병합 요청 기록을 남긴 뒤 세션을 종료한다. LiteQueue는 현재 `claim_id`가 맞는 완료·실패만 수락한다. Huey는 실행 결과와 예외를 저장하며 완료·오류·재시도 신호를 구분한다. [종료 처리][oms-exit] · [카드 검증][oms-ref] · [polecat 수명 주기][gt-life] · [LiteQueue claim][lq-claim] · [Huey 가이드][huey-guide]
- **확인** · Agent Orchestrator의 `ao report --done`은 세션을 닫지 않으며 `--artifact`로 산출물을 기록한다. Nimbalyst는 자식의 완료 보고를 부모에 전달하고, 세션 상태와 메시지 및 변경 파일 연결을 DB에 남긴다. **미검증** · Nimbalyst의 모든 완료를 검증 증거로 승인하는 계약. [워커 보고][ao-report] · [세션 계층][nim-life] · [세션 DDL][nim-db]
- **권고 · 유지** · `done --evidence`에서 성공·실패 보고, 결과 전문과 증거를 현재 Dispatch에 기록한다. 증거에는 검증 명령·종료 코드와 결과 위치를 담고, 코드 변경이 있으면 검증한 커밋 또는 diff를 식별할 수 있게 한다. 보고가 없으면 exit 0이나 `turn.completed` 뒤에도 Task는 미완료다. 결과가 이미 DB에 있으면 같은 보고의 재전송은 기존 기록을 반환한다. 질문만 남기고 종료한 정상 턴은 답변 대기 상태로 복구한다. [Codex 실행 방식](chatgpt-desktop-app.md) · [Claude 권한 거부 실험](team-up-db-write.md)

## 3. 워커 질문과 후속 지시

- **확인** · oh-my-symphony는 Codex App Server에서 `item/tool/requestUserInput`을 받아 빈 응답을 즉시 돌려준다. 확인한 경로에는 사용자에게 묻고 응답을 기다리는 단계가 없다. Gas Town은 `gt escalate`와 영속 메일로 지원 요청을 남기며, 이 Codex 실행 경로는 대화형 tmux 세션이다. Codex CLI 0.170.0의 `exec` 소스는 네이티브 질문 RPC를 거절한다. [Codex 어댑터][oms-codex] · [Gas Town 메일][gt-mail] · [Codex exec 소스][codex-exec]
- **확인** · Agent Orchestrator는 `ao report --needs-input`을 즉시 전달하며, Chat 후속 입력은 DB 큐에 넣어 턴 경계에서 전달한다. Nimbalyst는 질문 카드를 제공하고 Codex App Server의 승인 요청을 앱에 전달한다. **미검증** · 두 프로젝트에서 `codex exec`를 사용한 같은 턴 질문 왕복. [워커 보고][ao-report] · [Chat 큐][ao-arch] · [Nimbalyst README][nim] · [App Server 권한][nim-perm]
- **권고 · 유지** · 질문 ID와 Dispatch ID를 기록하고, 답변 저장 후 원래 worktree·세션 ID로 다음 턴을 시작한다. 미결 질문은 재시작 시 표시한다. 같은 질문에 대한 중복 답변이나 중복 재개는 상태 검사로 막는다. **미검증** · 셸 `ask` 대기와 App Server의 사용자 응답 왕복은 team-up 호스트에서 종단 간 확인이 남았다. [Codex 실행 방식](chatgpt-desktop-app.md) · [App Server 계약][codex-app]

## 4. 코디네이터 깨우기

- **확인** · oh-my-symphony는 실행 중인 서비스가 트래커를 주기 조회하고 백엔드 스트림을 받는다. 문서의 기본 조회 간격은 30초다. Gas Town은 데몬과 역할별 순찰을 두고, `gt nudge`로 살아 있는 tmux 세션을 깨운다. 대상이 죽으면 nudge는 유실된다. 재시작 뒤에도 필요한 요청은 Dolt 메일에 저장한다. [조회 설정][oms-ref] · [Gas Town 순찰][gt] · [메일과 nudge][gt-mail]
- **확인** · Agent Orchestrator는 SQLite의 `change_log`를 조회해 SSE로 반영한다. 활성 코디네이터가 없으면 보고는 DB에서 전달 대기 상태로 남는다. Nimbalyst는 부모를 자식 완료 보고로 깨운다. Huey는 consumer 조회 루프와 동기식 상태 신호를 제공한다. **미검증** · LiteQueue 자체의 외부 코디네이터 자동 깨우기. [변경 로그][ao-arch] · [보고 전달][ao-report] · [부모 세션][nim-life] · [Huey 가이드][huey-guide]
- **권고 · 유지** · DB에 상태 전이와 이벤트를 함께 커밋한 뒤 호스트 알림을 보낸다. `wait`는 실행 중인 코디네이터가 DB를 다시 조회하도록 하고, 시작 시와 대기 중에도 미처리 이벤트와 현재 상태를 확인한다. 동일 이벤트의 재처리가 배정을 늘리지 않도록 1번의 트랜잭션을 재사용한다. **미검증** · Claude Desktop Code 탭과 CLI의 자동 재개는 각각 확인이 필요하다. 확인 전에는 Run 명시 재개로 이어간다. [team-up 실행 방식](chatgpt-desktop-app.md) · [메일과 nudge][gt-mail]

## 5. 생존 확인, 중지, 재시도, 중복 배정

- **확인** · oh-my-symphony는 배정권을 `BEGIN IMMEDIATE`에서 확보하고 heartbeat로 연장한다. 기록된 백엔드 PID가 있으면 단순 만료 처리에서 제외한다. 정체 감시와 재시도·일시중지 처리가 있다. Gas Town의 설계 문서는 Witness의 세션 복구, 세 번 이상 반복된 크래시의 에스컬레이션, 최선형 중복 검사를 설명한다. LiteQueue는 만료 항목을 다시 준비 상태로 돌린다. 다음 배정이 `claim_id`를 올려 이전 워커의 완료를 차단한다. Huey는 SIGTERM이나 강제 종료 후 소비 중이던 작업의 자동 재시도를 보장하지 않는다. [배정권·PID][oms-reg] · [종료와 재시도][oms-exit] · [Gas Town 순찰 설계][gt-patrol] · [LiteQueue claim][lq-claim] · [Huey 종료 가이드][huey-guide]
- **확인** · Agent Orchestrator는 런타임과 프로세스를 따로 확인하며, 컨트롤러 세대와 실행 ID로 늦은 이벤트를 걸러낸다. Nimbalyst는 워커 시작 전에 부모별 용량을 예약하고, DB에 남은 대기·실행 요청을 한도에 포함한다. **미검증** · Nimbalyst의 범용 재시도 상한, LiteQueue 자체의 워커 종료와 횟수 제한. LiteQueue 만료 복구는 워커 프로세스 종료를 수행하지 않는다. Huey는 예외에 대한 재시도 횟수·지연을 설정할 수 있다. [런타임 감시][ao-arch] · [세션 계층][nim-life] · [LiteQueue 장기 실행][lq-claim] · [Huey 가이드][huey-guide]
- **권고 · 변경** · 외부 프로세스를 띄우기 전에 Dispatch를 예약한다. 시작 뒤 PID·프로세스 시작 식별자 또는 호스트 세션 ID를 기록한다. 예약과 식별자 저장 사이에 죽으면 시작 여부 미확인으로 남기고 재개 시 확인한다. heartbeat 만료나 중지 요청만으로 슬롯을 재배정하거나 worktree를 지우지 않는다. 종료가 확인되면 `retry_of`와 시도 번호를 기록하고 활성 Dispatch ID가 맞을 때만 보고를 받는다. 일시적 시작 실패에 지연을 두고 같은 체인에서 3회 실패하면 자동 시도를 멈춘다. 권한 거부·설치 누락은 원인이 바뀔 때까지 보류한다. 포기는 사용자 결정으로 기록하고 생존 상태는 계속 추적한다. [SQLite 배정권][oms-reg] · [LiteQueue claim][lq-claim]

## 6. worktree와 상태 정리, 사용자 인수

- **확인** · oh-my-symphony에는 종료 카드 정리 과정에서 이력을 검증하고, 결과를 보존하지 못하면 워크스페이스를 남기는 경로가 있다. Gas Town은 세션·worktree·병합 증거의 수명 주기를 구분한다. `gt done` 후 브랜치와 병합 요청을 보존하고 Witness와 Refinery가 정리를 맡는다. [종료 카드 정리][oms-clean] · [polecat 수명 주기][gt-life]
- **확인** · Agent Orchestrator는 세션 삭제에서 산출물을 기본 보존한다. Nimbalyst는 worktree 제거 시 연결을 비우고 세션 이력을 남긴다. LiteQueue는 완료 메시지의 정리 API를 제공한다. Huey는 기본 설정으로 조회한 결과를 저장소에서 제거한다. **미검증** · 두 오케스트레이터에서 team-up의 keep-open과 동일한 사용자 인수 계약. [세션 수명 주기][ao-arch] · [worktree 처리][nim-tree] · [LiteQueue API][lq-release] · [Huey 결과 API][huey-api]
- **권고 · 유지** · 사용자 인수·keep-open을 삭제 제외 조건으로 저장한다. 정리 직전에 소유권, 워커 종료, 경로와 브랜치 일치, dirty 상태, 전달 여부를 확인한다. 중지·정리·재배정이 경합하면 정리 권한을 한 번 확보하고 새 인수나 시작을 보류한다. 종료가 불확실하거나 예상 밖 worktree가 발견되면 재시작 시 표시한다. DB와 결과는 명시적 삭제까지 보존한다. **미검증** · 외부 Codex 스레드의 데스크톱 실시간 인수는 확인이 남아 있다. [고아·재시작 보고][gt-orphan] · [Codex 인수 범위](chatgpt-desktop-app.md)

## 7. PR과 병합 인계

- **확인** · Gas Town은 `gt done`에서 브랜치 푸시와 병합 요청을 남기고 Refinery가 별도 병합 큐를 처리한다. oh-my-symphony는 Done에서 설정에 따라 호스트가 로컬 병합을 수행하며 수동 PR 경로도 문서화한다. Beads의 관리자는 PR이 `MERGED`일 때만 후속 작업을 여는 게이트 운용 예를 설명한다. [Refinery][gt] · [호스트 병합][oms-ref] · [PR 게이트 논의][bd-gates]
- **확인** · Agent Orchestrator는 PR·CI·리뷰 사실을 기록하며 명시적 병합은 예상 head SHA를 확인한다. Nimbalyst는 worktree에 PR 번호·remote·URL을 묶고 검사 결과를 별도로 저장한다. **미검증** · Nimbalyst에서 그 기록을 필수 CI 병합 게이트로 강제하는 경로. [리뷰·병합 흐름][ao-review] · [PR 연결 DDL][nim-pr] · [검사 DDL][nim-db]
- **권고 · 유지** · team-up은 브랜치·커밋 또는 diff·검증 결과를 인계한다. PR 생성은 사용자 명시 `ship-it` 호출로 진행한다. 필수 `verify`를 통과하고 지정한 기본 브랜치에 필요한 변경이 반영됐을 때만 병합 선행 Task를 연다. [저장소 결정](../decisions.md) · [호스트 검증 근거][oms-sandbox]

## 8. 알려진 문제와 첫 구현 범위

- **확인 · SQLite 잠금.** Huey #925는 새 DB를 여러 프로세스가 동시에 WAL로 열 때 timeout이 있어도 잠금 오류가 난 사례다. Huey 3.5.2에 수정이 기록됐다. team-up의 로컬 실험에서도 동시 WAL 전환에서 누락이 있었고 선초기화 후에는 재현되지 않았다. SQLite WAL에서도 쓰기는 한 번에 하나다. 코디네이터가 WAL·스키마를 먼저 설정하고 워커는 연결 시 `busy_timeout`을 적용한다. Agent Orchestrator #6219에는 보존 기간이 지난 이벤트를 지우는 쿼리가 단일 쓰기 연결을 오래 막아 훅과 종료 기록이 지연되거나 유실됐다는 보고가 있다. Git·프로세스 대기·로그 수집은 쓰기 트랜잭션 밖에 둔다. [Agent Orchestrator #6219][ao-lock] · [Huey #925][huey-lock] · [Huey 변경 이력][huey-changelog] · [SQLite WAL][wal] · [로컬 DB 실험](team-up-db-write.md)
- **확인 · SQLite WAL-reset 결함.** SQLite는 복수 연결의 쓰기·체크포인트가 겹칠 때 드물게 DB 손상이 가능한 결함을 공개했다. 수정판은 3.51.3 이상 또는 3.44.6·3.50.7 백포트다. 이 조사에서 PATH의 `python3`은 SQLite 3.51.1을 보고했다. team-up의 동시 WAL 쓰기 검증에는 실제 워커 Python의 SQLite 버전과 수정 포함 여부를 확인한다. **미검증** · 워커 호스트별 빌드 버전과 수정 적용 여부. [SQLite WAL-reset 공식 문서][wal]
- **확인 · 고아 worktree와 잘못된 재사용.** Gas Town #1255는 재시작 뒤 고아화된 작업이 멈춘 사례, #2621은 기존 worktree 재사용 시 예상 브랜치와 실제 브랜치가 어긋난 사례다. Nimbalyst는 Git 생성 후 DB 등록 실패와 메모리 정리 큐 유실을 기록했고, Agent Orchestrator #5598은 워커 정리가 활성 코디네이터 worktree를 삭제한 사례다. 배정을 시작·재개하기 전에 worktree 경로와 브랜치를 대조하고, DB와 Git 목록의 불일치는 사람이 확인할 수 있게 남긴다. [재시작 보고][gt-orphan] · [브랜치 불일치 보고][gt-branch] · [Nimbalyst 정리 문서][nim-clean] · [코디네이터 worktree 삭제 보고][ao-clean]
- **확인 · 알림 유실·중복.** Gas Town 문서는 죽은 세션에 보낸 nudge 유실을 명시한다. #3972에는 완료된 convoy 알림이 데몬에서 반복 발송된 사례가 있다. Vibe Kanban #3227은 연결 재개에 실패해 완료 갱신이 도착하지 않은 사례다. 이벤트를 커밋한 직후 깨우기를 놓친 경우와, 같은 알림을 두 번 받은 경우 모두에서 DB로 복구할 수 있어야 한다. [메일과 nudge][gt-mail] · [완료 알림 반복 보고][gt-notify] · [Vibe Kanban 연결 중단 보고][vibe-stream]
- **확인 · 결과와 프로세스 종료의 불일치.** Vibe Kanban #2495에는 Claude가 성공 결과를 출력한 뒤에도 stdin을 기다려 실행 중 기록이 남은 사례가 있다. 결과 보고를 저장한 뒤 프로세스 종료를 별도로 확인한다. [Vibe Kanban #2495][vibe-exit]
- **확인 · Codex 샌드박스와 Git 경로.** openai/codex #23661에는 `--add-dir`을 줘도 linked worktree의 index lock이 읽기 전용이었던 환경이 보고됐다. oh-my-symphony는 worktree index와 공통 object DB가 서로 다른 쓰기 경로임을 기록하고 Git 이력 검증을 호스트로 옮겼다. 별도 SQLite 경로 쓰기, 새 blob을 쓰는 Git 작업, 사용자 인수는 각각 확인한다. Claude `-p`의 `permission_denials`도 완료 판정에 반영한다. [Codex #23661][codex-git] · [oh-my-symphony의 샌드박스 검증][oms-sandbox] · [로컬 DB 실험](team-up-db-write.md)
- **확인 · 상태 스키마 갱신.** LiteQueue 문서는 구버전 워커가 새 배정권 검사를 우회할 수 있어 업그레이드 중 워커를 멈추고 WAL을 포함해 백업하도록 안내한다. team-up도 실행 중인 워커가 쓰는 DB를 마이그레이션할 때 스크립트와 스키마 버전의 호환성을 확인해야 한다. oh-my-symphony #58은 Linear 스키마 변경으로 배정 조회가 중단된 사례이며 v0.22.0에서 수정됐다. [LiteQueue 마이그레이션][lq-claim] · [Linear #58][oms-linear]
- **권고 · 유지** · 첫 구현은 단일 로컬 Git 저장소와 team-up이 시작한 워커에 한정한다. Git 작업공간, DB, 프로세스 수명 주기를 복구하는 데 필요한 정보는 SQLite와 Dispatch 메시지로 충분하다. Gas Town의 주소·순찰·페더레이션이나 oh-my-symphony의 외부 보드 연동은 현재 범위 밖이다. 참고한 큐의 소유권 검사와 재시도 규칙을 표준 라이브러리로 구현하는 설계를 권한다. [설치·운영 범위][gt] · [oh-my-symphony 의존성][oms-deps] · [저장소 결정](../decisions.md)

[oms]: https://github.com/cskwork/oh-my-symphony
[oms-license]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/LICENSE
[oms-release]: https://github.com/cskwork/oh-my-symphony/releases/tag/v0.29.0
[oms-ref]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/docs/reference.md
[oms-deps]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/pyproject.toml
[oms-db]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/orchestrator/migrations.py
[oms-scheduler]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/orchestrator/scheduler.py
[oms-reg]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/orchestrator/run_registry.py
[oms-exit]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/orchestrator/worker_exit.py
[oms-codex]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/backends/codex.py
[oms-clean]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/src/symphony/orchestrator/retry_reconcile.py
[oms-sandbox]: https://github.com/cskwork/oh-my-symphony/blob/v0.29.0/docs/llm-wiki/worktree-git-sandbox.md
[gt]: https://github.com/gastownhall/gastown
[gt-license]: https://github.com/gastownhall/gastown/blob/main/LICENSE
[gt-commit]: https://github.com/gastownhall/gastown/commit/94cc82289d2ead275a62e1db4ef1d4ada4a1f98e
[gt-life]: https://github.com/gastownhall/gastown/blob/main/docs/concepts/polecat-lifecycle.md
[gt-mail]: https://github.com/gastownhall/gastown/blob/main/docs/design/mail-protocol.md
[gt-patrol]: https://github.com/gastownhall/gastown/blob/main/docs/design/polecat-lifecycle-patrol.md
[gt-orphan]: https://github.com/gastownhall/gastown/issues/1255
[gt-branch]: https://github.com/gastownhall/gastown/issues/2621
[gt-notify]: https://github.com/gastownhall/gastown/issues/3972
[bd]: https://github.com/gastownhall/beads/blob/main/docs/reference/faq.md
[bd-gates]: https://github.com/gastownhall/beads/discussions/2164
[lq-claim]: https://github.com/litements/litequeue/blob/main/docs/message_claim_ids.md
[huey-guide]: https://github.com/coleifer/huey/blob/master/docs/guide.rst
[huey-lock]: https://github.com/coleifer/huey/issues/925
[huey-changelog]: https://github.com/coleifer/huey/blob/master/CHANGELOG.md
[wal]: https://sqlite.org/wal.html
[codex-exec]: https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/exec/src/lib.rs
[codex-app]: https://learn.chatgpt.com/docs/app-server
[codex-git]: https://github.com/openai/codex/issues/23661
[ao]: https://github.com/OrchestratorInc/agent-orchestrator
[ao-license]: https://github.com/OrchestratorInc/agent-orchestrator/blob/main/LICENSE
[ao-commit]: https://github.com/OrchestratorInc/agent-orchestrator/commit/591a985c93e905ed846f748a954607ecc2882b8c
[ao-arch]: https://github.com/OrchestratorInc/agent-orchestrator/blob/main/docs/architecture.md
[ao-report]: https://github.com/OrchestratorInc/agent-orchestrator/blob/main/backend/internal/skillassets/using-ao/commands/report.md
[ao-review]: https://github.com/OrchestratorInc/agent-orchestrator/blob/main/frontend/src/docs/content/guides/review-loop.mdx
[ao-auto]: https://github.com/OrchestratorInc/agent-orchestrator/blob/main/frontend/src/docs/content/configuration/lifecycle-automation.mdx
[ao-lock]: https://github.com/OrchestratorInc/agent-orchestrator/issues/6219
[ao-clean]: https://github.com/OrchestratorInc/agent-orchestrator/issues/5598
[nim]: https://github.com/Nimbalyst/nimbalyst
[nim-license]: https://github.com/Nimbalyst/nimbalyst/blob/main/LICENSE
[nim-commit]: https://github.com/Nimbalyst/nimbalyst/commit/813acfb4ce14e3432c263e2173c23c4a130f7441
[nim-oss]: https://nimbalyst.com/open-source/
[nim-tree]: https://github.com/Nimbalyst/nimbalyst/blob/main/docs/WORKTREES.md
[nim-life]: https://github.com/Nimbalyst/nimbalyst/blob/main/docs/SESSION_HIERARCHY.md
[nim-perm]: https://github.com/Nimbalyst/nimbalyst/blob/main/docs/AGENT_PERMISSIONS.md
[nim-db]: https://github.com/Nimbalyst/nimbalyst/blob/main/packages/electron/src/main/database/sqlite/schemas/0001_initial.sql
[nim-pr]: https://github.com/Nimbalyst/nimbalyst/blob/main/packages/electron/src/main/database/sqlite/schemas/0009_worktree_pr_linkage.sql
[nim-clean]: https://github.com/Nimbalyst/nimbalyst/blob/main/docs/WORKTREE_RELIABILITY_IMPROVEMENTS.md
[lq]: https://github.com/litements/litequeue
[lq-license]: https://github.com/litements/litequeue/blob/main/LICENSE
[lq-release]: https://pypi.org/project/litequeue/0.14/
[huey]: https://github.com/coleifer/huey
[huey-license]: https://github.com/coleifer/huey/blob/master/LICENSE
[huey-release]: https://pypi.org/project/huey/3.5.4/
[huey-store]: https://github.com/coleifer/huey/blob/master/huey/storage.py
[oban-lite]: https://github.com/oban-bg/oban/blob/v2.24.2/lib/oban/engines/lite.ex
[vibe-release]: https://github.com/BloopAI/vibe-kanban/releases/tag/v0.1.46.1794744340
[vibe-sunset]: https://www.vibekanban.com/blog/shutdown
[vibe-stream]: https://github.com/BloopAI/vibe-kanban/issues/3227
[vibe-exit]: https://github.com/BloopAI/vibe-kanban/issues/2495
[oms-linear]: https://github.com/cskwork/oh-my-symphony/issues/58
[oban-rescue]: https://oban.hexdocs.pm/Oban.Lifeline.html
[huey-api]: https://github.com/coleifer/huey/blob/master/huey/api.py
