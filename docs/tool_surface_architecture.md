# 도구 표면 아키텍처 — 로컬·원격 통합 관리

2026-08-20 사용자 확정. 로컬 버전과 원격 버전의 기능 범위(coverage)를 한 곳에서 관리하기 위한 구조와, DART 전체 데이터로 확장할 때 따라야 할 레시피를 기록한다.

## 컨셉 (사용자 확정, 2026-08-28 확장)

원격과 로컬은 일반 조회 도구 13개를 공유한다. 대용량 결과는 원격에서 서명된 커서로 페이지를 반복하고, 로컬에서는 전체 결과를 `.xlsx` 파일로 게시한다. 따라서 한 표면이 다른 표면의 단순한 상위집합은 아니다.

| 표면 | 컨셉 | 도구 구성 |
|---|---|---|
| **로컬** (`mcp_server.py`, stdio) | API 키를 사용자 컴퓨터에서 읽고 파일을 안전하게 게시 | 공통 조회 13종 + export 그룹 3종(xlsx 2종, md 1종), 총 16종 |
| **원격** (`remote_server.py`, Vercel) | 키를 요청마다 전달하고 대용량 결과를 호출당 3.5MB 미만의 페이지로 반환 | 공통 조회 13종 + `load_excel_page`, 총 14종 |

원칙: **공통 조회 정의는 카탈로그에 한 번만 두고, 전송·파일시스템 의존 도구만 표면별로 등록한다.** `load_excel_page`는 원격 전용이고 세 파일 반출 도구는 로컬 전용이다.

## 4계층 구조

```
① 데이터 계층   crawler_service.py — coverage의 단일 원천, CrawlerService가 한 줄 위임
                domains/ 패키지    — 도메인별 서비스가 검증·조회·크기가드를 담당
                  query_guards.py = corp_code/연도/reprt_code 등 공용 입력 검증 가드
                  registry.py     = RegistryEntry/as_registry, key·endpoint·label 레지스트리 공용 헬퍼
                                    (report_topics/ownership/material_events/registration_statements 네 도메인이 공유)
                  financials.py   = FinancialsService(전체 계정/주요계정/재무지표), DS003 조회
                  report_topics.py = ReportTopicService(감사정보 등 DS002 topic 레지스트리 조회)
                  company_profile.py = CompanyProfileService(기업개황 단일 조회), DS001 company.json
                  ownership.py    = OwnershipService(대량보유·임원 소유보고 레지스트리 조회), DS004
                  material_events.py = MaterialEventService(주요사항보고 36종 레지스트리 조회), DS005
                  registration_statements.py = RegistrationStatementService(증권신고서 6종 그룹 조회), DS006
                = 모두 DART에서 데이터를 가져와 Result[T]로 반환
                      │
② 도구 카탈로그  tool_catalog.py
                = 모든 도구의 이름·파라미터·설명이 여기 한 번만 존재
                  register_query_tools(공통) / register_export_tools(로컬 전용)
                      │
③ 표면 계층     mcp_server.py(로컬)          remote_server.py(원격)
                = 키를 settings에서 읽음       = 키를 요청(헤더/쿼리)에서 읽음
                  + export_query_excel           + load_excel_page
                      │
④ 출력 계층     원격: 커서 페이지와 최종 wire 크기 검증
                로컬: 첨부 xlsx/md + 조회 결과 xlsx 안전 게시
```

핵심 계약 — `ServiceRunner`(tool_catalog.py): 도구 정의는 "무엇을 조회하는가"만 알고, "키가 어디서 오는가"는 러너가 담당한다. 표면 간에 다를 수 있는 것은 러너와 등록하는 그룹 목록뿐이다.

## 회귀 방어

`tests/test_remote_server_surface.py`와 `tests/test_mcp_server.py`는 원격 14개·로컬 16개 도구 이름을 각각 검증한다. `tests/test_local_excel_export_equivalence.py`는 원격 페이지를 끝까지 이어 붙인 결과와 로컬 조회 결과 XLSX의 행·열이 같음을 검증한다. 공통 13개 도구의 정의는 카탈로그에만 존재한다.

## 새 DART 데이터 domain 추가 레시피 (다음 세션: DART 전체 데이터 확장)

1. **데이터 계층**: 조회 메서드를 서비스에 추가하고 응답 모델을 정의한다(`Result[T]` 반환, 크기 가드는 `section_models.py`의 상한 패턴을 따른다). `crawler_service.py`가 비대해지면 `domains/<이름>_service.py`로 분리하고 CrawlerService가 위임한다.
2. **카탈로그 등록**: 일반 조회 도구라면 `register_query_tools`에 추가해 로컬·원격에 함께 반영한다. 파일 반출 도구는 `register_export_tools`, 원격 페이지 도구는 `register_remote_excel_tool`의 명시적 표면 경계를 유지한다.
3. **테스트**: `test_mcp_server.py`와 `test_remote_server_surface.py`의 기대 도구 집합을 갱신하고, 일반 조회 정의의 공통성을 확인한다. **monkeypatch 주의**: 러너 함수는 등록 시점에 값으로 캡처되므로 `_run_ignoring_context`·`_with_remote_service` 자체를 교체해도 이미 등록된 도구에는 효과가 없다. 로컬 테스트는 호출 시점에 조회되는 `mcp_server._with_service`를 교체하고, 원격 테스트는 `create_remote_server()`를 테스트마다 새로 만들거나 `remote_server.CrawlerService`를 교체한다.
4. **렌더러(로컬 파일 반출)**: xlsx는 `excel_export.py`, md는 `markdown_export.py` 경로를 각각 사용한다. `ParsedDocument`/도메인 모델을 입력으로 받아 파일을 쓰고 `Result[ExportedFile]`(xlsx) 또는 `Result[MarkdownExportedFile]`(md) 형태를 따른다. xlsx는 핵심 재무제표 누락 시 하드 실패하지만, md는 있는 그대로 렌더링하고 `missing_sections`·`collection_status`·`PARTIAL_COLLECTION` 경고로만 알린다. 원격에는 절대 등록하지 않는다(쓰기 가능한 파일시스템 없음).
5. **주의사항**(설계 문서에서 검증된 함정): `find_disclosure`는 최악 수백 왕복이므로 신규 도구에서 호출 금지. 응답 크기는 자르지 말고 상한 초과 시 거부. 키는 오류·로그에 절대 노출 금지.

`get_report_topics`(DS002 정기보고서 주요정보)는 위 레시피를 레지스트리 패턴으로 한 번 더 압축한 사례다. `domains/report_topics.py`의 `REPORT_TOPICS`가 topic 키·OpenDART endpoint·한글 라벨을 한 곳에 모아두므로, **신규 DS002 topic 추가 = `REPORT_TOPICS`에 `ReportTopic` 1줄 추가 + 해당 topic용 픽스처 추가**로 끝난다. 서비스 로직(가드·부분실패 정책·크기 상한)과 `get_report_topics` 도구 정의는 손대지 않는다. 다만 도구 docstring은 지원 topic 목록을 리터럴로 나열하므로 레지스트리 확장 시 함께 갱신해야 하며, 이 정합성은 테스트로 강제된다.

`get_registration_statements`(DS006 증권신고서 주요정보)도 같은 계열의 레지스트리형 조회 도구다. MCP 표면은 `corp_code`, `stmt_type`, `bgn_de`, `end_de` 네 입력만 노출한다(`ctx`는 SDK가 주입하므로 스키마에 나오면 안 된다). `stmt_type`은 `equity_securities`, `debt_securities`, `depositary_receipts`, `merger`, `stock_exchange_transfer`, `division` 중 하나이고 날짜 2개는 필수다. 응답은 DART 공식 그룹 제목별 `groups`와 `returned_group_count`, `returned_row_count`를 돌려주며, 기간 내 자료가 없는 경우도 빈 그룹/행 수와 경고로 응답한다.

## 관련 문서

- `docs/remote_data_service_design.md` — 원격 서비스 설계와 사용자 확정 결정(키 전달 3순위 포함)
- `docs/unlimited_excel_delivery.md` — 원격 커서 페이지와 로컬 전체 결과 XLSX 계약
- `docs/excel_performance_validation.md` — 10,000행×20열 fresh-process 성능 검증 기록
- `README.md` — 사용자 대상 등록·사용 가이드
