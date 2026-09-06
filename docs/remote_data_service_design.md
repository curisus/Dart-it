# DART Crawler 원격 데이터 서비스 전환 — 세션 A 설계 문서

## Context (왜 이 작업을 하는가)

- 현재 dart_crawler는 **로컬 설치형 stdio MCP 서버**다. 사용자는 uv/Python 설치와 `claude mcp add` 등록이 필요하고, 산출물은 서버 컴퓨터에 저장되는 Excel 파일이다.
- 목표: **설치 불필요 원격 데이터 서비스** — Claude 계열 클라이언트에 서버 주소만 등록하면 감사·검토보고서의 표 데이터를 (파일이 아니라) **데이터로** 돌려받는다.
- 원본 요청: 본체 저장소 `feedbacks/20260811_remote_mcp_self_hosted`(pending). 2026-08-19 확정 방향: 데이터 반환 우선 · 정기보고서 최우선 · Vercel 우선 배포.
- 이 문서가 **세션 A(설계) 산출물**이다. 승인 후 세션 B(감사·검토보고서 데이터 반환 도구 구현)로 진행한다.

## 사용자 확정 결정 (2026-08-19 AskUserQuestion)

| 결정 | 선택 |
|---|---|
| 도구 목록 | **5개**: 기존 3개(search_companies, list_report_filings, list_report_attachments) + 신규 `list_report_sections`(구역 목차) + `get_report_sections`(선택 구역 표 데이터). `export_report_excel`은 원격판 제외·로컬판 유지. **2026-08-20 보완**: 도구 정의를 `tool_catalog.py`로 통합하고 로컬 표면을 "조회 5종 + export"의 superset으로 확장 — `docs/tool_surface_architecture.md` 참조 |
| 저장소 구조 | **현 저장소 확장** — api/ 진입점 + vercel.json, src/dart_crawler 공유(DRY) |
| 키 전달 | **헤더 필수** — 요청마다 HTTP 헤더로 전달, 서버 env 폴백 없음, URL 노출 금지. **2026-08-20 일부 번복(사용자 AskUserQuestion 승인)**: claude.ai 커넥터의 Request headers 기능이 베타 미배포인 계정은 헤더를 전혀 보낼 수 없음이 확인되어, 최후 폴백으로 URL `?key=` 쿼리 전달을 허용. 헤더가 항상 우선이며 OAuth 구현은 공개 확산 시점까지 보류 |
| 접속 방식 | **MCP streamable-http 단독** |

## 탐색으로 확정된 사실 (설계 근거, 전부 file:line 검증)

- 기존 3개 도구는 이미 순수 데이터 반환. 파일시스템 결합은 export 경로(excel_export.py:137, workbook_writer.py:54-65, output_file.py)와 `load_settings`(settings.py:80 `is_dir()`, :47 `.env`)뿐. 전역 상태·캐시 0건 → **이미 무상태 구조**. 접합점은 `_run_with_settings`(mcp_server.py:36-47, 카탈로그 통합 후 위치).
- 파싱 결과는 Excel 이전에 `ParsedDocument → DocumentSection → DocumentBlock`(document_model.py:43-99)으로 존재. 주석은 `주석 N` 개별 섹션으로 분할됨(document_model.py:257-291). 섹션에 안정적 ID는 없음(인덱스+제목뿐).
- 실측: 감사보고서 1건 = 섹션 48~59개, 전체 JSON 159~533KB(AI 컨텍스트에 과대), 핵심 재무제표 4종 ≈ 전체 셀의 9%, 단일 주석 최대 3,320셀 → 구역 선택 구조 필수.
- MCP SDK 2.0.0(설치본 검증): `Context.headers`로 도구 함수 안에서 HTTP 헤더 접근(mcpserver/context.py:277-285), sync 도구는 스레드로 실행되어 async 전환 불필요(mcpserver/resolve.py:553-556), `streamable_http_app(json_response, stateless_http, transport_security, ...) -> Starlette`(mcpserver/server.py:1218-1245). **함정**: transport_security 미지정 시 DNS rebinding 보호 자동 활성화로 Vercel에서 전 요청 421 거부(lowlevel/server.py:738-744) → 명시적 비활성화 필요.
- Vercel(2026-07 공식 문서): Python 3.13 + ASGI 지원, Hobby maxDuration 최대 300초(vercel.json에 진입점 파일 기준 설정).
- 게이트·함정: pytest `filterwarnings=["error"]`(신규 의존 경고 하나로 273개 전멸 — SDK의 deprecated 로깅 API 사용 금지), CI push 트리거에 현 브랜치 없음(PR은 동작), 로컬 셸에 OPEN_DART_API_KEY 있으면 `pytest -v`가 live 테스트 실행, Vercel=Linux vs 개발=Windows(공식 레그).
- 실행시간 위험: `find_disclosure`(dart_api.py:134-186) 최악 수백 왕복 — **신규 섹션 도구는 이 함수를 호출하지 않는 흐름으로 설계해 원천 회피**(회사명·접수일 메타는 Excel 경로에만 필요했음).

## 설계

### 1. 요청별 API 키 주입 (헤더 우선, 쿼리 최후 폴백)

- 헤더: `X-OpenDART-API-Key` 1순위, `Authorization: Bearer <키>` 2순위 폴백. Claude Code 등록 예: `claude mcp add --transport http dart <url> --header "X-OpenDART-API-Key: <키>"`.
- 쿼리 폴백(2026-08-20 추가, 사용자 승인): 헤더를 전혀 못 보내는 클라이언트(Request headers 베타 미배포 claude.ai 계정)를 위해 URL `?key=<키>`를 3순위로 수용. 키가 서버 접속 로그에 남을 수 있으므로 헤더가 가능해지면 헤더 사용을 권장.
- 검증 계층: **HTTP 401이 아니라 도구 계층의 `Result.failure(ErrorCode.CONFIG_ERROR)`** — 401은 MCP 클라이언트의 OAuth 탐색을 유발해 혼란. `initialize`/`tools/list`는 키 없이 성공해야 커넥터 등록이 가능. 형식은 맞으나 무효인 키는 기존 `UPSTREAM_AUTH` 매핑이 처리. 새 ErrorCode 불필요.
- 키 획득: 도구 파라미터에 `ctx: Context` 어노테이션 → SDK 자동 주입 → `ctx.headers`에서 추출(`_api_key_from_headers(headers) -> Result[SecretStr]`).

### 2. settings 리팩터링 — 원격 경로는 load_settings를 타지 않음

`CrawlerService`의 실사용은 `api_key`와 `output_dir`(export 전용)뿐이므로 생성자를 좁힌다:
```python
class CrawlerService:
    def __init__(self, api_key: SecretStr, http_client: HttpClient, *, output_dir: Path | None = None) -> None: ...
    # export_report_excel: output_dir=None → CONFIG_ERROR
```
- `load_settings`/`AppSettings`(settings.py)는 로컬 stdio 전용으로 무변경. mcp_server.py의 호출부만 수정.
- 원격은 `CrawlerService(헤더키, http)` — project_dir/.env/output_dir 개념 자체가 없어 Vercel 읽기전용 FS와 충돌 없음.

### 3. 신규 도구 데이터 흐름 (find_disclosure 미호출)

```
ctx.headers → 키 추출
→ CrawlerService._load_parsed_document(rcept_no, attachment_id)   # 신규 공용 메서드
   = AttachmentService.list → 첨부 선택(기존 crawler_service.py:170 재사용) → read_selected
     → parse_attachment(document_parser.py:11) → validate_document(하드 게이트 유지)
→ summarize_sections(...)  또는  select_sections(...)
```
`export_report_excel`도 `_load_parsed_document`를 재사용하도록 내부 정리(DRY).

### 4. section_id와 선택 의미론

- **`s{원문순서:03d}-{kind}`** (예: `s001-opinion`, `s007-balance_sheet`, `s023-note`). 파싱이 결정적이므로 같은 rcept_no+attachment_id → 항상 동일. 제목 중복·주석 비순차(tests/test_parsers.py:738)에도 유일성 보장. 응답에 `source_sha256`+`parser_version` 포함으로 드리프트 검출.
- `get_report_sections(rcept_no, attachment_id, section_ids=(), section_kinds=())`: 둘 중 1개 이상 필수, 합집합·중복 제거·원문 순서 유지. `section_kinds`는 SectionKind 7종 + 별칭 `"statements"`(4대 재무제표). 미지 값 → INVALID_INPUT, 0건 매칭 → NOT_FOUND(+ next_action "list_report_sections를 다시 호출").
- get은 선행 list 없이도 동작(one-shot: kind 선택자만으로 호출 가능) — stateless 재파싱 비용 완화.
- **크기 가드 2종** — 부분 잘림(truncation)은 정합성 검증이 불가능하므로 어느 쪽도 자르지 않고 거절한다.
  1. **`MAX_RESPONSE_CELLS = 20_000`** (표): 초과 시 INVALID_INPUT + details(`selected_cell_count`, `limit`).
  2. **`MAX_RESPONSE_TEXT_CHARS = 200_000`** (표 밖 서술 텍스트): 초과 시 INVALID_INPUT + details(`selected_text_char_count`, `limit`).
- 두 지표는 **서로 겹치지 않는다** — 표 내용은 셀 수가 이미 값을 매기므로 텍스트 지표는 TABLE이 아닌 블록(제목·문단·이미지)의 `len(text)` 합만 센다. 셀만 세면 주석·감사의견처럼 **표가 0셀인 서술 위주 선택이 가드를 통째로 우회**한다(주석 55개·0셀·JSON 267KB가 통과하던 결함).
- `SectionSummary.text_char_count` / `ReportSectionList.total_text_char_count`로 목차 단계에서 두 비용을 모두 보여 주므로, 클라이언트는 요청 전에 분할 여부를 판단할 수 있다. 응답 쪽도 같은 두 축(`ReportSectionData.returned_cell_count` / `returned_text_char_count`)을 실어, 요청한 것과 받은 것을 블록을 훑지 않고 대사할 수 있다.
- 200,000자 근거: 실제 감사보고서 **전체**의 서술 분량이 이 한도보다 훨씬 작아(삼성전자 47구역 보고서 전체가 실측 **29,611자**) 정상 요청은 하나도 거절되지 않고, 설계가 "과대"로 규정한 159~533KB 구간의 선택은 분할된다.
- 두 한도를 동시에 초과하면 INVALID_INPUT 하나에 양쪽 키를 모두 실어(`selected_cell_count`+`limit`, `selected_text_char_count`+`text_char_limit`) 셀만 줄인 뒤 다시 거절당하는 왕복을 없앤다.

### 5. 응답 모델 (src/dart_crawler/section_models.py — 전부 frozen, extra="forbid")

```python
class TableData(BaseModel):
    rows: tuple[tuple[str, ...], ...]                          # 셀은 전부 문자열(원문 그대로)
    merged_ranges: tuple[tuple[int, int, int, int], ...] = () # 1-base (r1,c1,r2,c2)

class SectionBlock(BaseModel):
    kind: BlockKind; text: str = ""; table: TableData | None = None; image_source: str | None = None

class SectionSummary(BaseModel):
    section_id: str; title: str
    heading: str | None = None                 # 주석 원제목("28. 재무위험관리"), 그 외 None
    kind: SectionKind
    block_count: int; table_count: int
    cell_count: int; text_char_count: int      # 표 / 표 밖 서술, 서로 겹치지 않음
    has_image: bool

class ReportSectionList(BaseModel):    # list_report_sections 응답
    rcept_no: str; attachment_id: str; report_title: str | None
    source_type: str; source_sha256: str; parser_version: str
    coverage_complete: bool; section_count: int
    total_cell_count: int; total_text_char_count: int
    sections: tuple[SectionSummary, ...]

class SectionData(BaseModel):
    section_id: str; title: str; kind: SectionKind; blocks: tuple[SectionBlock, ...]

class ReportSectionData(BaseModel):    # get_report_sections 응답
    rcept_no: str; attachment_id: str; source_sha256: str; parser_version: str
    returned_cell_count: int; returned_text_char_count: int   # 목차와 같은 두 축
    sections: tuple[SectionData, ...]
```
순수 함수: `section_id(index, kind)`, `summarize_sections(document)`, `validate_section_selectors(section_ids, section_kinds) -> GuardViolation | None`, `select_sections(document, section_ids, section_kinds) -> Result[...]`. 선택자 구문 검증은 `validate_section_selectors`에 있고 첨부 다운로드 **이전**에 호출한다 — 오타 하나에 OpenDART 원문 다운로드가 낭비되지 않도록. `select_sections`도 같은 함수를 최상단에서 호출해 단독 정합성을 유지한다. 섹션 데이터는 블록 전체(제목/문단/표/이미지) 포함 — 주석·감사의견은 서술문이 본체이므로.

### 6. 핵심 재무제표 게이트 — 데이터 도구는 경고로 완화

- Excel 경로의 하드 실패(excel_export.py:99-109, CORE_STATEMENT_MISSING)는 무변경 유지.
- 데이터 도구의 계약은 "원문에 있는 것을 그대로 반환": 4대 재무제표 결측 시 실패 대신 **`PARTIAL_COLLECTION` 경고 + details.missing_sections**. `_missing_core_sections`(excel_export.py:246-262)는 공용 모듈로 이동해 양쪽에서 공유.
- 단 `validate_document`(파싱 충실도: 커버리지 완전성·표 직사각형·병합 정합)는 **양쪽 모두 하드 게이트 유지** — 파싱이 깨진 데이터를 반환하지 않는다.

### 7. 모듈 배치 (snake_case)

| 파일 | 상태 | 내용 |
|---|---|---|
| `src/dart_crawler/section_models.py` | 신규 | 위 모델 + 순수 함수 |
| `src/dart_crawler/crawler_service.py` | 변경 | 생성자 축소, `_load_parsed_document` 추출, `list_report_sections`/`get_report_sections` 추가 |
| `src/dart_crawler/remote_server.py` | 신규 | `create_remote_server() -> MCPServer`(도구 5개, ctx 주입), `_api_key_from_headers`, `_with_remote_service`, `build_app(*, path="/api/mcp") -> Starlette` |
| `src/dart_crawler/mcp_server.py` | 변경 | CrawlerService 호출부만 수정(stdio·도구 4개 유지) — **2026-08-20 카탈로그 통합으로 조회 5종+export 6종의 superset으로 확장** |
| `api/mcp.py` | 신규 | `app = build_app()` (파일 경로=URL `/api/mcp`) |
| `vercel.json` | 신규 | `{"functions": {"api/mcp.py": {"maxDuration": 300}}}` |
| `requirements.txt` | 신규 | `uv export --no-dev --no-emit-project --no-hashes` + 로컬 패키지 `.` 한 줄 |
| `tests/test_section_models.py`, `tests/test_remote_server.py` | 신규 | 아래 TDD 목록 |
| `scripts/validate_remote_live.py` | 신규 | 라이브 검증 클라이언트 |

- **로컬/원격은 별도 MCPServer 인스턴스** (표면 6개 vs 5개, 키 소스 상이). 공유는 서비스 계층에 더해 **도구 카탈로그 계층(`tool_catalog.py`, 2026-08-20)**에서 달성 — 도구 정의는 카탈로그에 한 번만 존재하고 표면은 러너만 다르다.
- `build_app`: `streamable_http_app(streamable_http_path=path, json_response=True(단일 JSON 응답·서버리스 친화), stateless_http=True, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))` — 마지막 항목이 Vercel 421 함정 회피(인증은 요청별 키가 담당).
- `build_app`은 그 위에 **POST 전용 가드**(`_PostOnlyEndpoint`, 순수 ASGI 미들웨어)를 씌운다. json_response+stateless 조합에서는 서버→클라이언트 스트림에 실을 것이 아예 없는데도 SDK는 GET에 SSE 스트림을 열고 클라이언트가 끊을 때까지 유지한다(streamable_http.py:687 `_handle_get_request`). 서버리스에서는 **인증 없는 GET 한 건이 함수를 최대 실행시간(300초)까지 점유**하므로, MCP 경로의 비-POST 요청은 즉시 `405 Allow: POST`로 끝낸다. SDK 기본 405가 내보내던 `Allow: GET, POST, DELETE`(GET을 쓸 수 있다고 광고)도 함께 바로잡힌다.

## 검증·증거 계획 (세션 B에서 실행 — 코드 읽기 추론 보고 금지)

### (a) 프로그램적 셀 단위 교차 검증 (zero-missing)
1. 같은 소스 바이트를 두 경로로: ① `parse_attachment` 독립 파스 ② `get_report_sections`(전 섹션) JSON.
2. 단언: 모든 TABLE 블록 `rows` 문자열 완전 일치, `merged_ranges` 일치, 섹션 수·순서·제목·kind·문단 텍스트 일치.
3. `validate_document`의 `checked_cell_count` ↔ 응답 `returned_cell_count` 대사 — 누락 0 단언.
4. `workbook_validation._sheet_expectations`(workbook_validation.py:283-321)의 {(row,col): value} 맵과 JSON 재구성 맵 비교 — Excel 경로와 데이터 경로가 동일 원본 사실임을 증명.

### (b) 라이브 검증 (실존 접수번호, OBSERVED/CONSTRUCTED 라벨로 validation_log.md 기록)
- 서버: `uv run uvicorn --factory dart_crawler.remote_server:build_app --port 8765` (서버에 키 없음).
- 클라이언트 `scripts/validate_remote_live.py`(키는 클라이언트 env에서): search→filings→attachments→sections 목차→statements 선택 수신, 셀 표본 3곳 이상을 DART 원문과 대조.
- 음성 케이스: 키 헤더 없음 → `ok:false, error.code=="CONFIG_ERROR"` 확인, Bearer 폴백 1회 확인.

### (c) TDD 테스트 목록 (구현 전 작성)
- test_section_models: section_id 안정성(제목 중복·주석 비순차 케이스 재사용) / summarize 집계 정확성 / select 합집합·순서·별칭·미지 kind INVALID_INPUT·0건 NOT_FOUND / 크기 가드 초과 INVALID_INPUT / 핵심표 결측 → 성공+PARTIAL_COLLECTION.
- test_remote_server: `_api_key_from_headers` 변형(직접/Bearer/대소문자/None=stdio) / **도구 표면 단언: 원격=정확히 5개(export 부재), 로컬=4개 유지** / `httpx2.ASGITransport(app=build_app())` in-process 통합: 키 없는 tools/call → CONFIG_ERROR 봉투 / `output_dir=None` export → CONFIG_ERROR.
- 기존 273개 무회귀. 게이트: `uv run ruff check .` / `uv run mypy --strict src tests` / `uv run pytest -v`.

## 세션 로드맵

- **세션 B (다음)**: 설계 문서를 저장소 docs/에 반영 → TDD로 section_models → crawler_service 리팩터링 → remote_server → uvicorn 라이브 검증 + validation_log.md. api/mcp.py·vercel.json·requirements.txt는 스캐폴드만(배포 안 함). 커밋 전 적대 리뷰 주체는 커밋 직전 사용자 확인(기본: codex), 푸시는 사용자 확인 후.
- **세션 C (Vercel 배포)**: 미검증 3건 확정(① /api/mcp 경로 동작 ② Python 버전 핀 방식 ③ requirements의 `.` 로컬 패키지 설치 가부) → 배포 URL smoke test(라이브 스크립트 재실행) → Claude 클라이언트 등록 문서화 → CI ubuntu 레그 승격·push 트리거 정리.
- **세션 D (성능)**: corpCode ZIP 웜 인스턴스 캐시(순수 캐시, stateless 계약 무충돌), 응답 페이징·주석 키워드 선택(기존 백로그 연계).

## 리스크

| 리스크 | 근거 | 대응 |
|---|---|---|
| DNS rebinding 자동 활성화 → Vercel 전 요청 421 | lowlevel/server.py:738-744 (직접 확인) | build_app에서 명시적 비활성화 |
| filterwarnings=["error"] + 신규 import 경고 | pyproject:93 | starlette/uvicorn은 이미 mcp 전이 의존으로 설치 확인, SDK deprecated 로깅 API 사용 금지, 테스트에서 실제 import |
| HTTP 401 → 클라이언트 OAuth 탐색 혼선 | MCP 스펙 동작 | 도구 계층 Result 봉투로 통일 |
| claude.ai 커넥터가 커스텀 헤더 미지원 | Bearer 중심 | Authorization: Bearer 폴백 → **대응 불충분으로 판명(2026-08-20)**: Request headers 베타 미배포 계정은 헤더 자체를 못 보냄. URL `?key=` 쿼리 폴백으로 해소 |
| Vercel=Linux vs 개발=Windows | ci.yml ubuntu experimental | 세션 C에서 ubuntu 승격 |
| `Context` 공개 import 경로 미확정 | mcpserver/context.py 정의만 확인 | 구현 시 확인(기능 영향 없음) |
