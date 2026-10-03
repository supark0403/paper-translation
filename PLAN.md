# 논문 한글화 — 레퍼런스 분석 + 개발 기획

## 1. 레퍼런스 전/후 분석 (reference/before.webp → after.webp)

### 1.1 바뀐 것 (번역 대상)
- **서술형 본문 문장 → 학술 한국어 (평서체 `~이다/~된다`)**
  - 예: `various physical quantities including response vectors ...` → `응답 벡터, 가해진 힘, 상호작용 힘, 응력/변형률을 포함한 다양한 물리량은 필요에 따라 후처리를 수행함으로써 동시에 식별될 수도 있습니다.`
  - 예: `This work especially focuses on ...` → `이 연구는 특히 인터페이스 지점에서의 클램핑력 예측에 중점을 둡니다.`
- **캡션·참조 표현 현지화**
  - `Table 4 Computation sequence ...` → `표 4 역동학 및 순동학의 계산 순서.`
  - `Fig. 13` → `그림 13`, `Section 4` → `4절`/`섹션 4에서는 → `4절에서는`, `Sections 2 and 3` → `2절과 3절`
  - `Eq. (25)`는 그대로 `Eq. (25)`로 두는 경우와 `식 (6a)`, `식 (27)`로 바꾸는 경우가 혼재 → **혼용 허용**으로 확정 (사용자 선택)
- **섹션 타이틀**: `5. Experimental result` → `5. 실험 결과`
- **문단·줄바꿈 구조 유지**: 문단 나눔, 표→본문→수식→본문 순서는 동일. 텍스트가 길어져도 박스 폭 안에서 줄바꿈만 늘어남.

### 1.2 유지한 것 (보존 대상)
1. **수식 전체**: 행렬, 기호 (`M, C, K, u, f`, 윗첨자 `n+1`, 아래첨자), 수식 번호 `(26), (27a/b/c), (28)` 완전 보존. 위치·줄간격도 동일.
2. **표(Table 4) 내부**: `Step 1. Initialization`, `Load system matrices ...`, `Eq. (12)`, `User-defined` 등 **영문 그대로**. 표 선·열 구조도 동일.
3. **고유명사·약어·수치·단위**: `MDPS, BLAC, FE, ROM, off-line/on-line, Boolean localization matrix (L), User-defined, PCB Piezotronics (356A15, PCB Piezotronics)`, 모델명·수치·단위 원문 유지.
4. **레이아웃**: 여백, 폰트 크기 계열, 페이지 분할, 그림/표 자리 유지. 한글 폰트만 바뀌고 박스 위치는 그대로.
5. **인용·상호참조 번호**: `Eq. (11)/(25)`, `Table 4`, `Fig. 13` 번호 자체는 유지 (접두어만 현지화).

### 1.3 엣지 케이스 (레퍼런스에서 발견)
- `5.1. Process implementation and experimental setup` 소제목은 **미번역 상태**로 남아 있음 → 표 내부와 같은 이유로 소제목 스타일(짧은 헤더)은 번역기에서 스킵될 수 있음. V1에서는 **짧은 헤더도 번역 시도하되 실패 시 원문 유지** 폴백으로 처리.
- `Eq.` vs `식` 혼용 → V1은 **원문 태그 유지 우선** (`Eq. (6a)` → `Eq. (6a)` 또는 `식 (6a)` 둘 다 허용, 역번역 금지). 프롬프트에 강제하지 않고 예시로만 유도.
- `off-line`, `on-line`은 번역하지 않음 → 약어/하이픈 전문어는 유지 목록에 포함.

## 2. 테스트 파일 분석 (test/*.pdf)

| 파일 | 페이지 | 크기 | 유형 | 특징 |
|---|---|---|---|---|
| 1.ROME...pdf | 14 | 612x792 Letter 세로 | 논문 | 텍스트 블록 18~73/페이지, 도형 5~2363, TOC 37개, 2단 + 그림 |
| 2.MEMIT.pdf | 21 | 612x792 Letter 세로 | 논문 | 블록 11~62/페이지, ICLR 양식 |
| 3.AlphaEdit...pdf | 31 | 612x792 Letter 세로 | 논문 | 블록 13~217/페이지, 수식+그림 많음 |
| 4..pdf | 6 | 720x540 가로(4:3) | PPT 슬라이드 | 블록 5~11/페이지, 이미지 위주, 큰 폰트, TOC 없음, 헤더 `High Performance & Intelligence Computing LAB` 반복 |

분류 규칙 (classifier):
- 가로(`w>h`) + 페이지≤15 + 페이지당 평균 블록≤15 + 평균 폰트≥18pt + 이미지 많음 → `slide`
- 그 외 세로 + 고밀도 텍스트 + TOC 존재 → `paper`

## 3. 로컬 모델 연결 검증 (완료)
- `baseURL=http://localhost:8080`, `model=local-model` (`Qwen3 27B Q6_K`, `n_ctx=90112`)
- `/health ok`, `/v1/models`에 `local-model` 확인
- **주의**: Qwen3 thinking 모델이라 일반 호출 시 reasoning이 `max_tokens`를 소진해 `content=""`, `finish_reason=length`가 됨.
  - `enable_thinking:false`, `reasoning_effort:none` 등은 무효/오번역.
  - **`/no_think` 접두사가 유일하게 안정적**임을 확인 (짧은 문장 즉시 번역, 긴 문단도 `stop`으로 완료).
  - 단, `/no_think`라도 2문단 이상은 ~38초 소요 → **문단 단위 배치 + 진행률 표시 + 캐시** 필수.

## 4. 개발 기획 (V1)

### 4.1 목표
- 입력: 영어 논문 PDF 또는 PPT형 PDF → 출력: **원본 레이아웃 유지 한글 PDF** (사용자 선택 확정)
- 표·그림·수식 내부는 유지, 본문·캡션·섹션 타이틀만 번역 (사용자 선택 확정)
- `Eq./식` 혼용 허용, `Fig.→그림, Table→표, Section→절` (사용자 선택 확정)
- 실행 형태: **CLI 배치 + 간단 웹 GUI** (사용자 선택 확정, Flask 없이 표준라이브러리만으로 동작하는 단일 `app.py`)

### 4.2 아키텍처
```
PDF → classifier(paper/slide) → extractor(블록+판별) → translator(로컬LLM) → renderer(한글 오버레이) → *_ko.pdf
                                     ↕ cache (.cache/sha256.json)      ↕ fonts (malgun/NotoSansKR)
Web GUI (app.py) ─────────────────── 같은 파이프라인 호출 (업로드→진행률→다운로드)
```

### 4.3 모듈
- `src/config.py`: baseURL/model/limit, 폰트 경로, 분류 임계값
- `src/translator.py`: `urllib` 기반 OpenAI-compatible 클라이언트. `/no_think`+system 지시문(학술체, 태그·약어 유지, ONLY Korean), `temperature=0.1`, 재시도 3회, 빈 응답 시 청크 분할 재시도, 파일 캐시
- `src/extractor.py`: PyMuPDF `dict` 추출 → header/footer 제거 → 수식/표 스킵 휴리스틱(짧은 단편, 기호율, `(27a)` 같은 번호 패턴, 도형 밀집 영역) → 2단 읽기 순서 정렬
- `src/classifier.py`: 크기·방향·블록밀도·폰트·TOC로 paper/slide 판별
- `src/renderer.py`: 블록 bbox에 흰색 박스 + 한글 `insert_textbox` (맑은고딕/NotoSansKR 임베드). 넘치면 폰트 축소(최대 3단계). 원본은 건드리지 않고 복사본에 기록.
- `src/main.py`: CLI (`--input`, `--output`, `--type auto/paper/slide`, `--pages`, `--limit-chars` 테스트용, `--mock` LLM 없이 레이아웃 테스트)
- `src/app.py`: 표준라이브러리 `http.server` 기반 업로드/변환/다운로드 단일 파일 웹. 의존성 추가 없음.

### 4.4 번역 프롬프트 원칙
- `system`: 학술 영→한 번역가. 본문만 한국어로. `Eq./Fig./Table/Section` 번호·수식·약어(MDPS, BLAC, FE, ROM, off-line/on-line)·고유명사·수치·단위 유지. `Table→표, Figure/Fig.→그림, Section→~절` 예시. 출력은 한글만.
- `user` 앞에 `/no_think` 필수. `Translate to Korean. Output ONLY Korean.\n<chunk>` 형태.
- 청크: 문단 단위 ~800–1200자, 문장 중간 절단 금지, 앞뒤 1문장 오버랩(연결성용, 번역 시 중복 제거는 후처리).

### 4.5 QA
- 미번역 검출: 출력에 영어 장문(>20단어 영어)이 남으면 경고
- 수식 보존: `(26)` 등 번호가 출력 PDF에 그대로 있는지(추출 텍스트 기준) 확인
- 오버플로우: `insert_textbox` 반환값(남은 문자)으로 감지 → 폰트 축소 로그
- 테스트: `4..pdf` 전체 + `1.ROME` 앞 2페이지만 먼저 LLM 실번역, 나머지는 `--mock`으로 레이아웃 검증 (시간 절약)

### 4.6 리스크
- Qwen3 속도: 전체 논문(30p) 실번역 시 수십 분~수 시간 → V1은 **부분 번역(페이지 지정) + 캐시 + 진행률**로 대응. 전체 일괄은 백그라운드 실행.
- 표 검출 불완전: V1은 보수적으로(짧은 블록은 스킵) 처리 → 재현율보다 정밀도 우선.
- 한글 줄바꿈: PyMuPDF textbox에 맡김. CJK는 `insert_textbox`에서 자동 처리됨.

## 5. 산출물 (예정)
- `PLAN.md` (본 파일), `requirements.txt` (pymupdf+reportlab+requests), `src/*.py`, `outputs/*_ko.pdf`, `README.md`

## 6. 구현 결과 (V1 완료, 2026-10-03 실측)

- `src/` 7개 모듈 + `src/app.py` 웹 GUI(표준라이브러리만, `http.server`). Python 3.13의 `cgi` 제거 대응(자체 multipart 파서).
- 파이프라인 검증:
  - 분류: ROME/MEMIT/AlphaEdit→`paper`, `4..pdf`→`slide` 정확히 판별.
  - 논문 실번역: ROME p0 제목·`Abstract→초록`·초록 본문 한글화 확인, 저자·소속·수식·인용 유지. `outputs/preview_p0.png`.
  - 슬라이드 실번역: p1~p2 9블록. `Problem & Solution→문제 및 해결`, `ΔW(s)`·`W(base)`·고유명사 보존, 중간 끊김 조각(`questio`/`ns`, `Dialogue`/`turn`)은 union-find 병합 후 번역. `outputs/preview_slide*.png`.
- 로컬 모델 실측 이슈 3건 해결:
  1. Qwen3 thinking이 `max_tokens` 소진 → 프롬프트 선두 `/no_think`가 유일 해법.
  2. PyMuPDF `insert_textbox` 한글 `?` tofu → 원문 redact + ReportLab(맑은고딕 TTFont, `wordWrap=CJK`) 오버레이 합성.
  3. `insert_textbox` 반환값 부호 오해(양수=여유) → ReportLab `wrap()` 기반 shrink-to-fit로 교체.
- 웹 E2E: 업로드→변환→다운로드 200 확인 (포트 8023/8024).
- 전체 논문 실번역은 장시간(페이지당 수 분) → 페이지 분할 + `.cache/` 재사용. `outputs/`의 `_ko.pdf` 2건은 부분 번역 데모.

## 7. 상용 API 프로바이더 (V2, 2026-10-03)

- `src/providers.py`: `local | openai-compat | anthropic | gemini` 4종. SDK 없이 urllib만 사용.
  - `openai-compat` 하나로 OpenAI·OpenRouter·Together·Groq·DeepSeek·xAI·vLLM 커버 (`/chat/completions`).
  - Anthropic `x-api-key`+`anthropic-version: 2023-06-01` (공식 문서 확인), Gemini `x-goog-api-key` (공식 문서 확인).
- `src/translator.py`는 오케스트레이션(캐시·분할재시도)으로 축소, thinking `/no_think`는 local 전용으로 이동.
- CLI `--provider/--model/--base-url/--api-key`, 웹 폼 동일 필드(키는 메모리만).
- `tests/test_providers.py` 스텁 테스트 5종 통과. 실 키 검증은 사용자 키 입력 후 `--pages 0 --limit-chars 200`으로 권장.

## 8. 비교 뷰어 + 다국어 (V3, 2026-10-03)

- 비교하기: `/compare/<job>` — 원문·결과물 좌우 병렬, ◀ ▶ 버튼·방향키·페이지 점프로 동시 넘기기. 썸네일은 서버 렌더(PNG, 80개 캐시).
- 10개 언어: `config.SUPPORTED_LANGS`, 언어별 프롬프트·폰트·출력 접미사·캐시 분리. `.ttc`는 `subfontIndex` 지정 (MS YaHei는 index 1이 정식 regular임을 실측 확인).
- 실측: 일본어 `Abstract→抄録`, 문장 번역 정상. 랜덤 4건(Attention/BERT/ResNet/GAN) p0 실번역 성공 — `Figure 1.→그림 1.`, arXiv 날짜 현지화 확인.
- https://github.com/supark0403/paper-translation 등록 (master).

## 9. 문서 적응형 서체 (V4, 2026-10-03)

- 지적 반영: 단일 레퍼런스 하드코딩(바탕 고정) 폐지. `src/fontmatch.py`가 문서마다 본문 서체를 실측:
  - serif/sans (내장 폰트명 휴리스틱, 본문 단락 문자 가중 투표)
  - 본문 크기 중앙값, 행간 중앙값 (이상치 제외, 1.12~1.7 클램프)
  - 블록별 줄끝 x좌표로 양쪽정렬 판정 → 정렬 추종
- 언어×스타일 폰트 매트릭스 (`config.FONT_SERIF/FONT_SANS`): 한 명조=바탕/고딕=맑은고딕,
  중 간체 명조=SimSun/고딕=MS YaHei 등. 실측: ROME/MEMIT/AlphaEdit→serif 10pt, 슬라이드→sans 24pt.
- exe는 시스템 venv 오염으로 867MB → 격리 venv 빌드로 37MB (`dist-clean/PaperTranslator.exe`, `--windowed`).

## 10. 전 페이지 검수 결과와 해결방안 (V5, 2026-10-03, 72페이지)

대상: test 4종 전체 (slide 6p, ROME 14p, MEMIT 21p, AlphaEdit 31p) 원문·결과 좌우 대조 + 자동 스윕.
양호: 본문 번역 품질, 수식·그림·캡션 위치, 저자·인용·URL·쪽번호 보존, 표(짧은 셀) 보존.

### P1. 선(ruling)으로囲인 영역 내부 문장 번역 + 넘침 [심각]
- 사례: ROME p5 Table 1, MEMIT p5 Algorithm 1, ROME p9 Figure 6 텍스트박스, AlphaEdit p5 Table 1, p20 Case 박스, p25 Table 2/3.
- 원인: 셀 문장이 길면 길이 휴리스틱을 통과해 번역되고, 박스 안에 안 들어가 겹침.
- 해결: (a) `page.find_tables()` 영역(2행2열 이상) 내부 블록 스킵 (b) monospace 지배 블록 스킵 (알고리즘/코드) (c) stroked-rect 도형에 완전히 포함된 텍스트 블록 스킵 (면적 < 페이지 80%).

### P2. References 번역 [심각]
- 사례: ROME p11-13, MEMIT p10-12, AlphaEdit p11-14 인용문헌 제목·학회명 번역됨.
- 해결: `References/Bibliography` 헤더 이후 블록 전부 스킵 (헤더 자체는 `참고문헌`으로 번역).

### P3. 여백 스탬프 번역 [중]
- 사례: MEMIT p0 좌측 세로 arXiv 스탬프가 세로로 번역됨.
- 해결: 폭<30pt·높이>100pt 블록 스킵.

### P4. 부록 문자 헤더 미번역 [경]
- 사례: `E DEMONSTRATIONS`, `F ABLATIONS`, `F.1 ...`, `C.1.2 CASE 2`, `8 ACKNOWLEDGEMENTS.` (후자는 조사 필요).
- 해결: 헤더 패턴에 `^[A-Z](\.\d+)*\s+[A-Z]`, `^Appendix\b` 추가. 번호 없는 ALL-CAPS는 원문 유지로 통일 (Step/User-defined 규칙과 일관).

### P5. 짧은 매달림 조각 미번역 [중]
- 사례: ROME p1 `read from the last hidden state.` 잔류, Checklist 한영 교대.
- 해결: 60자 미만 블록을 이전 블록에 병합 (같은 페이지·열, 간격<40pt, 폰트±1.5).

### P6. 캡션 넘침 [중]
- 사례: MEMIT p2/p4, AlphaEdit p6 Figure 캡션 한글이 박스를 초과.
- 해결: 렌더러가 아래 빈 공간을 실측해 박스를 아래로 확장 (clearance 방식).

### P7. 그림 내부 텍스트 번역 [중]
- 사례: MEMIT p3/p4 Figure 3/4 라벨·수식 조각 번역 + `$` 오탐.
- 해결: 내장 이미지와 50% 이상 겹치는 블록 스킵. 짧은(<150자) 블록이 도형 밀집 영역이면 스킵.

### P8. 고정 용어 오역 [경]
- 사례: `Acknowledgements → 사사`(틀림).
- 해결: 프롬프트 용어집 `Acknowledgements→감사의 글, Abstract→초록, References→참고문헌`.

### P9. 수식 밀집 블록 난독화 [중]
- 사례: AlphaEdit p17 증명 블록 `k 0|W l in |yhl` 등.
- 해결: 수식 기호 비율 초과 블록 스킵 (임계값은 실측 후 확정).

### P10. 괄호 영문 잔류 [경]
- 사례: `(factual associations)`, `(causal intervention)` 등이 한글 문장 안에 잔류.
- 해결: 프롬프트에 "고유명사·기호 외 영문 잔류 금지" 추가. (모델 의존적, 부분 개선)

### P11. 슬라이드 제목 크기·빈 박스 [경]
- 사례: `Thank you → 감사합니다.` 작아짐, `Answer` 박스 빈칸.
- 해결: 슬라이드 상한 26→32pt. 빈칸은 캐시 조사 후 별도 판단.

### P12. 추출 글리프 손실 [제한사항, 수정 없음]
- 사례: `→`→`!`, `∈`→`2` 등 (원문 추출 단계 손실). 렌더·번역 문제가 아니라 수정 불가. 문서화에만 남김.

### U1. figure 페이지 통째 미번역 [심각, 해결]
- 사례: 사용자 실행본 ROME p1~p3 Figure 캡션+본문 전체 영어 잔류.
- 원인: 외곽 rect 규칙이 figure 배경 tint(면적 44%)를 상자로 오인, 캡션·본문 중심이 내부에 있어 전부 스킵.
- 해결: 외곽 규칙을 외곽선(stroke) 있는 상자로 한정 + 상자는 긴 텍스트(>100자)만 스킵. 배경 tint·범례·라벨은 제외.

### U2. 단 넘김 꼬리 영어 잔류 [중, 해결]
- 사례: `T ) is read from the last hidden state.` 등 다음 단으로 넘어간 문장 꼬리.
- 해결: 열 기준 읽기 순서로 이전 블록을 찾아 문맥을 주고 꼬리만 번역(`translate_fragment`).

### U3. stale 변수로 엉뚱한 스킵 [심각, 해결]
- 원인: `iter_blocks`에서 텍스트 생성 전에 이전 블록의 `text` 길이로 스킵 판정.
- 해결: 텍스트 확정 후로 순서 이동.

### U4. 본문+표 혼합 블록 통째 스킵 [심각, 해결]
- 사례: ROME p6 `In order to facilitate...` 문단 통째 영어 잔류 (표와 같은 dict 블록).
- 해결: 눈금선 판정을 줄 단위로 변경. 표 줄만 제거하고 본문 줄은 블록으로 유지.

### U5. `Step N:` 절차 문단 스킵 [중, 해결]
- 사례: ROME p5 `Step 2/3:` 절차 문단 영어 잔류.
- 해결: CITATION 스킵을 150자 미만으로 한정. 표 셀(짧음)은 유지, 본문 절차(긺)는 번역.

### U6. 양쪽정렬+CJK 글자 겹침 [심각, 해결]
- 원인: ReportLab TA_JUSTIFY + wordWrap CJK에서 overfull 줄이 겹쳐 렌더. 대조 실험 확정.
- 해결: CJK 타깃은 좌측 정렬 고정 (라틴만 원문 정렬 추종).

### U7. 병합 체인 페이지 삼킴 + 이중 번역 [심각, 해결]
- 사례: MEMIT p2 불릿존 이중 렌더, p3 3중 렌더.
- 원인: 병합 길이 무제한 체인으로 거대 블록 생성, 동일 문단의 변형 블록들이 중복 번역.
- 해결: 병합 체인 1200자 상한, 리거처 정규화 비교, 퍼지 중복 제거(20자 공통 부분문자열).

### U8. 표 본문 번역 + 렌더 폭 넘침 [심각, 해결]
- 사례: ROME p5 표 수치행이 번역 후보에 포함, 좁은 좌열 한글이 표 위로 침범.
- 원인: in_table_region 완전포함 판정(3px 빗나감 허용 안 됨), 렌더가 높이만 맞추고 폭 넘침 무시.
- 해결: 표 영역 겹침 50% 기준, 수치행(단어<8·숫자>15) 제외, 렌더 폭 조건 추가.

### U9. NMS 별개 문단 삭제 + 박스 겹침 [심각, 해결]
- 사례: ROME p4 Step 1 문단 소실 (NMS 0.4가 69px 겹친 별개 문단을 중복으로 삭제).
- 원인: PyMuPDF 박스 패딩으로 별개 문단 박스가 겹침. 텍스트 무관 NMS가 내용 삭제.
- 해결: NMS 순수 레이아웃 기준 0.65로 완화 + 완전 포함 시에만 삭제, 잔여 겹침은 deoverlap_cands 박스 절반 나눔 (텍스트 보존).

### U10. 표 영역의 본문 침범 + 페이지 경계 단편 소실 [심각, 해결]
- 사례: ROME p5 표 영역 하단 694까지 확장되어 본문 우반부 유령 영문 잔류, p8→p9 넘김 문단 머리/꼬리 소실.
- 원인: 표 하단 확장 루프가 표 아래 본문까지 흡수 (숫자 시작 검사만으로 부족), 병합 상한 900/1200이 겹침·인접 조각 병합 차단.
- 해결: 확장 중단 조건에 소문자 개수(≥15) 추가 (p5: 694→627), 겹침 병합 상한 3000·인접 2500.
- ROME 1번 전 페이지 검수 완료 (v37): OVERLAP 0, 미번역 0 (Figure/표 내부·참고문헌은 정책상 원문 유지).

### U11. 부록 재개 실패 + 표지판 헤더 소실 [심각, 해결]
- 사례: MEMIT 부록 통째 미번역, 참고문헌 번역됨.
- 원인: 부록 헤더가 후보가 아니라 위치를 못 찾음, NMS가 REFERENCES 헤더 삭제, 페이지 번호를 부록으로 오인.
- 해결: appendix_start를 PDF 원시 텍스트 기준으로, NMS/포함제거에서 분기 헤더 보호, 재개 헤더에서 순수 숫자 제외.
- MEMIT 2번 전 페이지 검수 완료 (v53): OVERLAP 0, 미번역 0, 수식번호 보존 (Figure/표/박스 내부·참고문헌은 정책상 원문 유지).

### 적용 상태 (V6)
- P1: 눈금선 교차 판정 + monospace + 테두리상자 + 이미지 겹침 스킵 (논문만). 표 내부 보존 확인.
- P2: References 이후 제외 (`참고문헌` 헤더 유지). 전 문서 확인.
- P3: 세로 스탬프(w<30·h>100) 스킵. MEMIT arXiv 스탬프 제거 확인.
- P4: 부록 문자 헤더 패턴 추가. 번호 없는 ALL-CAPS는 원문 유지로 통일.
- P5: 매달림 병합(60자 미만, 간격<40). 체크리스트·잔줄 처리.
- P6: 아래 빈 공간 실측 확장 (최대 3배). 캡션 넘침 해소.
- P7: 이미지 50% 겹침 + 벡터 밀집 짧은 블록 스킵.
- P8/P10: 용어집 + 영문 잔류 금지 (모델 의존적).
- P9: 한 글자 토큰 비율>0.3 스킵. 증명 난독화 해소.
- P11: 슬라이드 상한 32pt. 행 블록 박스 분할 + 경계越 병합 금지로 박스별 번역.
- 추가 수정: 저자·소속행 필터 강화, LaTeX 살균($·\text·\Delta→Δ), 캐시 읽기 시 정화, 용어 확정 교정(사사→감사의 글).
