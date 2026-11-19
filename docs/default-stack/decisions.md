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

## 후보

| 항목 | 메모 |
|---|---|
| 속성 기반 UI 테스트 | 무작위 입력 아래 불변 조건 확인 |
| 성능 기준선 | 시작·입력·전환 시간 회귀 시 CI 실패, pstack `benchmark-checklist` |
| 지표 리포트 | 되돌림 비율, 검증 토큰 비중, PR 병합 시간 |
| 정기 점검 | `maintain-verification-skill`, `correct` 주기 실행 |
