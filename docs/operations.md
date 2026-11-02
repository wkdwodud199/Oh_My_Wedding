# 처음 실행하고 실제로 연결하기

현재 구현은 **Google Sheets + Telegram**을 연결하고, AI 요약에는 **Codex CLI에 저장된 ChatGPT OAuth 로그인**을 사용한다. Discord는 [메신저 비교](messengers.md)의 대안이며 아직 실행 어댑터가 없다. 아래는 사용자가 연결을 시작할 때 따르는 절차다. 실제 봇·Google 자격증명·상시 실행 작업은 자동으로 생성되지 않는다.

## 1. Windows에서 로컬 실행

Python 3.11 이상을 설치한 뒤, 프로젝트 폴더에서 PowerShell을 연다. 가상 환경을 직접 호출하므로 활성화 스크립트 설정은 필요 없다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
.\.venv\Scripts\python.exe -m wedding_assistant demo
.\.venv\Scripts\python.exe -m wedding_assistant doctor
```

`demo`는 가상 데이터로 조사·알림·수정을 실행하고 결과를 `artifacts`에 남긴다. 실제 검색·Google Sheets 수정·Telegram 발송은 없다. 기본 `doctor`도 외부 호출 없이 설정의 존재 여부만 확인한다.

`.env`의 초기값은 `WEDDING_MODE=demo`, `SHEETS_WRITE_ENABLED=false`로 둔다. Telegram·검색 키는 `.env`, Google 자격증명은 별도 파일에 입력한다. ChatGPT 인증은 Codex 로그인이 관리하므로 AI용 API 키나 OAuth 토큰을 `.env`에 넣지 않는다.

## 2. Google Sheets 연결 준비

Codex 앱에 연결된 Google 계정의 인증 정보가 이 백그라운드 Python 프로그램으로 자동 전달되지는 않는다. 별도 서비스 계정으로 이 프로그램이 사용할 파일만 공유하는 방식으로 설정한다.

1. Google Cloud 프로젝트를 만들거나 선택하고 **Google Sheets API**를 활성화한다. 이 구현에는 파일 검색용 Drive API가 필요하지 않다. [Google API 활성화 안내](https://developers.google.com/workspace/guides/enable-apis)
2. 서비스 계정을 만들고 JSON 키를 내려받는다. 예를 들어 프로젝트 밖의 사용자 전용 폴더에 보관하고 `.env`의 `GOOGLE_APPLICATION_CREDENTIALS`에 파일 경로를 넣는다. [서비스 계정·키 생성 안내](https://developers.google.com/workspace/guides/create-credentials#service-account)
3. **실제 연결 대상으로 정한 시트**의 공유 메뉴에서 서비스 계정 이메일(`…@…iam.gserviceaccount.com`)에 편집 권한을 부여한다. 이 서비스 계정이 공유받은 문서에 접근하는 방식이다. [서비스 계정의 공유 문서 접근](https://developers.google.com/workspace/guides/create-credentials)
4. `.env`의 `SPREADSHEET_ID`에 URL의 `/d/` 다음부터 `/edit` 앞까지의 파일 ID만 입력한다.
5. 사용자가 실제 적용을 결정했을 때만 [시트 변경안](sheet-plan.md)에 따라 `준비업무`, `조사결과`, `변경기록` 탭과 헤더를 준비한다. 기존 17개 탭은 그대로 둔다. 프로그램은 없는 탭을 자동 생성하거나 기존 표를 변환하지 않는다.

경로는 `.env`에서 따옴표와 `/`를 쓰면 공백 처리가 단순하다. 다음은 값의 모양만 보여 주는 예시다.

```dotenv
SPREADSHEET_ID=여기에_연결하기로_정한_파일_ID
GOOGLE_APPLICATION_CREDENTIALS="C:/사용자전용폴더/service-account-wedding.json"
SHEETS_WRITE_ENABLED=false
```

서비스 계정 JSON은 OAuth 클라이언트 설정 파일과 다른 파일이다. 앱에 전달할 것은 서비스 계정 키다. 조직 정책 때문에 JSON 키 생성이 제한되어 있다면 정책을 우회하지 말고 사용 가능한 인증 방식을 먼저 확인한다.

## 3. Telegram 그룹 연결

1. Telegram의 공식 [@BotFather](https://t.me/BotFather)에서 `/newbot`으로 봇을 만든다. 받은 토큰을 `.env`의 `TELEGRAM_BOT_TOKEN`에 입력한다. [공식 봇 생성 안내](https://core.telegram.org/bots/features#botfather)
2. 두 사람의 그룹에 봇을 추가한다. 기본 privacy mode를 유지한다.
3. 그룹에서 `/help@봇사용자이름`을 한 번 보낸다. 아직 프로세스가 실행되지 않았으므로 답이 없어도 된다.
4. 다른 봇 실행 프로세스가 꺼진 상태에서 다음 명령으로 수신된 대화방 ID를 확인한다.

```powershell
.\.venv\Scripts\python.exe -m wedding_assistant telegram-info
```

출력된 그룹 ID를 부호까지 그대로 `.env`의 `TELEGRAM_CHAT_ID`에 넣는다. `telegram-info`는 봇 정보·수신된 대화방만 조회하며 메시지를 발송하지 않는다. 다른 용도로 webhook이 설정된 봇이면 자동으로 해제하지 않고 안내 후 중단한다. long polling과 webhook은 함께 사용할 수 없다. [Telegram Bot FAQ](https://core.telegram.org/bots/faq)

현재 구현은 이 `chat_id`의 사람 메시지만 처리한다. 두 사용자 ID를 따로 등록하지 않으므로, 두 사람이 사용하는 전용 그룹을 지정한다. 명령에는 `/help@봇사용자이름`처럼 봇 이름을 붙일 수 있다.

## 4. ChatGPT OAuth와 업체 검색 설정

봇을 실행할 **같은 장치·같은 운영체제 사용자 계정**에서 Codex CLI를 사용할 수 있어야 한다. 다음 명령으로 ChatGPT 로그인을 확인하고, 필요하면 브라우저 로그인을 완료한다. 로그인 상태가 이미 ChatGPT라면 다시 로그인할 필요는 없다. [공식 인증 안내](https://learn.chatgpt.com/docs/auth)

```powershell
codex --version
codex login status
# 로그인이 필요할 때만 실행
codex login
```

`.env`의 AI 설정은 다음과 같다.

```dotenv
AI_BACKEND=codex_oauth
CODEX_COMMAND=codex
CODEX_MODEL=
CODEX_TIMEOUT_SECONDS=180
```

`CODEX_COMMAND`는 실행할 Codex 명령 또는 실행 파일 경로다. `CODEX_MODEL`을 비워 두면 CLI 기본 모델을 사용한다. Python 프로그램이 `codex exec`를 호출하고 저장된 ChatGPT 로그인으로 근거 요약을 받는다. OAuth 인증에 실패하면 API 키 방식으로 자동 전환하지 않는다. 로그인 관리와 제한은 [OAuth 운영 안내](oauth.md)를 참고한다. [공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)

실제 업체 검색은 별도 데이터 공급자다. [Tavily API 키 발급 화면](https://app.tavily.com/)에서 키를 받아 `TAVILY_API_KEY`에 넣는다. 이 키는 ChatGPT 인증을 대체하지 않는다. 키를 비워 두면 업체 검색은 실행되지 않으며 일정·상태 기능은 사용할 수 있다. [Tavily 공식 시작 안내](https://docs.tavily.com/)

| 설정 | 실제 동작 |
| --- | --- |
| Tavily 키 없음 | 실제 업체 검색 비활성화 |
| Tavily + `AI_BACKEND=codex_oauth` | 검색 근거를 ChatGPT OAuth로 요약 |
| Tavily + `AI_BACKEND=none` | 사용자가 AI 요약을 끄고 출처·검색 발췌만 확인 |

ChatGPT 구독 이용 한도가 적용되며 무제한 실행을 뜻하지 않는다. Tavily 검색의 이용 조건·비용은 별도 계정 기준이다. AI는 조사 요약용이며 현재 수정 입력은 `/edit 업무ID 열이름=값`이다. 일반 대화에서 임의로 수정 내용을 추론해 실행하지 않는다. 검색 발췌는 실제 후기 전문·확정 견적·예약 가능 여부와 다르다.

## 5. 읽기 확인 후 상시 실행

필요한 설정과 3개 탭을 준비한 뒤 `.env`에서 다음처럼 전환하되 쓰기는 아직 꺼 둔다. 실제 모드는 데모와 다른 상태 파일을 사용한다.

```dotenv
WEDDING_MODE=live
STATE_PATH=data/live-state.sqlite3
SHEETS_WRITE_ENABLED=false
```

상태 파일은 실행 모드와 연결 대상에 묶인다. 데모 파일을 재사용하거나 다른 시트·대화방의 기존 파일을 지정해 불일치가 발생하면 새 상태 파일을 정한다. 실제 처리 이력이 있는 파일을 임의로 지워 해결하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m wedding_assistant doctor --check-connections
```

이 명령은 `준비업무` 읽기와 Telegram 봇 조회를 확인한다. 시트 쓰기·메시지 발송·실제 업체 검색까지 검증하는 명령은 아니다.

실제로 수정·조사 결과 기록·발송을 시작할 때 `.env`에서 `SHEETS_WRITE_ENABLED=true`로 바꾸고 실행한다.

```powershell
.\.venv\Scripts\python.exe -m wedding_assistant serve
```

live의 `serve`, `tick`, `chat`은 쓰기가 켜져 있어야 한다. `serve`는 시트·Telegram을 연결하고 주기 작업을 함께 실행한다. 종료는 `Ctrl+C`다. 기본 정기 작업 시간은 서울 시간 20:00~21:00이며 명령 응답은 실행 중 언제든 가능하다.

그룹에서는 먼저 `/help@봇사용자이름`, `/status@봇사용자이름`으로 확인한다. 수정 예시는 다음과 같다. `TASK-001`은 설명용 ID이므로 실제 등록한 업무 ID로 바꿔 사용한다.

```text
/edit@봇사용자이름 TASK-001 담당=공동
/edit@봇사용자이름 TASK-001 메모="상담 때 추가금 확인"
/research@봇사용자이름 TASK-001
```

## 6. 계속 켜 둘 장치

PC가 꺼지거나 절전 상태가 되면 봇 수신과 예약 시각의 작업도 멈춘다. 계속 켜 두는 Windows PC·NAS·서버 한 곳에서 프로세스를 실행한다. Codex 채팅을 열어 두는 것만으로 실행되는 서비스가 아니다.

Windows 자동 시작이 필요하면 작업 스케줄러 UI에서 직접 작업을 만들 수 있다. 프로그램은 프로젝트 안 `.venv\Scripts\python.exe`의 절대 경로, 인수는 `-m wedding_assistant serve`, 시작 위치는 프로젝트 폴더의 절대 경로로 지정한다. 실행 계정이 `.env`와 Google 서비스 계정 키를 읽고, 같은 계정으로 Codex ChatGPT 로그인을 사용할 수 있어야 한다. NAS에서는 같은 작업 폴더·Python·Codex 환경을 마련한 뒤 해당 장치의 서비스 실행 기능을 사용한다.

현재 자동 시작 작업이나 Codex 자동화가 생성된 상태는 아니다. 같은 상태 파일을 사용하는 `serve`를 두 번 실행하지 않는다. 작업을 다른 장치로 옮길 때는 `.env`, Google 자격증명, `data/live-state.sqlite3` 등 실행 상태의 위치를 확인하고, 실행 계정으로 Codex에 로그인한다.
