# 플러그인 구조

관련: [decisions.md](../decisions.md), [vision.md](../vision.md)

## 디렉터리

```
default-stack/                      # 저장소 루트 = 마켓플레이스 루트
├── .agents/plugins/
│   └── marketplace.json            # Codex 마켓플레이스 → ./plugin
├── .claude-plugin/
│   └── marketplace.json            # Claude Code 마켓플레이스 → ./plugin
├── plugin/                         # 플러그인 루트 (배포 대상)
│   ├── plugin.json                 # Codex 매니페스트 (portable)
│   ├── .claude-plugin/
│   │   └── plugin.json             # Claude Code 매니페스트
│   ├── skills/
│   │   └── <skill>/                # coffee-chat, whats-wrong, shall-we, is-it-ok, just-do-it
│   │       ├── SKILL.md            # disable-model-invocation: true
│   │       └── agents/openai.yaml  # policy.allow_implicit_invocation: false
│   └── references/
│       ├── docs-convention.md      # 문서 탐색·생성·갱신 규칙 (모든 스킬 공통)
│       ├── coffee-chat.md          # 각 단계의 실행 절차
│       ├── whats-wrong.md
│       ├── shall-we.md
│       └── is-it-ok.md
├── docs/default-stack/             # 이 설계 문서 (배포 대상 아님)
├── README.md
└── LICENSE
```

- 저장소 메타(마켓플레이스, README, 설계 문서)와 플러그인 본체를 `plugin/`으로 분리해, 설치 시 플러그인 파일만 복사되게 한다.
- just-do-it은 자체 `references/` 문서가 없다. 단계 순서와 루프 한도(3회)만 `SKILL.md`에 두고 나머지는 위 문서들을 가리킨다.

## 역할 분리

- `SKILL.md`: 호출 조건, 역할, 참조할 `references/` 문서. 명시 호출 전용.
- `references/`: 실제 실행 절차. 개별 스킬과 just-do-it이 같은 문서를 참조한다.
- 같은 규칙을 두 곳 이상에 쓰지 않는다.

## 문서 규칙 (`references/docs-convention.md`의 내용)

1. 실행 시 기존 문서와 디렉터리 구조를 먼저 확인한다.
2. 재사용 가능한 문서가 있으면 그것을 갱신한다.
3. 적절한 문서가 없을 때만 `docs/default-stack/` 아래에 필요한 파일만 만든다.
4. 독립적인 주제만 별도 문서로 분리하고, 관련 문서는 상대경로 링크로 연결한다.
5. 내용 중복과 불필요한 구조 변경을 피한다.

| 경로 | 내용 |
|---|---|
| `index.md` | 문서 간 연결 |
| `vision.md` | 프로젝트 목적과 아이디어 |
| `decisions.md` | 확정 결정과 근거 |
| `research/` | 기술 조사 자료 (주제별) |
| `work/` | 문제 정의, Phase/Step 계획, 검증 결과 (주제별) |
