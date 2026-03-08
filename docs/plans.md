# Product Requirements Document: AI Agent Discord Messaging System

**Product Name:** AI Agent Messaging
**Status:** Draft
**Author:** taco
**Date Created:** 2026-03-07
**Last Updated:** 2026-03-07
**Version:** 1.1

---

## Executive Summary

**One-liner:** 로컬 CLI AI 모델(Claude, Codex, Gemini)과 Discord 봇을 연결하여, 에이전트별 페르소나, 지속 세션, 영구 메모리를 가진 멀티 에이전트 메시징 시스템.

**Overview:**

현재 Claude Code, Codex CLI, Gemini CLI 등 강력한 로컬 AI 도구들이 존재하지만, 이들은 터미널에서만 사용 가능하다. Discord와 같은 메시징 플랫폼에서 여러 에이전트를 정의하고 각각의 페르소나, 기억, 전문성을 가진 AI와 대화하려면 복잡한 연결 작업이 필요하다.

이 시스템은 로컬에서 실행되는 CLI AI 모델을 Discord 봇으로 래핑하여, 사용자가 Discord 채팅과 슬래시 명령어를 통해 자연스럽게 AI와 대화할 수 있게 한다. 각 에이전트는 독립적인 봇 토큰, 페르소나, 메모리, 작업 디렉토리를 가지며, 동일한 Discord 대화 스코프 안에서는 `/new`를 명시적으로 호출하기 전까지 동일한 CLI 세션을 유지한다. 모든 대화 기록은 마크다운 파일로 영구 저장되어 세션이 종료되거나 compaction이 발생해도 손실되지 않는다.

**Quick Facts:**
- **Target Users:** AI CLI 도구를 사용하는 개발자 / 파워 유저
- **Problem Solved:** 로컬 AI CLI 모델을 Discord에서 편리하게 사용, 영구 메모리 관리
- **Key Metric:** 에이전트 응답 성공률 (메시지 수신 → 응답 전달 완료 비율)
- **Target Launch:** MVP 2026 Q2

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals & Objectives](#goals--objectives)
3. [User Personas](#user-personas)
4. [User Stories & Requirements](#user-stories--requirements)
5. [Success Metrics](#success-metrics)
6. [Scope](#scope)
7. [Technical Considerations](#technical-considerations)
8. [Design & UX Requirements](#design--ux-requirements)
9. [Timeline & Milestones](#timeline--milestones)
10. [Risks & Mitigation](#risks--mitigation)
11. [Dependencies & Assumptions](#dependencies--assumptions)
12. [Open Questions](#open-questions)

---

## Problem Statement

### The Problem

로컬 CLI AI 모델(Claude, Codex, Gemini)은 강력하지만 다음과 같은 한계가 있다:

1. **접근성 제한:** 터미널에서만 사용 가능. 모바일이나 다른 디바이스에서 접근 불가.
2. **메모리 휘발성:** 세션이 끝나면 대화 컨텍스트가 사라짐. Compaction 발생 시 이전 대화 기록 손실.
3. **멀티 에이전트 부재:** 하나의 CLI에서 여러 페르소나/역할의 에이전트를 동시에 운영할 수 없음.
4. **협업 불가:** 다른 사람과 AI 대화를 공유하거나, 팀에서 동일한 에이전트에 접근하기 어려움.

### Current State

- 사용자는 터미널을 열고 `claude`, `codex`, `gemini` 명령어를 직접 입력하여 대화
- 이전 대화를 참조하려면 수동으로 세션을 resume하거나 기억에 의존
- 에이전트별 페르소나를 유지하려면 매번 시스템 프롬프트를 수동으로 설정
- Discord 등 메시징 플랫폼과의 연동은 각자 별도로 구현해야 함

### Impact

**User Impact:**
- 터미널에서만 AI를 사용할 수 있어 이동 중이나 다른 디바이스에서 접근 불가
- 중요한 대화 내용이 세션 종료 시 손실되어 반복적인 컨텍스트 설정 필요
- 여러 역할의 AI를 전환하며 사용하는 데 마찰이 큼

**Business Impact:**
- AI CLI 도구의 활용 범위가 터미널 사용자로 제한됨
- 팀/커뮤니티에서 AI 도구를 공유할 수 없어 생산성 손실

### Why Now?

- Claude CLI, Codex CLI, Gemini CLI 모두 2025-2026년에 비대화형 모드(subprocess pipe, JSON streaming)를 지원하기 시작
- 세 CLI 모두 프로그래밍적으로 통합할 수 있는 표준화된 인터페이스 제공
- Discord.py 2.x가 안정화되어 비동기 봇 개발이 성숙
- 로컬 실행 기반 AI 도구에 대한 수요 증가 (프라이버시, 비용, 커스터마이징)

---

## Goals & Objectives

### Business Goals

1. **AI CLI 활용 확대:** 터미널을 넘어 Discord 메시징 환경에서 AI 모델 활용
2. **영구 메모리 시스템:** 세션/compaction과 무관하게 모든 대화가 영구 보존되어 검색 가능
3. **멀티 에이전트 플랫폼:** 다양한 역할/전문성을 가진 에이전트를 손쉽게 정의하고 운영

### User Goals

1. **어디서든 AI 접근:** Discord가 있는 모든 디바이스에서 AI 에이전트와 대화
2. **기억하는 AI:** 이전 대화를 기억하고, 컨텍스트를 유지하며, 페르소나를 일관되게 유지하는 에이전트
3. **쉬운 에이전트 관리:** YAML 설정 파일 하나로 에이전트 정의, 시작, 관리
4. **세션 제어 가능성:** Discord에서 `/new`와 CLI native `/` 명령을 사용해 세션과 모델 상태를 직접 제어

### Non-Goals

- 웹 UI / 대시보드 구축 (Discord를 UI로 사용)
- AI 모델 자체의 학습이나 파인튜닝
- 다중 사용자 권한 관리 (개인 사용 우선)
- Discord 외 메시징 플랫폼 지원 (MVP)
- 음성 채널 통합
- 이미지/파일 생성 기능

---

## User Personas

### Primary Persona: AI Power User (개발자)

**Demographics:**
- Role: 소프트웨어 개발자 / AI 도구 파워 유저
- Tech savviness: High
- 현재 Claude Code, Codex, Gemini CLI를 일상적으로 사용

**Behaviors:**
- 여러 AI 도구를 작업 목적에 따라 전환하며 사용
- 코드 리뷰, 문서 작성, 아이디어 브레인스토밍 등 다양한 용도로 AI 활용
- Discord를 일상적으로 커뮤니케이션 채널로 사용

**Needs & Motivations:**
- 터미널 외 환경에서도 AI에 접근하고 싶음
- 이전 대화를 검색하고 참조하고 싶음
- 용도별 에이전트를 정의해서 사용하고 싶음 (코드 리뷰어, 기획자, 학습 도우미 등)

**Pain Points:**
- CLI 세션이 끝나면 대화 컨텍스트가 사라짐
- 매번 시스템 프롬프트를 다시 설정하는 반복 작업
- 모바일에서 AI 도구를 사용할 수 없음
- 여러 AI 모델을 목적에 맞게 빠르게 전환하기 어려움

**Quote:** _"Claude에게 어제 논의한 아키텍처 결정을 물어보고 싶은데, 세션이 끝나서 처음부터 다시 설명해야 해요."_

### Secondary Persona: 팀 리더 / 커뮤니티 운영자

**Demographics:**
- Role: 팀 리더, Discord 서버 운영자
- Tech savviness: Medium-High

**Needs & Motivations:**
- 팀 Discord 서버에 AI 어시스턴트를 배치하고 싶음
- 팀원들이 공통 AI 에이전트와 대화할 수 있게 하고 싶음

**Pain Points:**
- API 기반 봇은 비용이 높고 설정이 복잡
- 로컬 실행 모델을 팀에 공유하기 어려움

---

## User Stories & Requirements

### Epic 1: Discord 봇 연결

#### Must-Have Stories (P0)

##### Story 1: Discord 메시지 수신 및 CLI 전달

**User Story:**
```
As a Discord 사용자,
I want to Discord 채널/DM에서 메시지를 보내면 로컬 AI CLI에게 전달되도록,
So that 터미널 없이도 AI와 대화할 수 있다.
```

**Acceptance Criteria:**
- [ ] Given Discord 봇이 실행 중일 때, when 사용자가 봇에 DM을 보내면, then 해당 메시지가 로컬 CLI 프로세스의 stdin으로 전달된다
- [ ] Given CLI가 응답을 생성하면, when stdout으로 출력되면, then 해당 응답이 Discord 메시지로 사용자에게 전송된다
- [ ] Given CLI가 응답 텍스트를 생성하면, when Discord에 전송할 때, then 임의 요약, 재포맷팅, Embed 변환 없이 원문 그대로 전달한다
- [ ] Given 응답이 2000자를 초과하면, when Discord에 전송할 때, then 원문 순서를 유지한 채 여러 메시지로 분할하여 전송한다
- [ ] Given CLI 프로세스가 비정상 종료하면, when 사용자가 메시지를 보내면, then "에이전트가 재시작 중입니다" 메시지를 표시하고 자동 재시작한다

**Priority:** Must Have (P0)
**Effort:** L

---

##### Story 1A: Discord 슬래시 명령어 라우팅

**User Story:**
```
As a Discord 사용자,
I want to Discord의 / 명령어로 에이전트 세션과 CLI native 명령을 제어할 수 있도록,
So that 터미널 없이도 대화 컨텍스트와 모델 상태를 직접 조작할 수 있다.
```

**Acceptance Criteria:**
- [ ] Given 사용자가 `/new`를 실행하면, when 현재 channel 기반 세션이 존재할 때, then 해당 CLI 세션이 종료되고 다음 사용자 메시지에서 새 세션이 시작된다
- [ ] Given 사용자가 channel A에서 `/new`를 실행하면, when channel B에 활성 세션이 있을 때, then channel B 세션에는 영향을 주지 않는다
- [ ] Given 사용자가 CLI native slash command를 실행해야 할 때, when Discord에서 `/cli` passthrough 명령을 호출하면, then whitelist된 원시 명령 문자열(`/help`, `/stats`, `/model`)이 현재 channel 세션의 CLI에 전달된다
- [ ] Given native command가 단순 텍스트 결과를 반환할 때, when CLI가 응답을 생성하면, then 결과는 Discord에 원문 그대로 전송된다
- [ ] Given 사용자가 whitelist 외 명령을 `/cli`로 호출하면, when 시스템이 명령을 검증할 때, then 실행하지 않고 "MVP 미지원 명령" 오류를 반환한다
- [ ] Given `/model`이 추가 선택이나 입력을 요구할 때, when Discord에서 명령이 호출되면, then Discord modal 또는 select 기반 상호작용으로 필요한 값을 수집한 뒤 provider adapter를 통해 실행한다

**Priority:** Must Have (P0)
**Effort:** M

---

##### Story 2: 에이전트 정의 및 설정

**User Story:**
```
As a 시스템 관리자,
I want to YAML 파일로 에이전트를 정의하고 각각 Discord 봇 토큰과 CLI 모델을 매핑할 수 있도록,
So that 여러 에이전트를 쉽게 관리할 수 있다.
```

**Acceptance Criteria:**
- [ ] Given agents.yaml 파일이 존재할 때, when 시스템이 시작되면, then 정의된 모든 에이전트가 자동으로 실행된다
- [ ] Given `agents.<agent_id>` 키가 존재할 때, when 시스템이 에이전트를 로드하면, then 해당 키를 stable agent identifier로 사용한다
- [ ] Given 에이전트 설정에 discord_token, cli_type(claude/codex/gemini), `persona` 또는 `persona_file`, `workspace_dir`, `memory_dir`가 포함될 때, when 에이전트가 시작되면, then 각 에이전트는 독립된 Discord 봇으로 실행된다
- [ ] Given optional `display_name`이 설정될 때, when Discord 또는 로그에 표시할 이름이 필요하면, then `display_name`을 사용하고 내부 저장 경로와 식별에는 `agent_id`를 유지한다
- [ ] Given `session_mode: persistent`가 기본값일 때, when 사용자가 같은 channel에서 일반 메시지를 연속해서 보내면, then 같은 CLI 세션을 재사용한다
- [ ] Given DM과 guild channel이 다를 때, when 같은 사용자가 대화하더라도, then 서로 다른 세션으로 관리된다
- [ ] Given thread가 생성되더라도, when 부모 channel과 동일한 에이전트를 사용하면, then thread는 별도 세션 키를 만들지 않는다
- [ ] Given `persona_file`이 설정되어 있을 때, when 에이전트가 시작되면, then provider에 맞는 초기화 문서(`CLAUDE.md`/`AGENTS.md`/`GEMINI.md`)가 workspace_dir에 준비된다
- [ ] Given 설정 파일이 잘못되었을 때, when 시스템이 시작되면, then 명확한 에러 메시지와 함께 어떤 설정이 잘못되었는지 표시한다
- [ ] 에이전트 설정 예시:

```yaml
agents:
  code-reviewer:
    display_name: Code Reviewer
    discord_token: ${CODE_REVIEWER_DISCORD_TOKEN}
    cli_type: claude
    model: opus
    workspace_dir: ${AGENT_WORKSPACE_BASE}/code-reviewer
    persona_file: ./personas/code-reviewer.md
    memory_dir: ${MEMORY_BASE_DIR}/code-reviewer
    session_mode: persistent
  planner:
    display_name: Planner
    discord_token: ${PLANNER_DISCORD_TOKEN}
    cli_type: gemini
    model: pro
    workspace_dir: ${AGENT_WORKSPACE_BASE}/planner
    persona_file: ./personas/planner.md
    memory_dir: ${MEMORY_BASE_DIR}/planner
    session_mode: persistent
```

**Priority:** Must Have (P0)
**Effort:** M

---

##### Story 3: 에이전트 페르소나 유지

**User Story:**
```
As a Discord 사용자,
I want to 에이전트가 항상 정의된 페르소나를 유지하도록,
So that 일관된 성격과 전문성을 가진 AI와 대화할 수 있다.
```

**Acceptance Criteria:**
- [ ] Given 에이전트에 페르소나가 설정되어 있을 때, when 새 세션이 시작되면, then CLI에 시스템 프롬프트로 페르소나가 자동 주입된다
- [ ] Given compaction이 발생하더라도, when 에이전트가 응답할 때, then 페르소나에 맞는 톤과 전문성을 유지한다
- [ ] Given 페르소나에 "코드 리뷰어"가 설정되어 있을 때, when 사용자가 코드를 보내면, then 코드 리뷰어 관점에서 피드백을 제공한다

**Priority:** Must Have (P0)
**Effort:** S

---

##### Story 3A: 동일 세션 유지 및 명시적 세션 리셋

**User Story:**
```
As a Discord 사용자,
I want to `/new`를 호출하기 전까지 같은 CLI 세션이 유지되도록,
So that CLI의 원래 대화 흐름과 컨텍스트를 Discord에서도 그대로 이어갈 수 있다.
```

**Acceptance Criteria:**
- [ ] Given 동일한 channel에서 사용자가 연속 메시지를 보낼 때, when `/new`를 호출하지 않았다면, then 시스템은 새 subprocess를 매번 만들지 않고 기존 interactive CLI 세션에 입력을 이어서 보낸다
- [ ] Given 사용자가 `/new`를 호출하면, when 다음 메시지를 보낼 때, then 이전 세션 컨텍스트 없이 새 CLI 세션으로 시작한다
- [ ] Given 사용자가 다른 channel 또는 DM에서 같은 에이전트와 대화할 때, when 기존 channel 세션이 존재하더라도, then 별도 세션으로 시작한다
- [ ] Given CLI 프로세스가 예기치 않게 종료되면, when 시스템이 복구를 시도할 때, then provider가 resume를 지원하면 기존 세션 복구를 우선 시도하고 실패 시 새 세션 시작 사실을 사용자에게 명시한다
- [ ] Given 메모리 저장소는 별도로 존재할 때, when 세션이 새로 시작되더라도, then 영구 메모리는 유지되어 이후 검색에 사용된다

**Priority:** Must Have (P0)
**Effort:** L

---

### Epic 2: 영구 메모리 시스템

#### Must-Have Stories (P0)

##### Story 4: 대화 기록 자동 저장

**User Story:**
```
As a 시스템,
I want to 모든 대화 내용을 날짜별 디렉토리의 md 파일로 자동 저장하도록,
So that 세션 종료나 compaction과 무관하게 전체 대화 기록이 영구 보존된다.
```

**Acceptance Criteria:**
- [ ] Given 사용자와 에이전트 간 대화가 발생하면, when 메시지가 교환될 때마다, then `{MEMORY_DIR}/{agent_id}/{YYYY-MM-DD}/` 하위에 md 파일로 저장된다
- [ ] Given md 파일이 500줄을 초과하면, when 새 메시지가 추가될 때, then 새 파일(`conversation_002.md`, `003.md` ...)로 분할된다
- [ ] Given md 파일의 YAML frontmatter에 날짜, 태그, 토픽, 요약이 포함될 때, when 파일이 생성되면, then 현재 대화를 수행한 에이전트가 가이드라인에 따라 `tags`, `topic`, `summary`를 생성한다
- [ ] Given frontmatter 생성 가이드라인이 존재할 때, when 에이전트가 메타데이터를 만들면, then `tags`는 검색 가능한 핵심 키워드 3-8개, `topic`은 대표 주제 1줄, `summary`는 검색용 1-3문장으로 제한한다
- [ ] Given 메시지가 md 파일에 append될 때, when 저장이 완료되면, then 같은 write path 안에서 frontmatter도 함께 갱신된다
- [ ] md 파일 포맷 예시:

```markdown
---
date: 2026-03-07
agent: code-reviewer
display_name: "Code Reviewer"
tags: [python, architecture, design-pattern]
topic: "FastAPI 프로젝트 구조 리뷰"
summary: "FastAPI 프로젝트의 레이어 구조와 의존성 주입 패턴에 대한 코드 리뷰"
participants: [user:taco]
message_count: 24
---

## 14:30 - User
FastAPI 프로젝트 구조 좀 봐줘. src/ 아래 구조가 이래...

## 14:31 - Agent (code-reviewer)
네, 프로젝트 구조를 살펴보겠습니다. 몇 가지 개선 사항이 보이네요...
```

**Priority:** Must Have (P0)
**Effort:** L

---

##### Story 5: 메모리 검색

**User Story:**
```
As a Discord 사용자,
I want to 에이전트에게 이전 대화 내용을 질문하면 기억에서 검색하여 답변하도록,
So that 과거 대화 컨텍스트를 활용한 연속적인 대화가 가능하다.
```

**Acceptance Criteria:**
- [ ] Given 사용자가 "지난주에 논의한 아키텍처 결정이 뭐였지?"라고 질문하면, when 에이전트가 메모리를 검색할 때, then ripgrep을 사용하여 관련 md 파일에서 키워드를 찾아 답변한다
- [ ] Given 에이전트에 메모리 검색 tool이 제공될 때, when 과거 대화 관련 질문이 들어오면, then 에이전트가 자율적으로 해당 tool을 호출한다
- [ ] Given 검색 결과가 여러 파일에 걸쳐 있을 때, when 에이전트가 답변을 구성할 때, then 가장 관련성 높은 내용을 종합하여 답변한다
- [ ] Given frontmatter의 날짜/태그 필터링이 가능할 때, when 특정 기간이나 주제로 검색할 때, then 범위를 좁혀 정확한 결과를 반환한다

**Priority:** Must Have (P0)
**Effort:** XL

---

##### Story 6: 에이전트의 메모리 인지

**User Story:**
```
As a 에이전트,
I want to 내 메모리 디렉토리 구조와 검색 방법을 정확히 알고 있도록,
So that 효과적으로 과거 대화를 찾아 활용할 수 있다.
```

**Acceptance Criteria:**
- [ ] Given 에이전트의 시스템 프롬프트에 메모리 가이드가 포함될 때, when 에이전트가 초기화되면, then 다음 정보를 알고 있다:
  - 메모리 디렉토리 경로 (`MEMORY_DIR`)
  - 디렉토리 구조 (`{agent_id}/{YYYY-MM-DD}/conversation_NNN.md`)
  - frontmatter 스키마 (date, tags, topic, summary)
  - 메모리 검색 tool 사용법 (쿼리 예시, 날짜 필터링, 기대 결과 형식)
- [ ] Given 에이전트에게 "어제 뭐 했어?"라고 물으면, when 에이전트가 어제 날짜 디렉토리를 조회할 때, then 해당 날짜의 대화 요약을 제공한다
- [ ] Given 에이전트가 자동으로 메모리 가이드 프롬프트를 받을 때, when 새 세션이 시작되면, then 별도 설정 없이 메모리 검색이 가능하다

**Priority:** Must Have (P0)
**Effort:** M

---

### Epic 3: CLI 모델 통합

#### Must-Have Stories (P0)

##### Story 7: 통일된 CLI 래퍼

**User Story:**
```
As a 시스템 개발자,
I want to Claude, Codex, Gemini CLI를 동일한 인터페이스로 사용할 수 있도록,
So that 에이전트 정의 시 CLI 종류에 관계없이 동일한 방식으로 작동한다.
```

**Acceptance Criteria:**
- [ ] Given CLIWrapper 프로토콜이 `start()`, `send_user_message()`, `send_native_command(command, args)`, `reset_session()`, `stop()`, `is_alive()`, `supports_native_command(command)`, `session_scope_key(channel_id, is_dm, parent_channel_id)` 메서드를 정의할 때, when 각 CLI 래퍼가 이를 구현하면, then 상위 코드는 CLI 종류를 알 필요 없다
- [ ] Given Claude CLI 래퍼일 때, when persistent interactive session을 시작하면, then 동일 세션에 연속 입력과 slash command를 전달할 수 있다
- [ ] Given Codex CLI 래퍼일 때, when persistent interactive session 또는 resume 가능한 실행 경로를 시작하면, then 일반 메시지와 세션 재개를 동일 추상화로 다룰 수 있다
- [ ] Given Gemini CLI 래퍼일 때, when persistent interactive session을 시작하면, then 일반 메시지와 built-in command를 동일 세션 안에서 처리할 수 있다
- [ ] Given provider별 명령 기능 차이가 있을 때, when 상위 계층이 native command를 호출하면, then 래퍼는 지원 여부를 명시적으로 반환한다

**Priority:** Must Have (P0)
**Effort:** L

---

##### Story 8: CLI 프로세스 생명주기 관리

**User Story:**
```
As a 시스템,
I want to CLI 프로세스의 시작, 종료, 재시작을 안정적으로 관리하도록,
So that 에이전트가 장시간 안정적으로 운영된다.
```

**Acceptance Criteria:**
- [ ] Given CLI 프로세스가 크래시하면, when 시스템이 감지할 때, then 자동으로 프로세스를 재시작한다 (최대 3회, 이후 사용자에게 알림)
- [ ] Given 에이전트가 10분 이상 유휴 상태이면, when 새 메시지가 들어올 때, then 동일 세션 유지 정책을 우선하되 provider 또는 리소스 제약으로 세션이 정리된 경우 resume 또는 새 세션 시작 여부를 사용자에게 명시한다
- [ ] Given 시스템이 종료(SIGTERM/SIGINT)되면, when 모든 에이전트가 정리될 때, then 현재 대화를 저장하고 CLI 프로세스를 정상 종료한다
- [ ] Given CLI 프로세스가 응답에 120초 이상 걸리면, when 타임아웃이 발생할 때, then Discord에 "응답 생성에 시간이 걸리고 있습니다" 메시지를 전송한다

**Priority:** Must Have (P0)
**Effort:** L

---

#### Should-Have Stories (P1)

##### Story 9: 스트리밍 응답

**User Story:**
```
As a Discord 사용자,
I want to AI 응답이 실시간으로 스트리밍되어 Discord에 표시되도록,
So that 긴 응답을 기다리지 않고 생성 과정을 볼 수 있다.
```

**Acceptance Criteria:**
- [ ] Given CLI가 stream-json 모드로 응답할 때, when 토큰이 생성될 때마다, then Discord 메시지를 주기적으로(1~2초 간격) 편집하여 업데이트한다
- [ ] Given 스트리밍 중 Discord API rate limit에 도달하면, when 다음 업데이트 시, then 적절한 간격을 두고 재시도한다
- [ ] Given 최종 응답이 완성되면, when 스트리밍이 종료될 때, then 전체 응답으로 메시지를 최종 업데이트한다

**Priority:** Should Have (P1)
**Effort:** M

---

### Epic 4: 시스템 운영

#### Should-Have Stories (P1)

##### Story 10: 멀티 에이전트 동시 실행

**User Story:**
```
As a 시스템 관리자,
I want to 여러 에이전트를 하나의 프로세스에서 동시에 실행하도록,
So that 시스템 리소스를 효율적으로 사용하며 관리가 간편하다.
```

**Acceptance Criteria:**
- [ ] Given agents.yaml에 3개의 에이전트가 정의되어 있을 때, when `python -m agent_messaging`을 실행하면, then 3개의 Discord 봇이 동시에 시작된다
- [ ] Given asyncio.TaskGroup을 사용하여 에이전트를 실행할 때, when 하나의 에이전트가 에러를 발생시켜도, then 다른 에이전트에 영향을 주지 않는다
- [ ] Given 시스템 시작 시, when 각 에이전트의 상태가 로깅될 때, then 어떤 에이전트가 정상 시작되었고 어떤 에이전트가 실패했는지 확인할 수 있다

**Priority:** Should Have (P1)
**Effort:** M

---

##### Story 11: 메모리 인덱싱 (Tier 2)

**User Story:**
```
As a 시스템,
I want to md 파일의 내용을 SQLite FTS5로 인덱싱하도록,
So that 대량의 대화 기록에서 BM25 랭킹 기반 검색이 가능하다.
```

**Acceptance Criteria:**
- [ ] Given 새 md 파일이 생성/수정되면, when 인덱서가 감지할 때, then FTS5 테이블에 내용이 자동 인덱싱된다
- [ ] Given `search_memory("아키텍처 결정")`을 호출하면, when FTS5가 BM25 랭킹으로 검색할 때, then 관련도순으로 결과를 반환한다
- [ ] Given Python 내장 sqlite3를 사용할 때, when 추가 의존성 없이, then 인덱싱과 검색이 동작한다

**Priority:** Should Have (P1)
**Effort:** M

---

### Functional Requirements

| Req ID | Description | Priority | Status |
|--------|-------------|----------|--------|
| FR-001 | Discord 메시지 수신 → CLI stdin 전달 → stdout 응답 → Discord 전송 | Must Have | Open |
| FR-002 | YAML 기반 에이전트 정의 (봇 토큰, CLI 종류, 페르소나, 메모리 경로) | Must Have | Open |
| FR-003 | 모든 대화를 날짜별 md 파일로 자동 저장 | Must Have | Open |
| FR-004 | md 파일 YAML frontmatter 자동 생성 (date, tags, topic, summary) | Must Have | Open |
| FR-005 | ripgrep 기반 메모리 검색 (Tier 1) | Must Have | Open |
| FR-006 | Claude/Codex/Gemini CLI 통일 래퍼 | Must Have | Open |
| FR-007 | CLI 프로세스 자동 재시작 및 생명주기 관리 | Must Have | Open |
| FR-008 | 에이전트 시스템 프롬프트에 메모리 가이드 자동 주입 | Must Have | Open |
| FR-009 | 스트리밍 응답 (Discord 메시지 실시간 업데이트) | Should Have | Open |
| FR-010 | SQLite FTS5 인덱싱 (Tier 2) | Should Have | Open |
| FR-011 | md 파일 자동 분할 (500줄 초과 시) | Must Have | Open |
| FR-012 | 2000자 초과 Discord 메시지 자동 분할 | Must Have | Open |
| FR-013 | `/new` 및 CLI native slash command passthrough 지원 | Must Have | Open |
| FR-014 | `/new` 전까지 동일 대화 스코프에서 같은 CLI 세션 유지 | Must Have | Open |
| FR-015 | provider-native init doc (`CLAUDE.md`/`AGENTS.md`/`GEMINI.md`) 생성 또는 동기화 | Must Have | Open |
| FR-016 | Discord 응답은 CLI 원문을 그대로 전송하고 transport-level chunking만 허용 | Must Have | Open |
| FR-017 | 세션 스코프는 channel 기준이며 DM과 guild channel은 별도 세션, thread는 별도 세션을 만들지 않음 | Must Have | Open |
| FR-018 | 메모리 검색 기능은 agent가 호출 가능한 tool로 제공 | Must Have | Open |
| FR-019 | interactive native command는 Discord 대체 UX 또는 명시적 미지원으로 처리 | Must Have | Open |
| FR-020 | `agent_id`를 stable identifier로 사용하고 optional `display_name`을 별도로 지원 | Must Have | Open |
| FR-021 | `/cli` whitelist는 `/help`, `/stats`, `/model`로 시작한다 | Must Have | Open |
| FR-022 | `/model`은 Discord modal/select 기반 상호작용 UX를 제공한다 | Must Have | Open |
| FR-023 | frontmatter는 메시지 append와 동시에 갱신된다 | Must Have | Open |
| FR-024 | MVP Discord surface는 DM과 guild channel 대화만 지원한다 | Must Have | Open |

### Non-Functional Requirements

| Req ID | Category | Description | Target |
|--------|----------|-------------|--------|
| NFR-001 | Performance | Discord 메시지 수신 → CLI 전달 지연시간 | < 500ms |
| NFR-002 | Performance | ripgrep 메모리 검색 속도 (1000 md 파일) | < 100ms |
| NFR-003 | Reliability | CLI 프로세스 크래시 후 자동 복구 | 30초 이내 |
| NFR-004 | Reliability | 시스템 가동 시간 (로컬 머신 가동 중) | 99% |
| NFR-005 | Storage | md 파일 1개 최대 크기 | 500줄 (~50KB) |
| NFR-006 | Scalability | 동시 실행 에이전트 수 | 최소 5개 |
| NFR-007 | Security | Discord 토큰 및 API 키 환경변수 관리 | .env 파일 |
| NFR-008 | Maintainability | 새 CLI 모델 추가 시 필요한 코드 변경량 | 래퍼 1파일 |
| NFR-009 | Fidelity | Discord로 전달되는 응답의 의미 변화 | 0 (임의 요약/재서술 금지) |
| NFR-010 | Session UX | 명시적 `/new` 없이 세션이 초기화되는 비율 | 1% 미만 |

---

## Success Metrics

### Key Performance Indicators (KPIs)

#### Primary Metric (North Star)

**Metric:** 에이전트 응답 성공률
**Definition:** (성공적으로 Discord에 응답이 전달된 메시지 수 / 총 수신 메시지 수) * 100
**Current Baseline:** N/A (신규 시스템)
**Target:** 99% (MVP 런치 후 1개월)
**Why This Metric:** 시스템의 핵심 가치는 "메시지를 보내면 AI가 답한다"이며, 이것이 안정적으로 작동하는지 측정

#### Secondary Metrics

| Metric | Current | Target | Timeframe |
|--------|---------|--------|-----------|
| 평균 응답 시간 (메시지→응답) | N/A | < 10초 (짧은 질문) | MVP+1개월 |
| 메모리 검색 정확도 | N/A | 80%+ 관련 결과 | MVP+2개월 |
| CLI 프로세스 자동 복구 성공률 | N/A | 95% | MVP+1개월 |
| 일일 에이전트 대화 수 | N/A | 측정 시작 | MVP 런치 |

### Measurement Framework

**Framework Used:** HEART (개발 도구 특성에 맞게)

**Task Success:** 에이전트 응답 성공률 99%+
**Happiness:** 사용자 주관적 만족도 (정성적 피드백)
**Engagement:** 일일/주간 대화 수
**Adoption:** 정의된 에이전트 중 실제 활성 사용 에이전트 비율
**Retention:** 주간 재사용률

---

## Scope

### In Scope

**Phase 1 (MVP):**
- Discord 봇 ↔ CLI 프로세스 연결 파이프라인
- Discord 앱 명령 `/new` + `/cli`
- YAML 기반 에이전트 정의 및 멀티 에이전트 동시 실행
- Claude, Codex, Gemini CLI 래퍼
- 동일 대화 스코프 내 persistent session 유지
- md 파일 기반 대화 기록 자동 저장 (날짜별 디렉토리, YAML frontmatter)
- ripgrep 기반 메모리 검색 tool (Tier 1)
- 에이전트 페르소나 시스템 프롬프트 주입
- 에이전트 메모리 인지 프롬프트 주입
- provider-native init doc 생성 (`CLAUDE.md`/`AGENTS.md`/`GEMINI.md`)
- CLI 프로세스 생명주기 관리 (시작, 크래시 복구, 정상 종료)

**Phase 2 (Post-MVP):**
- SQLite FTS5 인덱싱 (Tier 2)
- Discord 메시지 스트리밍 업데이트
- 에이전트 간 메모리 공유 (선택적)
- 메모리 요약 자동 생성 (일별/주별)

### Out of Scope

**Explicitly Excluded:**
- 웹 대시보드 / 관리 UI — Discord를 인터페이스로 사용하여 불필요
- 다중 사용자 인증/권한 관리 — 개인 로컬 사용 우선
- Discord 외 메시징 플랫폼 (Slack, Telegram 등) — MVP 이후 검토
- Semantic search / 임베딩 기반 검색 (Tier 3) — 필요성 확인 후 추가
- 음성/영상 채널 통합 — 텍스트 기반에 집중
- AI 모델 자체 호스팅/학습 — 기존 CLI 도구 활용

### Future Considerations

- Telegram, Slack 등 추가 채널 지원
- 웹 기반 메모리 브라우저/검색 UI
- 에이전트 간 대화 (에이전트 A가 에이전트 B에게 질문)
- Semantic search (Tier 3) 추가
- MCP (Model Context Protocol) 서버로의 확장

---

## Technical Considerations

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Local Machine                         │
│                                                          │
│  ┌──────────┐    ┌──────────────────┐    ┌────────────┐ │
│  │ Discord  │◄──►│  Agent Manager   │◄──►│  Memory    │ │
│  │ Bot (1)  │    │                  │    │  Store     │ │
│  └──────────┘    │  ┌────────────┐  │    │            │ │
│                  │  │ Agent 1    │  │    │ /memory/   │ │
│  ┌──────────┐    │  │ - persona  │  │    │  agent1/   │ │
│  │ Discord  │◄──►│  │ - cli wrap │  │    │   2026-03/ │ │
│  │ Bot (2)  │    │  └────────────┘  │    │  agent2/   │ │
│  └──────────┘    │  ┌────────────┐  │    │   2026-03/ │ │
│                  │  │ Agent 2    │  │    └────────────┘ │
│  ┌──────────┐    │  │ - persona  │  │                   │
│  │ Discord  │◄──►│  │ - cli wrap │  │    ┌────────────┐ │
│  │ Bot (N)  │    │  └────────────┘  │    │  Search    │ │
│  └──────────┘    └──────────────────┘    │  Engine    │ │
│                                          │ (rg/FTS5)  │ │
│  ┌──────────┐    ┌──────────────────┐    └────────────┘ │
│  │Claude CLI│    │ Codex CLI        │                   │
│  │(subprocess)   │ (subprocess)     │                   │
│  └──────────┘    └──────────────────┘                   │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   Discord API          Local AI Models
   (WebSocket)          (Anthropic/OpenAI/Google)
```

### Technology Stack

**Runtime:**
- Python 3.11+ (asyncio.TaskGroup 지원)
- discord.py 2.x (비동기 Discord 봇)
- asyncio.create_subprocess_exec (CLI subprocess 관리)

**Configuration:**
- pydantic-settings (타입 안전 설정, 환경변수 통합)
- YAML (에이전트 정의 파일)
- python-dotenv (.env 파일 로딩)

**Memory & Search:**
- ripgrep (rg) — Tier 1 키워드 검색
- sqlite3 (Python 내장) — Tier 2 FTS5 인덱싱
- python-frontmatter — md 파일 YAML 헤더 파싱

**Development:**
- uv (패키지 관리)
- pytest + pytest-asyncio (테스팅)
- structlog (구조화 로깅)

### Data Flow: Discord Message → CLI → Response

```
sequenceDiagram
    participant U as Discord User
    participant B as Discord Bot
    participant A as Agent Manager
    participant C as CLI Process
    participant M as Memory Store
    participant S as Search Engine

    U->>B: 메시지 전송
    B->>A: on_message 이벤트
    A->>M: 사용자 메시지 저장 (md append)
    A->>C: stdin으로 메시지 전달
    C-->>A: stdout stream-json 응답
    A->>M: 에이전트 응답 저장 (md append)
    A->>B: 응답 텍스트 전달
    B->>U: Discord 메시지 전송

    Note over U,S: 메모리 검색이 필요한 경우
    U->>B: "지난주에 뭐 했어?"
    B->>A: on_message
    A->>C: 메시지 + 메모리 검색 tool 제공
    C->>S: ripgrep/FTS5 검색 호출
    S-->>C: 검색 결과 반환
    C-->>A: 검색 결과 기반 응답
    A->>B: 응답 전달
    B->>U: 답변 전송
```

### Command Routing Model

- **App-owned command:** `/new`는 애플리케이션 계층에서 직접 처리한다.
- **CLI passthrough command:** `/cli` generic command를 제공하고, 현재 channel 세션의 provider CLI에 whitelist된 원시 slash command를 전달한다.
- **Provider coverage:** 모든 provider 명령을 Discord app command로 1:1 등록하지 않고, generic passthrough 하나로 수용한다.
- **Whitelist:** MVP whitelist는 `/help`, `/stats`, `/model`이다.
- **Interactive command policy:** `/model`은 Discord modal/select 기반 UX로 지원한다. provider별 CLI가 요구하는 실제 모델 목록과 인자 형식은 adapter에서 흡수하되, Discord UX는 공통 목록으로 정규화하지 않고 provider별 옵션을 그대로 노출한다.
- **Non-whitelisted commands:** whitelist 밖의 native command는 MVP에서 명시적으로 차단한다.

### Session Model

- 기본값은 **persistent interactive session**이다.
- 세션 키는 **channel 기준**이다.
- DM과 guild channel은 서로 다른 세션이다.
- thread는 Discord API 상 별도 channel-like object이지만, 이 프로젝트에서는 `parent_channel_id`로 정규화하여 부모 channel 세션을 공유한다.
- 동일한 channel의 일반 메시지는 같은 CLI 세션으로 전달된다.
- `/new`만이 명시적 세션 리셋 트리거다.
- 프로세스 크래시 시에는 provider resume 기능이 있으면 복구를 우선 시도하고, 없거나 실패하면 새 세션을 시작하되 사용자에게 세션 손실을 알린다.
- 영구 메모리는 live session과 별도 계층이므로, 세션 리셋 이후에도 검색 가능한 상태를 유지한다.
- live session 상태는 memory markdown과 분리된 별도 session registry로 관리한다.

### CLI Wrapper Interface

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class CLIWrapper(ABC):
    """통일된 CLI 래퍼 계약 초안"""

    @abstractmethod
    async def start(self) -> None:
        """CLI 세션 시작 및 초기화 문서 로딩"""
        ...

    @abstractmethod
    async def send_user_message(self, message: str) -> AsyncIterator[str]:
        """일반 사용자 메시지를 현재 세션에 전달"""
        ...

    @abstractmethod
    async def send_native_command(
        self,
        command: str,
        args: dict | None = None,
    ) -> AsyncIterator[str]:
        """provider-native slash command 전달"""
        ...

    async def reset_session(self) -> None:
        """현재 세션 종료 후 다음 입력에서 새 세션 시작"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """CLI 프로세스 정상 종료"""
        ...

    @abstractmethod
    def session_scope_key(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: str | None = None,
    ) -> str:
        """channel/thread 정규화를 포함한 세션 키 계산"""
        ...

    @abstractmethod
    def supports_native_command(self, command: str) -> bool:
        """개별 native command 지원 여부"""
        ...

    @abstractmethod
    def is_alive(self) -> bool:
        """CLI 프로세스 생존 여부 확인"""
        ...
```

메모리 검색은 wrapper 책임이 아니라 runtime tool 책임이다.
- `memory_search`는 agent가 호출 가능한 내부 tool로 제공한다
- runtime은 tool contract를 관리하고, provider wrapper는 CLI session과 native command만 담당한다

- 위 코드는 **구체 클래스 설계가 아니라 계약 수준의 인터페이스 초안**이다.
- 실제 클래스 분해(`DiscordAdapter`, `SessionStore`, `MemoryIndex`, `ClaudeWrapper` 등)는 상세 아키텍처 단계에서 확정한다.

### Initialization Document Strategy

- 각 에이전트는 전용 `workspace_dir`를 가진다. CLI는 이 디렉토리를 current working directory로 사용해 provider-native instruction file을 자동 로드한다.
- `persona_file`이 있는 에이전트만 provider-native init doc를 생성한다. persona 파일이 없으면 기존 workspace 상태를 그대로 둔다.
- 문서 이름은 provider-native 규칙을 따른다.
  - Claude: `CLAUDE.md`
  - Codex: `AGENTS.md`
  - Gemini: `GEMINI.md`
- 작성 방식은 **공통 canonical template + provider-specific materialization**을 기본으로 한다.
  - 한 곳에서 persona, 메모리 디렉토리 구조, 검색 규칙, 응답 fidelity 규칙을 관리
  - 시작 시 provider별 파일명으로 렌더링 또는 동기화
- 초기화 문서에 넣을 내용:
  - `agent_id`와 optional `display_name`
  - 에이전트 페르소나
  - memory path 및 디렉토리 구조
  - memory search tool 사용법 (질문 유형, 날짜 필터링, 결과 해석)
  - tool 사용 원칙
  - Discord transport 규칙: 응답은 원문 그대로 전달되며, 시스템이 하는 유일한 변형은 chunking뿐임
  - frontmatter 생성 가이드라인 (`tags/topic/summary` 작성 원칙)
- 초기화 문서에 넣지 않을 내용:
  - 현재 Discord channel/user/session id
  - 이번 요청에만 해당하는 임시 컨텍스트
  - 방금 검색한 메모리 결과
- 위 동적 정보는 세션 시작 프롬프트 또는 런타임 메타데이터로 별도 주입한다.

### Memory File Structure

```
config/
├── agents.yaml
└── personas/
    ├── code-reviewer.md
    └── planner.md

workspace/
├── code-reviewer/
│   └── AGENTS.md               # Codex 에이전트용 초기화 문서
└── planner/
    └── GEMINI.md               # Gemini 에이전트용 초기화 문서

memory/
├── code-reviewer/
│   ├── 2026-03-07/
│   │   ├── conversation_001.md
│   │   └── conversation_002.md
│   └── 2026-03-08/
│       └── conversation_001.md
└── planner/
    └── 2026-03-07/
        └── conversation_001.md
```

### Session Persistence Storage

- session persistence는 **live conversation continuity**를 위한 계층이다.
- memory markdown은 **long-term recall**을 위한 계층이다.
- 둘의 차이:
  - session persistence: 현재 channel에 붙어 있는 provider session id, process 상태, 마지막 activity 시각, 현재 model 같은 운영 상태
  - memory system: 대화 본문, 검색용 frontmatter, 장기 보존 기록
- MVP 저장 구조:
  - canonical SSOT는 `sessions.json` 같은 단일 JSON metadata 파일이다
  - 런타임 메모리 registry는 이 JSON SSOT를 읽어 초기화하고, 상태 변경 시 즉시 다시 기록한다
  - 운영 중 사람이 현재 상태를 볼 수 있도록 이 파일은 읽기 쉬운 구조를 유지한다
  - MVP는 단일 프로세스만 이 파일을 소유하고 갱신한다
  - 파일 쓰기는 프로세스 내부 단일 lock 아래에서 temp file write 후 atomic replace로 처리한다
- channel별 저장 예시:

```json
{
  "discord:channel:12345": {
    "agent_id": "code-reviewer",
    "provider": "claude",
    "provider_session_id": "uuid-or-handle",
    "current_model": "opus",
    "last_activity_at": "2026-03-07T16:00:00Z",
    "status": "active"
  }
}
```

- 이 registry는 메시지 본문을 저장하지 않는다.
- 메시지 본문과 검색 메타데이터는 항상 markdown memory store가 담당한다.
- session 상태 변경 이벤트(`/new`, `/model`, provider session id 변경, crash recovery`)는 모두 이 SSOT를 즉시 갱신한다.
- 다중 프로세스 동시 쓰기 조정은 MVP 범위 밖이다.

### Security Requirements

- **Discord 토큰:** 환경변수 또는 .env 파일로만 관리. 절대 YAML/코드에 하드코딩 금지
- **CLI 인증:** 각 CLI의 기존 인증 메커니즘 활용 (claude: API key, codex: OAuth, gemini: Google auth)
- **메모리 파일:** 로컬 파일시스템 권한으로 보호. 민감한 대화는 사용자 책임
- **subprocess:** shell=False로 실행하여 커맨드 인젝션 방지

### Performance Requirements

- **메시지 전달 지연:** < 500ms (Discord → CLI subprocess)
- **ripgrep 검색:** < 100ms (1000개 md 파일 기준)
- **FTS5 검색:** < 10ms (인덱싱 완료 후)
- **동시 에이전트:** 최소 5개 에이전트 안정 실행
- **메모리 사용량:** 에이전트당 < 100MB (CLI 프로세스 제외)

---

## Design & UX Requirements

### User Experience Principles

- **Zero-config 시작:** `pip install` + `.env` 설정 + `agents.yaml` 작성 → 바로 실행
- **Discord-native:** Discord의 기존 UX를 그대로 활용하되, MVP surface는 DM과 guild channel에 집중
- **Raw response fidelity:** Discord 응답은 CLI 원문을 그대로 보존하고, transport 제약으로 인한 chunking만 허용
- **Transparent AI:** 에이전트가 검색 중이거나 처리 중일 때 Discord typing indicator 표시
- **Graceful degradation:** CLI 오류 시 사용자에게 명확한 에러 메시지 제공

### User Flows

**Primary Flow: 기본 대화**
1. 사용자가 Discord DM 또는 guild channel에서 에이전트 봇에게 메시지 전송
2. 봇이 typing indicator 표시
3. 현재 대화 스코프의 existing CLI session에 메시지 전달
4. CLI 응답을 Discord 메시지로 전송
5. 대화 내용이 자동으로 md 파일에 저장

**Primary Flow: `/new` 세션 리셋**
1. 사용자가 Discord에서 `/new` 실행
2. 시스템이 현재 대화 스코프의 CLI session 종료
3. 세션 메타데이터 초기화 및 확인 메시지 전송
4. 다음 일반 메시지에서 새 CLI session 시작

**Alternative Flow: provider slash command passthrough**
1. 사용자가 Discord에서 `/cli` 실행
2. 시스템이 명령이 whitelist(`/help`, `/stats`, `/model`)에 있는지 확인
3. `/help`, `/stats`는 현재 channel session에 직접 전달
4. `/model`은 provider별 옵션을 반영한 Discord modal/select로 값을 수집한 뒤 provider adapter를 통해 실행
5. modal submit은 `request_id`와 `session_key`가 일치하는 경우에만 적용
6. 결과를 원문 그대로 Discord에 전송

**Alternative Flow: 메모리 검색 대화**
1. 사용자가 과거 대화 관련 질문
2. 에이전트가 메모리 검색 tool 필요성 판단
3. tool이 ripgrep 기반으로 관련 md 파일 검색
4. 검색 결과를 컨텍스트에 포함하여 응답
5. 대화 내용 및 검색 활동 기록

메모리 검색 구현 원칙:
- `memory_search`는 runtime tool boundary 뒤에서 실행된다
- tool 입력은 `query`, `top_k`, `date_from`, `date_to`, `tags`
- tool 출력은 `results[path, date, topic, summary, snippet, score]`
- provider wrapper는 search backend를 직접 알지 않는다

**Error Flow: CLI 크래시**
1. CLI 프로세스 비정상 종료 감지
2. Discord에 "잠시만요, 에이전트를 재시작하고 있습니다" 메시지 전송
3. 자동 재시작 시도 (최대 3회)
4. 성공 시 마지막 메시지 재전달, 실패 시 에러 알림

---

## Timeline & Milestones

### Phases

| Phase | Deliverables | Start | End |
|-------|-------------|-------|-----|
| **Design** | PRD 확정, 기술 설계 문서, ADR | Week 1 | Week 2 |
| **Foundation** | 프로젝트 구조, 설정 시스템, CLI 래퍼 프로토콜 | Week 3 | Week 4 |
| **Core** | Discord 봇 연결, CLI subprocess 통합, 기본 메시지 파이프라인 | Week 5 | Week 7 |
| **Memory** | md 파일 저장, ripgrep 검색, 메모리 가이드 프롬프트 | Week 8 | Week 10 |
| **Integration** | 멀티 에이전트 실행, 페르소나 유지, E2E 테스트 | Week 11 | Week 12 |
| **Polish** | 에러 처리, 로깅, 문서화, 안정화 | Week 13 | Week 14 |

### Key Milestones

- **Week 2:** PRD 확정 + 기술 설계 완료
- **Week 4:** 단일 CLI 래퍼 작동 확인 (Claude)
- **Week 7:** Discord → CLI → Discord 기본 파이프라인 완성
- **Week 10:** 메모리 저장 + 검색 동작 확인
- **Week 12:** 3개 CLI + 멀티 에이전트 E2E 테스트 통과
- **Week 14:** MVP 릴리스

---

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation Strategy |
|------|--------|------------|---------------------|
| CLI 도구의 인터페이스 변경 (breaking change) | High | Medium | 래퍼 추상화로 변경 범위 격리. CLI 버전 고정 옵션 |
| CLI subprocess가 불안정 (메모리 누수, 행) | High | Medium | 프로세스 타임아웃 + 자동 재시작 + 헬스체크 |
| Discord API rate limiting | Medium | High | 메시지 큐잉 + 백오프 전략 + 스트리밍 간격 조절 |
| md 파일 대량 축적으로 검색 성능 저하 | Medium | Low | Tier 2(FTS5) 도입 + 날짜 범위 필터링 |
| 에이전트가 메모리 검색을 효과적으로 사용 못함 | Medium | Medium | 메모리 가이드 프롬프트 반복 개선 + 검색 도구 UX 개선 |
| provider별 interactive slash command 차이 | High | High | generic passthrough + provider adapter + interactive command whitelist |
| persistent session 복구 실패 | High | Medium | provider resume 우선 시도 + 실패 시 사용자 고지 + 영구 메모리로 보완 |
| provider-native init doc 드리프트 | Medium | Medium | canonical template에서 생성하여 중복 편집 방지 |
| frontmatter 동기 갱신 실패 | Medium | Medium | append와 frontmatter 갱신을 단일 write path로 묶고, 실패 시 재생성 루틴 제공 |

### Contingency Plans

**If CLI subprocess 방식이 불안정할 경우:**
- Claude: Anthropic SDK (Python)로 직접 전환 가능
- Codex/Gemini: 각각의 Python SDK로 전환 검토
- 판단 기준: 크래시율 > 5% 또는 타임아웃율 > 10%

**If 메모리 검색 품질이 낮을 경우:**
- Tier 2 (FTS5) 조기 도입
- frontmatter 태그 자동 생성 품질 개선
- 검색 결과 reranking 로직 추가

---

## Dependencies & Assumptions

### Dependencies

**Internal:**
- [ ] Python 3.11+ 설치
- [ ] Discord 봇 토큰 생성 (에이전트 수만큼)
- [ ] ripgrep (rg) 설치

**External:**
- [ ] Claude CLI 설치 및 인증 완료
- [ ] Codex CLI 설치 및 인증 완료 (사용 시)
- [ ] Gemini CLI 설치 및 인증 완료 (사용 시)
- [ ] Discord API 가용성

### Assumptions

- 사용자의 로컬 머신에 CLI 도구가 이미 설치되어 있음
- 로컬 머신이 인터넷에 연결되어 있음 (Discord API + AI model API 접근)
- 각 CLI 도구의 interactive session 또는 resume 기능이 최소 MVP 범위에서 안정적으로 동작함
- Discord 봇 토큰은 사용자가 직접 생성하여 제공
- 단일 사용자 사용이 기본 (멀티 유저 지원은 이후)
- channel 단위 세션을 계산할 수 있는 Discord 식별자(channel/DM)를 확보할 수 있음

---

## Open Questions

- [x] **CLI 세션 전략: ephemeral vs persistent?**
  - **Decision:** `persistent session + explicit /new reset + memory backup`
  - **Rationale:** 사용자가 명시적으로 `/new`를 호출하지 않는 이상 동일 세션을 유지해야 하며, provider의 native command 흐름도 살릴 수 있음

- [x] **Discord 메시지 형식: 일반 메시지 vs Embed?**
  - **Decision:** `일반 텍스트 only`
  - **Rationale:** "CLI agent 응답 그대로" 요구사항을 만족하려면 transport-level chunking 외의 표현 변형을 최소화해야 함

- [x] **초기화 문서 전략: provider-native file vs 단일 템플릿?**
  - **Decision:** `공통 canonical template + provider-native file 생성`
  - **Rationale:** Claude/Codex/Gemini가 각자 읽는 파일 이름을 존중하면서도 내용 드리프트를 막을 수 있음

- [x] **대화 스코프 단위는 무엇인가?**
  - **Decision:** `channel 기준`
  - **Rationale:** 다른 channel이면 다른 세션, DM과 guild channel도 분리, thread는 세션 키와 무관

- [x] **provider passthrough Discord 명령이 필요한가?**
  - **Decision:** `필요함`
  - **Rationale:** 사용자가 CLI native `/` 명령, 특히 `/model` 같은 상태 제어 명령을 Discord에서 호출할 수 있어야 함

- [x] **interactive native command를 어디까지 지원할 것인가?**
  - **Decision:** `MVP에서 /model을 Discord modal/select로 지원`
  - **Rationale:** `/model`은 제품 핵심 제어 명령이고, 단순 passthrough보다 Discord 친화적인 상호작용이 필요함

- [x] **메모리 frontmatter 생성 주체?**
  - **Decision:** `현재 대화를 수행한 agent가 생성`
  - **Rationale:** 실제 대화 맥락을 가장 잘 이해하는 주체가 tags/topic/summary를 만들고, 시스템은 형식 가이드라인만 제공하는 편이 검색 품질이 높음

- [x] **에이전트에게 메모리 검색 도구를 어떻게 제공?**
  - **Decision:** `agent가 호출 가능한 tool로 제공`
  - **Rationale:** 사용자가 "전에 얘기했던 ..."처럼 물었을 때 agent가 자율적으로 검색해 오도록 만들기 가장 자연스러움

- [x] **메모리 search tool의 질의/응답 스키마는 무엇인가?**
  - **Decision:** `중간형 schema`
  - **Input:** `query`, `top_k`, `date_from`, `date_to`, `tags`
  - **Output:** `results[path, date, topic, summary, snippet, score]`
  - **Rationale:** 날짜성 질문과 태그 필터를 지원하면서도 MVP에 과도한 복잡성을 들이지 않는 균형점

- [x] **session persistence metadata를 어디에 저장할 것인가?**
  - **Decision:** `JSON SSOT 파일 + 런타임 메모리 registry`
  - **Rationale:** channel별 현재 세션 상태를 항상 최신으로 기록하고 사람이 직접 볼 수 있게 하려면 단일 JSON SSOT가 가장 단순하고 명확함

---

## Appendix

### Glossary

- **Agent:** 하나의 Discord 봇 + CLI 모델 + 페르소나 + 메모리를 가진 독립적인 AI 어시스턴트 단위
- **CLI Wrapper:** Claude/Codex/Gemini CLI를 통일된 인터페이스로 추상화하는 Python 클래스
- **Memory Store:** md 파일 기반의 영구 대화 기록 저장소
- **Persona:** 에이전트의 성격, 역할, 전문성을 정의하는 시스템 프롬프트
- **Frontmatter:** md 파일 상단의 YAML 메타데이터 (날짜, 태그, 토픽, 요약)
- **Compaction:** CLI 모델이 컨텍스트 윈도우 한계에 도달했을 때 이전 대화를 요약/압축하는 과정
- **Tier 1/2/3:** 메모리 검색 전략의 복잡도 수준 (ripgrep → FTS5 → semantic search)

### Related Documents

- [OpenClaw GitHub](https://github.com/openclaw/openclaw) — 참조 시스템
- [Letta/MemGPT](https://github.com/letta-ai/letta) — 메모리 아키텍처 참조
- [discord.py Documentation](https://discordpy.readthedocs.io/) — Discord 봇 프레임워크

### Change Log

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-07 | taco | Initial draft |
| 1.1 | 2026-03-07 | Codex | Slash command, persistent session, raw response fidelity, init doc strategy refinement |

## Supplemental Planning Artifacts

### Findings & Decisions

#### Requirements
- Extend the PRD with Discord slash command support for CLI-agent commands.
- Preserve the same CLI session unless the user explicitly invokes `/new`.
- Send Discord responses as a faithful passthrough of the CLI output, with only Discord-driven chunking when needed.
- Design how each CLI agent reads startup guidance and memory/tool instructions.
- Technically review feasibility and ask for any missing product decisions.

#### Research Findings
- The current PRD already defines a strong MVP around Discord bot messaging, YAML-configured agents, persistent markdown memory, and CLI wrappers.
- New requirements mainly affect command routing, conversation/session lifecycle, output formatting guarantees, and bootstrap/instruction file strategy.
- `claude --help` confirms resumable sessions (`--continue`, `--resume`, `--session-id`) and project/local settings support.
- `codex --help` confirms interactive sessions, explicit resume/fork commands, and non-interactive `exec`; session continuity is feasible but needs wrapper strategy.
- Local `gemini --help` did not return usable output during inspection, so Gemini capabilities need confirmation from official docs before locking the design.
- Anthropic documents built-in slash commands including `/init`, `/memory`, `/clear`, and custom project commands stored as Markdown files under `.claude/commands/`.
- Anthropic documents hierarchical `CLAUDE.md` loading and explicit `/memory` editing; `CLAUDE.md` is suitable for persistent project instructions, but dynamic runtime state still needs separate injection.
- Gemini CLI docs describe built-in slash commands, `/chat` save/resume, `/resume`, `/restore`, and hierarchical `GEMINI.md` context loading.
- Gemini CLI docs allow customizing the context filename list, which means Gemini can be configured to also read `AGENTS.md`, but the default and most portable choice remains `GEMINI.md`.
- Gemini CLI context files are instructional context, not a guarantee that the CLI will autonomously execute tool calls on startup; they should describe tool usage, not rely on implicit tool execution.
- OpenAI’s AGENTS.md standard is described as being used by Codex. Combined with the current local Codex environment using AGENTS.md instructions, AGENTS.md is a reasonable provider-native instruction file for Codex.
- Codex local help confirms persistent session primitives (`resume`, `fork`, `exec --resume`, `--ephemeral`), but did not expose a documented native in-session slash-command catalog from help output alone.

#### Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Validate CLI-specific behavior before finalizing PRD language | Slash commands and instruction-file behavior are tool-specific and change over time |
| Treat Discord output formatting as transport-level only by default | This preserves CLI output fidelity while still respecting Discord message size constraints |
| Recommend persistent interactive sessions as the MVP default | Requirement 2 explicitly prefers same-session continuity until `/new` |
| Recommend app-level command routing with a generic provider passthrough command | Discord slash commands are statically registered, while provider-native command catalogs differ and can change |
| Recommend generated provider-native init docs from one canonical template | This preserves native loading behavior for Claude/Codex/Gemini without duplicating authoring effort |
| Scope sessions by channel | User specified that different channels and DMs must map to different sessions, while threads should not create a new session |
| Include provider slash-command passthrough in MVP | The user needs Discord to forward native CLI slash commands, including model-control commands |
| Expose memory retrieval as an agent-callable tool | This best supports natural user prompts like "전에 얘기했던..." without requiring explicit user commands |
| Treat interactive native commands as a separate compatibility layer | Commands like `/model` may require provider-specific Discord UX adapters rather than raw passthrough alone |
| Let the active agent generate `tags/topic/summary` with guidelines | The acting agent has the best local understanding of the conversation semantics for retrieval metadata |
| Distinguish `agent_id` from display name | Internal storage and memory paths need a stable slug even if the human-facing bot name changes |

#### Issues Encountered
| Issue | Resolution |
|-------|------------|
| Repository is not a git repo | Proceed using direct file inspection and patch-based edits |
| `gemini --help` did not produce usable output | Confirm Gemini behavior from official documentation instead of guessing |

#### Resources
- `/Users/taco/projects/ai-agent-messaging/docs/plans.md`
- `/Users/taco/.agents/skills/prd-generator/SKILL.md`
- `/Users/taco/.agents/skills/planning-with-files/SKILL.md`
- https://docs.anthropic.com/en/docs/claude-code/slash-commands
- https://docs.anthropic.com/en/docs/claude-code/memory
- https://geminicli.com/docs/cli/
- https://geminicli.com/docs/cli/commands
- https://geminicli.com/docs/cli/gemini-md
- https://geminicli.com/docs/cli/checkpointing
- https://openai.com/index/agentic-ai-foundation/

#### Visual/Browser Findings
- None yet.

### MVP Todo

- [x] Create package skeleton and project metadata
- [x] Add settings loader and agent registry
- [x] Add `sessions.json` SSOT with atomic write semantics
- [x] Add channel/thread session normalization logic
- [x] Add `/new` and `/cli` command routing primitives
- [x] Add raw-response transport chunking
- [x] Add markdown memory writer and frontmatter updater
- [x] Add `memory_search` runtime tool
- [x] Add provider wrapper base and provider adapters
- [x] Add provider-native init doc generation
- [x] Add application service to orchestrate sessions, providers, memory, and commands
- [x] Add runnable tests for core MVP behavior
- [x] Wire `discord.py` gateway to the application service
- [x] Replace test-double providers with real Claude/Codex/Gemini subprocess adapter scaffolds

### Task Plan

#### Goal
Refine and organize the planning documents for the Discord-wrapped CLI agent system under `docs`.

#### Current Phase
Phase 5

#### Phases

##### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify current PRD structure and gaps
- [x] Document findings in the planning artifacts section
- **Status:** complete

##### Phase 2: Technical Validation
- [x] Verify current CLI capabilities and constraints
- [x] Resolve command/session/init-doc design options
- [x] Identify open questions that materially affect implementation
- **Status:** complete

##### Phase 3: PRD Revision
- [x] Update PRD requirements and architecture
- [x] Add new stories, acceptance criteria, and open questions
- [x] Align scope and technical considerations with revised design
- **Status:** complete

##### Phase 4: Verification
- [x] Review PRD for internal consistency
- [x] Ensure new requirements are implementation-ready
- [x] Capture remaining assumptions and risks
- **Status:** complete

##### Phase 5: Delivery
- [x] Summarize key changes
- [x] Call out unresolved questions for the user
- [x] Deliver updated document state
- **Status:** complete

#### Key Questions
1. How should Discord slash commands map to each CLI's native slash or session commands?
2. Which session persistence model is viable across Claude, Codex, and Gemini without degrading UX?
3. What initialization document layout gives the strongest portability across CLI agents?

#### Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use PRD refinement rather than a fresh rewrite | Existing PRD already has a strong MVP structure and only needs concrete additions |
| Use file-based planning artifacts for this task | The work spans exploration, technical validation, PRD edits, and follow-up questions |
| Set persistent sessions as the default PRD direction | The user explicitly wants session continuity until `/new` |
| Use provider-native init doc generation from one canonical source | This matches Claude/Codex/Gemini loading behavior while avoiding duplicated authoring |
| Model Discord command support as app-owned commands plus generic provider passthrough | Static Discord command registration does not fit dynamic per-provider command catalogs |

#### Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `git status` failed because the directory is not a git repository | 1 | Continue without git-based change inspection |

#### Notes
- Re-read this plan before major decisions.
- Log newly discovered CLI constraints before editing the PRD.

### Progress Log

#### Session: 2026-03-07

##### Phase 1: Requirements & Discovery
- **Status:** complete
- **Started:** 2026-03-07 15:40
- Actions taken:
  - Read the current PRD and summarized its MVP, architecture, and open design questions.
  - Loaded the `prd-generator` and `planning-with-files` skills from `~/.agents/skills`.
  - Inspected the workspace structure and planning templates.
- Files created/modified:
  - `docs/plans.md` (task plan section, created before consolidation)
  - `docs/plans.md` (findings section, created before consolidation)
  - `docs/plans.md` (progress log section, created before consolidation)

##### Phase 2: Technical Validation
- **Status:** complete
- Actions taken:
  - Inspected local CLI help output for Claude and Codex to validate session and command capabilities.
  - Identified the need to verify Gemini and CLI-specific init-document behavior from official docs.
  - Verified Anthropic slash command and `CLAUDE.md` behavior from official docs.
  - Verified Gemini slash commands, `GEMINI.md`, and checkpoint/session docs from official docs.
  - Formed a provisional architecture: persistent interactive sessions, app-owned `/new`, and generic provider-command passthrough.
- Files created/modified:
  - `docs/plans.md` (task plan section updated before consolidation)
  - `docs/plans.md` (findings section updated before consolidation)

##### Phase 3: PRD Revision
- **Status:** complete
- Actions taken:
  - Updated the PRD to add slash-command routing, persistent session rules, raw response fidelity requirements, and provider-native init document strategy.
  - Expanded agent config examples with `workspace_dir`, `session_mode`, and `persona_file`.
  - Added new functional and non-functional requirements tied to `/new`, passthrough commands, and response fidelity.
- Files created/modified:
  - `docs/plans.md` (PRD section updated before consolidation)

##### Phase 4: Verification
- **Status:** complete
- Actions taken:
  - Re-read the modified PRD for consistency across stories, requirements, technical considerations, and open questions.
  - Fixed the broken Data Flow code block after inserting new design sections.
  - Applied user decisions for channel-scoped sessions, optional passthrough removal, and tool-based memory search.
  - Reintroduced CLI slash-command passthrough after the user clarified it is required, and added interactive-command handling notes for `/model`.
  - Locked frontmatter generation to the acting agent and clarified stable `agent_id` vs optional `display_name`.
- Files created/modified:
  - `docs/plans.md` (PRD section updated before consolidation)

#### Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Claude CLI help | `claude --help` | Show supported options and session controls | Help output returned with resume/session/settings options | PASS |
| Codex CLI help | `codex --help` | Show supported options and session controls | Help output returned with resume/fork/exec options | PASS |
| Gemini CLI help | `gemini --help` | Show supported options | No usable output captured | BLOCKED |

#### Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-03-07 15:47 | `git status` failed outside a git repo | 1 | Continued without git metadata |
| 2026-03-07 16:03 | PRD Data Flow section code block was malformed after edit | 1 | Reordered the sequence diagram and new subsections |

#### 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Delivery complete; awaiting user decisions on remaining open questions |
| Where am I going? | Lock conversation scope and passthrough UX, then move to implementation planning or docs refinement |
| What's the goal? | Refine and organize the PRD and planning documents for the new command/session/init-document requirements |
| What have I learned? | The design now assumes channel-scoped persistent sessions, `/new` as the only MVP slash command, and tool-based memory retrieval |
| What have I done? | Read the PRD, loaded skills, created planning files, verified CLI capabilities, and updated the PRD twice with concrete product decisions |

### Manual Test

#### 1. Install runtime dependencies

```bash
python3 -m pip install -e '.[discord]'
```

#### 2. Prepare environment

Create `.env` from [.env.example](/Users/taco/projects/ai-agent-messaging/.env.example):

```bash
cp .env.example .env
```

Set:
- `CODE_REVIEWER_DISCORD_TOKEN`

#### 3. Prepare agent config

Run [init.sh](/Users/taco/projects/ai-agent-messaging/setup/init.sh) first, then edit [agents.yaml](/Users/taco/projects/ai-agent-messaging/config/agents.yaml):
- `provider`
- `cli_args`
- `workspace_dir`
- `memory_dir`

Examples:
- provider별 기본 실행 명령은 내부 adapter가 결정
- provider별 PTY 사용 여부도 내부 adapter가 결정

#### 4. Start the app

```bash
PYTHONPATH=src python3 -m agent_messaging --config config/agents.yaml
```

Expected:
- bot logs in successfully
- `workspace_dir` contains provider init doc
- `runtime/sessions.json` appears after first interaction

#### 5. Discord checks

Run these in order:
1. DM the bot with a normal message.
2. Send a second DM and confirm the same session is reused.
3. Run `/new` and confirm the next message starts a new session.
4. Run `/cli raw:/help`
5. Run `/cli raw:/stats`
6. Run `/cli raw:/model` and choose a model from the select UI.
7. In a guild channel, send a normal message and confirm a reply.
8. In a thread under that channel, send a message and confirm the parent channel session is reused.

#### 6. Files to inspect

- `runtime/sessions.json`
- `memory/<agent_id>/<YYYY-MM-DD>/conversation_001.md`
- `workspace/<agent_id>/<PROVIDER_DOC>.md`

#### 7. Failure checks

- If the provider executable is missing, Discord should show a clear startup error.
- If provider output takes too long, Discord should show the delayed-response notice.
