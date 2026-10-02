# 논문/PPT 한글화 (로컬 LLM)

영어 논문·슬라이드 PDF를 **원본 레이아웃 유지** 한글 PDF로 변환합니다.
`reference/before.webp → after.webp` 규칙을 모방합니다.

## 규칙 (레퍼런스 분석, PLAN.md 참고)

- 번역: 서술 본문, 캡션(`표 4 ...`), 섹션 타이틀(`5. 실험 결과`), 참조 접두어(`Fig.→그림, Section→절`)
- 유지: 수식·행렬·수식번호, 표 내부 영문, 약어·고유명사·수치·단위
  (`MDPS, BLAC, FE, ROM, off-line/on-line, Boolean localization matrix (L), User-defined`),
  저자·소속·연구실 헤더·쪽번호, 전체 레이아웃

## 요구사항

- `llama.cpp` 서버 실행 중 (`http://localhost:8080`, 모델명 `local-model`)
  - Qwen3 thinking 모델 기준: 프롬프트에 `/no_think` 자동付与 (translator.py)
- Python 3.10+, `pip install -r requirements.txt` (pymupdf, reportlab, requests)
- 한글 폰트: `C:\Windows\Fonts\malgun.ttf` (없으면 NotoSansKR)

## CLI

```powershell
# 자동 판별 + 변환 (outputs/<원본>_ko.pdf)
python -m src.main --input "test/4..pdf"
python -m src.main --input "test/1.ROME-....pdf" --pages 0-1
```

## 모델 프로바이더 (로컬 + 상용 API)

기본값은 로컬(`llama.cpp :8080`). 시중 툴처럼 상용 API도 사용 가능:

| `--provider` | 대상 | 필요한 값 |
|---|---|---|
| `local` (기본) | llama.cpp 로컬 | 없음 |
| `openai-compat` | OpenAI·OpenRouter·Together·Groq·DeepSeek·xAI·vLLM | `--base-url` + `--api-key` |
| `anthropic` | Claude | `--api-key` (또는 `ANTHROPIC_API_KEY`) |
| `gemini` | Gemini | `--api-key` (또는 `GEMINI_API_KEY`) |

```powershell
# OpenAI
$env:TRANSLATE_API_KEY="sk-..."
python -m src.main --input test/1.ROME-....pdf --provider openai-compat `
  --base-url https://api.openai.com/v1 --model gpt-4o --pages 0-1

# OpenRouter (같은 규격, baseURL만 변경)
python -m src.main --input test/1.ROME-....pdf --provider openai-compat `
  --base-url https://openrouter.ai/api/v1 --model anthropic/claude-sonnet-4 --api-key $env:OR_KEY

# Claude / Gemini (baseURL 고정, 키만)
python -m src.main --input test/4..pdf --provider anthropic --model claude-sonnet-4-6
python -m src.main --input test/4..pdf --provider gemini --model gemini-2.0-flash
```

환경변수: `TRANSLATE_PROVIDER`, `TRANSLATE_BASE_URL`, `TRANSLATE_MODEL`,
`TRANSLATE_API_KEY`, `ANTHROPIC_API_KEY/MODEL`, `GEMINI_API_KEY/MODEL`.
키는 웹 입력 시 메모리에만 보관 (디스크 저장 없음). 캐시는 프로바이더·모델별로 분리 저장.
테스트: `python tests/test_providers.py` (실제 키 불필요, 로컬 스텁 검증).

# 레이아웃만 검증 (LLM 호출 없음)
python -m src.main --input "test/2.MEMIT.pdf" --pages 0 --mock

# 테스트용 글자 상한
python -m src.main --input "test/3.AlphaEdit_Null_Space_Cons.pdf" --pages 0 --limit-chars 800
```

## 웹 GUI (의존성 추가 없음, 표준라이브러리만)

```powershell
python src/app.py          # http://localhost:8000
python src/app.py 8081     # 포트 지정
```

업로드 → 자동분류(paper/slide) → 페이지 지정 → 변환 → 다운로드.
장문 논문은 페이지 나눠 변환 권장 (로컬 27B 기준 수 분/페이지).

**비교하기:** 변환 완료 작업마다 `비교하기` 링크가 생성됩니다.
원문과 결과물을 좌우로 나란히 두고 ◀ ▶ 버튼·방향키로 두 페이지를 동시에 넘기며 대조할 수 있습니다.

## 번역 언어 (10개)

원문/번역 언어를 각각 선택 (CLI `--src-lang/--tgt-lang`, 웹 드롭다운, 기본 영→한):

English, Korean, Japanese, Chinese (Simplified/Traditional),
Spanish, French, German, Vietnamese, Indonesian

언어별 폰트 자동 선택 (맑은고딕·MS Gothic·MS YaHei·SimSun·MingLiU·Arial),
출력 파일명은 언어 접미사 (`_ko/_ja/_zh-CN/_en/...`). 캐시는 언어쌍별로 분리.

## 구조

```
src/config.py      연결·임계값·폰트 설정
src/classifier.py  paper/slide 판별 (가로세로비·블록밀도·폰트)
src/extractor.py   블록 추출·번역판별·줄조각 병합·청킹
src/translator.py  OpenAI-compatible 클라이언트 + 파일 캐시(.cache/)
src/renderer.py    원문 redact + ReportLab 한글 오버레이 합성
src/main.py        CLI 배치
src/app.py         웹 GUI
```

## 알려진 한계 (V1)

- 박스 안 줄조각은 병합되나, 도표 박스 경계 초과 시 한글이 박스 밖으로 삐칠 수 있음
  (shrink-to-fit + CJK 줄바꿈으로 완화, 폰트 하한 6pt)
- 전체 논문(20~30p) 실번역은 수십 분 소요 → 페이지 분할 + `.cache` 재사용
- `Eq.`/`식` 혼용은 레퍼런스대로 허용 (프롬프트 강제 없음)
