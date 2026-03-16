# AI Agent Messaging

Discord에서 로컬 AI CLI 에이전트를 호출하고, 채널별 세션과 markdown 메모리를 유지하는 멀티 에이전트 메시징 시스템입니다.

이 프로젝트는 AI provider API를 다시 감싸지 않습니다. 대신 새 컴퓨터에서도 평소 터미널에서 직접 쓰는 `codex`, `claude`, `gemini` CLI를 그대로 실행해서, 로컬 로그인 상태와 workspace 문맥을 Discord로 확장합니다.

## 무엇을 해주는가

- Discord DM/채널별 대화 세션 유지
- agent별 persona markdown 지원
- 날짜별 markdown 메모리 저장
- session snapshot 기반 작업 재개
- provider별 `/help`, `/stats`, `/model` 슬래시 커맨드
- background job, skill, external tool 로딩
- macOS `launchd` 자동 등록 지원

## 새 컴퓨터 셋업

이 섹션만 따라가면 새 컴퓨터에서도 실행할 수 있게 작성했습니다.

### 1. 공통 선행 조건

- `git`
- `Python 3.10+`
- `node` + `npm`
- Discord Bot 토큰
- 사용할 provider CLI

`claude`, `codex`, `gemini`를 전부 설치할 필요는 없습니다. `config/agents.yaml`에 등록할 provider만 설치하면 됩니다.

### 2. provider CLI 설치 및 로그인

프로젝트는 provider CLI가 실제로 PATH에서 실행되는 것을 전제로 합니다.

#### Codex

- 설치:

```bash
npm install -g @openai/codex
```

- 설치 후 `codex`를 한 번 실행해서 로그인 또는 초기 인증을 마치세요.
- 공식 문서: https://developers.openai.com/codex/cli

#### Claude Code

- 설치:

```bash
npm install -g @anthropic-ai/claude-code
```

- 설치 후 `claude`를 한 번 실행해서 로그인 또는 초기 인증을 마치세요.
- 공식 문서: https://docs.anthropic.com/en/docs/claude-code/getting-started

#### Gemini CLI

- 설치:

```bash
npm install -g @google/gemini-cli
```

- 설치 후 `gemini`를 한 번 실행해서 로그인 또는 초기 인증을 마치세요.
- 공식 문서: https://github.com/google-gemini/gemini-cli

### 3. Discord Bot 준비

agent 하나당 Bot 하나를 쓰는 구성이 가장 단순합니다.

필수 준비:

1. Discord Developer Portal에서 Bot 생성
2. Bot token 발급
3. 서버에서 쓸 경우 Bot 초대
4. Message Content Intent 활성화
5. `bot`, `applications.commands` 권한으로 초대

Message Content Intent가 꺼져 있으면 서버 채널에서 멘션 메시지를 제대로 처리하지 못할 수 있습니다.

### 4. 저장소 clone

```bash
git clone <repository-url>
cd ai-agent-messaging
```

### 5. 초기 setup 실행

```bash
./setup/init.sh
```

이 스크립트가 다음을 처리합니다.

- `config/`, `jobs/`, `skills/`, `agents/`, `tools/`, `runtime/`, `memory/`, `workspace/` 생성
- `setup/agents.yaml.template`을 `config/agents.yaml`로 복사
- `.venv` 생성
- editable install 수행
- interactive setup wizard 실행
- macOS에서는 선택적으로 `launchd` 등록

TTY가 아닌 환경이면 plain prompt 모드로 실행하세요.

```bash
.venv/bin/python setup/bootstrap.py --config config/agents.yaml --no-tui
```

### 6. wizard에서 입력할 값

각 agent에 대해 아래 필드를 채우면 됩니다.

| 필드 | 설명 |
|---|---|
| `display_name` | Discord와 로그에 표시될 이름 |
| `provider` | `codex`, `claude`, `gemini` 중 하나 |
| `discord_token` | 해당 Bot token |
| `model` | 기본 모델 |
| `persona_file` | persona markdown 경로 |
| `workspace_dir` | 실제 CLI 실행 작업 디렉터리 |
| `memory_dir` | 대화 메모리 저장 디렉터리 |
| `cli_args` | provider CLI 추가 인자 |

root 설정 필드:

| 필드 | 설명 |
|---|---|
| `runtime_dir` | 세션/로그/runtime 파일 저장 디렉터리 |
| `jobs_dir` | background job YAML 디렉터리 |
| `skills_dir` | skill markdown 디렉터리 |
| `subagents_dir` | subagent persona markdown 디렉터리 |
| `tools_dir` | external tool manifest/scripts 디렉터리 |
| `job_store_path` | scheduler/job 상태를 저장할 SQLite 경로 |

경로는 `config/agents.yaml` 기준 상대 경로로 해석됩니다.

### 7. 최소 설정 예시

아래는 `codex` 하나만 사용하는 가장 단순한 예시입니다.

```yaml
runtime_dir: ../runtime
jobs_dir: ../jobs
skills_dir: ../skills
subagents_dir: ../agents
tools_dir: ../tools
job_store_path: ../runtime/jobs.sqlite

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

provider별 기본 `cli_args`는 wizard가 자동으로 제안합니다.

### 8. persona 파일 준비

`config/personas/<agent>.md` 파일을 작성하세요.

예:

```md
# codex

당신은 개발에 진심인 시니어 개발자입니다.
정확성, 유지보수성, 검증 가능성을 우선합니다.
```

wizard를 마치면 기본 persona 파일도 자동 생성됩니다.

앱 시작 시 persona 파일이 있으면 provider 초기 문서가 `workspace/<agent>/` 아래에 생성됩니다.

### 9. 실행

수동 실행:

```bash
source .venv/bin/activate
agent-messaging --config config/agents.yaml
```

상태 확인:

```bash
.venv/bin/python setup/status.py
```

JSON 상태 확인:

```bash
.venv/bin/python setup/status.py --json
```

macOS `launchd` 재시작:

```bash
.venv/bin/python setup/restart.py
```

macOS에서 wizard 중 `launchd` 설치를 선택했다면 부팅 후 자동 시작됩니다. 다른 플랫폼에서는 수동 실행 기준으로 사용하면 됩니다.

## Discord 사용 방법

### DM

봇에게 직접 메시지를 보내면 응답합니다.

### 서버 채널

봇을 멘션한 뒤 메시지를 보내면 응답합니다.

### 슬래시 커맨드

| 커맨드 | 설명 |
|---|---|
| `/new` | 현재 채널 세션 초기화 |
| `/help` | provider 도움말 |
| `/stats` | 현재 선택 모델, 확인된 실제 모델, 세션 정보 표시 |
| `/model` | provider별 모델 선택 UI 표시 |

## 어떻게 저장되는가

### 메모리

대화는 agent별 날짜 디렉터리에 markdown으로 저장됩니다.

```text
memory/
  codex/
    2026-03-08/
      conversation_001.md
```

frontmatter 메타데이터:

- `date`
- `agent`
- `display_name`
- `participants`
- `message_count`
- `tags`
- `topic`
- `summary`

### Snapshot

session snapshot은 workspace 아래에 저장됩니다.

```text
workspace/
  codex/
    .agent-messaging/
      snapshots/
        codex/
          discord_dm_123456.json
```

여기에는 현재 작업, 최근 결론, 다음 단계 같은 resume 정보가 저장됩니다.

## 사용자 자산 디렉터리

```text
jobs/     # background job 정의
skills/   # agent가 읽는 skill 문서
agents/   # subagent persona 문서
tools/    # external tool manifest + 실행 스크립트
```

이 디렉터리들은 로컬 사용자 자산 영역입니다. 저장소에는 예시만 `examples/` 아래에 둡니다.

## 프로젝트 구조

```text
ai-agent-messaging/
├── setup/
├── config/
├── agents/
├── jobs/
├── skills/
├── tools/
├── examples/
├── resources/
├── runtime/
├── memory/
├── workspace/
├── docs/
├── src/
├── tests/
└── pyproject.toml
```

## 개발

editable install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[discord]"
```

테스트:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -q
```

## 트러블슈팅

### `Provider executable not found`

해당 provider CLI가 설치되지 않았거나 PATH에 없습니다. 새 터미널을 열고 `codex`, `claude`, `gemini`가 직접 실행되는지 먼저 확인하세요.

### 슬래시 커맨드가 안 보임

Bot 초대 권한에 `applications.commands`가 빠졌거나, Discord 쪽 동기화가 아직 끝나지 않았을 수 있습니다.

### 서버 채널에서 봇이 반응하지 않음

Message Content Intent 설정과 멘션 방식부터 확인하세요.

### macOS 자동 실행이 안 됨

다시 확인:

```bash
.venv/bin/python setup/status.py
.venv/bin/python setup/restart.py
```
