# Dart-Crawler MCP

DART의 감사보고서와 검토보고서를 찾아 원문 첨부문서에서 검색·계산 가능한 Excel 파일을 만드는 로컬 MCP 서버입니다. 서버는 사용자 컴퓨터에서 `stdio` 방식으로 실행되며 요청 사이에 회사나 보고서 선택 상태를 저장하지 않습니다.

같은 수집 엔진을 설치 없이 쓸 수 있는 [원격 MCP 서버](#원격-mcp-서버-vercel)도 Vercel에 배포되어 있습니다. 원격 서버는 Excel 파일 대신 보고서 데이터를 그대로 반환합니다.

## 지원 범위

- Python 3.13
- Windows 10/11 x64: v0.1.0 공식 지원
- macOS/Linux: 동일한 오프라인 테스트를 실행하는 실험적 지원
- DART 회사코드 목록과 대상 정기공시에 포함된 회사
- 별도·연결 감사보고서, 분기 검토보고서, 반기 검토보고서

v0.1.0에서는 OCR, 수동 PDF 업로드, 화면 프로그램, DART F유형 독립 감사공시, 원문 화면 모양의 완전한 복제를 지원하지 않습니다. 이미지 전용 구역은 OCR하지 않고 부분수집으로 표시합니다.

## 설치와 API 키

Windows에서 `uv`를 설치한 뒤 프로젝트를 동기화합니다.

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv sync --frozen
```

API 키는 [OpenDART](https://opendart.fss.or.kr/)에서 발급받습니다. 운영체제 환경변수가 프로젝트 `.env`보다 우선합니다.

```powershell
$env:OPEN_DART_API_KEY = "발급받은_키"
$env:DART_MCP_PROJECT_DIR = "C:\작업폴더"
# 선택 사항
$env:DART_MCP_OUTPUT_DIR = "C:\작업폴더\output"
```

환경변수를 사용하지 않으면 MCP 기준 폴더에 `.env`를 만들고 다음처럼 작성합니다. `.env`는 Git에 포함하지 마세요.

```dotenv
OPEN_DART_API_KEY=발급받은_키
DART_MCP_OUTPUT_DIR=output
```

상위 폴더의 `.env`는 검색하지 않습니다. 여러 작업 폴더가 동시에 제공되어 기준 폴더를 하나로 정할 수 없으면 서버는 `CONFIG_ERROR`를 반환합니다.

## Claude Code와 Codex 등록

공개 Git 태그에서 설치하는 최종 명령은 다음과 같습니다.

```powershell
claude mcp add --transport stdio --scope user dart_crawler -- uvx --from git+https://github.com/curisus/Dart-Crawler.git@v0.1.0 dart-crawler-mcp
codex mcp add dart_crawler -- uvx --from git+https://github.com/curisus/Dart-Crawler.git@v0.1.0 dart-crawler-mcp
```

로컬 작업 중에는 다음처럼 실행할 수 있습니다.

```powershell
uv run dart-crawler-mcp
```

## MCP 도구 사용 순서

1. `search_companies(company_query, report_kind)`에서 회사명 또는 종목코드를 검색합니다. 결과는 최대 5개이며 `audit`, `quarterly_review`, `half_year_review` 중 하나를 사용합니다.
2. `list_report_filings(corp_code, report_kind)`에서 최근 5개 사업연도의 대표 공시를 선택합니다. 감사는 `FY`, 반기는 `HY`, 분기는 `1Q`와 `3Q`로 표시합니다.
3. `list_report_attachments(rcept_no)`에서 별도 또는 연결 첨부문서를 선택합니다. 식별자는 `opendart:접수번호:ZIP파일명` 또는 `viewer:접수번호:dcmNo`입니다.
4. `export_report_excel(rcept_no, attachment_id)`로 수집·검증·생성합니다. 결과에는 출력 경로, 전체·부분수집 상태, 기존 파일 재사용 여부, 경고가 포함됩니다.
5. 검색·계산 가능한 Excel 대신 원문 전체를 그대로 옮긴 문서가 필요하면 `export_report_markdown(rcept_no, attachment_id)`을 사용합니다. 첨부문서의 모든 구역(의견, 재무제표, 주석, 기타 서술)을 원문 순서대로 마크다운 파일 하나에 옮기며 금액·문구는 그대로(verbatim) 보존합니다. Excel과 달리 핵심 재무제표가 빠져 있어도 실패하지 않고, 있는 그대로 생성한 뒤 `missing_sections`와 `collection_status`로 무엇이 빠졌는지 알려줍니다.

파일 없이 데이터만 보려면 원격 서버와 동일한 `list_report_sections`·`get_report_sections`·`get_financial_statements`·`get_major_accounts`·`get_financial_indicators`·`get_report_topics`·`get_company_profile`·`get_ownership_reports`(아래 원격 도구 사용 순서 참조)도 로컬에서 그대로 사용할 수 있습니다. 로컬 서버는 전체 기능을 제공하며 API 키가 컴퓨터 밖으로 나가지 않고, 원격 서버는 설치 없이 모든 조회 도구를 제공합니다(파일 반출은 로컬 전용).

모든 도구는 `ok`, 성공 시 `data`, 실패 시 `error { code, message, retryable, details }`, `warnings`, `next_action` 구조를 사용합니다. API 키나 비밀번호는 오류 내용에 넣지 않습니다.

## 원격 MCP 서버 (Vercel)

설치 없이 사용할 수 있는 원격 서버가 Vercel의 Linux 환경에 배포되어 있습니다.

- 주소: `https://dart-mcp-remote.vercel.app/api/mcp`
- 인증: 요청마다 본인의 OpenDART API 키를 전달합니다. 서버는 키를 저장하지 않으며, 키 없이 도구를 호출하면 `CONFIG_ERROR`로 거부합니다. 서버 연결과 도구 목록 확인은 키 없이도 됩니다.
  - 기본: `X-OpenDART-API-Key: 발급받은_키` 헤더
  - 대체: `Authorization: Bearer 발급받은_키` 헤더
  - 헤더를 못 쓰는 클라이언트용: URL 뒤에 `?key=발급받은_키`
- 도구: `search_companies`, `list_report_filings`, `list_report_attachments`, `list_report_sections`, `get_report_sections`, `get_financial_statements`, `get_major_accounts`, `get_financial_indicators`, `get_report_topics`, `get_company_profile`, `get_ownership_reports` 11개 (조회 전용)
- Excel 파일 생성(`export_report_excel`)은 원격 서버가 파일을 저장할 위치가 없어 제공하지 않습니다. 로컬 서버에서만 가능합니다.

### Claude for Excel에서 사용하기

Claude for Excel(Excel 안에서 Claude를 쓰는 추가 기능)은 claude.ai 계정에 등록한 커넥터를 그대로 사용합니다. 아래 절차로 한 번만 등록하면 Excel 사이드바에서 DART 데이터를 바로 조회할 수 있습니다.

1. [claude.ai](https://claude.ai) 접속 → 설정 → **Connectors** → **Add custom connector**
2. URL 칸에 `https://dart-mcp-remote.vercel.app/api/mcp` 입력
3. **Request headers** 항목을 열고 헤더를 추가합니다.
   - 이름: `Authorization`
   - 값: `Bearer 발급받은_키` — `Bearer` 뒤 공백 하나를 포함해 그대로 입력합니다. 키는 [OpenDART](https://opendart.fss.or.kr/)에서 발급받습니다.
4. **Add**를 눌러 저장합니다. 저장한 키 값은 다시 표시되지 않습니다.
5. Excel에서 Claude 사이드바를 열고, 대화 입력창의 **+** 버튼 → **Connectors**에서 방금 등록한 커넥터를 켭니다.
6. 예를 들어 "삼성전자 2025 사업보고서의 재무상태표를 가져와 시트에 정리해줘"라고 요청하면 Claude가 아래 원격 도구 사용 순서대로 호출해 데이터를 가져옵니다.

주의: Request headers 기능은 베타라서 계정에 따라 아직 보이지 않을 수 있습니다. **Request headers 칸이 없다면**, 2번의 URL 대신 키를 포함한 주소를 등록하세요.

```
https://dart-mcp-remote.vercel.app/api/mcp?key=발급받은_키
```

이 방식은 키가 주소에 포함되어 서버 운영자의 접속 기록에 남을 수 있으므로, Request headers 칸이 생기면 헤더 방식으로 바꾸는 것을 권장합니다. claude.ai 웹과 Claude Desktop에서도 같은 절차로 사용할 수 있습니다.

### Claude Code에서 원격 서버 등록

```powershell
claude mcp add --transport http --scope user dart_remote https://dart-mcp-remote.vercel.app/api/mcp --header "X-OpenDART-API-Key: 발급받은_키"
```

이 명령은 키를 사용자 설정 파일에 평문으로 저장하고 명령어 기록에도 남으므로 본인 컴퓨터에서만 사용하세요.

### 원격 도구 사용 순서

1. `search_companies`, `list_report_filings`, `list_report_attachments`는 로컬과 동일하게 사용합니다.
2. `list_report_sections(rcept_no, attachment_id)`로 첨부문서의 목차를 확인합니다. 섹션마다 `section_id`, 제목, 종류(`kind`), 표 셀 수, 이미지 포함 여부가 표시되고 내용은 포함되지 않습니다. 이미지 전용 구역은 OCR하지 않으므로 내용이 비어 있을 수 있습니다.
3. `get_report_sections(rcept_no, attachment_id, section_ids, section_kinds)`로 선택한 섹션의 내용을 받습니다. `section_ids`(목차의 id), `section_kinds`(예: `balance_sheet`, `note`) 중 하나 이상을 지정하며, `section_kinds`에 `statements`를 주면 재무상태표·손익(포괄손익)계산서·자본변동표·현금흐름표 네 가지 종류의 재무제표 구역을 한 번에 받습니다. 한 번에 받을 수 있는 분량에는 한도가 있으며, 넘으면 일부만 주는 대신 요청을 나누라는 안내와 함께 거부합니다.
4. 원문 첨부문서를 거치지 않고 DART 공식 재무 API에서 바로 조회하려면 아래 세 도구를 사용합니다. `corp_code`는 `search_companies`로 확인한 8자리 DART 고유번호이며 종목코드가 아닙니다. `reprt_code`는 `11011`(사업보고서/연간), `11012`(반기), `11013`(1분기), `11014`(3분기)이고, 2015 사업연도부터 조회됩니다. 금액은 모두 DART 원문 그대로의 문자열(쉼표 포함 가능)이며 서버가 숫자로 변환하지 않습니다.
   - `get_financial_statements(corp_code, bsns_year, reprt_code, fs_div="CFS")`: 한 회사의 한 보고서 기간에 대한 전체 공식 계정과목을 받습니다. `fs_div`는 기본값 `CFS`(연결) 또는 `OFS`(별도)이며, 연결재무제표가 없는 회사는 `fs_div="OFS"`로 다시 시도하라는 안내와 함께 거부됩니다.
   - `get_major_accounts(corp_codes, bsns_year, reprt_code)`: 최대 10개 회사의 주요 재무상태표·손익계산서 계정을 한 번에 받아 회사 간 비교에 사용합니다. 계정 상세는 `get_financial_statements`를 사용하세요.
   - `get_financial_indicators(corp_codes, bsns_year, reprt_code, idx_cl_code)`: 최대 10개 회사의 재무지표 한 분류를 받습니다. `idx_cl_code`는 `M210000`(수익성), `M220000`(안정성), `M230000`(성장성), `M240000`(활동성) 중 하나입니다.
5. 정기보고서 주요정보(DS002) 28종을 확인하려면 `get_report_topics(corp_code, bsns_year, reprt_code, topics)`를 사용합니다. `topics`에는 아래 중 하나 이상, 최대 10개까지 지정할 수 있습니다. 배당·주주(최대주주·소액주주)·임원·보수·채무증권 미상환 잔액·자금 사용내역 등을 포괄하며, 그중 감사인 관련 3종은 다음과 같습니다.
   - `audit_opinion`: 회계감사인의 명칭 및 감사의견
   - `audit_service_contract`: 감사용역 체결현황
   - `non_audit_service_contract`: 회계감사인과의 비감사용역 계약체결 현황

   나머지 topic 키와 라벨은 지원하지 않는 topic으로 호출했을 때 오류 상세(`supported_topics`)에 전체 목록이 함께 반환됩니다. 결과는 요청한 `topics` 순서대로 반환되며, topic별 행 수(`row_count`)와 원문 필드를 그대로 담습니다. 자료가 없는 topic은 빈 목록으로 처리되고 경고가 함께 반환되며, 요청한 모든 topic이 비어 있으면 실패로 처리됩니다.
6. `get_company_profile(corp_code)`로 기업개황(DS001)을 조회합니다. 회사명(국문·영문), 종목명·종목코드, 대표자명, 법인구분(`corp_cls`), 사업자·법인등록번호, 주소, 홈페이지·IR URL, 전화·팩스번호, 업종코드, 설립일, 결산월을 원문 그대로 반환합니다.
7. `get_ownership_reports(corp_code, report_type, bgn_de, end_de)`로 지분공시(DS004)를 조회합니다. `report_type`은 `major_holding`(5% 대량보유 상황보고) 또는 `insider_ownership`(임원·주요주주 소유보고) 중 하나이며, 한 번의 호출은 한 가지 보고 유형만 받습니다. 행은 원문 필드 그대로 반환되고, 해당 보고 유형의 자료가 없는 회사도 실패하지 않고 빈 목록과 경고로 응답합니다. 지원하지 않는 `report_type`은 오류 상세에 전체 목록과 함께 거부됩니다. `bgn_de`·`end_de`(둘 다 선택, `YYYYMMDD`)로 접수일 기간을 좁힐 수 있으며 비워두면 그쪽 경계는 열려 있습니다. 삼성전자의 `insider_ownership`처럼 보고 이력이 많아 응답 행 수 한도를 넘는 회사는 이 기간으로 나누어 다시 호출해야 합니다. 응답의 `total_row_count`는 기간 필터 적용 전 행 수, `returned_row_count`는 필터 적용 후 실제 반환된 행 수입니다.

## 출력 파일

기본 출력 폴더는 기준 폴더 아래 `output`입니다. `DART_MCP_OUTPUT_DIR`가 있으면 그 위치를 사용합니다. 첫 시트는 항상 `수집정보`이고, 이후 원문 순서에 따라 의견, 핵심 재무제표, 주석, 기타 구역을 별도 시트로 저장합니다. 핵심 재무제표가 없으면 파일을 만들지 않습니다. 일부 구역이 이미지 전용이면 파일명에 `_부분수집`을 붙입니다.

원문 문단과 표 칸의 선행 들여쓰기(공백, 탭, 비분리공백, 전각공백)는 시트 값에 그대로 유지하고, 원문의 빈 문단은 빈 행으로 반영하여 줄 간격을 보존합니다. 다만 확실한 숫자 금액은 계산 가능하도록 들여쓰기 없이 숫자로 저장합니다.

금액은 확실한 숫자만 Excel 숫자로 저장하며, 외부 입력이 수식으로 실행되지 않도록 문자열을 검사합니다. 같은 접수번호·첨부 식별자·원문 SHA-256을 가진 기존 파일은 재사용하고, 이름만 같은 다른 원문은 덮어쓰지 않습니다.

## 개발 검증

```powershell
uv sync --frozen
uv run ruff check .
uv run mypy --strict src tests
uv run pytest -v
uv build
```

실제 OpenDART 자료를 사용하는 검사는 API 키가 있을 때만 별도로 실행합니다.

```powershell
uv run pytest -v -m live
```
