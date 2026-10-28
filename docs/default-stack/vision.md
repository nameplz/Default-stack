# Vision

막연한 아이디어를 구체화하고 구현까지 이어 주는 간단한 하네스. 소~중규모 개인 프로젝트를 아이디어 구상 단계부터 구현까지 진행하는 개인 워크플로를 플러그인으로 만든 것이다.

## 대상

- 아이디어 구상 단계인 프로젝트 초기
- 소~중규모 개인 프로젝트

## 배포

- Claude Code와 Codex 양쪽에서 동작하는 플러그인
- 마켓플레이스로 공유

## 핵심 원칙

- **가볍게 시작, 구조화는 나중에**: 대화는 자유롭게, 구조는 문서 저장 시점에만 적용한다.
- **규모에 비례하는 무게**: 리서치, Phase/Step 분할, 테스트 모두 프로젝트 크기에 맞춘다.
- **필요 최소한**: 문서도 코드도 필요한 만큼만 만든다. 오버 엔지니어링 금지.
- **증거 기반 판정**: 확인한 것과 확인하지 못한 것을 구분한다.
- **맥락 복원**: 이후 세션에서도 문서만으로 맥락을 되살릴 수 있게 한다.

## 스킬 구성

| 스킬 | 단계 | 산출물 |
|---|---|---|
| [coffee-chat](work/skills/coffee-chat.md) | 아이디어 | `vision.md`, `decisions.md` 갱신 |
| [whats-wrong](work/skills/whats-wrong.md) | 문제 정의 | `research/`, `work/` 문서 |
| [shall-we](work/skills/shall-we.md) | 구현 | 코드, 테스트, Step별 커밋 |
| [is-it-ok](work/skills/is-it-ok.md) | 검증 | 검증 보고 (`work/`) |
| [just-do-it](work/skills/just-do-it.md) | 전체 | 위 전부 |
