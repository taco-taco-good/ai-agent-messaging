# AI Agent Messaging

로컬 CLI AI 도구(Claude, Codex, Gemini)를 Discord 봇으로 연결하는 멀티 에이전트 메시징 시스템입니다.

에이전트별 페르소나, 채널 단위 세션, 마크다운 기반 메모리 저장을 지원합니다.

## 프로젝트 배경과 필요성

이 프로젝트는 각 AI provider의 API를 다시 감싸는 대신, 사용자가 평소 터미널에서 직접 쓰는 로컬 CLI를 그대로 호출하는 방향으로 설계했습니다.

그 이유는 실제 활용 맥락이 이미 로컬 환경 위에 쌓여 있기 때문입니다. provider CLI를 직접 실행하면 로컬에 로그인된 계정 상태, 작업 디렉터리, 설치된 도구, provider별 기본 워크플로우를 그대로 활용할 수 있습니다.

특히 Codex 같은 로컬 CLI 에이전트는 workspace 안의 `AGENTS.md`, 로컬 skill, 메모리 검색 스크립트, 사용자 맞춤 설정처럼 로컬 파일 시스템에 설치된 컨텍스트를 함께 사용하는 경우가 많습니다. 이 프로젝트는 그런 환경을 별도 재구현하지 않고, Discord를 메시지 인터페이스로 추가해서 기존 로컬 작업 방식을 확장하는 데 목적이 있습니다.

즉, 이 시스템의 필요성은 "Discord에서 AI를 부른다"에만 있지 않습니다. 이미 로컬 CLI 중심으로 구축한 개인용 에이전트 환경을 유지한 채, 같은 능력을 원격 메시징 채널에서도 이어서 사용할 수 있게 만드는 데 있습니다.

## 주요 기능

- 멀티 프로바이더: `claude`, `codex`, `gemini`를 같은 인터페이스로 래핑
- 채널별 세션 유지: Discord DM/채널 단위로 대화 세션 관리
- 영구 메모리: 날짜별 markdown 파일에 대화와 메타데이터 저장
- 에이전트 페르소나: agent별 persona markdown 파일 지원
- 모델 전환: Discord `/model`로 provider별 모델 카탈로그 선택
- 안정성: watchdog, 자동 재시작, 유휴 wrapper 정리

## 아키텍처

```text
Discord Gateway  ->  Application Layer  ->  Provider Wrapper  ->  CLI Process
     |                    |                      |
     |                    +-> Session Manager    +-> claude / codex / gemini
     |                    +-> Memory Writer
     |                    +-> Runtime Tools
     v
 Discord API
```

## 빠른 시작

### 1. 사전 요구사항

- Python 3.9+
- 각 provider CLI가 로컬에 설치되어 있어야 합니다.
  - `claude`
  - `codex`
  - `gemini`
- 각 agent마다 Discord Bot 토큰이 필요합니다.

### 2. 대화형 setup 실행

```bash
git clone <repository-url>
cd ai-agent-messaging

./setup/init.sh
```

`./setup/init.sh`가 한 번에 처리합니다.

- 디렉터리 생성
- `setup/agents.yaml.template` -> `config/agents.yaml` 복사
- `.venv` 생성
- 패키지 설치
- 색상 있는 curses 기반 setup TUI 실행
- macOS에서는 launchd 백그라운드 서비스 등록 및 자동 시작 설정

wizard를 마치면 `config/agents.yaml`이 실제 값으로 채워집니다.

TUI 조작:

- `A`: agent 추가/수정
- `S`: 저장 후 계속 진행
- `Q`: 취소
- 입력 화면에서 `Esc`: 현재 입력 취소

TTY 환경이 아니거나 plain prompt가 필요하면:

```bash
.venv/bin/python setup/bootstrap.py --config config/agents.yaml --no-tui
```

### 3. 생성되는 설정 예시

```yaml
agents:
  codex:
    display_name: codex
    provider: codex
    discord_token: <DISCORD_BOT_TOKEN>
    model: gpt-5.4
    persona_file: ./personas/codex.md
    workspace_dir: ../workspace/codex
    memory_dir: ../memory/codex
    cli_args:
      - --dangerously-bypass-approvals-and-sandbox
```

### 4. 설정 필드

| 필드 | 설명 |
|---|---|
| `display_name` | Discord와 로그에 표시되는 이름 |
| `provider` | `claude`, `codex`, `gemini` 중 하나 |
| `discord_token` | 해당 agent의 Discord Bot 토큰 |
| `model` | 기본 모델 |
| `persona_file` | 페르소나 markdown 파일 경로 |
| `workspace_dir` | 실제 CLI 실행 작업 디렉터리 |
| `memory_dir` | 대화 메모리 저장 디렉터리 |
| `cli_args` | provider CLI에 추가로 넘길 인자 |

### 5. 페르소나 작성

`config/personas/` 아래에 agent별 markdown 파일을 작성합니다.

예:

```md
# codex

시스템의 총괄 관리자이자 사용자의 비서로 행동한다.
충직하고 꼼꼼하며 완벽을 추구한다.
```

wizard는 `config/personas/<agent>.md` 파일도 기본 내용으로 만들어줍니다.

앱 시작 시 persona 파일이 있으면 provider별 초기 문서가 `workspace/<agent>/` 아래에 생성됩니다.

### 6. 수동 실행

```bash
source .venv/bin/activate
agent-messaging --config config/agents.yaml
```

macOS에서 launchd 등록을 선택했다면 백그라운드로 자동 시작됩니다.

현재 로컬 상태를 확인하려면:

```bash
.venv/bin/python setup/status.py
```

JSON 형식이 필요하면:

```bash
.venv/bin/python setup/status.py --json
```

확인 가능한 항목:

- `config/agents.yaml` 존재 여부
- `.venv` 준비 여부
- 등록된 agent 목록과 provider/model
- stdout/stderr 로그 경로
- macOS `launchd` 등록 및 실행 상태

## Discord 사용법

### 메시지

- DM: 봇에게 직접 메시지를 보내면 응답합니다.
- 서버 채널: 봇을 멘션한 뒤 메시지를 보내면 응답합니다.

### 슬래시 커맨드

| 커맨드 | 설명 |
|---|---|
| `/new` | 현재 채널 세션 초기화 |
| `/help` | provider 도움말 |
| `/stats` | 현재 선택 모델, 확인된 실제 모델, 세션 정보 표시 |
| `/model` | provider별 모델 선택 UI 표시 |

## 지원 프로바이더

| 프로바이더 | 실행 방식 | 비고 |
|---|---|---|
| Claude | headless prompt 실행 | 세션 로그 기반 exact model 확인 |
| Codex | `codex exec` 기반 실행 | Codex thread id를 세션으로 유지 |
| Gemini | headless prompt 실행 | chat log 기반 exact model 확인 |

## 메모리 시스템

대화는 agent별 날짜 디렉터리에 markdown으로 저장됩니다.

```text
memory/
  codex/
    2026-03-08/
      conversation_001.md
```

각 문서에는 frontmatter 메타데이터가 포함됩니다.

- `date`
- `agent`
- `display_name`
- `participants`
- `message_count`
- `tags`
- `topic`
- `summary`

메타데이터는 현재 추가 모델 호출 없이 로컬 규칙 기반으로 생성됩니다.

## 프로젝트 구조

```text
ai-agent-messaging/
├── setup/
│   ├── agents.yaml.template
│   ├── bootstrap.py
│   ├── init.sh
│   └── status.py
├── config/             # 로컬 설정, persona 파일
├── runtime/            # 세션 상태 저장
├── memory/             # 대화 메모리 저장
├── workspace/          # 실제 provider 작업 디렉터리
├── docs/
│   ├── plans.md
│   └── architecture.md
├── src/
│   └── agent_messaging/
│       ├── application/
│       ├── config/
│       ├── core/
│       ├── gateway/
│       ├── memory/
│       ├── observability/
│       ├── providers/
│       ├── runtime/
│       └── services/
├── tests/
└── pyproject.toml
```

## 개발

### 테스트

현재 저장소의 기본 검증은 `unittest` 기준으로 맞춰져 있습니다.

```bash
source .venv/bin/activate
python -m unittest discover -s tests -q
```

### 로깅

| 환경변수 | 설명 | 기본값 |
|---|---|---|
| `LOG_LEVEL` | 로그 레벨 | `INFO` |
| `LOG_FORMAT` | `text` 또는 `json` | `text` |

## 멀티 에이전트

여러 agent를 동시에 둘 수 있고, 각 agent는 독립된 Discord 봇 토큰과 workspace/memory를 가집니다.

```yaml
agents:
  codex:
    provider: codex
    discord_token: <CODEX_BOT_TOKEN>
    model: gpt-5.4
    workspace_dir: ../workspace/codex
    memory_dir: ../memory/codex

  claude:
    provider: claude
    discord_token: <CLAUDE_BOT_TOKEN>
    model: sonnet
    workspace_dir: ../workspace/claude
    memory_dir: ../memory/claude

  gemini:
    provider: gemini
    discord_token: <GEMINI_BOT_TOKEN>
    model: gemini-2.5-flash
    workspace_dir: ../workspace/gemini
    memory_dir: ../memory/gemini
```
