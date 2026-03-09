---
id: daily_ai_briefing
summary: Generate Taco's morning AI, homelab, and automation briefing.
allowed_tools:
  - job.sqlite_query
  - job.run_agent_prompt
  - job.persist_text
  - job.persist_memory
---

## Goal
타코를 위한 아침 브리핑을 작성합니다.

## Instructions
- AI 서비스, homelab, AI 자동화에 집중합니다.
- 빌드 시스템이나 현재 업무 성격이 강한 주제는 제외합니다.
- 중복 내용은 합치고, 과한 hype는 경계합니다.
- 링크가 있으면 마지막에 참고 링크를 짧게 정리합니다.

## Output Format
1. 한 줄 요약
2. 핵심 트렌드 3개
3. 오늘의 인사이트 2개
4. 오늘 실험해볼 만한 것 1~2개
