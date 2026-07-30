---
name: monthly
description: 운영 로그 월간 추출 JSON 경로 하나로 월간 운영 보고서(Chart.js 슬라이드 HTML)와 시사점을 생성한다. 사용자가 월간 보고서·운영 보고·Ops Logger 보고서 작성을 요청할 때 사용. 경로 없이 호출하면 후보 데이터 파일을 찾아 제시하고, 팀 프로필이 없으면 그 자리에서 만든다. 집계 오버뷰를 보여주고 승인을 받은 뒤 보고서를 만든다. 운영 분류체계가 없는 팀은 데이터에서 분류체계를 도출해 함께 제안한다.
argument-hint: "<데이터.json 경로>"
---

# 월간 운영 보고서 생성

데이터 경로: **$ARGUMENTS**

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

## 0. 데이터 경로 확정 — 경로가 비어 있을 때만

`$ARGUMENTS`가 비어 있으면 **"어떤 파일인가요?"만 묻지 말 것.** 후보를 먼저 찾아 제시한다.

현재 위치와 그 아래에서 Glob으로 찾는다 — `data/**/*.json`, `*.json`. `profile.json`·`baselines.json`과 `report-work/` 아래 파일(`stats.json`·`narrative.json`·`report.json`·`taxonomy.json`)은 데이터가 아니므로 후보에서 뺀다.

| 후보 수 | 행동 |
|---|---|
| 여러 개 | 파일명·크기와 **파일명에서 읽히는 대상월**을 붙여 최근 순으로 나열하고 고르게 한다. `baselines.json`에 이미 있는 달은 "이미 보고서 있음"으로 표시 |
| 1개 | 그 파일로 진행할지 확인만 받는다 |
| 0개 | 경로를 묻는다. 이때 데이터 요구사항(요청일 기준 추출)을 한 줄로 함께 알려 준다 |

## 1. 집계

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aggregate.py" <데이터.json> --out report-work/stats.json
```

`profile.json`은 데이터 폴더에서 위로 올라가며 자동 탐색된다. 실행 결과에 찾은 프로필과 **팀 루트**가 표시된다.

### 프로필이 없으면 그 자리에서 만든다

`stats.json`의 `meta.flags.profile_found`가 `false`면 프로필이 없다. **집계가 성공했더라도 확인할 것** — 데이터 필드명이 기본값과 우연히 맞으면 집계는 통과하지만 팀명·분류체계·해석 관점이 전부 비어 보고서가 반쪽이 된다. 실패 여부로 판단하지 말고 이 플래그로 판단한다.

`false`면 사용자에게 셋업할지 묻지 말고 바로 만든다. 별도로 `setup` 스킬을 실행하라고 안내하지도 말 것 — 여기서 끝낸다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_profile.py" <데이터.json>
```

필드 매핑·UTC 여부·채널·자사명·분류체계 성숙도를 자동 추론해 `profile.json`과 빈 `baselines.json`을 만든다. 진단 결과를 요약해 보여주고, `TODO`로 남은 항목(팀명·조직명·보고서 제목·해석 관점)만 **한 번에** 물어 채운 뒤 1단계를 다시 실행한다. 이 항목들은 데이터에서 추론할 수 없어 물어볼 수밖에 없다.

### 데이터 한계 확인

`stats.json`의 `meta.flags`·`meta.taxonomy`를 읽는다.

| 상황 | 대응 |
|---|---|
| `undercount_risk` 있음 | 로깅일 기준 추출이라 월말 요청 누락 가능. 요청일 기준 재추출을 권하고, 안 되면 각주로 남기고 진행 |
| `has_started_at: false` | 처리시간 산출 불가. 다른 필드로 대체 계산 금지. 관련 지표는 자동 생략되고 각주가 붙는다 |
| `requester_name_available: false` | 요청자 집중도는 조직+부서 대체 집계 (각주 자동) |
| `taxonomy.mode`가 `coded` 아님 | 3단계로 분류체계를 도출한다 |

## 2. 오버뷰 승인 — 승인 없이 3단계로 가지 말 것

집계 결과를 먼저 보여주고 **사용자 승인을 받은 뒤** 보고서를 만든다. 이 지점을 넘기면 에이전트 호출이 시작되므로, 잘못된 파일·잘못된 달은 여기서 잡아야 한다.

`stats.json`에서 읽어 이 표를 보여준다. 숫자를 직접 세지 말고 집계값을 그대로 쓴다.

| 항목 | 출처 |
|---|---|
| 대상월 | `meta.month`. `meta.month_distribution`에 다른 달이 섞여 있으면 그 분포도 함께 보여준다 |
| 총 건수 | `total` (운영일 `working_days`일, 일평균 `daily_avg`건) |
| 전월 비교 | 베이스라인 개월 수. 0이면 "첫 보고서 — 비교 없이 생성" |
| 채널 구성 | `channels` 상위 |
| 유형 구성 | `types` 상위 3개 + `taxonomy.mode` (`coded` 아니면 "분류체계를 도출해 제안 예정") |
| 처리시간 | `duration_overall` 있으면 평균·중위, 없으면 "산출 불가" |
| 05장 분석 축 | `meta.org_dimension` — `company`면 조직별, `dept`면 **요청자 부서별**(한 회사만 담당하는 팀). `meta.org_dimension_reason`을 근거로 함께 보여주고, 의도와 다르면 프로필 `org_dimension`을 고정하면 된다고 알려 준다 |
| 데이터 한계 | 위 표에서 걸린 항목 |
| 저장 위치 | `report/<대상연도>/` |

### 확인 질문 — 같은 메시지에서 한 번에

데이터에 없어 물어볼 수밖에 없는 정보다. **추상적으로 "부재 일정 있으셨나요?"라고만 묻지 말 것.** 답변 예시를 함께 보여주고, 공휴일은 달력으로 1차 산출해 제시해 확인만 받는다. 그래야 한 번에 답이 온다.

아래 형태로 오버뷰 표 다음에 붙인다.

> **확인이 필요한 것** — 데이터에 없는 정보라 물어볼 수밖에 없습니다.
>
> **1. 공휴일** — 확인만 해 주세요
> 7월 공휴일 없음 → 실운영일 **23일**로 계산했습니다. 임시공휴일·회사 휴무가 있었으면 알려 주세요.
>
> **2. 담당자 부재 일정** — 처리량 증감을 성과로 오독하지 않으려면 필요합니다
> 예: `담당자 A 7/7~7/11 연차, 담당자 B 7/24 교육`
>
> **3. 특이 이벤트**
> 예: `7/15 그룹웨어 v3 배포`, `7월 말 조직개편`, `7/20~7/22 내부감사`
>
> **4. 전월 확인 포인트**
> 지난달 남긴 항목: "AI 도구 문의 증가 지속 여부" — 이번 달 어땠나요?
>
> 없었으면 **"없음"**만 답해 주셔도 됩니다. 이대로 진행할까요?

- 공휴일이 있는 달은 날짜를 나열해 제시한다 (예: `6/3 지방선거, 6/6 현충일(토)`).
- 4번은 `baselines.json` 마지막 달에 `next_month_watch`가 있을 때만 넣는다. 없으면 항목을 빼서 질문을 짧게 유지한다.
- **"없음"도 유효한 답이다.** 매달 반복되는 질문이라 답변 부담을 늘리지 않는다.

답변이 오면 그것을 승인으로 본다. **대상월이나 파일이 틀렸다고 하면 멈추고 0단계로 돌아간다.**

## 3. 답변 반영 — 재집계

받은 답을 여기서 데이터에 반영한다. **공휴일을 받았으면 반드시 재집계한다** — 실운영일이 바뀌면 일평균과 요일 해석이 전부 달라진다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aggregate.py" <데이터.json> \
    --holidays 2026-07-17 --out report-work/stats.json
```

`taxonomy.mode`가 `coded`가 아니면 분류체계를 먼저 도출해 같은 재집계에 함께 넣는다. `taxonomy-builder`에 `stats.json`의 `text_corpus`를 넘겨 받은 결과를 `report-work/taxonomy.json`으로 저장한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aggregate.py" <데이터.json> \
    --taxonomy report-work/taxonomy.json --holidays 2026-07-17 \
    --out report-work/stats.json
```

제안 분류체계는 04 슬라이드에 자동 수록된다. `review_points`는 팀이 확정 전에 판단할 경계 사례이므로 사용자에게 그대로 전달한다.

**부재 일정과 특이 이벤트는 재집계 대상이 아니다.** 다음 단계에서 이렇게 쓰인다.

| 받은 답 | 반영되는 곳 |
|---|---|
| 공휴일 | `--holidays` 재집계 → 실운영일·일평균·요일 평균 |
| 담당자 부재 | `insight-analyst`에 컨텍스트로 전달 → `slides.assignee.absence`로 06장 부재 일정표에 실림 |
| 특이 이벤트 | `insight-analyst`에 컨텍스트로 전달 → 증감 해석의 근거. 배포 사실이 없으면 효과를 단정하지 않는다 |
| 전월 팔로업 답변 | 09장 시사점과 다음 달 `next_month_watch`에 반영 |

## 4. 시사점 작성 — 이 보고서의 핵심

`insight-analyst`에 `stats.json`, `baselines.json`, **2단계에서 받은 부재 일정·특이 이벤트·전월 팔로업 답변**, 프로필 `insight_frame`을 전달해 `narrative.json`을 받는다. 사용자가 "없음"이라고 답했으면 그 사실도 그대로 전달한다 — 부재가 없었다는 정보 자체가 처리량 해석의 근거다.

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
