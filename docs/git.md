# Git Convention

## 브랜치 전략

`main` + feature branch 모델을 사용합니다.

### 브랜치 종류

| 브랜치 | 패턴 | 용도 |
|---|---|---|
| `main` | `main` | 항상 배포 가능한 상태 유지 |
| feature | `feat/<설명>` | 새 기능 개발 |
| fix | `fix/<설명>` | 버그 수정 |
| refactor | `refactor/<설명>` | 구조 개선 (동작 변경 없음) |
| docs | `docs/<설명>` | 문서 작업 |
| chore | `chore/<설명>` | 빌드, CI, 의존성 등 비기능 작업 |

### 브랜치 이름 규칙

- 소문자 + 하이픈 구분: `feat/discord-slash-commands`
- 짧고 명확하게: `fix/pty-fd-leak`, `refactor/flatten-src-layout`
- 이슈 번호가 있으면 포함: `feat/12-memory-search`

### 브랜치 흐름

```
main
 ├── feat/session-persistence
 │    └── PR → main
 ├── fix/watchdog-backoff
 │    └── PR → main
 └── docs/git-convention
      └── PR → main
```

- feature branch는 `main`에서 분기
- 작업 완료 후 PR을 통해 `main`으로 merge
- merge 후 feature branch 삭제
- force push 금지 (`main` 브랜치)

## 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/) 규칙을 따릅니다.

### 형식

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| type | 설명 |
|---|---|
| `feat` | 새 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 동작 변경 없는 코드 구조 개선 |
| `docs` | 문서 추가/수정 |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, CI, 의존성 등 비기능 변경 |
| `style` | 포맷팅, 세미콜론 등 코드 의미에 영향 없는 변경 |
| `perf` | 성능 개선 |

### Scope (선택)

변경이 영향을 주는 모듈을 괄호 안에 표기합니다:

- `gateway`, `providers`, `memory`, `runtime`, `services`, `core`, `config`, `app`

### Subject

- 명령형 현재 시제: "add" (O), "added" (X), "adds" (X)
- 첫 글자 소문자
- 마침표 없음
- 50자 이내

### 예시

```
feat(gateway): register individual slash commands

Replace generic /cli passthrough with dedicated /help, /stats, /model
Discord slash commands for native UX.
```

```
fix(providers): close PTY file descriptor on startup failure
```

```
refactor(runtime): extract watchdog loop into separate method
```

```
test(stability): add crash recovery and idle cleanup tests
```

```
chore: flatten src/agent_messaging into src
```

## Pull Request

### PR 제목

커밋 메시지와 동일한 형식을 따릅니다:

```
feat(gateway): register individual slash commands
```

### PR 본문

```markdown
## Summary
- 변경 사항을 1-3줄로 요약

## Test plan
- [ ] 기존 테스트 통과 확인
- [ ] 새 기능에 대한 테스트 추가
- [ ] 수동 테스트 항목 (필요시)
```

### 체크리스트

- PR당 하나의 논리적 변경
- 테스트가 모두 통과하는 상태에서 PR 생성
- 불필요한 파일 변경 포함하지 않기
- `.env`, 토큰 등 민감 정보 커밋하지 않기

## 태그 & 릴리스

시맨틱 버저닝 (`v<major>.<minor>.<patch>`)을 사용합니다:

- **major**: 호환성을 깨는 변경
- **minor**: 하위 호환 기능 추가
- **patch**: 하위 호환 버그 수정

```bash
git tag v0.2.0
git push origin v0.2.0
```
