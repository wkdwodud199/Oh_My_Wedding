# 검증 기록

검증일: 2026-11-01 (Asia/Seoul)

## 실행한 확인

- Windows / Python 3.13.9에서 의존성 설치 후 **83개 unittest 통과**.
- API 키 인증 거부, OAuth 실패 시 API 폴백 없음, 구조화 응답과 출처 인용 검증.
- 명령 다중 필드 수정, 잘못된 값 무쓰기, 재시작·전송 실패 복구, 동일 요청 중복 억제.
- Google Sheets 모의 API로 변경 셀 제한·최신 값 충돌·쓰기 후 재조회·기록ID 중복 처리 확인.
- 마감 단계, 지연 알림, 월말·윤년, 완료/보류 제외, 오래된 알림 폐기, 재시도 시 남은 날짜 갱신 확인.
- 지정 Telegram 방과 봇 이름 필터, 긴 메시지 분할, 수신 커서 재시도 확인.
- demo/live 및 서로 다른 대상이 같은 상태 DB를 공유하지 못하도록 검증.
- 실제 Codex CLI 0.158.0의 `codex login status`에서 ChatGPT 로그인 확인.
- **`python -m wedding_assistant oauth-check --infer` 실제 실행 성공:** 저장된 ChatGPT OAuth 인증으로 `{ "status": "ok" }` 응답 확인. 토큰 파일이나 토큰 값은 읽거나 출력하지 않음. Google Sheets 및 Telegram 호출 없음.
- 가상 검색 응답 + 실제 ChatGPT OAuth를 결합해 업체별 JSON 스키마와 인용 검증까지 성공. 검색 자체는 모의 응답이며 실제 업체 정보가 아니다. 당시 로컬 결과는 `artifacts/oauth-research-check.json`이며 실행 산출물은 저장소에 포함하지 않는다.
- `pip check` 통과, wheel 빌드 성공 및 배포 패키지 안의 가상 예제 JSON 포함 확인.
- 로컬 가상 예제에서 조사 → 공지 → 계약완료 수정 → 변경기록 공지 검증. 같은 시각 재실행 시 추가 공지 0건, 이미 계약완료인 업무에 조사/마감 알림 0건.

당시 로컬 데모 대화 기록은 `artifacts/verified-oauth-version/transcript.md`에 생성했다. 실행 산출물은 저장소에 포함하지 않으며 아래 `demo` 명령으로 새 기록을 만들 수 있다. 데모는 실제 업체 추천이나 실제 두 사람의 일정이 아니다.

## 아직 실행하지 않은 확인

- 실제 Google Sheets 읽기/쓰기 어댑터 왕복: 별도 Google 자격증명과 합의한 3개 탭이 필요.
- 실제 Telegram 그룹 수신/발송: BotFather 토큰과 그룹 chat_id가 필요.
- 실제 Tavily 검색과 OAuth 요약의 결합: 검색 키를 설정한 뒤 실제 대상 지역·분야로 확인해야 함.
- 상시 운영, 재부팅 후 자동 시작, 장시간 네트워크 장애 복구: 운영 장치를 정한 뒤 확인.

기존 결혼 준비 Google Sheets는 변경하지 않았다. 봇 메시지 발송·예약·결제·상시 작업 등록도 하지 않았다.

## 재현

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m wedding_assistant demo
.\.venv\Scripts\python.exe -m wedding_assistant oauth-check --infer
```

앞의 두 명령은 외부 호출이 없다. 마지막 명령만 실제 ChatGPT OAuth 추론을 한 번 수행하며 이용 한도를 사용한다. 검증 당시 Python 의존성 버전은 `requirements.lock.txt`에 기록했다.
