# 보고서 목차·렌더링 규격

목차와 구성은 2026년 6월 Ops Logger 보고서를 기준으로 고정돼 있으며, `compose.py`가 자동 생성한다. 이 문서는 산출물이 어떻게 구성되는지 확인할 때 본다. **표나 차트를 손으로 만들 일은 없다.**

## 10슬라이드 목차 (고정)

| # | id | 내비게이션 | 자동 생성 내용 | 시사점 소스 |
|---|---|---|---|---|
| 00 | `cover` | 표지 | 제목·기간·건수·집계기준·작성일 | `cover_subtitle` |
| 01 | `summary` | Executive Summary | KPI 최대 6장 (건수·일평균·중앙값·평균·최다 채널·최다 유형) | `summary_lead`, `summary_insights` |
| 02 | `trend` | 월별 추이·일평균 | 비교카드 4장, 일별 차트, 월별 건수+처리시간 차트, 4개월 지표표 | `slides.trend` |
| 03 | `channel` | 채널별 유입·처리시간 | 채널표(월별+처리시간), 채널 비교 차트, 처리시간 차트, 유입경로 분해표 | `slides.channel` |
| 04 | `type` | 유형별 분포·변화 | 유형표(추적지표 하위행·기타 묶음), 유형 추이·구성비 차트, 분류체계 제안표 | `slides.type` |
| 05 | `company` | 조직별 유입량 | 상위 10 가로막대, 자사 접수 분해 도넛, 조직표 | `slides.company` |
| 06 | `assignee` | 담당자별 처리 현황 | 담당자표(비중·평균·중앙값), 비중 도넛, 부재 일정표 | `slides.assignee` |
| 07 | `requester` | 요청자 집중도 | KPI 4장, 담당자별 분산도표 | `slides.requester` |
| 08 | `peak` | 피크 패턴 분석 | KPI 4장, 요일별·시간대별 차트, 피크일 callout | `slides.peak` |
| 09 | `takeaway` | 종합 시사점 | SIGNAL 카드 3장, 집계 기준 안내, 다음 달 확인 포인트 | `takeaways`, `next_month_watch` |

05의 축과 제목은 집계가 정한다. 원요청 조직이 여러 종이면 `org_dimension_label`(계열사별/고객사별), 1종뿐이면 **요청자 부서**로 전환해 `dept_dimension_label`을 쓴다. 프로필 `org_dimension`으로 고정할 수 있다.

## 문체 — 명사형 종결 (보고서체)

보고서에 렌더되는 모든 문장은 **명사형으로 끝낸다.** `~습니다`·`~합니다`체를 쓰지 않는다.

- 스크립트가 만드는 고정 문구(집계 기준 안내·표 각주·차트 부제)는 이미 이 문체로 작성돼 있다.
- 에이전트가 쓰는 문장(`lead`·`insights`·`takeaways`·`notes`·`basis_notes`)도 같은 규칙을 따른다. 규칙은 `insight-analyst`에 있고 `insight-critic`이 검증한다.
- `build_report.py`가 `~니다`로 끝나는 문장과 140자를 넘는 `lead`를 **경고**로 잡는다. 빌드를 막지는 않는다.

`lead`는 한 문장이다. 대상과 핵심 수치만 담고, 해석은 `insights`로, 집계 기준은 `basis_notes`로 보낸다.

## 조건부 동작

| 조건 | 결과 |
|---|---|
| 처리시간 산출 불가 | 관련 KPI·열·차트가 빠지고 09장에 각주 자동 삽입 |
| 원요청 조직 1종 | 05장이 요청자 부서 축으로 전환되고 제목·부제가 함께 바뀜 |
| 대행 접수 0건 | 05장 자사 접수 분해 도넛 생략 |
| 05장 축이 전월과 다름 | 이름이 맞지 않으므로 전월 비교 열 생략 |
| 베이스라인 없음 (첫 보고서) | 비교 열·델타 생략, "첫 보고 · 비교 기준 없음" 표기 |
| 분류체계 미확정 | 04장 상단에 신뢰도 안내, 하단에 "데이터 기반 분류체계 제안" 표 |
| 요청자명 없음 | 07장이 조직+부서 단위 집계로 전환되고 집계 단위 각주 표기 |
| 요청자 집중도 산출 불가 | 07 슬라이드 자체가 생략 |

## 디자인 토큰 (renderer.html)

- 폰트 Pretendard + JetBrains Mono, Chart.js 4.4.0, 좌측 고정 사이드바 260px
- `--brand:#0248ff` `--good:#11a36c` `--warn:#d97706` `--bad:#dc2626`
- **월 비교 색상은 자동 롤링된다**: 오래된 달 회색 → 전월 보라 `#6366f1` → 당월 파랑 `rgba(2,72,255,0.78)`

## 블록 타입 (report.json)

`compose.py`가 생성하고 `renderer.html`이 해석한다. 직접 쓸 일은 없지만 구조 확인용으로 남긴다.

`kpi` · `compare` · `table` · `charts` · `insight` · `callouts` · `takeaway` · `heading` · `note` · `html`

표 셀은 문자열 또는 `{v, cls, pill:{text,tone}, indent}` 형태다. 차트는 `{kind, labels, datasets, horizontal, highlight, cutout}`이며 `datasets[].tone`으로 월 색상을, `colors`로 개별 막대 색을 지정한다.

## 빌드 검증 (build_report.py)

다음을 자동 검사하고 실패 시 중단한다.

- 표 헤더 열 수와 각 행·합계 행의 셀 수 일치
- 차트 라벨 개수와 데이터 개수 일치
- `meta.total`과 집계 총건수 일치
- 처리시간 미산출·과소집계 위험 시 각주 존재 여부 (경고)
