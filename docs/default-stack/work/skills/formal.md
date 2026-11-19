# formal

버그 비용은 크고 테스트가 닿기 어려운 곳의 속성을 형식 검증으로 증명하고, 코드가 바뀌어도 증명이 코드를 계속 설명하게 유지한다.

실행 절차는 [references/formal.md](../../../../plugin/references/formal.md).

## 흐름

1. 형식 검증 스킬이 없으면 pstack `create-formal-verification-skill`, 있으면 `maintain-formal-verification-skill`, 상태 흐름 시각화는 `statechart`.
2. 생성 스킬은 `.claude/skills/formal-<area>/`, Codex는 `.agents/skills/` 링크.
3. 2분 안팎이면 `verify`에 넣어 필수 검사로, 느리면 별도 명령과 예약 CI.
4. 실제 코드를 일부러 깨서 검사가 실패하는 것을 확인한 뒤 되돌린다.
5. 커밋하지 않고 [ship-it](ship-it.md)으로 전달.
