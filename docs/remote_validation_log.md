# 원격 데이터 서비스 라이브 검증 로그 (세션 B)

실행일 2026-08-20 / 브랜치 `feat/remote_data_service` / Windows 11, Python 3.13.

각 항목은 **OBSERVED**(실제로 실행하고 출력을 캡처함) 또는 **CONSTRUCTED**(코드를 읽고 추론함)로
라벨링한다. 이 문서에 CONSTRUCTED 항목은 없다 — 모든 수치는 이번 실행에서 받은 값이다.

API 키는 클라이언트 프로세스 환경변수(`OPEN_DART_API_KEY`)로만 주입했고, 서버 프로세스와
이 문서 어디에도 값이 남지 않는다. 헤더는 전부 `X-OpenDART-API-Key: ****`로 마스킹한다.

대상: 삼성전자 사업보고서 (2025.12), 접수번호 `20260310002820`,
첨부 `opendart:20260310002820:20260310002820_00760.xml` (별도감사보고서).

---

## 1. 서버 기동 — 키 없는 환경 · **OBSERVED**

명령 (서버 프로세스 환경에 `OPEN_DART_API_KEY`를 넣지 않았고, `.env`도 로드하지 않음):

```
cd "C:/python Project/dart-mcp-remote" && env | grep -c OPEN_DART_API_KEY || echo "server env: OPEN_DART_API_KEY absent (0 matches)"; uv run uvicorn --factory dart_crawler.remote_server:build_app --port 8765 2>&1
```

출력:

```
0
server env: OPEN_DART_API_KEY absent (0 matches)
INFO:     Started server process [54580]
INFO:     Waiting for application startup.
StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

첫 줄의 `0`은 서버 프로세스 환경변수에 `OPEN_DART_API_KEY`가 하나도 없다는 `grep -c`의 결과다.
서버는 키를 알지 못하며, 모든 키는 요청 헤더로만 들어온다.

세션 종료 후 포트 확인 (**OBSERVED**):

```
$c = Test-NetConnection -ComputerName 127.0.0.1 -Port 8765 -InformationLevel Quiet -WarningAction SilentlyContinue; "port 8765 open: $c"
port 8765 open: False
```

서버는 두 번 기동했다. 1차(pid 54580)는 스크립트 10건 + 원시 프로브 2건 = `POST /api/mcp` 12건,
2차(pid 55040, `_sheet_expectations` 대조를 추가한 뒤 재실행)는 10건. 전부 HTTP 200.
아래 3~9절의 수치는 **2차 실행(14개 검사)** 기준이며, 1차와 값이 다른 것은 응답 시간뿐이다.

## 2. 도구 표면 — `tools/list`, 키 없이 · **OBSERVED**

```
### tools/list (no key)
HTTP 200 content-type: application/json
tool names: ['search_companies', 'list_report_filings', 'list_report_attachments', 'list_report_sections', 'get_report_sections']
raw body bytes: 20831
```

5개, `export_report_excel` 부재. 응답은 SSE 스트림이 아니라 단일 JSON 본문
(`content-type: application/json`)이며, `initialize` 핸드셰이크 없이 곧바로 성공했다.

## 3. 라이브 검증 스크립트 실행 · **OBSERVED**

명령 (키는 `.env`에서 읽어 이 프로세스 환경에만 주입, 값은 출력되지 않음):

```powershell
cd 'C:\python Project\dart-mcp-remote'
$line = (Get-Content .env | Where-Object { $_ -like 'OPEN_DART_API_KEY=*' } | Select-Object -First 1)
$env:OPEN_DART_API_KEY = $line.Substring($line.IndexOf('=')+1).Trim()
$env:PYTHONIOENCODING = 'utf-8'
uv run python scripts/validate_remote_live.py
```

사람이 읽는 출력 (전문):

```
대상 서버 http://127.0.0.1:8765/api/mcp / 헤더 X-OpenDART-API-Key: ****
       (tools/list 0.01s)
[PASS] tools/list surface: 5개: search_companies, list_report_filings, list_report_attachments, list_report_sections, get_report_sections
       (search_companies 6.51s)
[PASS] search_companies: 삼성전자 corp_code=00126380 match=exact
       (list_report_filings 6.75s)
[PASS] list_report_filings: 사업보고서 (2025.12) rcept_no=20260310002820 receipt_date=20260310
       (list_report_attachments 1.24s)
[PASS] list_report_attachments: 별도감사보고서 attachment_id=opendart:20260310002820:20260310002820_00760.xml
       (list_report_sections 1.78s)
[PASS] list_report_sections: 섹션 47개, 표 셀 6594개, coverage_complete=True
       (get_report_sections(statements) 1.95s)
[PASS] get_report_sections(statements): 4개 구역, 셀 804개: 재무상태표, 손익계산서, 자본변동표, 현금흐름표
       (get_report_sections(note) 1.94s)
[PASS] get_report_sections(note by section_id): s009-note '주석' 셀 4개
       (list_report_attachments(키 없음) 0.01s)
[PASS] 키 헤더 없음 → CONFIG_ERROR: ok=False code='CONFIG_ERROR'
       (search_companies(Bearer) 6.10s)
[PASS] Authorization: Bearer 폴백: ok=True code=''
       (get_report_sections(batch 1/1) 2.23s)
[PASS] 전 구역 수집: 1회 호출로 47/47개 구역, 표 셀 6594개
       (독립 로컬 파싱 1.83s)
[PASS] 셀 단위 교차 검증 (zero-missing): 구역 47개, 블록 731개, 표 셀 6594개 비교, 불일치 0건
[PASS] 엑셀 경로 셀 맵 대조 (_sheet_expectations): 시트 47개, 좌표-값 7040개 비교, 불일치 0건
[PASS] 대사 항등식 checked == returned + 비표 블록: 7040 == 6594 + 446 (7040)
[PASS] 공식 금액 대조 (3건 이상): 자산총계 원문 '358,902,051' x1000000 == 공식 358902051000000; 부채총계 원문 '104,571,968' x1000000 == 공식 104571968000000; 자본총계 원문 '254,330,083' x1000000 == 공식 254330083000000
--- PASS: 14/14 검사 통과 ---
```

프로세스 종료 코드 0.

### 호출별 소요 시간 (초) · **OBSERVED**

| 호출 | 초 |
|---|---|
| tools/list | 0.011 |
| search_companies | 6.511 |
| list_report_filings | 6.751 |
| list_report_attachments | 1.243 |
| list_report_sections | 1.777 |
| get_report_sections(statements) | 1.947 |
| get_report_sections(note) | 1.936 |
| list_report_attachments(키 없음) | 0.008 |
| search_companies(Bearer) | 6.104 |
| get_report_sections(batch 1/1) | 2.226 |
| 독립 로컬 파싱(클라이언트 측) | 1.831 |

`search_companies`가 6.5초인 것은 요청마다 OpenDART corpCode ZIP을 새로 내려받기 때문이며,
설계 문서의 세션 D(웜 인스턴스 캐시) 항목과 일치한다. 키가 없는 호출은 상류 요청을 하기 전에
0.008초 만에 거절된다.

## 4. 목차(TOC) 발췌 · **OBSERVED**

`list_report_sections` 응답 메타:

```json
{
  "report_title": "본문",
  "source_type": "xml",
  "source_sha256": "a9c54c3a826c919b98fcbf05384a54d66a55b8a7ef319c69d3d93a58631d5763",
  "coverage_complete": true,
  "section_count": 47,
  "total_cell_count": 6594
}
```

앞 12개 구역 (전체 47개 중):

| section_id | title | kind | cell_count |
|---|---|---|---|
| s001-other | 본문 | other | 12 |
| s002-other | 목 차 | other | 44 |
| s003-opinion | 독립된 감사인의 감사보고서 | opinion | 8 |
| s004-other | (첨부)재 무 제 표 | other | 21 |
| s005-balance_sheet | 재무상태표 | balance_sheet | 291 |
| s006-income | 손익계산서 | income | 162 |
| s007-equity | 자본변동표 | equity | 156 |
| s008-cash_flow | 현금흐름표 | cash_flow | 195 |
| s009-note | 주석 | note | 4 |
| s010-note | 주석 1 | note | 0 |
| s011-note | 주석 2 | note | 12 |
| s012-note | 주석 3 | note | 0 |

## 5. `get_report_sections(section_kinds=["statements"])` 실제 데이터 · **OBSERVED**

반환 구역 4개 (`s005-balance_sheet` 재무상태표, `s006-income` 손익계산서,
`s007-equity` 자본변동표, `s008-cash_flow` 현금흐름표), `returned_cell_count` 804.

재무상태표 표의 앞 8행 (원문 문자열 그대로, 가공 없음):

```json
[["재 무 상 태 표", ""],
 ["제 57 기 : 2025년 12월 31일 현재", ""],
 ["제 56 기 : 2024년 12월 31일 현재", ""],
 ["삼성전자주식회사", "(단위 : 백만원)"],
 ["과 목", "주석", "제 57 (당) 기", "", "제 56 (전) 기", ""],
 ["자 산", "", "", "", "", ""],
 ["Ⅰ. 유 동 자 산", "", "", "101,439,429", "", "82,320,322"],
 ["   1. 현금및현금성자산", "4, 28", "12,581,632", "", "1,653,766", ""]]
```

원문의 들여쓰기(`   1. 현금및현금성자산`), 자릿수 구분 쉼표, 단위 표기 `(단위 : 백만원)`가
모두 원본 그대로 보존된다.

주석 구역을 section_id로 단건 조회한 결과 (**OBSERVED**):

```json
{"section_id": "s009-note", "title": "주석", "block_count": 3, "returned_cell_count": 4}
```

요청한 `s009-note` 1개만 반환되었다.

## 6. zero-missing 셀 단위 교차 검증 · **OBSERVED**

같은 첨부를 두 경로로 얻어 비교했다.

- 경로 A: 원격 서버 `get_report_sections`(section_id 배치로 47개 구역 전부).
- 경로 B: 클라이언트에서 공개 API만으로 독립 수집·파싱
  (`AttachmentService.list` → `read_selected` → `parse_attachment`).

동일 원본 확인: 두 경로의 `source_sha256`이 같다.

```
서버 응답 source_sha256 : a9c54c3a826c919b98fcbf05384a54d66a55b8a7ef319c69d3d93a58631d5763
로컬 파싱 source_sha256 : a9c54c3a826c919b98fcbf05384a54d66a55b8a7ef319c69d3d93a58631d5763
```

비교 결과:

```json
{
  "sections_compared": 47,
  "blocks_compared": 731,
  "table_cells_compared": 6594,
  "mismatch_count": 0,
  "mismatches": []
}
```

비교 대상: 구역 수·순서·`section_id`·제목·kind, 블록 수·블록 kind·문단 텍스트·이미지 출처,
그리고 모든 TABLE 블록의 `rows`(셀별 문자열 동등성)와 `merged_ranges`.
불일치 0건, 누락 0건.

**대사 항등식** (`validate_document`의 검사 셀 수 ↔ 반환 셀 수):

```
checked_cell_count == returned_cell_count(전 구역 합) + 비TABLE 블록 수
7040 == 6594 + 446
```

`validate_document`는 HEADING/PARAGRAPH/IMAGE 블록을 1로 세고 TABLE은 격자 칸 수로 세므로,
이 항등식이 성립한다는 것은 검증기가 확인한 모든 항목이 응답에 그대로 실렸다는 뜻이다.

한계 (정직한 기록): 이 첨부의 전체 표 셀은 6,594개로 서버의 `MAX_RESPONSE_CELLS`(20,000) 및
스크립트의 배치 한도(18,000)보다 작아, 전 구역 수집이 **배치 1회**로 끝났다. 다중 배치 분할
경로는 이번 실행에서 실행되지 않았다(분할 로직 자체는 단위 테스트가 담당).

## 7. 엑셀 경로 셀 맵 대조 · **OBSERVED**

설계 (a)4 항목: 데이터 경로가 엑셀 경로와 **동일한 원본 사실**을 나르는지 확인한다.

방법 — 알고리즘을 두 번 구현하지 않기 위해, 엑셀 경로가 워크북에 쓸 내용을 계산하는
`workbook_validation._sheet_expectations`(`{(행, 열): 값}` 맵 + 병합 범위 + 표시형식)에
**입력만 다른 두 문서**를 넣고 결과를 비교했다.

- 입력 ①: 클라이언트가 원본 바이트에서 독립 파싱한 `ParsedDocument`
- 입력 ②: 서버 JSON 응답만으로 재구성한 `ParsedDocument`

결과:

```json
{
  "sheets_compared": 47,
  "expectation_cells_compared": 7040,
  "mismatch_count": 0,
  "mismatches": []
}
```

시트 47개, 좌표-값 7,040개, 불일치 0건. 병합 범위(`A1:B2` 형태 문자열 집합)와 숫자
표시형식(`#,##0;(#,##0)` 등)까지 전부 동일했다.

이 검사가 6절과 별개로 말해 주는 것: 원격 JSON만으로 엑셀 경로의 입력을 **완전히 복원**할 수
있다는 것. 즉 행 번호 배정, 이미지 자리표시자 행, `parse_cell_value`의 문자열→숫자 변환,
병합 범위의 엑셀 좌표 변환, 천단위 표시형식이 모두 응답 안의 정보만으로 같은 값에 도달한다.
6절이 "같은 값이 들어 있다"를 보인다면, 7절은 "그 값으로 같은 워크북을 만들 수 있다"를 보인다.

## 8. 공식 수치 대조 3건 · **OBSERVED**

OpenDART `fnlttSinglAcntAll.json`을 클라이언트에서 직접 호출
(`corp_code=00126380`, `bsns_year=2025`, `reprt_code=11011`, `fs_div=OFS`) 하여
재무상태표(`sj_div=BS`) 계정을 받아 원문 셀과 대조했다.

| 계정 | 원문 셀 (백만원) | 공식 API 값 (원) | 배율 | 일치 |
|---|---|---|---|---|
| 자산총계 | `358,902,051` | `358902051000000` | ×1,000,000 | 예 |
| 부채총계 | `104,571,968` | `104571968000000` | ×1,000,000 | 예 |
| 자본총계 | `254,330,083` | `254330083000000` | ×1,000,000 | 예 |

매칭된 원문 행 (원격 응답에서 그대로 발췌):

```json
["자 산 총 계", "", "", "358,902,051", "", "324,966,127"]
["부 채 총 계", "", "", "104,571,968", "", "88,569,470"]
["자 본 총 계", "", "", "254,330,083", "", "236,396,657"]
```

각 행의 4번째 칸(`column_index: 3`)이 제 57 기(당기) 금액이고, 6번째 칸이 제 56 기(전기)다.

**단위 처리 방법**: 원문 감사보고서는 금액을 백만원 단위로 적고(위 4행의
`(단위 : 백만원)` 참조), OpenDART API는 항상 원 단위로 답한다. 그래서 스크립트는 원문 셀 값에
1 / 1,000 / 1,000,000 / 100,000,000을 차례로 곱해 **정확히 같아지는** 배율을 찾는다.
세 계정 모두 ×1,000,000에서 정확히 일치했고(반올림이나 오차 허용 없이 완전 동등), 이 배율은
원문이 스스로 밝힌 단위와 일치한다. 즉 단위 때문에 근사 비교로 물러선 부분은 없다.

## 9. 음성 케이스 · **OBSERVED**

### 9-1. 키 헤더 없음 → `CONFIG_ERROR` (HTTP는 200)

원시 JSON-RPC 왕복 전문 (1차 기동 중 원시 프로브로 캡처):

```
### tools/call list_report_attachments (no key header)
HTTP 200 content-type: application/json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "text": "{\n  \"ok\": false,\n  \"data\": null,\n  \"error\": {\n    \"code\": \"CONFIG_ERROR\",\n    \"message\": \"OpenDART API 키 헤더가 없습니다.\",\n    \"retryable\": false,\n    \"details\": {}\n  },\n  \"warnings\": [],\n  \"next_action\": \"X-OpenDART-API-Key 헤더(또는 Authorization: Bearer)에 OpenDART API 키를 설정한 뒤 다시 호출하세요.\"\n}",
        "type": "text"
      }
    ],
    "isError": false,
    "structuredContent": {
      "ok": false,
      "data": null,
      "error": {
        "code": "CONFIG_ERROR",
        "message": "OpenDART API 키 헤더가 없습니다.",
        "retryable": false,
        "details": {}
      },
      "warnings": [],
      "next_action": "X-OpenDART-API-Key 헤더(또는 Authorization: Bearer)에 OpenDART API 키를 설정한 뒤 다시 호출하세요."
    }
  }
}
```

HTTP 401이 아니라 200 + Result 봉투다. 설계 의도(401은 MCP 클라이언트의 OAuth 탐색을 유발)대로
동작한다.

### 9-2. `Authorization: Bearer` 폴백

`X-OpenDART-API-Key` 없이 `Authorization: Bearer ****`만 보낸 `search_companies` 호출:

```
[PASS] Authorization: Bearer 폴백: ok=True code=''
```

`ok=true`로 성공 경로에 도달했다(= CONFIG_ERROR가 아니며 상류 조회까지 수행됨), 6.104초.

## 10. 게이트 · **OBSERVED**

```
cd 'C:\python Project\dart-mcp-remote'; uv run ruff check .; if ($?) { uv run mypy --strict src tests }
All checks passed!
Success: no issues found in 57 source files
```

```
cd 'C:\python Project\dart-mcp-remote'; uv run pytest -v
...
=========================== short test summary info ===========================
SKIPPED [1] tests\test_live.py:9: OPEN_DART_API_KEY is not set
======================= 324 passed, 1 skipped in 6.01s ========================
```

`OPEN_DART_API_KEY`는 검증 스크립트 프로세스에만 주입했으므로 `pytest` 셸에는 없고,
`test_live.py`는 의도대로 skip 되었다.

## 11. 이 실행이 증명하지 않는 것

- Vercel 배포 환경(Linux, 서버리스)에서의 동작 — 세션 C 범위.
- 20,000셀 초과 선택의 거절 및 다중 배치 분할 — 이 첨부(6,594셀)로는 도달하지 않는다.
- 삼성전자 외 다른 회사·보고서 종류의 파싱 일반성 — 별도 코퍼스 검증 과제.

---

# 적대 리뷰 반영 (2026-08-20)

적대 리뷰가 재현한 결함 3건을 고친 뒤 다시 실행한 기록이다. 위와 같은 라벨 규칙을 쓰며,
이 절의 모든 항목은 **OBSERVED**다 — 코드를 읽고 추론한 값은 하나도 없다.

## 12. D1 — `GET /api/mcp`가 스트림을 열지 않고 즉시 거절된다 · **OBSERVED**

**고치기 전 증상**: MCP SDK의 `streamable_http.py:687 _handle_get_request`는 `json_response`·
`stateless_http` 설정과 무관하게 GET에 SSE 스트림을 열고 클라이언트가 끊을 때까지 유지한다.
이 서버는 서버→클라이언트로 보낼 것이 애초에 없으므로 그 스트림에는 아무것도 실리지 않는다.
서버리스에서는 **인증 없는 GET 한 건이 함수를 최대 실행시간(300초)까지 점유**한다.

같은 in-process 재현을 3초 데드라인으로 걸어 고치기 전 동작을 측정한 결과(**OBSERVED**):

```
POST: 400 allow=None in 0.0032s
GET: HUNG (fail_after fired at 3.01s)
DELETE: 405 allow=None in 0.0022s
OPTIONS: 405 allow='GET, POST, DELETE' in 0.0020s
PUT: 405 allow='GET, POST, DELETE' in 0.0016s
```

GET만 멈춘 것이 아니라, SDK가 내보내던 405의 `Allow: GET, POST, DELETE`가 **멈추는 메서드인
GET을 쓸 수 있다고 광고**하고 있었다.

**고친 뒤** — 실서버 기동(`uv run uvicorn --factory dart_crawler.remote_server:build_app --port 8766`,
서버 환경에 API 키 없음) 후 curl 전문:

```
$ curl -sS -o /dev/null -D - --max-time 20 -w "\nHTTP=%{http_code}  time_total=%{time_total}s\n" \
    -X GET http://127.0.0.1:8766/api/mcp -H "Accept: application/json, text/event-stream"
HTTP/1.1 405 Method Not Allowed
date: Wed, 19 Aug 2026 22:38:16 GMT
server: uvicorn
allow: POST
content-length: 0

HTTP=405  time_total=0.004329s
```

300초 점유가 **0.004초 거절**로 바뀌었다.

POST는 그대로 동작한다 (키 없이 `tools/list`, **OBSERVED**):

```
HTTP=200  time_total=0.008030s
tool names: ['search_companies', 'list_report_filings', 'list_report_attachments', 'list_report_sections', 'get_report_sections']
```

DELETE·OPTIONS도 같은 정직한 `Allow`를 받는다 (**OBSERVED**):

```
HTTP/1.1 405 Method Not Allowed
allow: POST
HTTP=405 time_total=0.003627s      # DELETE
HTTP/1.1 405 Method Not Allowed
allow: POST
HTTP=405 time_total=0.003485s      # OPTIONS
```

가드는 MCP 경로에만 적용된다 — 다른 경로의 GET은 그대로 라우터가 404를 낸다
(`test_the_method_guard_leaves_other_paths_to_the_router`).

## 13. D2 — 서술 텍스트 크기 가드가 실제로 발동한다 · **OBSERVED**

**고치기 전 증상**: 크기 가드가 표 셀만 셌기 때문에, 주석·감사의견처럼 **표가 0셀인 서술 위주
선택은 가드를 통째로 우회**했다. 게다가 `SectionSummary.cell_count`가 0으로 보고되어 클라이언트는
그 응답이 공짜인 줄 알았다.

재현 방법: 주석 55개·표 0개짜리 합성 첨부를 만들고, 문서 로더만 교체한 채 **실제 서버·실제 도구·
실제 봉투**로 HTTP 왕복했다(`uvicorn narrative_server:app --port 8767`).

고쳤을 때 목차가 두 비용을 모두 보여 준다 (`list_report_sections`, **OBSERVED**):

```
{"section_count": 55, "total_cell_count": 0, "total_text_char_count": 252056}
```

`cell_count`는 0이지만 `text_char_count`가 252,056자임이 요청 전에 드러난다.

가드 발동 (**OBSERVED**):

```
$ curl -sS --max-time 30 -X POST http://127.0.0.1:8767/api/mcp \
    -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" \
    -H "X-OpenDART-API-Key: ****" \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_report_sections","arguments":{"rcept_no":"20260310002820","attachment_id":"opendart:20260310002820:notes.xml","section_kinds":["note"]}}}'
HTTP=200 bytes=891
```

응답 봉투 전문:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "INVALID_INPUT",
    "message": "선택한 구역의 서술 텍스트 분량이 한 번에 반환할 수 있는 한도를 초과했습니다.",
    "retryable": false,
    "details": {
      "selected_text_char_count": 252056,
      "limit": 200000
    }
  },
  "warnings": [],
  "next_action": "구역을 나누어 여러 번 호출하세요."
}
```

**막아 낸 크기** (**OBSERVED**) — 고치기 전이라면 이 선택이 그대로 반환되었을 응답의 data 부분:

```
구역 수                : 55
returned_cell_count    : 0
서술 텍스트 문자 수     : 252056
data 부분 JSON 바이트   : 642223
```

셀 가드에는 0셀로 보이던 선택이 실제로는 **642KB**였다.

`next_action`대로 절반(27개 구역)으로 나눈 재호출은 성공한다 (**OBSERVED**):

```
HTTP=200 bytes=639175
ok= True  구역 수= 27  returned_cell_count= 0
```

### 한도 200,000자의 근거 · **OBSERVED**

실제 원문으로 측정했다. 삼성전자 사업보고서(2025.12) 별도감사보고서 **전체 47구역**의
`total_text_char_count`는 **29,611자**로, 한도의 **1/6.8** 수준이다(아래 15절 라이브 재실행).
즉 보고서 하나를 통째로 요청해도 이 가드에 걸리지 않으며, 걸리는 것은 위 55구역·252,056자처럼
정상 보고서의 8.5배에 달하는 선택뿐이다.

구역별로 보면 서술이 실제로 어디에 몰려 있는지도 드러난다 (**OBSERVED**, 앞 12구역):

| section_id | title | cell_count | text_char_count |
|---|---|---|---|
| s003-opinion | 독립된 감사인의 감사보고서 | 8 | 4,279 |
| s005-balance_sheet | 재무상태표 | 291 | 0 |
| s006-income | 손익계산서 | 162 | 0 |
| s011-note | 주석 2 | 12 | 6,648 |
| s012-note | 주석 3 | 0 | 2,593 |

재무제표 구역은 셀만 있고 서술이 0자, 감사의견과 주석은 셀이 0~12개인데 서술이 수천 자다.
**두 지표가 서로 다른 구역을 붙잡는다**는 것이 이 표에서 그대로 보인다 — 셀만 세던 옛 가드가
`s012-note`(0셀·2,593자) 같은 구역을 전혀 계량하지 못한 이유다.

### 이번 실행이 드러낸 것 — 와이어 크기 · **OBSERVED**

이번 실행에서 **MCP 응답이 같은 내용을 두 벌**
(`structuredContent` + `content[0].text`의 이스케이프본) 싣는다는 것이 드러났다: 27구역
126,028자가 와이어에서 639,175바이트였다. 한도인 200,000자는 와이어 기준 약 1MB에 해당한다.
이는 기존 `MAX_RESPONSE_CELLS`(20,000셀)에도 똑같이 적용되는 성질이라 두 한도는 서로
정합적이지만, **두 한도를 문자·셀이 아니라 실제 응답 바이트로 재보정할지는 별도 판단 대상**이다.
이번 작업에서는 지시받은 200,000을 그대로 두고 측정값만 기록한다.

## 14. D3 — `requirements.txt` 재생성이 로컬 패키지 줄을 잃지 않는다 · **OBSERVED**

**고치기 전 증상**: `uv export`는 파일 전체를 다시 쓰므로, 마지막 줄 `.`(이 저장소 자체를
설치하라는 지시)이 재생성할 때마다 사라진다. 그러면 Vercel은 의존성은 다 갖췄지만
`dart_crawler` import에 실패하는 함수를 배포한다.

맨손 `uv export`가 그 줄을 지운다는 것 (**OBSERVED**):

```
$ uv export --format requirements-txt --no-dev --no-emit-project --no-hashes -o requirements.txt
$ tail -3 requirements.txt
    # via mcp
zstandard==0.25.0 ; python_full_version < '3.14'
    # via httpx2
```

`.`이 없다. 이어서 `scripts/export_requirements.py`로 재생성 (**OBSERVED**):

```
$ uv run python scripts/export_requirements.py
Resolved 60 packages in 2ms
$ uv export --format requirements-txt --no-dev --no-emit-project --no-hashes -o requirements.txt
requirements.txt 재생성 완료 — 마지막 3줄:
      # via httpx2
  # local package (do not remove; see scripts/export_requirements.py)
  .

$ tail -3 requirements.txt
    # via httpx2
# local package (do not remove; see scripts/export_requirements.py)
.
```

멱등성 — 연속 두 번 실행한 파일의 해시가 같다 (**OBSERVED**):

```
run N   sha256: 2a9cf971794ceb7546f037138575043955960aab8e00116ba175c04cd4330900
run N+1 sha256: 2a9cf971794ceb7546f037138575043955960aab8e00116ba175c04cd4330900
IDEMPOTENT: identical
```

저장소의 `requirements.txt`는 이 스크립트로 재생성한 결과물이다(손으로 고치지 않았다).

## 15. 라이브 재검증 — 실 DART 원문으로 무회귀 확인 · **OBSERVED**

새 필드와 새 가드가 실제 보고서 경로를 깨뜨리지 않았는지 확인하려고 3절의 라이브 스크립트를
같은 대상(삼성전자 사업보고서 2025.12, 접수번호 `20260310002820`)으로 다시 실행했다.
서버에는 키가 없고, 키는 클라이언트 프로세스 환경변수로만 주입했다.

```powershell
cd 'C:\python Project\dart-mcp-remote'
$line = (Get-Content .env | Where-Object { $_ -like 'OPEN_DART_API_KEY=*' } | Select-Object -First 1)
$env:OPEN_DART_API_KEY = $line.Substring($line.IndexOf('=')+1).Trim()
$env:PYTHONIOENCODING = 'utf-8'
uv run python scripts/validate_remote_live.py
```

사람이 읽는 출력 (전문):

```
대상 서버 http://127.0.0.1:8765/api/mcp / 헤더 X-OpenDART-API-Key: ****
       (tools/list 0.02s)
[PASS] tools/list surface: 5개: search_companies, list_report_filings, list_report_attachments, list_report_sections, get_report_sections
       (search_companies 6.79s)
[PASS] search_companies: 삼성전자 corp_code=00126380 match=exact
       (list_report_filings 8.22s)
[PASS] list_report_filings: 사업보고서 (2025.12) rcept_no=20260310002820 receipt_date=20260310
       (list_report_attachments 1.46s)
[PASS] list_report_attachments: 별도감사보고서 attachment_id=opendart:20260310002820:20260310002820_00760.xml
       (list_report_sections 2.45s)
[PASS] list_report_sections: 섹션 47개, 표 셀 6594개, 서술 29611자, coverage_complete=True
       (get_report_sections(statements) 2.41s)
[PASS] get_report_sections(statements): 4개 구역, 셀 804개: 재무상태표, 손익계산서, 자본변동표, 현금흐름표
       (get_report_sections(note) 2.99s)
[PASS] get_report_sections(note by section_id): s009-note '주석' 셀 4개
       (list_report_attachments(키 없음) 0.00s)
[PASS] 키 헤더 없음 → CONFIG_ERROR: ok=False code='CONFIG_ERROR'
       (search_companies(Bearer) 6.84s)
[PASS] Authorization: Bearer 폴백: ok=True code=''
       (get_report_sections(batch 1/1) 3.04s)
[PASS] 전 구역 수집: 1회 호출로 47/47개 구역, 표 셀 6594개
       (독립 로컬 파싱 2.51s)
[PASS] 셀 단위 교차 검증 (zero-missing): 구역 47개, 블록 731개, 표 셀 6594개 비교, 불일치 0건
[PASS] 엑셀 경로 셀 맵 대조 (_sheet_expectations): 시트 47개, 좌표-값 7040개 비교, 불일치 0건
[PASS] 대사 항등식 checked == returned + 비표 블록: 7040 == 6594 + 446 (7040)
[PASS] 공식 금액 대조 (3건 이상): 자산총계 원문 '358,902,051' x1000000 == 공식 358902051000000; 부채총계 원문 '104,571,968' x1000000 == 공식 104571968000000; 자본총계 원문 '254,330,083' x1000000 == 공식 254330083000000
--- PASS: 14/14 검사 통과 ---
```

3절(수정 전)과 대조해 **달라진 것은 딱 하나** — `list_report_sections` 줄에 `서술 29611자`가
새로 붙었다. 셀 수(6,594), 구역 수(47), 교차 검증 불일치(0건), 좌표-값 대조(7,040개, 0건),
대사 항등식(7040 == 6594 + 446), 공식 금액 3건이 전부 이전 실행과 동일하다. 즉 새 필드와
새 가드는 기존 데이터 경로에 아무 영향도 주지 않았다.

## 16. 게이트 · **OBSERVED**

```
cd 'C:\python Project\dart-mcp-remote'; uv run ruff check .
All checks passed!
```

```
cd 'C:\python Project\dart-mcp-remote'; uv run mypy --strict src tests
Success: no issues found in 57 source files
```

```
cd 'C:\python Project\dart-mcp-remote'; uv run pytest -v
=========================== short test summary info ===========================
SKIPPED [1] tests\test_live.py:9: OPEN_DART_API_KEY is not set
======================= 336 passed, 1 skipped in 7.11s ========================
```

기준선 324 → 336 (+12): D1 6건, D2 6건.

## 17. 후속 — 응답 계약의 비대칭 해소 · **OBSERVED**

13절 이후 목차(`ReportSectionList`)는 셀·서술 두 축을 모두 보고하는데 데이터 응답
(`ReportSectionData`)은 `returned_cell_count`만 실어, 클라이언트가 받은 서술 분량을 스스로
블록을 훑어야만 알 수 있는 비대칭이 남아 있었다. 배포 전에 계약을 맞췄다:
`ReportSectionData.returned_text_char_count`를 추가하고 `crawler_service`의 조립부에서
기존 `returned_text_char_count()` 순수 함수로 채운다(계수 로직 중복 없음).

와이어 확인 — 주석 2개 구역을 `section_ids`로 요청한 응답의 `structuredContent.data`
(**OBSERVED**):

```json
{
  "rcept_no": "20260310002820",
  "attachment_id": "opendart:20260310002820:notes.xml",
  "parser_version": "0.1.0",
  "returned_cell_count": 0,
  "returned_text_char_count": 9164
}
```

고치기 전이라면 이 응답은 `returned_cell_count: 0` 하나만 실어, 실제로는 9,164자를 나르면서도
크기를 밝히지 않았을 것이다.

게이트 재실행 (**OBSERVED**):

```
All checks passed!
Success: no issues found in 57 source files
======================= 338 passed, 1 skipped in 8.02s ========================
```

336 → 338 (+2: `test_report_section_data_reports_both_size_counts`,
`test_report_section_data_requires_the_narrative_count`). 기존
`test_get_report_sections_returns_only_the_selected_sections`도 새 값을 단언하도록 갱신했다.

## 18. 이 절이 증명하지 않는 것

- Vercel 실배포에서의 405 동작과 `.` 줄 설치 성공 — 여전히 세션 C 범위다.
- 두 한도를 초과한 선택 하나가 양쪽 키를 함께 싣는 경로는 단위 테스트
  (`test_select_sections_names_both_dimensions_when_both_limits_are_exceeded`)로만 확인했고,
  HTTP 왕복으로는 실행하지 않았다.
- 13절의 서술 문서는 실제 DART 원문이 아니라 적대 리뷰의 재현 조건(주석 55개·0셀)을 본뜬
  합성 문서다. 교체한 것은 문서 로더뿐이고 도구·가드·봉투는 배포될 코드 그대로다.
