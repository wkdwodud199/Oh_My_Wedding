# 결혼 준비 자동화에 사용할 오픈소스 비교

조사 기준: **2026-11-01, Asia/Seoul**. 프로젝트 공식 저장소·라이선스·문서를 확인했다. 아래 버전은 조사 당시 확인한 유지 상태의 증거이며, 설치 버전을 지정하는 목록은 아니다. 실제 의존성은 프로젝트의 의존성 파일과 검증 결과를 따른다.

두 사람이 쓰는 현재 목적에는 **작은 Python 서비스 + Google 공식 API 클라이언트 + Telegram 또는 Discord 봇 + 주기 실행기**가 가장 단순하다. 시각적으로 흐름을 편집하고 싶다면 **Activepieces Community Edition**이 대안이다. 이것은 요구사항과 운영 규모에 따른 설계 판단이다. 기존 Google Sheets를 변경하거나 실제 메시지를 발송한 결과가 아니다.

AI 인증은 사용자의 선택에 따라 **설치된 Codex CLI의 ChatGPT OAuth 로그인**을 사용한다. 현재 기본값 `AI_BACKEND=codex_oauth`는 `codex exec`의 저장된 로그인을 사용하며, 직접 OpenAI API 키로 호출하는 경로는 두지 않는다. 검색 자료는 별도 Tavily 연결에서 얻는다. `AI_BACKEND=none`을 명시하면 AI 요약 없이 검색 발췌를 사용한다. [인증 운영 안내](oauth.md), [공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)

## 후보 비교

| 후보 | 라이선스·공개 범위 | 유지 상태 확인 | 이번 프로젝트에서의 판단 |
| --- | --- | --- | --- |
| [n8n](https://github.com/n8n-io/n8n) | Sustainable Use License 및 Enterprise License. 공식 설명은 **fair-code/source-available**이며 MIT 같은 오픈소스 라이선스와 구분해야 한다. | 공식 저장소와 제품이 운영 중이다. | Sheets·주기 실행·메신저 연결을 빠르게 구성하기 좋다. 개인 용도는 SUL 허용 범위에 들어가지만, 순수 오픈소스 선택이라는 이유로 채택하면 안 된다. 별도 서비스 운영이 필요하다. [라이선스 원문](https://github.com/n8n-io/n8n/blob/master/LICENSE.md) |
| [Activepieces](https://github.com/activepieces/activepieces) | Community 코어는 MIT. `packages/ee/` 및 `packages/server/api/src/app/ee` 등은 별도 라이선스다. | [릴리스 페이지](https://github.com/activepieces/activepieces/releases)에서 `0.92.3-hotfix.2` 등 배포 확인. | **시각적 자동화 도구를 고르면 1순위 후보.** 일정·HTTP·Sheets·메신저 흐름을 조합하는 용도. 다만 업체 중복 식별, 근거 품질 판정, 기존 시트의 특수 구조 해석은 별도 코드가 필요하다. [라이선스 범위](https://github.com/activepieces/activepieces/blob/main/LICENSE) |
| [APScheduler](https://github.com/agronholm/apscheduler) | MIT | [안정 릴리스](https://github.com/agronholm/apscheduler/releases) `3.11.3` 확인. main의 4.x는 운영 사용을 권하지 않는 사전 릴리스 경고가 있다. | 정해진 요일의 업체 조사와 주기적인 일정 확인에 적합하다. **3.x 안정 계열**을 검증해 사용하거나 운영체제 스케줄러로 대체한다. 실행 이력과 알림 중복 방지는 애플리케이션에서 관리한다. |
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | LGPL-3.0-only. 사용하는 애플리케이션 전체에 LGPL을 강제하는 것과 라이브러리 자체의 배포 의무는 구분한다. | [릴리스](https://github.com/python-telegram-bot/python-telegram-bot/releases) `22.8` 확인. | Telegram을 선택할 때 적합하다. 비동기 핸들러, 명령, 버튼을 활용할 수 있다. 두 사람의 지정 대화방만 처리하는 작은 봇을 만들기 쉽다. [현재 패키지 메타데이터](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/pyproject.toml) |
| [discord.py](https://github.com/Rapptz/discord.py) | MIT | [공식 변경 기록](https://discordpy.readthedocs.io/en/stable/whats_new.html)에 `2.7.1` 확인. | Discord를 이미 쓴다면 적합하다. `/요청` 같은 명령과 텍스트 입력을 사용하면 된다. 일반 채널의 모든 메시지를 읽는 형태는 Message Content Intent 설정이 추가된다. |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | Apache-2.0 | 공식 지원이며 **maintenance mode**: 새 기능보다 주요 버그·보안 수정 중심이라고 명시한다. | **Sheets 연동 우선 후보.** 범위 읽기, 배치 수정, 시트 메타데이터를 직접 다루기 좋다. 라이브러리 유지 모드가 Sheets API 종료를 뜻하지 않는다. |
| [gspread](https://github.com/burnash/gspread) | MIT | 현재 README에 유지보수자를 구하며 기존 팀이 유지보수하지 못한다고 명시한다. | 사용법은 간단하지만 **새 핵심 의존성으로는 후순위**. 이미 쓰고 있다면 즉시 교체하기보다 필요한 API와 테스트를 확인한다. |
| [Playwright for Python](https://github.com/microsoft/playwright-python) | Apache-2.0 | [릴리스](https://github.com/microsoft/playwright-python/releases) `1.64.1` 확인. | 공식 공개 페이지가 JavaScript 렌더링을 요구할 때만 보조 도구로 사용한다. 검색 API, 업체 홈페이지 HTTP 수집으로 충분하면 설치하지 않아도 된다. 사이트 변경에 따른 추출 규칙 유지 비용이 있다. |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | Apache-2.0로 표시하지만 현재 LICENSE 끝에 별도 **Attribution Requirement**가 포함된다. 순수 Apache 조건만 있다고 단정하지 않는다. | [릴리스](https://github.com/unclecode/crawl4ai/releases) `0.9.5` 확인. | 여러 홈페이지를 Markdown으로 정리할 때 유용한 확장 후보. 현재 두 사람의 소규모 조사에는 필수 아님. 도입 버전의 LICENSE와 공개 사용 시 크레디트 조건을 함께 확인한다. [라이선스 원문](https://github.com/unclecode/crawl4ai/blob/main/LICENSE) |
| [Firecrawl](https://github.com/firecrawl/firecrawl) | 핵심 AGPL-3.0, SDK 및 일부 UI는 MIT. Cloud의 추가 기능은 별도 서비스다. | [릴리스](https://github.com/firecrawl/firecrawl/releases) 및 [자체 호스팅 문서](https://docs.firecrawl.dev/contributing/self-host)가 운영 중이다. | 수집 규모가 커지면 검토한다. 자체 호스팅에 여러 서비스가 필요하고 Cloud와 기능이 동일하지 않다. 작은 봇에 처음부터 넣기에는 운영 부담이 크다. |

## 추천 구성과 선택 기준

초기 구현은 Python 애플리케이션 하나에 업무 규칙을 모으고, SQLite에 실행 이력·알림 이력·요청 처리 상태를 저장하는 구성을 권한다. Google Sheets는 두 사람이 보는 협업 화면으로 유지한다. 봇 프레임워크는 실제 사용하는 메신저 하나를 우선 연결하고, 나머지는 같은 업무 함수를 호출하는 얇은 어댑터로 추가하면 된다.

| 요구 | 최소 구성 | 확장 시점 |
| --- | --- | --- |
| 미정 업체 주기 조사 | 명시적인 조사 대상 목록 + 허가된 검색 API + 업체 공식 공개 정보 | 사이트별 렌더링이 꼭 필요할 때 Playwright, 페이지 수가 많아질 때 크롤러 검토 |
| 조사 결과를 시트에 기록 | Google 공식 클라이언트 + 고정된 대상 시트/열 매핑 | 둘 이상의 실행자가 동시에 쓰기 시작하면 작업 큐와 충돌 처리 강화 |
| 일정 사전 알림 | 주기 실행기 + Asia/Seoul 날짜 처리 + 발송 이력 | 상시 가동 장치가 없으면 작은 서버나 관리형 실행 환경으로 이전 |
| 메신저 요청으로 수정 | Telegram 또는 Discord 어댑터 + 구조화한 수정 요청 | 자유로운 표현 지원은 별도 확장. 현재 Codex OAuth AI는 조사 요약에 사용 |
| 화면에서 자동화 수정 | Activepieces Community Edition | 비개발자가 정기적으로 흐름을 바꿔야 할 때 Python 서비스와 HTTP로 연계 |

APScheduler 3.x는 `coalesce`, `misfire_grace_time`, `max_instances`를 제공한다. 한 프로세스에서 조사·알림 작업을 실행하고, 재시작 때 누락된 예약을 읽어 필요한 것만 처리하는 방식이면 충분하다. 같은 job store를 여러 스케줄러가 공유하는 구성은 3.x 문서에서 금지한다. **프로세스가 꺼져 있으면 예약 시각에 알림이 나갈 수 없으므로**, 실제 운영 장치의 가동 여부도 설계에 포함해야 한다. [APScheduler 운영 규칙](https://apscheduler.readthedocs.io/en/3.x/userguide.html)

Telegram은 long polling과 webhook 중 하나를 선택한다. 초기 개인용 봇에는 외부 수신 서버가 필요 없는 long polling이 간단하다. 그룹의 privacy mode가 켜져 있으면 봇을 향한 명령·답글 중심으로 메시지를 받는다. [Telegram Bot FAQ](https://core.telegram.org/bots/faq)

Discord는 slash command의 문자열 인수로 자연어 요청을 받는 방식을 우선 고려한다. 일반 채널 대화를 읽도록 확장할 때는 Message Content Intent가 필요한 범위를 확인한다. [Discord Gateway 문서](https://docs.discord.com/developers/events/gateway#message-content-intent)

## 업체 조사에서 실제로 얻을 수 있는 정보

오픈소스 수집 도구를 설치했다고 웨딩 업체의 가격·평점·계약 가능 여부가 자동으로 정확해지는 것은 아니다. 자료별로 확인 가능한 사실을 분리해야 한다.

| 자료 | 쓸 수 있는 근거 | 한계와 기록 방법 |
| --- | --- | --- |
| [네이버 지역 검색 API](https://developers.naver.com/docs/serviceapi/search/local/local.md) | 업체명, 주소, 분류, 링크, 좌표 등 후보 탐색 | 문서의 요청 파라미터 기준 `display` 최대 5, `start` 최대 1이다. 일반적인 전체 업체 목록 수집용 페이지 순회가 아니다. 반환 필드에 가격·평점·리뷰 본문이 없다. `sort=comment`는 리뷰 개수 기준 정렬이지 평점이 아니다. |
| [네이버 블로그 검색 API](https://developers.naver.com/docs/serviceapi/search/blog/blog.md) | 후기 후보의 URL, 제목, 요약 패시지, 게시일 | `description`은 본문 전체가 아니다. 검색 스니펫만 확인했으면 **검색 요약 확인**으로 표시하고, 후기 전체 분석·방문 인증·협찬 여부 확인으로 표현하지 않는다. |
| 업체 공식 홈페이지·공식 공지 | 공개 가격, 구성, 위치, 행사 조건 | 세금·추가금·주말 요금·지점·게시일·적용 기간을 같이 읽는다. 공개하지 않은 가격은 `문의 필요`로 둔다. 허가된 범위에서 수집한다. |
| 직접 받은 견적·예약 확인 | 날짜·조건이 특정된 가격과 실제 예약 상태 | 사용자 입력/확인 근거로 기록하고 공개 검색 결과와 구분한다. 같은 업체라도 촬영일·구성에 따라 견적이 달라질 수 있다. |
| [Google Places API](https://developers.google.com/maps/documentation/places/web-service/policies) | 허용되는 범위의 장소 정보·평점·리뷰 표시 | 저장·캐싱 및 저자 표시 조건이 있다. API 응답의 평점·리뷰 원문을 제한 없이 Sheets에 영구 축적하는 기본 설계로 쓰지 않는다. 저장 예외인 place ID와 실시간 표시 요구 등을 구분한다. |

권장 결과 필드는 `업체 식별자`, `카테고리`, `지역/지점`, `공식 URL`, `가격`, `가격 기준/포함 항목`, `가격 상태`, `후기 출처 URL`, `근거 종류`, `게시일`, `조회일`, `미확인 사항`, `다음 확인일`이다. 실제 저장 가능 필드는 각 출처의 이용 조건에 맞춘다. 리뷰는 출처와 확인 범위를 남기는 데 집중하고, 확인하지 못한 사실을 점수로 채우지 않는다.

추천 순위는 두 사람이 정한 지역·예산·필수 조건으로 먼저 거르고, **확인된 가격**과 **출처가 있는 장단점**을 비교하는 형태가 이해하기 쉽다. 검색 관련도, 블로그 노출 순위, 리뷰 개수를 만족도 점수로 바꾸지 않는다. 같은 상호의 다른 지점은 주소나 공식 URL로 구분한다. 새 조사에서 변동을 발견하면 기존 정보와 새 근거의 시점을 함께 보여준다.

수집은 공식 API와 허용된 공개 페이지를 우선한다. 크롤러의 기술적 접근 성공이 해당 데이터의 저장·재사용 허가를 뜻하지 않는다. 로그인, 접근 제한, 봇 차단이 있는 자료는 자동으로 우회하지 않고 링크를 남겨 사용자가 확인할 수 있게 한다. Firecrawl 역시 사이트 정책 준수를 사용자 책임으로 명시한다. [Firecrawl 수집 정책 안내](https://github.com/firecrawl/firecrawl)

## 현재 시트에 맞춘 적용 원칙

- `(언니꺼)` 탭은 참고 사례로 취급하고 현재 두 사람의 업체 상태·금액·일정에 합치지 않는다.
- 빈 셀을 미계약·미완료로 추정하지 않는다. `상태`와 `조사 여부`가 명시된 항목만 자동 조사 대상으로 삼는다.
- 초기에는 로컬 예제로 개발한다. 실제 반영 시점에 메타데이터와 열 매핑을 다시 읽고, 정해진 범위만 수정한다. 이 조사 작업에서는 기존 시트를 변경하지 않는다.
- 향후 자연어 수정은 `대상`, `필드`, `변경값`으로 해석하는 구조가 적합하다. 현재 구현은 `/edit 업무ID 열이름=값` 형식의 명시적인 명령만 수정에 사용하며, Codex의 ChatGPT OAuth로 실행하는 AI는 조사 결과 요약에 사용한다. 단순한 요청에 별도 다단계 승인 절차를 붙이지 않는다.
- 하객 이름이나 연락처 등 조사에 필요 없는 데이터는 검색 서비스로 보내지 않는다. 봇 토큰은 저장소 밖에 두고 지정된 대화방만 처리한다.
- 완료·취소된 항목은 조사와 마감 알림에서 제외한다. 같은 요청 재수신과 같은 일정의 재알림은 로컬 처리 이력으로 막는다.
- 조사 결과가 없거나 가격이 확인되지 않으면 그대로 표시한다. 연결 오류를 “후기 없음”이나 “예약 가능”으로 바꾸지 않는다.

이 규모에서는 기업용 권한 체계나 별도 보안 대시보드보다, 원본 범위 보존·정확한 근거·중복 방지·간단한 실행 로그가 실용적이다. 라이선스와 API 조건은 도입·업그레이드 시 해당 버전의 원문을 다시 확인한다.
