---
name: monthly
description: 운영 로그 월간 추출 JSON 경로 하나로 월간 운영 보고서(Chart.js 슬라이드 HTML)와 시사점을 생성한다. 사용자가 데이터 파일 경로를 지정하며 월간 보고서·운영 보고·Ops Logger 보고서 작성을 요청할 때 사용. 운영 분류체계가 없는 팀은 데이터에서 분류체계를 도출해 함께 제안한다.
argument-hint: "<데이터.json 경로>"
---

# 월간 운영 보고서 생성

데이터 경로: **$ARGUMENTS** (비어 있으면 경로를 물어본다)

사용자는 **경로만 입력한다.** 프로필·베이스라인은 스크립트가 알아서 찾고, 출력 파일명도 자동으로 정해진다. 옵션 입력을 요구하지 말 것.

응답·산출물은 한국어. `${CLAUDE_SKILL_DIR}/scripts/`가 숫자와 레이아웃을 전담하고 **당신과 에이전트는 해석만 담당한다.** HTML이나 표를 직접 쓰지 말 것.

## 경로 규칙

**팀 루트는 `profile.json`이 있는 폴더**다. 스크립트가 데이터 경로에서 거슬러 올라가 찾고, `--out`에 준 상대경로를 cwd가 아니라 **팀 루트 기준으로** 해석한다. 그래서 어느 위치에서 실행해도 산출물이 같은 자리에 쌓인다.

```
우리팀-운영보고/                          ← 팀 루트
├── profile.json / baselines.json         설정 (평면 유지, 누적 파일)
├── data/…                                입력 — 사용자가 정리한 대로 둔다
├── report/<대상연도>/…보고서.html         산출물 (스크립트가 만든다)
└── report-work/                          중간 산출물 (매 실행 덮어씀)
```

중간 산출물(`stats.json`·`narrative.json`·`report.json`·`taxonomy.json`)은 항상 `report-work/`에 둔다. 아래 명령의 `--out` 경로를 그대로 쓰면 된다.

**데이터 폴더 구조에는 관여하지 않는다.** 사용자가 `data/` 아래를 어떻게 정리했든(연도별·평면·더 깊은 중첩) 그대로 읽는다. 폴더를 만들거나 파일을 옮기라고 제안하지 말 것. 자동으로 정해지는 건 보고서가 저장되는 `report/<대상연도>/`뿐이다.

## 1. 집계

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aggregate.py" <데이터.json> --out report-work/stats.json
```

`profile.json`은 데이터 폴더에서 위로 올라가며 자동 탐색된다. 실행 결과에 찾은 프로필과 **팀 루트**가 표시되므로, 이후 단계에서 산출물 위치를 확인할 때 참고한다.

**프로필이 없다는 메시지가 나오면** 사용자에게 묻지 말고 바로 만든다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_profile.py" <데이터.json>
```

필드 매핑·UTC 여부·채널·자사명·분류체계 성숙도를 자동 추론해 `profile.json`과 빈 `baselines.json`을 만든다. 진단 결과를 사용자에게 요약해 보여주고, `TODO`로 남은 항목(팀명·조직명·보고서 제목·해석 관점)만 **한 번에** 물어 채운 뒤 1단계를 다시 실행한다.

이어서 `stats.json`의 `meta.flags`·`meta.taxonomy`를 확인한다.

| 상황 | 대응 |
|---|---|
| `undercount_risk` 있음 | 로깅일 기준 추출이라 월말 요청 누락 가능. 요청일 기준 재추출을 권하고, 안 되면 각주로 남기고 진행 |
| `has_started_at: false` | 처리시간 산출 불가. 다른 필드로 대체 계산 금지. 관련 지표는 자동 생략되고 각주가 붙는다 |
| `requester_name_available: false` | 요청자 집중도는 조직+부서 대체 집계 (각주 자동) |
| `taxonomy.mode`가 `coded` 아님 | 3단계로 분류체계를 도출한다 |

## 2. 운영 컨텍스트 확인 (한 번에 질문)

데이터에 없는 정보라 반드시 물어야 한다. 1~2는 필수다.

1. 해당 월 **공휴일·임시공휴일** — 달력으로 1차 산출해 제시하고 확인만 받는다
2. **담당자 부재 일정** (연차·워크샵·교육) — 처리량 해석에 필수
3. **특이 이벤트** (배포·조직개편·감사 등)
4. **전월 팔로업** — `baselines.json` 마지막 달의 `next_month_watch`를 읽어 그대로 확인한다

## 3. 분류체계 도출 (mode ≠ coded 일 때만)

`taxonomy-builder` 에이전트에 `stats.json`의 `text_corpus`를 넘겨 분류체계와 배정을 받아 `report-work/taxonomy.json`으로 저장한 뒤 재집계한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aggregate.py" <데이터.json> \
    --taxonomy report-work/taxonomy.json --holidays 2026-06-03,2026-06-06 \
    --out report-work/stats.json
```

제안 분류체계는 04 슬라이드에 자동 수록된다. 에이전트의 `review_points`는 팀이 확정 전에 판단할 경계 사례이므로 사용자에게 그대로 전달한다.

공휴일이 확정됐다면 mode와 무관하게 `--holidays`를 붙여 재집계한다.

## 4. 시사점 작성 — 이 보고서의 핵심

`insight-analyst`에 `stats.json`, `baselines.json`, 2단계 컨텍스트, 프로필 `insight_frame`을 전달해 `narrative.json`을 받는다.

이어서 `insight-critic`에 `narrative.json` + 같은 입력을 넘겨 검증한다. `verdict: revise`면 `blocking` 지적을 `insight-analyst`에 되돌려 수정본을 받는다. **최대 2회** 반복하고, 그래도 남으면 해당 주장을 삭제하거나 가설로 낮춘다.

## 5. 생성

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/compose.py" \
    report-work/stats.json report-work/narrative.json --out report-work/report.json
python3 "${CLAUDE_SKILL_DIR}/scripts/build_report.py" \
    report-work/report.json --stats report-work/stats.json
```

`compose.py`가 10슬라이드 목차(표지·Executive Summary·월별 추이·채널·유형·조직·담당자·요청자 집중도·피크 패턴·종합 시사점)와 모든 표·차트를 만든다. `build_report.py`는 표 셀 수·차트 데이터 길이·총건수·각주 누락을 검증하고 실패 시 중단한다.

출력 경로는 `--out` 없이도 자동 결정된다 — `<팀 루트>/report/<대상연도>/<제목> N월 보고서(YY.MM.DD).html`. 연도는 **데이터의 대상월** 기준이라 26년 12월분을 27년 1월에 만들어도 `report/2026/`에 들어간다. 없는 폴더는 만들어진다.

빌드가 실패하면 원인을 고쳐 다시 돌린다. HTML을 손으로 고쳐 우회하지 말 것.

## 6. 마무리

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/update_baselines.py" \
    report-work/stats.json --narrative report-work/narrative.json
```

당월 수치와 다음 달 확인 포인트가 `baselines.json`에 자동 기록된다. **이 단계를 빠뜨리면 다음 달 전월 비교가 끊기므로 반드시 실행한다.**

마지막으로 사용자에게 보고한다.

- 생성된 파일 경로, 총건수·슬라이드 수
- 데이터 한계로 생략된 지표가 있으면 그 사실
- 분류체계를 새로 제안했다면 확정 절차 (확정 후 `profile.json`의 `taxonomy_map`에 반영하면 다음 달부터 코드 기반 집계로 전환)
- 다음 달 확인 포인트

스키마는 [references/schemas.md](references/schemas.md), 목차·디자인 규격은 [references/report-spec.md](references/report-spec.md) 참조.
