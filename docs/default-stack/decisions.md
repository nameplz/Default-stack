# Decisions

## 확정

| 결정 | 근거 |
|---|---|
| Claude Code·Codex 호환 플러그인, 마켓플레이스 배포 | 두 도구를 모두 사용하고 공유할 예정 |
| 모든 스킬은 명시 호출 전용 | 워크플로 단계를 사용자가 직접 통제 |
| 기본 문서 경로는 `docs/default-stack/`, 기존 문서가 있으면 그것을 우선 재사용 | 중복 문서와 불필요한 구조 변경 방지 |
| `SKILL.md`는 호출 조건과 역할만, 실행 절차는 `references/` 공통 문서에 | 개별 스킬과 just-do-it이 같은 정의를 참조해 일관되게 동작 |
| just-do-it은 다른 스킬을 호출하지 않고 공통 워크플로 정의를 따라 실행 | 지침 중복 제거 |
| coffee-chat은 정형 인터뷰가 아닌 자유 대화 | 정리되지 않은 생각을 맥락과 함께 탐색 ([영감](https://x.com/karpathy/status/2079610838143623371?s=20), voice는 제외) || 아이디어 상태를 확정 / 후보 / 미결정 / 폐기로 구분 | 탐색 중인 생각과 결정을 섞지 않기 위해 |
| whats-wrong의 리서치 깊이는 프로젝트 규모에 비례 | 작은 기능마다 딥리서치는 과함 |
| Phase/Step은 사용자에게 실제로 동작하는 작은 기능 단위 | 파일·기술 계층 기준 분해 방지 |
| shall-we는 TDD (Red → Green → Refactor), 변경 코드 커버리지 80%를 점검 기준으로 | 커버리지는 목표가 아닌 점검 도구 |
| Step마다 커밋 | 단위별 검증·롤백 가능 |
| is-it-ok 판정은 통과 / 실패 / 미확인 | 증거 없는 PASS 금지 |
| shall-we ⇄ is-it-ok 루프 최대 3회 | 무한 수정 루프 방지 |
| just-do-it 본문은 `references/` 워크플로 문서를 순서대로 가리키는 얇은 지시. 스킬 자체는 호출하지 않음 | "얇은 지시"와 "스킬 직접 호출 금지"를 함께 만족 |
| 커버리지 측정: ① 프로젝트에 설정된 도구 → ② 없으면 언어 표준 도구(JS/TS `vitest --coverage`·`jest --coverage`, Python `pytest-cov`, Go `go test -coverprofile`, Rust `cargo llvm-cov`)로 lcov/Cobertura 리포트 생성 → ③ [diff-cover](https://github.com/Bachmann1234/diff_cover)로 변경 라인만 측정. 실행 불가 시 미확인 | "변경 코드에만 80%"를 언어와 무관하게 같은 방식으로 점검 |
| 플러그인 본체는 `plugin/` 하위, 마켓플레이스·README·LICENSE·설계 문서는 저장소 루트 ([구조](work/plugin-structure.md)) | 배포 대상과 저장소 메타 분리 |
| 매니페스트는 `plugin/plugin.json`(Codex)과 `plugin/.claude-plugin/plugin.json`(Claude Code) 두 개, `skills/`는 공유. 플러그인 `name`은 `default-stack` | Claude Code는 `.claude-plugin/`만 읽음. Codex CLI 0.164.0이 루트 `plugin.json`으로 설치·스킬 등록하는 것을 확인 ([Claude](https://code.claude.com/docs/en/plugins-reference), [Codex](https://developers.openai.com/plugins/build/plugins)) |
| `SKILL.md` frontmatter에 `disable-model-invocation: true`를 그대로 둠 | Codex CLI 0.164.0이 모르는 frontmatter를 경고 없이 무시함을 확인 |
| 스킬에서 공통 문서는 `../../references/<name>.md` 상대경로로 참조. `${CLAUDE_PLUGIN_ROOT}` 등 변수는 쓰지 않음 | Codex는 SKILL.md 절대경로를 모델에 제공하고 `references/`도 설치본에 복사됨. 스킬 본문의 변수는 치환하지 않음 (Codex CLI 0.164.0에서 확인). Claude Code 2.1.312에서도 스킬 기준 상대경로로 바로 읽음을 확인 |
| 마켓플레이스는 `.claude-plugin/marketplace.json`과 `.agents/plugins/marketplace.json` 두 개, 둘 다 `./plugin`을 가리킴 | 각 도구 전용 형식으로 따로 관리. Codex 공식 위치는 `.agents/plugins/` |
| 명시 호출 전용: Claude Code는 `SKILL.md` frontmatter `disable-model-invocation: true`, Codex는 `skills/<name>/agents/openai.yaml`의 `policy.allow_implicit_invocation: false` | 각 도구의 공식 설정 ([Codex skills](https://learn.chatgpt.com/docs/build-skills)). 호출은 Claude `/default-stack:<skill>`, Codex `$` 멘션 (등록 이름 `default-stack:<skill>`) |
| is-it-ok 검증 세션은 서브에이전트. 스킬 지시로 생성을 요청하고 입력(문제 정의, 관련 문서 경로, Git diff, 테스트 결과)을 명시적으로 전달 | Claude Code는 내장 서브에이전트, Codex는 스킬 지시로 위임 가능 ([Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)). Codex 문서에 부모 맥락 상속 여부가 없으므로 입력을 명시 전달해 양쪽 동작을 같게 함 |
| 작성자 `nameplz`(GitHub), MIT 라이선스, 스킬·references 지침은 영어 | 마켓플레이스 공유. 대화와 생성 문서는 사용자 언어 |
| `commands/`, `agents/`, `hooks/` 미사용. 스킬만으로 구성 | OpenAI 제출 시 비호환 항목 ([가이드](https://developers.openai.com/plugins/guides/submit-claude-plugin.md)) |

