# 도구 표면 아키텍처 — 로컬·원격 통합 관리

2026-08-20 사용자 확정. 로컬 버전과 원격 버전의 기능 범위(coverage)를 한 곳에서 관리하기 위한 구조와, DART 전체 데이터로 확장할 때 따라야 할 레시피를 기록한다.

## 컨셉 (사용자 확정, 2026-08-20 변경)

원격을 "핵심 조회만 압축 제공"으로 두던 초기 방침을 바꿔, **원격도 조회(query) 도구는 전부 제공**하기로 확정했다. 로컬만 갖는 것은 파일 반출(export) 그룹뿐이다.

| 표면 | 컨셉 | 도구 구성 |
|---|---|---|
| **로컬** (`mcp_server.py`, stdio) | 전체 기능 superset. API 키가 컴퓨터 밖으로 나가지 않는 안전성이 강점. 파일 반출(xlsx, 향후 md 등)을 포함해 더 넓은 작업을 지원 | 공통 조회 9종 + export 그룹 |
| **원격** (`remote_server.py`, Vercel) | 모든 조회 도구를 제공. 설치 없이 사용, 키는 요청마다 전달(헤더 > Bearer > `?key=`) | 공통 조회 9종 전부 |

원칙: **중복 기능은 카탈로그로 통합, 파일 반출만 로컬에만.** 원격에는 파일을 쓸 수 없어 export 그룹만 못 올리고, 조회 도구는 로컬·원격에 항상 동시에 올린다.

## 4계층 구조

```
① 데이터 계층   crawler_service.py — coverage의 단일 원천, CrawlerService가 한 줄 위임
                domains/ 패키지    — 도메인별 서비스가 검증·조회·크기가드를 담당
                  query_guards.py = corp_code/연도/reprt_code 등 공용 입력 검증 가드
                  financials.py   = FinancialsService(전체 계정/주요계정/재무지표), DS003 조회
                  report_topics.py = ReportTopicService(감사정보 등 DS002 topic 레지스트리 조회)
                = 모두 DART에서 데이터를 가져와 Result[T]로 반환
                      │
② 도구 카탈로그  tool_catalog.py
                = 모든 도구의 이름·파라미터·설명이 여기 한 번만 존재
                  register_query_tools(공통) / register_export_tools(로컬 전용)
                      │
③ 표면 계층     mcp_server.py(로컬)          remote_server.py(원격)
                = 차이는 ServiceRunner 하나:   = 차이는 ServiceRunner 하나:
                  키를 settings에서 읽음         키를 요청(헤더/쿼리)에서 읽음
                      │
④ 렌더러        원격: 데이터 봉투 그대로 반환
                로컬: excel_export.py(xlsx) / (예정) markdown 렌더러
```

핵심 계약 — `ServiceRunner`(tool_catalog.py): 도구 정의는 "무엇을 조회하는가"만 알고, "키가 어디서 오는가"는 러너가 담당한다. 표면 간에 다를 수 있는 것은 러너와 등록하는 그룹 목록뿐이다.

## 회귀 방어

`tests/test_remote_server.py::test_local_surface_is_the_remote_surface_plus_the_export_group`
— 로컬 = 원격 + export 그룹이며, 공유 도구의 설명·파라미터 스키마가 두 표면에서 완전히 동일함을 검증한다. 카탈로그 밖에서 도구를 정의하면 이 테스트가 실패한다.

## 새 DART 데이터 domain 추가 레시피 (다음 세션: DART 전체 데이터 확장)

1. **데이터 계층**: 조회 메서드를 서비스에 추가하고 응답 모델을 정의한다(`Result[T]` 반환, 크기 가드는 `section_models.py`의 상한 패턴을 따른다). `crawler_service.py`가 비대해지면 `domains/<이름>_service.py`로 분리하고 CrawlerService가 위임한다.
2. **카탈로그 등록**: 조회 도구라면 `register_query_tools`에 추가 → 로컬·원격 동시 반영. 파일 반출 도구라면 `register_export_tools`에 추가 → 로컬에만 반영.
3. **테스트**: 표면 구성 테스트 2곳(`test_mcp_server.py`, `test_remote_server.py`)의 기대 도구 집합에 이름을 추가한다. parity 테스트는 자동으로 두 표면의 일치를 검증한다. **monkeypatch 주의**: 러너 함수는 등록 시점에 값으로 캡처되므로 `_run_ignoring_context`·`_with_remote_service` 자체를 교체해도 이미 등록된 도구에는 효과가 없다. 로컬 테스트는 호출 시점에 조회되는 `mcp_server._with_service`를 교체하고, 원격 테스트는 `create_remote_server()`를 테스트마다 새로 만들거나 `remote_server.CrawlerService`를 교체한다.
4. **렌더러(로컬 파일 반출)**: xlsx는 `excel_export.py` 경로 재사용. **md 렌더러는 신규 확장점** — `ParsedDocument`/도메인 모델을 입력으로 받아 파일을 쓰고 `Result[ExportedFile]` 형태를 따른다. 원격에는 절대 등록하지 않는다(쓰기 가능한 파일시스템 없음).
5. **주의사항**(설계 문서에서 검증된 함정): `find_disclosure`는 최악 수백 왕복이므로 신규 도구에서 호출 금지. 응답 크기는 자르지 말고 상한 초과 시 거부. 키는 오류·로그에 절대 노출 금지.

`get_report_topics`(DS002 정기보고서 주요정보)는 위 레시피를 레지스트리 패턴으로 한 번 더 압축한 사례다. `domains/report_topics.py`의 `REPORT_TOPICS`가 topic 키·OpenDART endpoint·한글 라벨을 한 곳에 모아두므로, **신규 DS002 topic 추가 = `REPORT_TOPICS`에 `ReportTopic` 1줄 추가 + 해당 topic용 픽스처 추가**로 끝난다. 서비스 로직(가드·부분실패 정책·크기 상한)과 `get_report_topics` 도구 정의는 손대지 않는다. 다만 도구 docstring은 지원 topic 목록을 리터럴로 나열하므로 레지스트리 확장 시 함께 갱신해야 하며, 이 정합성은 테스트로 강제된다.

## 관련 문서

- `docs/remote_data_service_design.md` — 원격 서비스 설계와 사용자 확정 결정(키 전달 3순위 포함)
- `README.md` — 사용자 대상 등록·사용 가이드
