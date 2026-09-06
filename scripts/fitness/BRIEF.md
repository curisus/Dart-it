# Dart it 실무 적합성 검증 캠페인 — 워커 공통 브리핑

## 절대 규칙
- 제품 코드(`C:\python Project\Dart Mcp\src`, `tests`, `scripts`, `docs`, `README.md`)를 수정하지 않는다. git commit/push 금지. 증거는 전부 스크래치패드 `runs/` 아래에만 쓴다.
- OpenDART API 키를 출력·기록·보고서에 절대 넣지 않는다(하네스가 `.env`에서 읽어 헤더로만 전달).
- 이 세션에 등록된 MCP 서버 `dart_crawler`(도구 4개 구버전)는 사용 금지. 현재 코드는 하네스(`runner.py --target local`)로 호출한다.
- `mcp__claude_ai_dart-it__*` 도구(프로덕션, 14개)는 탐색용으로 써도 되지만, 보고에 쓰는 증거는 반드시 하네스 기록(`runs/<run_id>/<scenario>/*.json`)이어야 한다.
- 모든 판단에는 `evidence_path`(하네스 기록 파일 경로)를 붙인다. 증거 없는 결함은 자동 폐기된다.
- 셸: PowerShell 5.1 환경. 명령은 `cd "C:\python Project\Dart Mcp"` 후 `uv run python ...`로만 실행하고 `$env:PYTHONIOENCODING="utf-8"`를 먼저 설정한다. Bash 도구를 쓰면 `cd "/c/python Project/Dart Mcp" && export PYTHONIOENCODING=utf-8 && uv run python ...`.
- 원문 다운로드 호출(`list_report_attachments`, `list_report_sections`, `get_report_sections`, `export_report_*`)은 회사당 60회 이내. 초과가 필요하면 생략하고 보고에 "미실행"으로 적는다.

## 하네스
경로: 저장소 `scripts\fitness\` (2026-09-06 스크래치패드에서 승격)
- `runner.py --run-id <RUN> --calls <calls.json> --out <runs_root> [--target local|remote] [--auth bearer|header|none]`
  - calls.json 항목: `{"scenario":"S02","step":"fs_cfs","tool":"get_financial_statements","args":{...},"target":"local"|"remote","auth":"bearer"(선택),"follow_cursor":true(load_excel_page 전용),"expect":{...}(기록만)}`
  - 기록: `runs/<RUN>/<scenario>/<seq>_<step>.json`(봉투 요약: ok, error_code, error_message, error_details, warning_codes, next_action, counts, elapsed_ms, bytes, output_path, data_path) + `<seq>_<step>.data.json`(data 전체) + `runs/<RUN>/summary.jsonl`.
  - 로컬 도구 16개(조회 13 + `export_report_excel`·`export_report_markdown`·`export_query_excel`)는 `--target local`, 출력 파일은 `runs/<RUN>/<scenario>/xlsx/`에 생성된다. `export_query_excel` 인자는 `{"request":{"domain":"<13개 도구명 중 하나>","arguments":{...}}}`.
  - `load_excel_page`는 원격 전용(`--target remote`), 인자 `{"request":{"domain":..., "arguments":{...}, "page_size":N, "cursor":null}}` + `"follow_cursor":true`면 next_cursor가 null이 될 때까지 자동 추적하며 `<step>`, `<step>_p1`, `<step>_p2`… 로 기록.
  - 같은 RUN에 여러 번 실행하면 seq가 이어진다. step 이름은 시나리오 안에서 유일해야 한다.
- `oracles.py --run-dir <runs_root>\<RUN>\<scenario> --checks <checks.json>` → `oracles.json`(누적) 및 `[PASS]/[FAIL]` 출력.
  - 검사 유형: `envelope_contract`, `expect_ok`, `expect_error{code}`, `expect_warnings{codes,mode=subset|exact|none}`, `row_count_consistency{rows_key,count_key}`, `official_reconciliation{api_record,sections_record,accounts}`, `balance_identity`, `page_sum{records}`, `equal_data{records,ignore_keys}`, `xlsx_report{path,expect_section_count}`, `xlsx_query{path,expect_total_rows,expect_domain}`, `md_utf8_order{path,expect_titles}`, `note_grep{record,pattern,excerpt}`, `sla_p95{records,limit_ms}`, `elapsed_max{record,limit_ms}`. 기록은 step 이름으로 참조.
  - 스모크 예시: `fitness/smoke_calls.json`, `fitness/smoke_checks.json`, 결과 `runs/SMOKE1/SMOKE/`.

## 대상 회사 (corp_code 확정)
| 회사 | corp_code | 비고 |
| --- | --- | --- |
| 삼성전자 | 00126380 | 기준선. FY2025 사업보고서 rcept_no 20260310002820, 별도감사보고서 attachment_id opendart:20260310002820:20260310002820_00760.xml |
| SK하이닉스 | 00164779 | |
| KB금융 | 00688996 | 금융지주. 재무제표 구조가 다르고 주석이 매우 큼(분할 필수 예상) |
| 삼성바이오로직스 | 00877059 | |
| NAVER | 00266961 | |

공통 인자: `bsns_year=2025`, `reprt_code=11011`, 기간 `bgn_de=20260101`, `end_de=20260906`. 금액은 OpenDART 원(KRW) 문자열, 원문 표는 대개 백만원(×1,000,000 대조).

## 도구 계약 요약
- `search_companies(company_query, report_kind?)` ≤5건 / `list_report_filings(corp_code, report_kind∈audit|quarterly_review|half_year_review)` 최근 5개 사업연도 / `list_report_attachments(rcept_no)` / `list_report_sections(rcept_no, attachment_id)` 목차(cell_count, text_char_count) / `get_report_sections(rcept_no, attachment_id, section_ids?|section_kinds?)` kinds: opinion, balance_sheet, income, equity, cash_flow, note, other, statements(핵심 4종). 원격 상한 20,000셀·200,000자(초과 시 INVALID_INPUT + 분할 next_action; 로컬은 상한 없음).
- `get_financial_statements(corp_code, bsns_year≥2015, reprt_code∈11011|11012|11013|11014, fs_div∈CFS|OFS)` / `get_major_accounts(corp_codes[], bsns_year, reprt_code)` / `get_financial_indicators(corp_codes[], bsns_year, reprt_code, idx_cl_code∈M210000|M220000|M230000|M240000)`.
- `get_report_topics(corp_code, bsns_year, reprt_code, topics[])` 28종: audit_opinion, audit_service_contract, non_audit_service_contract, dividend, capital_change, treasury_stock, largest_shareholder, largest_shareholder_change, minority_shareholders, executives, employees, director_individual_pay, director_total_pay, individual_pay_top5, other_corp_investment, total_shares, debt_securities_issued, commercial_paper_balance, short_term_bond_balance, corporate_bond_balance, hybrid_securities_balance, contingent_capital_balance, outside_directors, unregistered_executive_pay, director_pay_approved, director_pay_by_type, private_fund_usage, public_fund_usage. 전부 빈 경우 NOT_FOUND, 일부 빈 경우 ok+PARTIAL_COLLECTION.
- `get_company_profile(corp_code)` / `get_ownership_reports(corp_code, report_type∈major_holding|insider_ownership, bgn_de?, end_de?)` / `get_material_events(corp_code, event_types[], bgn_de, end_de)` 36종(항상 ok, 빈 유형은 PARTIAL_COLLECTION) / `get_registration_statements(corp_code, stmt_type∈equity_securities|debt_securities|depositary_receipts|merger|stock_exchange_transfer|division, bgn_de, end_de)`.
- 행 상한 1,000(초과는 잘라내지 않고 INVALID_INPUT). 주석 구역 제목은 "주석 N"으로만 표기되며 키워드 검색 도구는 없다(전체 주석을 배치로 받아 `note_grep`으로 찾는다).

## 판정 4층
① 응답 형식·건수(envelope_contract, row_count_consistency, expect_*) ② 교차 대사(official_reconciliation ×배율, balance_identity, page_sum, equal_data) ③ 실무 적합성 루브릭 1~5점(근거 필수): 5 = 오라클 전부 통과 + 재가공 없이 Excel·보고서에 붙일 수 있음(숫자형·단위·기간 명시·식별 가능한 제목) + next_action이 정확히 다음 호출을 지시 / 3 = 값은 맞으나 수작업 필요(단위 환산, "주석 N"으로 내용 특정 불가, 페이지 수동 병합, 파일명으로 인자 구분 불가) / 1 = 오답·누락·불가·복구 경로 불명 ④ xlsx 원문 형식 적재(xlsx_report·xlsx_query + 워커의 셀 표본 육안 대조: 격자·병합·숫자 서식 `#,##0`·주석 번호 나열 `26,34` 텍스트 보존·들여쓰기 보존·주석 시트 분할).

결함 심각도: Critical(값·구조·의미가 원문과 다름), Major(값은 맞으나 표시·활용성이 요구와 다름), Minor(운영·편의). 종합 판정: 통과 / 조건부 통과 / 배포 차단 / 기능 미지원.
