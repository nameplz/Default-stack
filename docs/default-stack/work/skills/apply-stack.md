# apply-stack

저장소 하나를 "지침이 아니라 검사가 에이전트를 붙잡는" 상태로 만드는 1회성 설정. Lauren Tan의 방식("All Code Is Slop (Except Mine)")에서 형식 검증과 릴리스별 자동 탐색을 뺀 기반이다.

실행 절차는 [references/apply-stack.md](../../../../plugin/references/apply-stack.md).

## 완료 기준

1. 단일 `verify` 명령 (위반 시 0이 아닌 종료 코드)
2. 같은 명령만 실행하는 CI (job 이름 `verify`)
3. pstack `create-verification-skill`로 만든 `.claude/skills/verify/`와 기능 지도, 실제 실행 증거, `.agents/skills/verify` 링크
4. pstack `correct`로 검사에 넣은 반복 오류 1건 이상, 아키텍처 경계 검사, 주석 금지 검사
5. `verify` 필수 검사에 묶인 자동 병합 (브랜치 보호)
6. `AGENTS.md`의 규칙-강제 대응표, PR 전달 규칙, 반복 지적 규칙. `CLAUDE.md`는 `@AGENTS.md`

## 경계

- GitHub 설정 변경(브랜치 보호, 자동 병합 허용)은 명령을 보여주고 승인받은 뒤 실행한다.
- 커밋하지 않는다. 전달은 [ship-it](ship-it.md)이 한다.
- 형식 검증과 릴리스 탐색은 이 기반 위에서 [formal](formal.md)과 [explore](explore.md)가 한다.
