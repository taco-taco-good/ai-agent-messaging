# Tasks

## Summary

`task`는 실행 가능한 작업 정의 단위입니다. task는 YAML 문서로 작성되며, `core`가 이를 파싱해 scheduler와 runner로 실행합니다.

- `core`: orchestration, scheduling, state, delivery
- `tool`: agent가 호출하는 개별 기능
- `task`: tool들을 사용한 workflow 정의

## Design Rules

- task는 Python 자유 코드가 아니라 제한된 YAML DSL로 작성합니다
- task는 허용된 `step type`과 `tool`만 사용할 수 있습니다
- 예외 처리, 상태 저장, 중복 방지, 재실행 제어는 `core`가 담당합니다

## Supported Step Types

| Step type | 역할 |
|---|---|
| `load` | 외부 데이터 또는 저장소에서 입력 로드 |
| `filter` | 후보 필터링 |
| `validate` | 품질 검증 |
| `enrich` | 부족한 맥락 보완 |
| `generate` | agent 또는 템플릿 기반 결과 생성 |
| `deliver` | Discord 등 외부 전달 |
| `persist` | 파일/DB 등에 산출물 저장 |

## Example

```yaml
id: daily_ai_briefing
description: Daily AI trend briefing
agent: codex
enabled: true

schedule:
  kind: cron
  expr: "0 7 * * *"
  timezone: "Asia/Seoul"

allowed_tools:
  - task.sqlite_query
  - task.render_template
  - task.run_agent_prompt
  - task.send_discord_message
  - task.persist_text

output:
  channel_id: "123456789012345678"
  artifact_path: "briefings/daily.md"

steps:
  - id: load_items
    type: load
    tool: task.sqlite_query
    with:
      database_path: /path/to/collector.sqlite
      sql: "SELECT title, summary FROM collected_items ORDER BY rowid DESC LIMIT 20"

  - id: compose_prompt
    type: generate
    tool: task.render_template
    with:
      template: |
        다음 데이터를 바탕으로 오늘의 AI 브리핑을 작성해 주세요.
        {{ steps.load_items.rows }}

  - id: generate_briefing
    type: generate
    tool: task.run_agent_prompt
    with:
      prompt: "{{ steps.compose_prompt.content }}"

  - id: deliver
    type: deliver
    tool: task.send_discord_message
    with:
      content: "{{ steps.generate_briefing.response }}"

  - id: persist
    type: persist
    tool: task.persist_text
    with:
      content: "{{ steps.generate_briefing.response }}"
```

## Built-in Tools

- `task.noop`
- `task.sqlite_query`
- `task.render_template`
- `task.run_agent_prompt`
- `task.send_discord_message`
- `task.persist_text`
- `task.persist_memory`

## Runtime Notes

- schedule은 현재 `cron` 기반으로 실행됩니다
- 같은 task는 같은 슬롯에서 중복 실행되지 않도록 SQLite run 기록으로 제어합니다
- Discord delivery는 기존 agent bot client를 재사용합니다
