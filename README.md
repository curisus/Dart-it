# Dart-Crawler MCP

DART의 감사보고서와 검토보고서를 찾아 원문 첨부문서에서 검색·계산 가능한 Excel 파일을 만드는 로컬 MCP 서버입니다. 서버는 사용자 컴퓨터에서 `stdio` 방식으로 실행되며 요청 사이에 회사나 보고서 선택 상태를 저장하지 않습니다.

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

모든 도구는 `ok`, 성공 시 `data`, 실패 시 `error { code, message, retryable, details }`, `warnings`, `next_action` 구조를 사용합니다. API 키나 비밀번호는 오류 내용에 넣지 않습니다.

## 출력 파일

기본 출력 폴더는 기준 폴더 아래 `output`입니다. `DART_MCP_OUTPUT_DIR`가 있으면 그 위치를 사용합니다. 첫 시트는 항상 `수집정보`이고, 이후 원문 순서에 따라 의견, 핵심 재무제표, 주석, 기타 구역을 별도 시트로 저장합니다. 핵심 재무제표가 없으면 파일을 만들지 않습니다. 일부 구역이 이미지 전용이면 파일명에 `_부분수집`을 붙입니다.

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
