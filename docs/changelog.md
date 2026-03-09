# Changelog

## Unreleased

### Added
- YAML 기반 task DSL과 `TaskRuntime`, `TaskScheduler`, `TaskStore`를 추가했습니다.
- task 실행 상태를 저장하는 SQLite 기반 `tasks.sqlite` 저장소를 추가했습니다.
- `task.noop`, `task.sqlite_query`, `task.render_template`, `task.run_agent_prompt`, `task.send_discord_message`, `task.persist_text` built-in tool을 추가했습니다.
- task 시스템 사용법과 DSL 예시를 담은 `docs/tasks.md`를 추가했습니다.

### Changed
- 패키지 구조를 기능 축 기준으로 재정리했습니다.
- `AgentRegistry`를 `config` 계층으로 이동했습니다.
- `ProviderRuntime`, `PendingInteractionStore`, `DeliveryRuntime`를 `runtime` 계층으로 이동했습니다.
- `CommandRouter`를 `services` 계층으로 이동했습니다.
- 앱 부팅 시 task 문서를 로드하고 scheduler를 시작하도록 확장했습니다.
- `README.md`, `docs/architecture.md`, `setup/agents.yaml.template`를 새 task/runtime 구조에 맞게 갱신했습니다.

### Tests
- task loader 검증 실패 케이스를 추가했습니다.
- task 등록과 scheduler 중복 실행 방지 테스트를 추가했습니다.
- app의 task runtime 위임 경로 테스트를 추가했습니다.
- 전체 테스트 스위트 통과를 확인했습니다 (`76 passed`).
