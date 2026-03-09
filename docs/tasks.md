# Jobs and Skills

## Summary

`job`은 시스템이 시작하는 백그라운드 실행 정의이고, `skill`은 agent가 읽는 작업 지침 문서입니다.

- `core`: orchestration, scheduling, state, delivery
- `tool`: agent와 job runtime이 호출하는 개별 기능
- `job`: scheduler가 읽는 YAML 실행 정의
- `skill`: agent가 읽는 markdown 작업 지침

## Locations

- root `jobs/`: 사용자 정의 job 문서
- root `skills/`: 사용자 정의 skill 문서
- root `tools/`: 사용자 정의 external tool
- `src/jobs`: 엔진 내부 job runtime
- `src/skills`: 엔진 내부 skill loader
- `src/tools`: 엔진 내부 built-in tool과 external tool loader
- `src/runtime/tools.py`: 공통 tool registry

## Design Rules

- `job`은 Python 자유 코드가 아니라 제한된 YAML DSL로 작성합니다
- `job`은 허용된 `step type`과 `tool`만 사용할 수 있습니다
- 예외 처리, 상태 저장, 중복 방지, 재실행 제어는 `core`가 담당합니다
- `skill`은 markdown 문서이며 frontmatter와 본문으로 구성됩니다
- `job`은 선택적으로 하나의 `skill`을 참조할 수 있습니다

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

## Job Example

```yaml
id: daily_ai_briefing
description: Daily AI trend briefing
agent: codex
enabled: true
skill: daily_ai_briefing

schedule:
  kind: cron
  expr: "0 7 * * *"
  timezone: "Asia/Seoul"

allowed_tools:
  - job.sqlite_query
  - job.render_template
  - job.run_agent_prompt
  - job.send_discord_message
  - job.persist_text

output:
  channel_id: "123456789012345678"
  artifact_path: "briefings/daily.md"

steps:
  - id: load_items
    type: load
    tool: job.sqlite_query
    with:
      database_path: /path/to/collector.sqlite
      sql: "SELECT title, summary FROM collected_items ORDER BY rowid DESC LIMIT 20"

  - id: compose_prompt
    type: generate
    tool: job.render_template
    with:
      template: |
        다음 데이터를 바탕으로 오늘의 AI 브리핑을 작성해 주세요.
        {{ steps.load_items.rows }}

  - id: generate_briefing
    type: generate
    tool: job.run_agent_prompt
    with:
      prompt: "{{ steps.compose_prompt.content }}"

  - id: deliver
    type: deliver
    tool: job.send_discord_message
    with:
      content: "{{ steps.generate_briefing.response }}"

  - id: persist
    type: persist
    tool: job.persist_text
    with:
      content: "{{ steps.generate_briefing.response }}"
```

## Skill Example

```md
---
id: daily_ai_briefing
summary: Generate Taco's morning AI, homelab, and automation briefing.
allowed_tools:
  - job.run_agent_prompt
---

## Goal
타코를 위한 아침 브리핑을 작성합니다.

## Instructions
- AI 서비스, homelab, AI 자동화에 집중합니다.
- 중복 내용은 합치고 과한 hype는 경계합니다.
```

## Built-in Tools

- `job.noop`
- `job.sqlite_query`
- `job.render_template`
- `job.run_agent_prompt`
- `job.send_discord_message`
- `job.persist_text`
- `job.persist_memory`

## External Tool Manifest

```yaml
id: google_calendar
timeout_seconds: 60
capabilities:
  - create_event
entry:
  command:
    - python3
    - run.py
```

## Runtime Notes

- schedule은 현재 `cron` 기반으로 실행됩니다
- 같은 job은 같은 슬롯에서 중복 실행되지 않도록 SQLite run 기록으로 제어합니다
- Discord delivery는 기존 agent bot client를 재사용합니다
