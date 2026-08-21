# Dart it

OpenDART 기업공시를 Claude와 Codex에서 바로 조회하고, 로컬에서는 검증된 Excel·Markdown 파일까지 생성합니다.

![Dart it GitHub 대표 이미지](docs/assets/dart_it_github_hero.png)

[![Version](https://img.shields.io/badge/version-0.1.0-2563EB)](https://github.com/curisus/Dart-it)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-F5C518)](LICENSE)

**DART**는 금융감독원의 전자공시시스템이고, **OpenDART API**는 프로그램이 DART 데이터를 요청할 수 있게 제공되는 공식 접속 방식입니다. **MCP(Model Context Protocol)**는 AI 앱이 외부 데이터와 기능을 정해진 형식으로 호출하게 연결하는 규격입니다. Dart it은 이 둘을 연결합니다.

> 원격 서버 주소: `https://dart-it-mcp.vercel.app/api/mcp`

## 목차

- [설치 없이 빠르게 시작하기](#설치-없이-빠르게-시작하기)
- [왜 Dart it을 사용하나요?](#왜-dart-it을-사용하나요)
- [무엇을 할 수 있나요?](#무엇을-할-수-있나요)
- [원격과 로컬의 차이](#원격과-로컬의-차이)
- [온보딩과 연결 방법](#온보딩과-연결-방법)
- [도구 목록](#도구-목록)
- [Result 응답 형식](#result-응답-형식)
- [개인정보와 보안](#개인정보와-보안)
- [지원 범위와 제한](#지원-범위와-제한)
- [개발 검증](#개발-검증)
- [라이선스](#라이선스)

## 설치 없이 빠르게 시작하기

원격 서버를 사용하면 Dart it 자체를 컴퓨터에 설치하지 않아도 됩니다. 필요한 것은 [OpenDART](https://opendart.fss.or.kr/)에서 발급한 API 키와 원격 MCP 연결을 지원하는 앱입니다.

**MCP 클라이언트**는 MCP 서버에 연결해 도구를 호출하는 앱입니다. 이 README에서 안내하는 연결 방식은 다음과 같습니다.

| MCP 클라이언트 | 원격 연결 | 로컬 연결 | 권장 용도 |
| --- | :---: | :---: | --- |
| Claude for Excel | 지원 | 별도 안내 없음 | 조회 결과를 현재 Excel 통합문서의 시트에 정리하고 분석 |
| claude.ai / Claude Desktop 앱 | 지원 | 별도 안내 없음 | 설치 없이 대화로 공시 조회 |
| Claude Code | 지원 | 지원 | 터미널에서 조회하거나 로컬 파일 생성 |
| Codex | 지원 | 지원 | 터미널에서 조회하거나 로컬 파일 생성 |

### Claude for Excel 빠른 시작

1. [OpenDART](https://opendart.fss.or.kr/)에 가입하고 **인증키 신청/관리** 메뉴에서 API 키를 발급합니다.
2. [claude.ai](https://claude.ai/)의 **Customize → Connectors → Add custom connector**에서 Dart it을 등록합니다.
3. 계정에 요청 헤더 입력란이 보이면 아래와 같이 등록합니다.
   - URL: `https://dart-it-mcp.vercel.app/api/mcp`
   - 헤더 이름: `X-OpenDART-API-Key`
   - 헤더 값: 발급받은 API 키
4. 요청 헤더 입력란이 없다면 다음 주소를 등록할 수 있습니다.

```text
https://dart-it-mcp.vercel.app/api/mcp?key=발급받은_키
```

URL에 키를 넣으면 클라이언트 설정이나 접속 기록에 키가 남을 수 있습니다. 헤더 입력이 가능한 환경에서는 헤더 방식을 우선 사용하세요.

5. Claude for Excel 사이드바에서 **+ → Connectors**를 열고 등록한 커넥터를 켭니다.
6. 다음과 같이 요청합니다.

```text
삼성전자 2025년 사업보고서의 별도 감사보고서를 찾아
재무상태표, 손익계산서, 현금흐름표를 현재 통합문서의 새 시트에 정리하고
기간과 주요 합계를 다시 확인해 줘.
```

원격 Dart it은 데이터를 반환하고, Claude for Excel이 그 데이터를 현재 통합문서에 입력합니다. 원격 서버가 Excel 파일을 직접 생성하는 것은 아닙니다.

## 왜 Dart it을 사용하나요?

DART에서 원하는 숫자를 분석하기 전에는 회사 검색, 공시 선택, 정정공시 확인, 별도·연결 첨부 선택, 표 복사와 열 정리 같은 준비 작업이 필요합니다. Dart it은 이 과정을 AI가 순서대로 호출할 수 있는 명시적인 단계로 제공합니다.

```text
회사 검색 → 공시 선택 → 별도·연결 첨부 선택 → 목차 확인
→ 필요한 구역만 구조화해 반환 → Excel 또는 AI에서 정리·검증·분석
```

각 단계는 회사의 8자리 DART 고유번호(`corp_code`), 14자리 접수번호(`rcept_no`), 첨부 식별자(`attachment_id`), 구역 식별자(`section_id`)를 사용합니다. 따라서 같은 대화 안에서 어떤 회사와 공시, 첨부문서를 선택했는지 확인할 수 있습니다.

실제 사용 흐름에서는 Claude for Excel이 삼성전자(`corp_code=00126380`)의 FY2025 사업보고서에서 **별도 감사보고서**를 선택하고, 목차를 확인한 뒤 `재무제표본문`, `손익계산서`, `재무상태표`, `현금흐름표` 네 개 워크시트에 원문 데이터를 정리할 수 있습니다. 이후 자산총계, 부채총계, 현금및현금성자산, 당기순이익과 전기·당기 기간을 다시 읽어 입력 결과를 확인할 수 있습니다.

수집한 공시를 바탕으로 채무증권의 이자비용을 추산하는 등 후속 분석도 요청할 수 있습니다. 다만 이러한 계산은 사용자의 지시와 AI 또는 Excel 수식으로 수행되는 후속 작업이며, Dart it에 내장된 자동계산 기능은 아닙니다.

## 무엇을 할 수 있나요?

- 회사명이나 종목코드로 회사를 찾고, 최대 5개의 후보를 유사도 순서로 확인할 수 있습니다.
- 최근 5개 사업연도의 감사보고서, 분기 검토보고서, 반기 검토보고서를 찾을 수 있습니다.
- 정정 이력을 한 묶음으로 정리한 대표 공시와 별도·연결 첨부문서를 선택할 수 있습니다.
- 감사의견, 재무상태표, 손익·포괄손익계산서, 자본변동표, 현금흐름표, 주석 등 필요한 구역만 받을 수 있습니다.
- 2015 사업연도 이후의 공식 재무제표 계정, 주요 계정, 재무지표를 조회할 수 있습니다.
- 배당, 주주, 임직원, 보수, 감사인, 자금 사용 등 정기보고서 주요정보 28종을 조회할 수 있습니다.
- 기업개황, 5% 대량보유·임원/주요주주 소유보고, 주요사항보고 36종, 증권신고서 주요정보 6종을 조회할 수 있습니다.
- 로컬 모드에서는 검색·계산 가능한 `.xlsx` 파일이나 원문 순서의 `.md` 파일을 생성할 수 있습니다.

예를 들어 다음과 같이 요청할 수 있습니다.

```text
삼성전자와 SK하이닉스의 2025년 사업보고서 주요 계정을 비교해 줘.
```

```text
이 회사의 2026년 유상증자 결정과 전환사채권 발행결정을 찾아 요약해 줘.
```

```text
선택한 별도 감사보고서의 재무제표와 주석을 로컬 Excel 파일로 만들어 줘.
```

## 원격과 로컬의 차이

| 구분 | 원격 서버 | 로컬 서버 |
| --- | --- | --- |
| 시작 방법 | 서버 주소를 MCP 클라이언트에 등록 | `uvx`로 사용자 컴퓨터에서 실행하고 MCP 클라이언트에 등록 |
| 연결 방식 | Streamable HTTP: 인터넷을 통한 요청·응답 연결 | stdio: 로컬 프로그램끼리 표준 입력과 표준 출력으로 통신하는 연결 |
| OpenDART API 키 | 각 도구 요청의 헤더 또는 URL에서 읽음 | 환경변수 또는 프로젝트 `.env`에서 읽음 |
| 제공 도구 | 조회 도구 13개 | 조회 도구 13개 + 파일 생성 도구 2개, 총 15개 |
| 결과 | 구조화된 데이터 | 구조화된 데이터 + 로컬 Excel·Markdown 파일 |
| 출력 폴더 | 사용하지 않음 | `DART_MCP_OUTPUT_DIR` 또는 프로젝트 폴더의 `output` |
| 처리 단위 | 각 HTTP 요청을 독립적으로 처리 | 로컬 MCP 프로세스가 요청을 처리 |
| 적합한 경우 | 설치 없이 Claude for Excel·웹·터미널에서 조회 | 파일 생성이 필요하거나 원격 Dart it을 거치지 않고 OpenDART를 호출하려는 경우 |

원격과 로컬의 13개 조회 도구는 이름, 입력값, 설명이 같습니다. 차이는 로컬에서만 `export_report_excel`과 `export_report_markdown`을 제공한다는 점입니다.

## 온보딩과 연결 방법

### 1. OpenDART API 키 발급

1. [OpenDART](https://opendart.fss.or.kr/)에 접속해 가입하고 로그인합니다.
2. **인증키 신청/관리** 메뉴에서 API 키를 신청합니다.
3. 발급된 값을 외부에 공개하지 말고 아래 연결 방식 중 하나에 설정합니다.

API 키는 OpenDART가 요청자를 확인하고 이용량을 관리하는 인증정보입니다. GitHub 이슈, 공개 저장소, 화면 캡처에 키를 포함하지 마세요.

### 2. claude.ai와 Claude for Excel에 원격 연결

[빠른 시작 절차](#claude-for-excel-빠른-시작)에 따라 claude.ai에 custom connector를 등록합니다. Claude for Excel은 같은 Claude 계정에 등록된 커넥터를 사이드바에서 켜서 사용합니다. 계정과 앱 버전에 따라 메뉴 이름이나 요청 헤더 입력란의 제공 여부가 다를 수 있습니다.

### 3. Claude Code에 원격 연결

터미널에서 다음 명령을 실행합니다.

```powershell
claude mcp add --transport http --scope user dart_remote https://dart-it-mcp.vercel.app/api/mcp --header "X-OpenDART-API-Key: 발급받은_키"
```

이 명령은 API 키가 명령 기록과 Claude Code 사용자 설정에 남을 수 있습니다. 본인이 관리하는 컴퓨터에서만 실행하고, 노출된 키는 OpenDART에서 재발급하세요.

### 4. Codex에 원격 연결

PowerShell에서 API 키를 환경변수로 설정한 뒤 원격 서버를 등록합니다.

```powershell
$env:OPEN_DART_API_KEY = "발급받은_키"
codex mcp add dart_remote --url https://dart-it-mcp.vercel.app/api/mcp --bearer-token-env-var OPEN_DART_API_KEY
```

이 설정은 키 자체가 아니라 키를 읽을 환경변수 이름을 Codex 설정에 기록합니다. 이후 Codex를 실행할 때도 `OPEN_DART_API_KEY` 환경변수에 키가 있어야 합니다. Codex는 이 값을 `Authorization: Bearer` 헤더로 전달합니다.

### 5. 로컬 서버 준비

로컬 서버는 Python 패키지를 격리된 실행 환경에서 내려받아 실행하는 `uvx`를 사용합니다. 먼저 [uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 `uv`를 설치합니다. PowerShell의 공식 설치 명령은 다음과 같습니다.

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

예를 들어 `C:\dart_mcp_workspace` 폴더를 만들고 그 안에 `.env` 파일을 작성합니다.

```dotenv
OPEN_DART_API_KEY=발급받은_키
DART_MCP_OUTPUT_DIR=output
```

`.env`는 이름과 값으로 실행 설정을 저장하는 텍스트 파일입니다. 이 파일을 Git에 커밋하거나 다른 사람에게 전달하지 마세요.

직접 실행해 서버가 시작되는지 확인하려면 다음 명령을 사용합니다. MCP 서버는 터미널에서 일반 대화를 받는 프로그램이 아니므로, 실행 후에는 MCP 클라이언트가 연결해 도구를 호출합니다.

```powershell
$env:DART_MCP_PROJECT_DIR = "C:\dart_mcp_workspace"
uvx --from git+https://github.com/curisus/Dart-it.git dart-crawler-mcp
```

### 6. Claude Code에 로컬 서버 등록

```powershell
claude mcp add --transport stdio --scope user dart_local -e DART_MCP_PROJECT_DIR=C:\dart_mcp_workspace -- uvx --from git+https://github.com/curisus/Dart-it.git dart-crawler-mcp
```

### 7. Codex에 로컬 서버 등록

```powershell
codex mcp add dart_local --env DART_MCP_PROJECT_DIR=C:\dart_mcp_workspace -- uvx --from git+https://github.com/curisus/Dart-it.git dart-crawler-mcp
```

로컬 설정은 다음 순서로 결정됩니다.

| 설정 | 적용 순서 |
| --- | --- |
| 프로젝트 기준 폴더 | `DART_MCP_PROJECT_DIR` → 서버 명령을 실행한 현재 폴더 |
| OpenDART API 키 | 운영체제·클라이언트 환경변수 `OPEN_DART_API_KEY` → 프로젝트 기준 폴더의 `.env` |
| 출력 폴더 | 환경변수 `DART_MCP_OUTPUT_DIR` → 프로젝트 `.env` → `<프로젝트 기준 폴더>/output` |

상위 폴더의 `.env`는 검색하지 않습니다. 상대경로로 지정한 출력 폴더는 프로젝트 기준 폴더 아래에 만들어집니다.

## 도구 목록

### 원격·로컬 공통 조회 도구 13개

| 구분 | 도구 | 주요 입력 | 하는 일과 기준 |
| --- | --- | --- | --- |
| 회사·공시 | `search_companies` | `company_query`, `report_kind` | 회사명 또는 6자리 종목코드로 최대 5개 회사를 찾습니다. `report_kind`는 `audit`, `quarterly_review`, `half_year_review` 중 하나입니다. |
| 회사·공시 | `list_report_filings` | `corp_code`, `report_kind` | 최근 5개 사업연도의 대표 공시를 반환합니다. 정정 계열은 묶고 철회된 공시는 제외합니다. |
| 회사·공시 | `list_report_attachments` | `rcept_no` | 선택 가능한 별도·연결 첨부를 반환합니다. 식별자는 `opendart:접수번호:파일명` 또는 `viewer:접수번호:dcmNo` 형식입니다. |
| 첨부 원문 | `list_report_sections` | `rcept_no`, `attachment_id` | 첨부문서의 목차를 내용 없이 반환합니다. 각 항목에는 `section_id`, 제목, 종류, 블록·표·셀·텍스트 수, 이미지 포함 여부가 들어갑니다. |
| 첨부 원문 | `get_report_sections` | `rcept_no`, `attachment_id`, `section_ids`, `section_kinds` | 선택한 구역의 문단과 표를 원문 순서로 반환합니다. 식별자 또는 종류 중 하나 이상이 필요하고, 둘 다 주면 합집합을 반환합니다. `statements`는 핵심 재무제표 4종을 뜻합니다. |
| 공식 재무정보 | `get_financial_statements` | `corp_code`, `bsns_year`, `reprt_code`, `fs_div` | 한 회사·한 기간의 공식 계정과목 전체를 반환합니다. `fs_div`는 기본 `CFS`(연결) 또는 `OFS`(별도)입니다. 금액은 OpenDART 원문 문자열로 유지합니다. |
| 공식 재무정보 | `get_major_accounts` | `corp_codes`, `bsns_year`, `reprt_code` | 최대 10개 회사의 주요 재무상태표·손익계산서 계정을 한 번에 반환합니다. |
| 공식 재무정보 | `get_financial_indicators` | `corp_codes`, `bsns_year`, `reprt_code`, `idx_cl_code` | 최대 10개 회사의 수익성·안정성·성장성·활동성 지표 중 한 분류를 반환합니다. |
| 정기보고서 | `get_report_topics` | `corp_code`, `bsns_year`, `reprt_code`, `topics` | 감사인, 배당, 주주, 임직원, 보수, 채무증권, 자금 사용 등 주요정보 28종 중 최대 10개를 반환합니다. |
| 기업정보 | `get_company_profile` | `corp_code` | 회사명, 대표자, 시장구분, 등록번호, 주소, 홈페이지·IR 주소, 연락처, 업종, 설립일, 결산월을 반환합니다. |
| 지분공시 | `get_ownership_reports` | `corp_code`, `report_type`, `bgn_de`, `end_de` | 5% 대량보유 또는 임원·주요주주 소유보고를 반환합니다. 시작일과 종료일은 선택이며 한쪽만 지정할 수도 있습니다. |
| 주요사항보고 | `get_material_events` | `corp_code`, `event_types`, `bgn_de`, `end_de` | 주요사항보고 36종 중 최대 10개를 조회합니다. 접수 시작일·종료일은 모두 필수입니다. |
| 증권신고서 | `get_registration_statements` | `corp_code`, `stmt_type`, `bgn_de`, `end_de` | 증권신고서 주요정보 6종 중 한 종류를 공식 그룹 제목별로 반환합니다. 접수 시작일·종료일은 모두 필수입니다. |

`corp_code`는 `search_companies`에서 확인하는 8자리 DART 고유번호이며 6자리 종목코드와 다릅니다. `bgn_de`와 `end_de`는 `YYYYMMDD` 형식입니다. `section_kinds`는 `opinion`, `balance_sheet`, `income`, `equity`, `cash_flow`, `note`, `other`와 핵심 재무제표 4종을 한 번에 고르는 `statements`를 지원합니다.

### 로컬 전용 파일 생성 도구 2개

| 도구 | 주요 입력 | 결과와 검증 |
| --- | --- | --- |
| `export_report_excel` | `rcept_no`, `attachment_id` | 선택한 첨부를 검색·계산 가능한 `.xlsx`로 생성합니다. `수집정보` 시트와 원문 순서의 구역별 시트를 만들고, 저장 후 원문 셀·병합 범위와 다시 대조합니다. 재무상태표, 손익·포괄손익, 자본변동표, 현금흐름표 중 누락이 있으면 파일을 만들지 않습니다. |
| `export_report_markdown` | `rcept_no`, `attachment_id` | 선택한 첨부의 의견·재무제표·주석·기타 구역을 원문 순서의 `.md` 파일 하나로 생성합니다. 핵심 재무제표가 빠져도 있는 내용을 생성하고 `missing_sections`와 `collection_status`로 알립니다. |

두 도구는 접수번호, 첨부 식별자, 원문 SHA-256 값이 같은 기존 파일을 재사용합니다. SHA-256은 같은 원문인지 확인하기 위한 고정 길이 식별값입니다. 이미지 전용 내용은 OCR하지 않고 자리표시자로 남기며, 이 경우 `partial` 상태와 경고가 반환될 수 있습니다.

## Result 응답 형식

모든 도구는 성공과 실패를 같은 **Result** 구조로 반환합니다. Result는 호출 결과, 경고, 다음 행동을 필드 이름으로 구분한 응답 형식입니다.

성공 응답은 `data`가 있고 `error`가 없습니다.

```json
{
  "ok": true,
  "data": {
    "example": "도구별 결과"
  },
  "error": null,
  "warnings": [],
  "next_action": null
}
```

실패 응답은 `error`가 있고 `data`가 없습니다.

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "INVALID_INPUT",
    "message": "report_kind가 지원 범위에 없습니다.",
    "retryable": false,
    "details": {}
  },
  "warnings": [],
  "next_action": null
}
```

| 필드 | 의미 |
| --- | --- |
| `ok` | 성공이면 `true`, 실패이면 `false` |
| `data` | 성공한 도구의 결과. 실패하면 `null` |
| `error` | 실패 원인인 `code`, `message`, 재시도 가능 여부 `retryable`, 추가 정보 `details`. 성공하면 `null` |
| `warnings` | 결과를 사용할 수는 있지만 일부 누락·대체 경로·기존 파일 재사용 등을 확인해야 할 때의 경고 목록. 각 경고는 `code`, `message`, `details`로 구성 |
| `next_action` | 입력 수정, 기간 분할, 다른 범위 재시도 등 다음 행동. 필요 없으면 `null` |

<details>
<summary>오류 코드와 경고 코드 전체 보기</summary>

오류 코드:

`CONFIG_ERROR`, `INVALID_INPUT`, `NOT_FOUND`, `UPSTREAM_AUTH`, `UPSTREAM_RATE_LIMIT`, `UPSTREAM_UNAVAILABLE`, `UPSTREAM_LAYOUT_CHANGED`, `PARSE_FAILED`, `CORE_STATEMENT_MISSING`, `OUTPUT_WRITE_FAILED`, `VALIDATION_FAILED`

경고 코드:

`PARTIAL_COLLECTION`, `IMAGE_CONTENT_SKIPPED`, `AMOUNT_MISMATCH`, `COMPARISON_UNAVAILABLE`, `FALLBACK_SOURCE_USED`, `ORIGINAL_FILING_SOURCE_USED`, `VIEWER_DISCOVERY_SKIPPED`, `EXISTING_FILE_REUSED`

</details>

## 개인정보와 보안

원격 요청에서 API 키를 읽는 우선순위는 다음과 같습니다.

1. `X-OpenDART-API-Key: 발급받은_키`
2. `Authorization: Bearer 발급받은_키`
3. URL의 `?key=발급받은_키`

`X-OpenDART-API-Key`와 `Authorization`을 함께 보내면 전자가 우선합니다. 유효한 헤더가 없을 때만 URL의 `key` 값을 확인합니다. 서버 연결 초기화와 도구 목록 확인은 키 없이 가능하지만, 도구 호출에는 키가 필요하며 없으면 Result 안의 `CONFIG_ERROR`로 응답합니다.

현재 구현은 원격 도구 요청마다 키를 읽어 OpenDART 요청에 사용하고, 해당 요청을 처리하는 서비스 객체를 새로 만듭니다. 이 저장소의 애플리케이션 코드에는 API 키를 데이터베이스나 출력 파일에 기록하는 기능이 없습니다. 다만 MCP 클라이언트, 배포 플랫폼, 네트워크 장비가 보관하는 설정이나 접속 기록까지 이 저장소가 통제하거나 보존 여부를 보장하지는 않습니다.

- 가능하면 URL보다 헤더를 사용하세요. URL은 접속 기록에 포함될 가능성이 더 큽니다.
- 로컬 `.env`는 Git에 포함하지 마세요. 이 저장소의 `.gitignore`는 `.env`와 `.env.*`를 제외하고 `.env.example`만 허용합니다.
- API 키가 노출되었다면 OpenDART에서 기존 키를 폐기하거나 재발급하세요.
- 로컬 모드는 원격 Dart it 서버를 거치지 않고 사용자 컴퓨터의 프로세스가 OpenDART를 직접 호출합니다.

## 지원 범위와 제한

### 첨부 원문 검색 대상

| `report_kind` | 대상 | 반환 기간 표시 |
| --- | --- | --- |
| `audit` | 사업보고서·감사보고서 계열 | `FY` |
| `quarterly_review` | 1분기·3분기 검토보고서 계열 | `1Q`, `3Q` |
| `half_year_review` | 반기 검토보고서 계열 | `HY` |

공시 목록은 최근 5개 사업연도로 제한됩니다. 실제로 별도·연결 첨부가 모두 있는지는 선택한 DART 공시의 원문 구성에 따라 달라집니다.

### 공식 재무정보의 기간과 코드

`get_financial_statements`, `get_major_accounts`, `get_financial_indicators`, `get_report_topics`는 2015 사업연도 이후를 지원합니다.

| `reprt_code` | 대상 보고서 |
| --- | --- |
| `11011` | 사업보고서 |
| `11012` | 반기보고서 |
| `11013` | 1분기보고서 |
| `11014` | 3분기보고서 |

재무지표 분류 코드는 `M210000`(수익성), `M220000`(안정성), `M230000`(성장성), `M240000`(활동성)입니다.

### 응답 크기 제한

- 회사 검색 결과: 최대 5개
- 여러 회사 비교: 한 번에 최대 10개 회사
- 정기보고서 topic과 주요사항 event type: 한 번에 최대 10개
- 첨부 구역 내용: 최대 20,000개 표 셀, 서술 텍스트 최대 200,000자
- OpenDART 행 기반 조회: 최대 1,000행
- 정기보고서·지분공시·주요사항보고·증권신고서 조회의 반환 텍스트: 최대 200,000자

한도를 넘은 요청은 일부만 잘라 반환하지 않고 실패로 처리합니다. `next_action`에 따라 회사, topic, event type, 기간 또는 구역을 나누어 다시 요청하세요.

### 지원 값 상세

<details>
<summary>정기보고서 주요정보 topic 28종</summary>

| 분류 | 지원 topic |
| --- | --- |
| 감사 | `audit_opinion`, `audit_service_contract`, `non_audit_service_contract` |
| 자본·주식 | `dividend`, `capital_change`, `treasury_stock`, `total_shares` |
| 주주 | `largest_shareholder`, `largest_shareholder_change`, `minority_shareholders` |
| 임직원 | `executives`, `employees`, `outside_directors` |
| 보수 | `director_individual_pay`, `director_total_pay`, `individual_pay_top5`, `unregistered_executive_pay`, `director_pay_approved`, `director_pay_by_type` |
| 투자·채무증권 | `other_corp_investment`, `debt_securities_issued`, `commercial_paper_balance`, `short_term_bond_balance`, `corporate_bond_balance`, `hybrid_securities_balance`, `contingent_capital_balance` |
| 자금 사용 | `private_fund_usage`, `public_fund_usage` |

</details>

<details>
<summary>지분공시, 주요사항보고, 증권신고서 지원 값</summary>

지분공시 `report_type`:

- `major_holding`: 5% 대량보유 상황보고
- `insider_ownership`: 임원·주요주주 소유보고

주요사항보고 `event_type` 36종:

- 경영·법적 사건: `bankruptcy`, `business_suspension`, `rehabilitation_filing`, `dissolution`, `creditor_management_start`, `creditor_management_stop`, `lawsuit`
- 자본: `paid_in_capital_increase`, `free_capital_increase`, `paid_in_and_free_increase`, `capital_reduction`
- 사채: `convertible_bond_issue`, `bond_with_warrant_issue`, `exchangeable_bond_issue`, `writedown_contingent_bond_issue`, `stock_related_bond_acquisition`, `stock_related_bond_transfer`
- 자기주식: `treasury_stock_acquisition`, `treasury_stock_disposal`, `treasury_trust_contract`, `treasury_trust_cancel`
- 구조개편·자산: `merger`, `split_merger`, `company_split`, `stock_exchange_transfer`, `business_acquisition`, `business_transfer`, `asset_transfer_putback_option`, `tangible_asset_acquisition`, `tangible_asset_transfer`, `other_corp_stock_acquisition`, `other_corp_stock_transfer`
- 해외 상장: `overseas_listing_decision`, `overseas_listing`, `overseas_delisting_decision`, `overseas_delisting`

증권신고서 `stmt_type` 6종:

`equity_securities`, `debt_securities`, `depositary_receipts`, `merger`, `stock_exchange_transfer`, `division`

</details>

### OCR과 기타 제한

- **OCR(Optical Character Recognition)**은 이미지 안의 글자를 텍스트로 읽는 처리입니다. 현재 Dart it은 OCR을 수행하지 않습니다.
- 이미지 전용 구역은 자리표시자와 `IMAGE_CONTENT_SKIPPED` 경고로 표시되며, 결과가 `partial`일 수 있습니다.
- 수동 PDF 업로드 기능은 제공하지 않습니다. DART에서 선택한 ZIP 또는 viewer 첨부를 읽습니다.
- 원격 서버는 파일을 생성하지 않습니다. Excel·Markdown 파일 생성은 로컬 전용입니다.
- 후속 계산과 해석은 MCP 클라이언트나 Excel에서 수행합니다. Dart it의 기계적 검증은 원문과 생성 파일의 일치 여부를 확인하며, 공시 내용의 적정성이나 투자 판단을 제공하지는 않습니다.

## 개발 검증

개발 환경은 Python 3.13 이상과 `uv`를 사용합니다.

```powershell
uv sync --frozen
uv run ruff check .
uv run mypy --strict src tests
uv run pytest -v
uv build
```

실제 OpenDART 네트워크와 API 키를 사용하는 검사는 별도로 실행합니다.

```powershell
uv run pytest -v -m live
```

## 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다.
