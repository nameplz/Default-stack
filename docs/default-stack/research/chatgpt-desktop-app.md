# ChatGPT 데스크톱 앱을 Codex 워커 호스트로 쓸 수 있는가

`team-up`의 기본 실행기는 팀이 만든 Git worktree에서 실행하는 `codex exec --json`을 권장한다. Claude와 Codex 코디네이터 모두 워커를 시작하고, 스트림과 프로세스 종료로 결과를 받고, 같은 세션에 후속 지시를 보낼 수 있다. 작업 턴 안에서 질문하고 답을 기다려야 한다면 app-server 클라이언트가 더 적합하다. 외부에서 시작한 워커의 앱 사이드바 자동 표시와 실행 중 인수인계는 미검증이다. Claude Code 세션은 별도 런타임에서 실행해야 한다.

**로컬 확인 · 2026-11-21 (KST)** — `/Applications/ChatGPT.app`의 `Info.plist`는 `26.1111.21308` (빌드 `27194`), 번들 Codex CLI는 `0.169.0-alpha.11.1`, PATH의 CLI는 `0.170.0`이다. 아래 로컬 확인은 버전, 명령 도움말, /tmp에 생성한 기본·실험 JSON Schema, 파일 이름에 한정한다. [공식 변경 이력][changelog]에는 앱 `26.1111`과 11월 20일자 CLI `0.171.0`도 실려 있다.

## 기능과 근거

| 기능 | 가능 여부 | 방법 | 근거 |
| --- | --- | --- | --- |
| 앱 로컬 스레드·병렬 실행 | 가능 | Codex 모드에서 프로젝트별 채팅을 병렬로 실행한다. 앱의 네이티브 서브에이전트 진행도 열람할 수 있다. 별도 로컬·worktree 백그라운드 스레드 조정은 앱 `26.527`에 기록돼 있다. | 문서화 · [macOS 출시, 2026-02-02][launch], [변경 이력][changelog], [서브에이전트][subagents] |
| 앱 내부의 스레드 간 조정 | 조건부 가능 | 앱 내부 Codex에 노출되는 `codex_app` 도구로 `create_thread`, `read_thread`, `send_message_to_thread`, `wait_threads` 등을 호출할 수 있다. 앱 내부 코디네이터의 후보다. 외부 CLI에서 이 앱 도구를 호출하는 공개 계약과 현재 설치의 노출 여부는 미검증이다. | 문서화 · [출시를 확인한 OpenAI 기여자 답변][cross], [도구 노출 회귀 보고][toolissue] |
| 앱 관리 worktree | 가능 | 새 채팅에서 Worktree 선택. 기본 경로는 `$CODEX_HOME/worktrees` (기본 `~/.codex/worktrees`), Settings에서 변경 가능. 앱에 연결된 worktree는 채팅에서 보고 Local↔Worktree Handoff 가능 (`26.303`). 자동 정리 기본 보관 개수는 15개다. | 문서화 · [Worktrees][worktrees], [변경 이력][changelog] |
| Cloud 작업 | 가능 | 앱의 Cloud 모드 또는 `codex cloud exec --env ENV_ID`, `status`, `list`, `diff`, `apply`. 원격 실행 환경이므로 이 Mac의 Git 공통 디렉터리에 있는 DB를 직접 쓰는 워커에는 부적합하다. | 로컬 확인 · CLI 도움말. 문서화 · [실행 환경][modes], [CLI][cli] |
| 알림·리뷰·diff | 가능 | 턴 완료, 질문, 권한 요청에 OS 알림을 설정할 수 있다. 앱에서 로컬 변경 diff·인라인 코멘트·`/review`를 사용하고, 통합 앱에는 diff 인라인 편집과 PR 리뷰 패널이 추가됐다. | 문서화 · [알림][notifications], [코드 리뷰][review], [통합 앱 출시, 2026-07-16][unified] |
| `codex app [PATH]`·딥링크 | GUI 열기 가능 | macOS에서 앱과 작업 경로를 연다. `codex://threads/<thread-id>`는 기존 채팅을 열고, `codex://threads/new?prompt=…&path=…`는 입력창을 채운다. 후자의 전송은 UI에서 한다. | 로컬 확인 · `app --help`. 문서화 · [CLI][cli], [앱 명령][links] |
| 외부에서 스레드 생성·제어 | 가능 | `codex app-server --listen stdio://`로 자식 프로세스와 JSON-RPC를 연결한다. `initialize` → `initialized` → `thread/start`와 `turn/start`. 기존 스레드는 `thread/resume`. 유휴 상태의 후속 입력은 `turn/start`, 실행 중 입력은 `turn/steer`와 `expectedTurnId`, 중단은 `turn/interrupt`. | 로컬 확인 · CLI와 앱 번들 스키마. 문서화 · [App Server][rpc] |
| 결과 수신·폴링 없는 완료 | 가능 | App Server의 `item/agentMessage/delta`, `item/completed`, `turn/completed`를 스트리밍으로 수신하고 최종 턴 상태를 확인한다. 저장된 결과는 `thread/read`, `thread/turns/list`, `thread/items/list`로 조회한다. exec에서는 JSONL의 `thread.started`, `item.completed`, `turn.completed`/`turn.failed`와 종료 코드를 받는다. CLI `notify`는 외부 프로그램에 `agent-turn-complete`를 보낼 수 있다. | 로컬 확인 · 스키마와 `exec --help`. 문서화 · [App Server][rpc], [비대화형 모드][exec], [알림][notifications] |
| 공유 daemon·proxy | 가능 | `codex app-server daemon`은 로컬 서버 수명주기를 관리하고 `codex app-server proxy [--sock PATH]`는 실행 중인 제어 소켓에 stdio를 연결한다. 직접 서버는 Unix 소켓과 실험적 WebSocket도 제공한다. 앱이 현재 사용하는 서버와 CLI 기본 소켓이 동일한지는 미검증이다. `codex exec --remote`는 CLI `0.171.0` 변경 사항이며 설치된 `0.170.0`의 exec 도움말에는 없다. | 로컬 확인 · 도움말과 `~/.codex`의 `app-server-control`, `app-server-daemon` 이름. 문서화 · [CLI][cli], [App Server][rpc], [변경 이력][changelog] |
| `codex remote-control` | 가능 | `start`, `stop`, `pair`는 원격 제어가 켜진 daemon과 기기 페어링을 위한 명령이다. 공식 클라이언트에서 호스트 작업을 시작·열람·조정할 수 있고, 데스크톱 앱에는 별도의 SSH 프로젝트 연결도 있다. | 로컬 확인 · 도움말. 문서화 · [CLI][cli], [원격 연결][remote] |
| `codex queue`·`codex agents` | 가능 | `queue --thread ID --message TEXT`로 기존 세션에 후속 메시지를 예약한다. `--resume`은 로컬 daemon 또는 지정한 원격 서버에서 언로드된 세션의 재개를 시도하며, 재개에 실패해도 큐 명령은 성공할 수 있다. 실험 스키마에 `thread/queue/add`·`thread/queue/start`가 있다. `agents`는 세션 검색·시작·전환·중단용 대화형 TUI다. | 로컬 확인 · 도움말 및 두 바이너리의 실험 스키마. 문서화 · [CLI][cli], [0.149.0 변경 이력][changelog] |
| `codex exec --worktree`·`exec resume` | 가능 | `--worktree`는 로컬의 새 관리 worktree에서 시작한다. 0.170.0 구현은 데스크톱과 같은 기본·설정 루트를 써서 `<root>/<id>/<repo>`에 생성하고 CLI 자체의 자동 정리는 끈다. `exec resume ID`는 기존 스레드에서 새 턴을 실행하므로 기존 체크아웃을 재사용한다. `resume --help`에도 `--worktree`가 나오지만 신규·fork용이다. | 로컬 확인 · 도움말. 문서화 · [CLI][cli], [관리 worktree 설정 소스][wtsettings], [경로 소스][wtpaths], [exec worktree PR][wtpr] |
| 공유 세션 저장소·앱 표시 | 저장 형식 공유, 자동 표시는 미검증 | 기본 `$CODEX_HOME=~/.codex`에서 `sessions/`, `session_index.jsonl`, `state_5.sqlite`, `thread_history_1.sqlite` 등의 이름을 확인했다. CLI 대화형 스레드→앱은 `/app`이 문서화돼 있고, CLI 선택기는 `codex resume --include-non-interactive`를 제공한다. App Server 목록의 기본 `sourceKinds`는 `cli`·`vscode`이며, `exec`·`appServer`를 명시 조회할 수 있다. CLI exec/외부 RPC→앱 사이드바·관리 worktree 연결, 앱→CLI의 개별 세션 재개 및 실행 중 공유는 사용자·Codex 홈·제공자·서버가 맞는 환경에서 검증할 사항이다. | 로컬 확인 · 이름과 도움말. 문서화 · [저장 경로][store], [CLI /app][cmds], [App Server][rpc]. 미검증 · 설치 앱의 실제 노출·양방향 인수 |
| `--thread-source` | 분류 가능 | exec 신규·fork 스레드의 `threadSource` 라벨이며 resume은 기존 라벨을 유지한다. 목록의 `sourceKinds`와 별도 필드다. 앱 노출을 보장하는 옵션으로 볼 근거는 없다. | 로컬 확인 · 도움말·스키마. 문서화 · [CLI][cli], [App Server][rpc] |
| 턴 중 질문·응답 | App Server에서 조건부 가능 | 기능이 노출된 턴에서 서버 요청 `item/tool/requestUserInput`의 `isBlocking`과 `threadId`·`turnId`를 보고 같은 JSON-RPC 요청 ID로 `answers`를 응답하면 해당 턴이 이어진다. Plan 모드는 질문을 지원하며 Default 모드의 노출은 기능 설정에 좌우된다. `exec` 구현은 이 서버 요청을 거절하므로 일반 질문을 결과로 남긴 후 다음 턴에 답한다. | 로컬 확인 · 두 바이너리의 질문/응답 스키마. 문서화 · [App Server][rpc], [Plan 모드][plan], [exec 소스][execsrc]. 미검증 · 설치 환경에서의 왕복 |
| Claude 워커 표시·호스팅 | 네이티브 지원 미확인 | 앱의 Import는 Claude Code/Cowork의 설정·프로젝트·최근 작업을 Codex로 가져온다. 통합 터미널에서 설치된 CLI를 실행하는 것은 가능하지만 Claude 런타임을 앱의 Codex 스레드로 등록·제어하는 공개 API는 찾지 못했다. | 문서화 · [가져오기][import], [통합 터미널][terminal]. 미검증 · 외부 런타임의 네이티브 연동 |
| 인증·샌드박스·플랫폼 | 조건부 | exec는 저장된 CLI 인증을 재사용하거나 `CODEX_API_KEY`를 사용할 수 있다. ChatGPT 플랜·워크스페이스 정책이 가용성을 결정한다. `--sandbox workspace-write --add-dir <절대경로>`로 추가 쓰기 루트를 요청할 수 있다. CLI는 macOS·Linux·Windows, 데스크톱 앱은 macOS(Apple Silicon)·Windows 및 Linux 프리뷰를 제공한다. | 로컬 확인 · 도움말. 문서화 · [인증][auth], [비대화형 모드][exec], [샌드박스][sandbox], [데스크톱][desktop], [Linux 프리뷰][linux] |
| 동시 실행 한도 | 병렬 가능, 앱 고정 한도 미확인 | `agents.max_concurrent_threads_per_session`은 한 세션에서 생성한 서브에이전트 수 설정이다. 독립 로컬 워커의 동시 실행은 별도로 관리하고 플랜/제공자 사용량 제한을 고려한다. 앱의 worktree 보관 수는 실행 제한과 별개다. | 문서화 · [설정][config], [인증][auth], [Worktrees][worktrees]. 미검증 · 독립 실행과 설치 앱의 실효 한도 |

## team-up 적용

| 요구 | 권장 방식 |
| --- | --- |
| 시작과 worktree 격리 | 코디네이터가 워커마다 `git worktree add`로 체크아웃과 브랜치를 준비하고 `codex exec --json -C "$worktree" --sandbox workspace-write --add-dir "$db_dir" -`를 감독 프로세스에서 실행한다. 작업 프롬프트는 stdin으로 보내고 `thread.started`의 ID와 worktree 경로를 DB에 기록한다. 같은 Git 수명주기를 Claude에도 적용한다. |
| 후속 지시 | 프로세스가 끝난 뒤 동일한 worktree와 권한으로 `codex exec -C "$worktree" --sandbox workspace-write --add-dir "$db_dir" resume --json "$thread_id" -`. 자동화는 정확한 ID를 사용한다. 사용자 인수와 재개를 위해 세션을 디스크에 저장한다. |
| 결과와 코디네이터 깨우기 | 감독 프로세스가 JSONL 최종 메시지, 종료 이벤트와 종료 코드를 받아 DB 상태를 갱신한 뒤 대기 중인 코디네이터에 전달한다. 턴 성공과 작업 완료를 구분한다. 이미 반환한 코디네이터 채팅을 다시 깨우려면 그 호스트에서 검증된 메시지 경로가 필요하다. Codex의 공유 daemon 세션이라면 `queue --resume`이 후보다. |
| 작업 중 질문 | 기본 경로는 질문을 구조화된 결과로 저장하고 턴을 끝낸 뒤, 답이 도착하면 같은 세션을 재개한다. 같은 턴에서 대기해야 한다면 팀이 소유한 App Server 연결에서 질문 RPC에 응답한다. |
| 사용자 관찰·인수 | 실행 중에는 감독 프로세스가 받은 이벤트를 표시한다. 종료 후 `codex resume "$thread_id"`로 터미널 인수를 제공한다. 앱 딥링크와 공유 서버를 통한 실시간 인수는 상호운용이 검증되면 추가한다. |

코디네이터는 `git rev-parse --path-format=absolute --git-common-dir` 결과를 `realpath`로 정규화한 뒤 해시해 `<repo-id>`를 구한다. DB 경로는 `~/.local/state/default-stack/team-up/<repo-id>.db`이며 `db_dir`는 그 상위 디렉터리다. 샌드박스가 `.git`과 linked worktree의 `gitdir`을 보호하므로 상태 DB는 Git 메타데이터 밖에 둔다. 워커가 DB와 SQLite 보조 파일을 쓰려면 `db_dir`에 대한 쓰기 권한이 필요하다. CLI에서는 `--add-dir "$db_dir"`를 사용한다. App Server에서는 `turn/start`의 `sandboxPolicy`를 `workspaceWrite`로 지정하고 `writableRoots`에 `db_dir`를 요청할 수 있다. 정책이 쓰기를 막으면 워커 요청을 받은 코디네이터가 DB에 기록하는 방식이 대안이다. 워커의 직접 쓰기가 필수인 실행 경로는 출시 전 쓰기 검증이 필요하다. [team-up DB 쓰기 검증](team-up-db-write.md), [App Server][rpc], [샌드박스][sandbox], [linked worktree 권한 보고][gitissue]

## 남은 확인

- **미검증** · 같은 호스트에서 CLI exec와 RPC로 각각 만든 저장 스레드가 사이드바·검색·딥링크 어디에 표시되는가. CLI 관리 worktree와 팀이 만든 worktree 각각의 프로젝트 연결, 새로고침 후 표시, 반대 방향 재개, 실행 중 동일 스레드 인수를 확인해야 한다. 공개 이슈에는 exec 스레드가 앱 재시작 후 사라지거나 고정되지 않는 사례가 있다. [exec 스레드 표시 보고][execissue], [worktree 사이드바 보고][sidebarissue]
- **미검증** · 앱과 외부 클라이언트가 같은 daemon에 붙을 때 활성 턴 이벤트·질문 응답이 어느 연결로 전달되는가. `queue --resume`으로 유휴 코디네이터가 실제로 새 턴을 실행하는지와 App Server 질문의 모드별 가용성도 확인해야 한다.
- **확인됨** · linked worktree의 Codex 워커가 `--add-dir "$db_dir"`로 SQLite 트랜잭션과 보조 파일 생성을 수행한다. 결과는 [team-up DB 쓰기 검증](team-up-db-write.md) 참고.
- **미검증** · 독립 워커 상한과 계정·워크스페이스별 사용량.

[changelog]: https://learn.chatgpt.com/docs/changelog
[launch]: https://openai.com/index/introducing-the-codex-app/
[unified]: https://help.openai.com/en/articles/6825453-chatgpt-for-developers
[subagents]: https://learn.chatgpt.com/docs/agent-configuration/subagents
[cross]: https://github.com/openai/codex/issues/14923
[toolissue]: https://github.com/openai/codex/issues/46653
[worktrees]: https://learn.chatgpt.com/docs/environments/git-worktrees
[modes]: https://learn.chatgpt.com/docs/environments/modes
[cli]: https://learn.chatgpt.com/docs/cli/reference
[notifications]: https://learn.chatgpt.com/docs/notifications
[review]: https://learn.chatgpt.com/docs/code-review
[links]: https://learn.chatgpt.com/docs/app/commands#tasks
[rpc]: https://learn.chatgpt.com/docs/app-server
[exec]: https://learn.chatgpt.com/docs/non-interactive-mode
[remote]: https://learn.chatgpt.com/docs/remote-connections
[wtsettings]: https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/worktree/src/settings.rs
[wtpaths]: https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/worktree/src/paths.rs
[wtpr]: https://github.com/openai/codex/pull/42652
[store]: https://learn.chatgpt.com/docs/reference/troubleshooting
[cmds]: https://learn.chatgpt.com/docs/developer-commands?surface=cli
[plan]: https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/collaboration-mode-templates/templates/plan.md
[execsrc]: https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/exec/src/lib.rs
[import]: https://learn.chatgpt.com/docs/import
[terminal]: https://learn.chatgpt.com/docs/integrated-terminal
[auth]: https://learn.chatgpt.com/docs/auth
[sandbox]: https://learn.chatgpt.com/docs/agent-approvals-security
[desktop]: https://learn.chatgpt.com/docs/app
[linux]: https://learn.chatgpt.com/docs/linux/linux-app
[config]: https://learn.chatgpt.com/docs/config-file/config-reference
[gitissue]: https://github.com/openai/codex/issues/23661
[execissue]: https://github.com/openai/codex/issues/45791
[sidebarissue]: https://github.com/openai/codex/issues/58002
