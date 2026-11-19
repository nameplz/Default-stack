# ship-it

현재 변경을 PR로 올리고 자동 병합을 켠다. 필수 검사(`verify`)만 통과하면 사람 리뷰 없이 바로 병합된다.

실행 절차는 [references/ship-it.md](../../../../plugin/references/ship-it.md).

## 흐름

1. 필수 검사와 자동 병합 설정을 확인한다. 없으면 [apply-stack](apply-stack.md)으로 안내하고 멈춘다 (필수 검사 없이 자동 병합을 켜면 즉시 병합된다).
2. 로컬 `verify` 통과 → 브랜치·커밋·푸시 → `gh pr create` → `gh pr merge --auto --squash`.
3. 검사 실패·브랜치 뒤처짐·충돌을 고치며 지켜본다. pstack `fix-ci`·`fix-merge-conflicts`가 있으면 따른다. 수정은 최대 3회.

## 금지

`--admin` 병합, 필수 검사·브랜치 보호 변경, 테스트 약화, 기본 브랜치 강제 푸시.
