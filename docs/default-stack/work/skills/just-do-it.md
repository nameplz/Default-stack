# just-do-it

[coffee-chat](coffee-chat.md) → [whats-wrong](whats-wrong.md) → [shall-we](shall-we.md) → [is-it-ok](is-it-ok.md)를 이어서 진행한다.

## 원칙

- 다른 스킬을 호출하지 않고 `references/`의 공통 워크플로 정의를 순서대로 따른다 ([plugin-structure.md](../plugin-structure.md)).
- 본문은 `references/` 워크플로 문서를 순서대로 가리키는 얇은 지시로 두고, 각 단계의 규칙을 다시 쓰지 않는다.

## 흐름

1. coffee-chat은 대화로 진행한다.
2. 정리 문서를 사용자에게 확인받는다.
3. 이후 whats-wrong → shall-we → is-it-ok를 자동 진행한다.
4. is-it-ok 실패 → shall-we 수정 → 재검증을 최대 3회 반복한다 ([decisions.md](../../decisions.md)).
5. 한도를 넘으면 미해결 항목을 보고하고 멈춘다.

자동 진행 중에도 shall-we의 중단 조건(명세 모호·코드 충돌 시 멈추고 묻기)은 유지된다.
