# Architecture: AI Agent Discord Messaging System

## Summary

이 문서는 MVP 구현을 위한 상세 아키텍처를 정의한다. 시스템은 Discord를 입력/출력 surface로 사용하고, channel 단위 live session은 `sessions.json` SSOT로 관리하며, 장기 기억은 Markdown memory store에 저장한다. Claude, Codex, Gemini는 provider adapter로 추상화하고, `/new`와 `/cli`를 통해 세션 제어와 native command 실행을 지원한다. `memory_search`는 provider wrapper가 아니라 runtime tool로 제공한다.

이 문서의 목표는 "무엇을 어떤 경계로 나누어 구현할 것인가"를 고정하는 것이다. 구체 클래스명은 변경 가능하지만, 책임 분리와 데이터 계약은 이 문서를 기준으로 유지한다.

## Scope

- In:
  - Discord DM/guild channel 메시지 처리
  - channel 기반 persistent session
  - `/new`, `/cli`
  - `/cli` whitelist: `/help`, `/stats`, `/model`
  - `/model` Discord modal/select UX
  - Markdown memory store + frontmatter 동기 갱신
  - ripgrep 기반 `memory_search` tool
  - provider-native init doc 생성

- Out:
  - Web UI
  - thread 전용 session
  - FTS5 indexing
  - semantic search
  - multi-user authorization
  - voice/image generation

## 1. System Topology

```text
Discord API
  -> Discord Gateway Layer
  -> Agent Runtime
     -> Session Manager
     -> Command Router
     -> Provider Wrapper
     -> Memory Service
     -> Session Store (sessions.json)
  -> Local Filesystem
     -> workspace/
     -> memory/
     -> sessions.json
```

핵심 계층은 네 개다.

1. `Discord Gateway Layer`
   - Discord 이벤트 수신
   - DM/guild channel 구분
   - slash command payload 파싱

2. `Agent Runtime`
   - 어떤 agent와 session으로 보낼지 결정
   - 일반 메시지와 slash command 분기
   - provider wrapper와 memory service를 orchestration

3. `Provider Wrapper Layer`
   - Claude/Codex/Gemini별 세션 시작, 메시지 전달, native command 실행
   - `/model` 같은 provider-specific adapter 처리

4. `Runtime Tool Layer`
   - `memory_search` 같은 agent-callable tool 실행
   - tool contract와 실제 검색 backend 분리

5. `Storage Layer`
   - `sessions.json`: live session SSOT
   - markdown memory store: long-term conversation memory
   - `tasks.sqlite`: task/scheduler run state SSOT

6. `Task Runtime Layer`
   - YAML task 문서 로드
   - schedule 기반 task 실행
   - task step orchestration
   - Discord delivery와 artifact 저장

## 2. Primary Modules

### 2.1 Discord Gateway

책임:
- `on_message` 처리
- `/new` 처리
- `/cli` 처리
- Discord modal/select response 처리
- typing indicator, chunked send

입력:
- Discord message event
- Discord interaction event

출력:
- runtime command object
- Discord response send/edit

### 2.2 Agent Registry

책임:
- `agents.yaml` 로드
- `agent_id` 기준 설정 보관
- `display_name`, provider type, model, workspace_dir, memory_dir 노출

핵심 규칙:
- `agent_id`는 stable slug
- `display_name`은 사용자 표시용

### 2.3 Session Manager

책임:
- channel 기준 session key 계산
- `sessions.json` 읽기/쓰기
- runtime cache 유지
- provider session 복구 시도

세션 규칙:
- DM은 독립 session
- guild channel은 독립 session
- thread는 `parent_channel_id`로 normalize

### 2.4 Command Router

책임:
- 일반 메시지 vs `/new` vs `/cli` 분기
- `/cli` whitelist 검증
- `/model`이면 modal/select flow 진입
- provider wrapper 호출 전에 normalized command 생성

MVP whitelist:
- `/help`
- `/stats`
- `/model`

### 2.5 Provider Wrapper Layer

책임:
- provider process/session lifecycle
- 일반 메시지 전달
- native command 전달
- `/model` adapter 처리
- provider-specific session id 노출

구성:
- `ClaudeWrapper`
- `CodexWrapper`
- `GeminiWrapper`

공통 계약:
- `start()`
- `send_user_message(message)`
- `send_native_command(command, args=None)`
- `reset_session()`
- `stop()`
- `is_alive()`
- `supports_native_command(command)`
- `session_scope_key(channel_id, is_dm, parent_channel_id=None)`

주의:
- 이것은 구체 클래스 설계가 아니라 구현 계약이다.
- 실제 내부 helper/class 분리는 provider별로 달라도 된다.

### 2.6 Memory Service

책임:
- 대화 append
- conversation file rollover
- frontmatter 생성/갱신
- `memory_search`가 사용할 검색 데이터 관리

세부 구성:
- `MemoryWriter`
- `FrontmatterGenerator`

### 2.7 Runtime Tool Layer

책임:
- agent가 호출하는 runtime tool 실행
- tool 이름과 실제 구현 연결
- provider wrapper와 분리된 retrieval contract 유지

세부 구성:
- `ToolRuntime`
- `MemorySearchTool`

규칙:
- `memory_search`는 provider wrapper 계약에 포함하지 않음
- wrapper는 tool 실행 결과를 모를 수 있어도 됨

### 2.8 Task Runtime Layer

책임:
- `config/tasks/*.yaml` 문서 로드
- 허용된 step type만 파싱
- task run state를 SQLite에 저장
- 일정 시각에 task 실행
- task가 tool을 순서대로 호출하도록 orchestration

구성:
- `TaskRegistry`
- `TaskRuntime`
- `TaskScheduler`
- `TaskStore`

규칙:
- task는 자유 Python 코드가 아니라 YAML DSL이다
- `core`는 orchestration과 state만 담당한다
- task는 workflow 정의, tool은 개별 기능 단위다

### 2.8 Transport Layer

책임:
- raw response fidelity 유지
- Discord 2000자 제한 대응 chunking
- code fence integrity 유지
- ordering 보장

금지:
- 요약
- rephrase
- embed styling
- 임의 formatting 변경

## 3. Source of Truth

### 3.1 Live Session SSOT

파일:
- `sessions.json`

역할:
- 현재 channel에 연결된 live provider session 상태 저장

포함 필드:
```json
{
  "discord:channel:12345": {
    "agent_id": "code-reviewer",
    "provider": "claude",
    "provider_session_id": "provider-session-handle",
    "current_model": "opus",
    "last_activity_at": "2026-03-07T16:00:00Z",
    "status": "active"
  }
}
```

업데이트 트리거:
- session start
- `/new`
- `/model`
- provider session id 갱신
- crash recovery
- session stop

원칙:
- runtime memory cache보다 `sessions.json`이 canonical
- 상태 변경 시 반드시 JSON 먼저/동시에 갱신
- 메시지 본문은 저장하지 않음
- MVP는 단일 프로세스만 `sessions.json`을 소유한다
- 파일 갱신은 단일 `asyncio.Lock` 아래에서 temp file write 후 `os.replace()`로 atomic replace 한다
- 다른 프로세스와의 동시 쓰기는 MVP 범위 밖이다

### 3.2 Long-Term Memory SSOT

위치:
- `{MEMORY_DIR}/{agent_id}/{YYYY-MM-DD}/conversation_NNN.md`

역할:
- conversation 본문과 검색용 메타데이터 저장

frontmatter 필드:
- `date`
- `agent`
- `display_name`
- `tags`
- `topic`
- `summary`
- `participants`
- `message_count`

원칙:
- 메시지 append와 frontmatter 갱신은 같은 write path에서 처리
- `tags/topic/summary`는 active agent가 생성

## 4. Data Contracts

### 4.1 Runtime Command Contract

```python
{
  "kind": "user_message" | "new_session" | "cli_command" | "modal_submit",
  "agent_id": str,
  "session_key": str,
  "channel_id": str,
  "parent_channel_id": str | None,
  "is_dm": bool,
  "payload": dict
}
```

### 4.2 `memory_search` Tool Contract

입력:
```json
{
  "query": "지난주 아키텍처 결정",
  "top_k": 5,
  "date_from": "2026-03-01",
  "date_to": "2026-03-07",
  "tags": ["architecture"]
}
```

출력:
```json
{
  "results": [
    {
      "path": "memory/code-reviewer/2026-03-05/conversation_001.md",
      "date": "2026-03-05",
      "topic": "세션 지속성 설계",
      "summary": "channel 기준 세션 유지와 /new reset 정책을 확정했다.",
      "snippet": "같은 channel이면 같은 session...",
      "score": 0.91
    }
  ]
}
```

MVP 구현 규칙:
- 검색 엔진은 `rg`
- `score`는 간단한 heuristic score여도 허용
- 결과는 relevance order로 정렬

### 4.3 `/model` Interaction Contract

흐름:
1. 사용자 `/cli raw:"/model"` 또는 equivalent UI 실행
2. router가 provider-specific adapter 필요 여부 확인
3. Discord modal/select로 해당 provider가 요구하는 model 옵션을 수집
4. wrapper가 provider-native command or equivalent API 실행
5. `sessions.json`의 `current_model` 갱신

MVP 기본 규칙:
- model 선택 UX는 provider별 옵션을 그대로 반영한다
- 공통 단일 모델 목록으로 정규화하지 않는다
- Discord interaction payload는 `request_id`, `command`, `agent_id`, `session_key`를 포함해 원래 세션에 귀속되어야 한다

## 5. End-to-End Flows

### 5.1 Standard Message

1. Discord message 수신
2. session key 계산
3. `sessions.json` 로드/확인
4. 세션 없으면 wrapper start
5. user message 전달
6. provider output stream 수신
7. memory append
8. frontmatter 갱신
9. transport chunking 후 Discord 전송
10. `last_activity_at` 갱신

### 5.2 `/new`

1. `/new` interaction 수신
2. session key 계산
3. active session stop/reset
4. `sessions.json` 상태 초기화 또는 제거
5. Discord 확인 메시지 전송

### 5.3 `/cli /help` or `/stats`

1. `/cli` 수신
2. whitelist 검증
3. active session 확보
4. wrapper `send_native_command()`
5. raw output chunking 전송

### 5.4 `/cli /model`

1. `/cli` 수신
2. whitelist 검증
3. Discord modal/select 표시
4. 사용자 선택 수신
5. `request_id`와 `session_key`를 검증한 뒤 provider adapter 실행
6. 결과 전송
7. `sessions.json.current_model` 갱신

### 5.5 Memory Recall

1. 사용자가 과거 대화 질문
2. agent가 `memory_search` tool 호출
3. tool이 markdown + frontmatter 검색
4. 결과를 응답 context로 제공
5. agent가 최종 답변 생성

## 6. File and Directory Plan

```text
docs/
  plans.md
  architecture.md

config/
  agents.yaml
  personas/

setup/
  agents.yaml.template
  init.sh

runtime/
  sessions.json

memory/
  <agent_id>/
    <YYYY-MM-DD>/
      conversation_001.md

src/agent_messaging/
  app.py
  settings.py
  agent_registry.py
  discord_gateway.py
  command_router.py
  session_manager.py
  session_store.py
  transport.py
  memory/
    writer.py
    frontmatter.py
    search.py
  providers/
    base.py
    claude.py
    codex.py
    gemini.py
```

## 7. Implementation Order

### Phase 1: Foundation

- Add settings loader and `agents.yaml` schema
- Add `session_store.py` for `sessions.json`
- Add provider base contract
- Add atomic JSON write rule and single-process ownership guard

### Phase 2: Single-Provider Vertical Slice

- Implement Claude wrapper first
- Implement Discord DM message roundtrip
- Implement raw transport chunking
- Implement markdown memory write + frontmatter update

### Phase 3: Session and Commands

- Add channel-scoped session manager
- Add `/new`
- Add `/cli`
- Add `/help` and `/stats`
- Add `/model` modal/select flow for first provider

### Phase 4: Memory Recall

- Add `memory_search` tool
- Add `ToolRuntime` boundary
- Inject tool guidance into init docs
- Validate recall behavior on natural questions

### Phase 5: Multi-Provider Expansion

- Add Codex wrapper
- Add Gemini wrapper
- Add provider-specific `/model` adapters

## 8. Validation Plan

Automated:
- unit tests for session key normalization
- unit tests for `sessions.json` read/write
- unit tests for atomic `sessions.json` replace path
- unit tests for conversation rollover
- unit tests for frontmatter update on append
- unit tests for `memory_search` ranking/filtering

Integration:
- Discord DM -> provider -> Discord roundtrip
- guild channel roundtrip
- `/new` resets only current channel session
- `/cli /help` and `/cli /stats` passthrough
- `/cli /model` updates session model and persists to SSOT
- modal submit correlation matches the original session and command
- provider crash triggers restart policy
- timeout path sends the delayed-response notice

Manual:
- 확인용으로 `sessions.json`을 열어 상태가 즉시 갱신되는지 검증
- markdown memory 파일이 append와 동시에 frontmatter를 갱신하는지 검증
- thread에서 메시지를 보내도 부모 channel session을 재사용하는지 검증

## 9. Remaining Non-Blocking Notes

- provider별 `/model` 실제 native syntax는 adapter 내부 구현 문제로 남겨둔다.
- `score` 계산은 MVP에서 heuristic으로 시작하고, later phase에서 고도화 가능하다.
- FTS5는 architecture boundary를 유지한 채 memory search backend만 교체하는 방향으로 추가한다.

## 10. Project Concepts

이 섹션은 프로젝트에서 사용하는 핵심 개념을 위계 기준으로 정리한다. 세부 요구사항은 [plans.md](/Users/taco/projects/ai-agent-messaging/docs/plans.md)를 따른다.

### 10.1 Product Level

- **AI Agent Messaging**
  - Discord를 UI로 사용해 로컬 CLI agent와 대화하는 시스템 전체

- **User**
  - Discord에서 agent와 대화하는 사람

- **MVP Surface**
  - DM
  - Guild channel

### 10.2 Interaction Level

- **Discord Conversation Scope**
  - 세션을 구분하는 단위
  - 이 프로젝트에서는 `channel 기준`
  - DM과 guild channel은 서로 다른 scope
  - Thread는 Discord API 상 별도 channel-like object이지만, `parent channel`로 정규화되어 별도 scope를 만들지 않음

- **Discord Command**
  - Discord에서 agent를 제어하기 위한 slash command
  - MVP 기준:
    - `/new`
    - `/cli`

- **Native CLI Command**
  - Claude/Codex/Gemini가 자체적으로 제공하는 `/help`, `/stats`, `/model` 같은 명령
  - Discord의 `/cli`를 통해 전달

### 10.3 Runtime Level

- **Agent Manager**
  - Discord 이벤트를 받고 어떤 agent/session에 전달할지 결정하는 상위 런타임 계층

- **Session Persistence**
  - 현재 channel에 붙어 있는 live CLI session 상태를 유지하는 계층
  - 장기 기억이 아니라 운영 상태 저장

- **Session Registry**
  - 현재 활성 세션들의 런타임 메모리 맵

- **Session SSOT**
  - 세션 상태의 canonical source of truth
  - 추천 형태: `sessions.json`
  - channel별 `agent_id`, provider, provider session id, current model, status, last activity를 저장
  - MVP에서는 단일 프로세스만 이 파일을 소유하고 갱신

- **CLI Wrapper**
  - Claude/Codex/Gemini를 공통 인터페이스로 감싸는 계층
  - 현재는 계약 초안 수준만 정의됨
  - 메시지 전달, native command 전달, session reset, 상태 확인 담당

- **Runtime Tool**
  - provider wrapper 바깥에서 실행되는 내부 도구 계층
  - 예: `memory_search`

- **Provider Session**
  - 실제 Claude/Codex/Gemini가 내부적으로 유지하는 세션 핸들 또는 session id

### 10.4 Agent Level

- **Agent**
  - 하나의 Discord bot + CLI provider + persona + memory를 가진 독립 단위

- **agent_id**
  - 내부 stable identifier
  - 예: `code-reviewer`
  - 메모리 경로, session registry, 내부 참조에 사용

- **display_name**
  - 사용자에게 보여주는 이름
  - 예: `Code Reviewer`

- **Persona**
  - agent의 역할, 톤, 전문성을 정의하는 지침

- **Provider**
  - 실제 모델 런타임
  - 예: Claude CLI, Codex CLI, Gemini CLI

- **Workdir**
  - provider CLI가 시작되는 작업 디렉터리
  - 이 위치에서 init doc를 자동 로드

- **Init Doc**
  - provider가 시작 시 읽는 문서
  - Claude: `CLAUDE.md`
  - Codex: `AGENTS.md`
  - Gemini: `GEMINI.md`

### 10.5 Memory Level

- **Persistent Memory**
  - 대화 본문을 장기 보존하는 계층
  - 세션이 끊겨도 유지됨

- **Conversation File**
  - 날짜별로 저장되는 Markdown 대화 파일
  - 예: `{MEMORY_DIR}/{agent_id}/{YYYY-MM-DD}/conversation_001.md`

- **Frontmatter**
  - 각 conversation file 상단의 YAML 메타데이터

- **tags**
  - 검색에 걸릴 핵심 키워드 3-8개

- **topic**
  - 대화 대표 주제 1줄

- **summary**
  - 검색 결과에서 빠르게 맥락을 복원하기 위한 1-3문장 요약

- **Participants**
  - 대화 참여자 정보

- **message_count**
  - 파일에 포함된 메시지 수

### 10.6 Retrieval Level

- **Memory Search Tool**
  - agent가 과거 대화를 찾기 위해 호출하는 내부 tool
  - runtime tool 계층에 속하며 wrapper 계약에는 포함되지 않음

- **Search Query**
  - 사용자의 자연어 질문에서 파생된 검색 질의
  - 예: `지난주 아키텍처 결정`

- **Search Filters**
  - 날짜 범위, 태그 같은 제한 조건
  - MVP 기준: `date_from`, `date_to`, `tags`, `top_k`

- **Search Result**
  - memory tool이 반환하는 단위 결과
  - MVP 기준 `path`, `date`, `topic`, `summary`, `snippet`, `score`를 포함

### 10.7 Transport Level

- **Raw Response Fidelity**
  - Discord로 보내는 응답은 CLI 원문을 유지해야 한다는 원칙

- **Transport Layer**
  - 응답 내용을 바꾸지 않고 Discord 전송 가능 형태로만 가공하는 계층

- **Chunking**
  - Discord 길이 제한 때문에 긴 응답을 분할 전송하는 처리

- **Modal / Select UX**
  - `/model`처럼 추가 입력이 필요한 command를 Discord에서 수행하기 위한 상호작용 컴포넌트
  - model 옵션은 공통 목록으로 추상화하지 않고 provider별 실제 선택지를 반영

### 10.8 Relationship Summary

- User는 Discord에서 Agent와 대화한다.
- Agent Manager는 Conversation Scope를 기준으로 Session을 찾는다.
- Session Persistence는 현재 live CLI 상태를 `sessions.json` SSOT로 관리한다.
- Agent의 실제 장기 기억은 Persistent Memory markdown에 저장된다.
- Agent는 필요 시 Memory Search Tool을 호출해 Persistent Memory를 검색한다.
- Transport Layer는 CLI 응답을 바꾸지 않고 Discord에 안전하게 전달한다.
