# ChatGPT OAuth로 AI 사용하기

이 프로젝트의 AI 요약은 **Codex CLI에 저장된 ChatGPT 로그인**을 사용한다. AI용 API 키를 발급하거나 Python 프로그램에 refresh token을 복사할 필요가 없다. 프로그램은 Codex의 비대화형 실행인 `codex exec`를 호출한다. 공식 문서는 저장된 CLI 인증 재사용과 JSON 스키마 형태의 출력 방식을 지원한다. [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)

## 서로 다른 인증의 역할

| 항목 | 사용하는 곳 | 준비 방법 |
| --- | --- | --- |
| ChatGPT OAuth | 업체 조사 근거의 AI 요약 | 봇 실행 계정에서 `codex login` |
| Telegram BotFather 토큰 | 그룹 메시지 송수신 | `TELEGRAM_BOT_TOKEN` |
| Google 서비스 계정 | 합의한 Google Sheets 읽기·수정 | 서비스 계정 파일 경로와 해당 시트 공유 |
| Tavily 검색 키 | 웹 검색 자료 수집 | `TAVILY_API_KEY` |

Telegram·Google·Tavily 인증은 ChatGPT API 토큰이 아니다. ChatGPT 로그인만으로 이 서비스들의 권한이 생기지는 않는다.

## 로그인과 실행

상시 실행 장치에서 **봇을 돌릴 사용자 계정**으로 다음을 확인한다.

```powershell
codex --version
codex login status
# 로그인되어 있지 않거나 ChatGPT 방식으로 전환해야 할 때
codex login
```

`codex login`의 브라우저 흐름에서 ChatGPT 로그인을 완료한다. `codex login status`로 인증 방식이 ChatGPT인지 확인한다. 다른 사용자가 로그인한 데스크톱 세션을 Windows 서비스 계정이 그대로 사용할 수 있다고 가정하지 않는다. [공식 인증 안내](https://learn.chatgpt.com/docs/auth)

프로그램 설정은 다음과 같다.

```dotenv
AI_BACKEND=codex_oauth
CODEX_COMMAND=codex
CODEX_MODEL=
CODEX_TIMEOUT_SECONDS=180
```

`CODEX_COMMAND`에 설치된 실행 파일을 지정할 수 있다. 모델을 비우면 CLI 기본값을 쓰며, `CODEX_MODEL`을 지정하면 해당 계정에서 사용 가능한 모델이어야 한다. 기본 실행 제한 시간은 180초다. 어댑터는 `forced_login_method=chatgpt` 설정으로 로그인 방식을 제한하고, 실패해도 API 키 방식으로 전환하지 않는다.

`AI_BACKEND=none`은 사용자가 AI 요약을 명시적으로 끄는 선택이다. 이 경우 Tavily 검색 결과와 출처만 정리한다. OAuth 장애를 숨기기 위한 자동 대체 방식이 아니다.

프로젝트에서 로그인만 확인하려면 다음 명령을 쓴다.

```powershell
.\.venv\Scripts\python.exe -m wedding_assistant oauth-check
```

실제 AI 응답까지 확인하려면 `--infer`를 붙인다. 이 검사는 작은 JSON 응답을 요청하므로 ChatGPT 이용량이 발생할 수 있으며, Google Sheets나 Telegram은 호출하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m wedding_assistant oauth-check --infer
```

## 로그인 유지와 장애 대응

Codex는 저장된 인증을 재사용하고 사용 중 토큰 갱신을 처리한다. 로그아웃·세션 철회·갱신 실패가 있으면 같은 실행 계정에서 `codex login status`를 확인하고 필요할 때 다시 로그인한다. 프로그램에 refresh token 갱신 코드를 별도로 넣거나 인증 파일 내용을 출력하지 않는다. [로그인 캐시와 갱신](https://learn.chatgpt.com/docs/auth)

AI 처리에서 인증 오류·시간 초과가 발생하면 연결 확인 대상이다. 이때 실제 처리 성공으로 기록되었다고 가정하지 말고 실행 로그·그룹 안내를 확인한다. ChatGPT/Codex 계정의 이용 한도가 적용되므로 구독이 무제한 자동 실행을 보장하지 않는다. [계정 인증을 쓰는 자동 실행](https://learn.chatgpt.com/docs/non-interactive-mode)

로그인 상태 확인은 모델 응답을 받아 본 검증과 다르다. 또한 AI 응답 검증이 성공해도 Google Sheets 쓰기·Telegram 발송까지 검증한 것은 아니다. 각 연동의 실제 확인 결과는 별도로 구분한다.
