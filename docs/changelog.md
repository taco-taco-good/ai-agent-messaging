# Changelog

## Unreleased

### Added
- YAML 기반 task DSL과 `TaskRuntime`, `TaskScheduler`, `TaskStore`를 추가했습니다.
- task 실행 상태를 저장하는 SQLite 기반 `tasks.sqlite` 저장소를 추가했습니다.
- `task.noop`, `task.sqlite_query`, `task.render_template`, `task.run_agent_prompt`, `task.send_discord_message`, `task.persist_text` built-in tool을 추가했습니다.
- `task.persist_memory` built-in tool을 추가했습니다.
- task 시스템 사용법과 DSL 예시를 담은 `docs/tasks.md`를 추가했습니다.
- 세션별 작업 상태를 `.agent-messaging/snapshots/<agent>/...json`에 저장하는 resume snapshot 확장 필드를 추가했습니다.

### Changed
- 패키지 구조를 기능 축 기준으로 재정리했습니다.
- `AgentRegistry`를 `config` 계층으로 이동했습니다.
- `ProviderRuntime`, `PendingInteractionStore`, `DeliveryRuntime`를 `runtime` 계층으로 이동했습니다.
- `CommandRouter`를 `services` 계층으로 이동했습니다.
- 앱 부팅 시 task 문서를 로드하고 scheduler를 시작하도록 확장했습니다.
- task가 선택적으로 기존 memory system 아래 `tasks/<task_id>/...` 구조에 실행 기록을 남길 수 있게 확장했습니다.
- `README.md`, `docs/architecture.md`, `setup/agents.yaml.template`를 새 task/runtime 구조에 맞게 갱신했습니다.
- resume context 주입이 같은 세션에서는 항상 동작하고, 새 세션에서는 관련 follow-up 요청에만 이전 작업 상태를 이어받도록 gating 로직을 강화했습니다.
- snapshot이 없을 때는 최신 유효 memory 문서를 읽어 최근 작업 요약, 마지막 사용자 메시지, 마지막 응답 요약으로 복구하도록 보강했습니다.
- snapshot에 activity type, work status, current artifact, latest conclusion, evidence basis, artifacts, last message summary 같은 복원용 필드를 함께 저장하도록 확장했습니다.

### Tests
- task loader 검증 실패 케이스를 추가했습니다.
- task 등록과 scheduler 중복 실행 방지 테스트를 추가했습니다.
- app의 task runtime 위임 경로 테스트를 추가했습니다.
- 전체 테스트 스위트 통과를 확인했습니다 (`76 passed`).
- 새 세션 resume gating, snapshot 유실 시 memory fallback, 최신 snapshot 선택 로직에 대한 테스트를 추가했습니다.
- 전체 `unittest` 스위트 통과를 다시 확인했습니다 (`130 tests`, `OK`).
