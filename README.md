# 월간 운영 보고서 생성기 (Claude Code 플러그인)

운영 로그 월간 추출 JSON **경로 하나로** 시사점 중심의 월간 운영 보고서(Chart.js 슬라이드 HTML)를 만듭니다. 여러 팀이 각자의 데이터·분류체계 성숙도로 함께 쓰도록 만들었습니다.

## 사용법

**처음 쓰는 팀** — 경로만 주면 데이터를 진단해 프로필을 만듭니다.

```
/ops-report:setup ./data/requests_202607.json
```

필드 매핑·UTC 여부·채널·자사명·분류체계 성숙도를 데이터에서 추론하고, 추론할 수 없는 것(팀명·보고서 제목·해석 관점)만 한 번에 물어봅니다.

**매월 보고서** — 경로만 주면 끝입니다.

```
/ops-report:monthly ./data/requests_202607.json
```

프로필과 베이스라인은 자동으로 찾고, 출력 파일명도 자동으로 정해집니다. 옵션을 외울 필요가 없습니다.

## 자동으로 처리되는 것

| 항목 | 동작 |
|---|---|
| 프로필·베이스라인 찾기 | 데이터 폴더 → 상위 → 현재 위치 순으로 자동 탐색 |
| 출력 파일명 | `<제목> N월 보고서(YY.MM.DD).html` 자동 생성 |
| 전월 비교 | 베이스라인이 있으면 자동, 없으면 첫 보고서로 비교 없이 생성 |
| 베이스라인 갱신 | 보고서 생성 후 당월 수치·다음 달 확인 포인트 자동 기록 |
| 데이터 한계 | 처리시간·요청자명이 없으면 관련 지표를 빼고 각주를 자동 삽입 |
| 분류체계 | 코드가 없으면 원문에서 도출해 제안 |

사람이 매달 해야 하는 일은 **공휴일·담당자 부재·특이 이벤트를 확인해 주는 것**뿐입니다. 데이터에 없는 정보라 물어볼 수밖에 없습니다.

## 설계 원칙

| 역할 | 담당 | 이유 |
|---|---|---|
| 숫자 집계 | `aggregate.py` | 같은 입력 → 같은 결과. LLM이 세지 않는다 |
| 표·차트 레이아웃 | `compose.py` + `renderer.html` | 매달 1000줄 HTML을 손으로 고치지 않는다 |
| **시사점 해석** | `insight-analyst` 에이전트 | 이 보고서의 실제 가치 |
| 시사점 검증 | `insight-critic` 에이전트 | 근거 없는 단정이 경영 보고로 나가지 않게 |
| 분류체계 도출 | `taxonomy-builder` 에이전트 | 분류체계가 없는 팀도 첫 달부터 쓸 수 있게 |
| 정합성 검사 | `build_report.py` | 체크리스트 대신 빌드 실패로 막는다 |

팀 고유 정보(필드 매핑·분류체계·과거 수치·해석 관점)는 **플러그인 밖 팀 폴더**의 `profile.json` / `baselines.json`에 둡니다. 플러그인에는 어떤 팀의 운영 데이터도 들어 있지 않습니다 — `examples/` 아래 값은 형식 설명용 가상 데이터입니다.

## 팀 폴더 구조 (권장)

```
우리팀-운영보고/
├── data/
│   ├── requests_202606.json
│   └── requests_202607.json
├── profile.json        # setup이 생성
├── baselines.json      # 매월 자동 누적
└── 운영 보고 7월 보고서(26.08.03).html
```

## 설치

```
/plugin marketplace add mjun94/ops-logger-report
/plugin install ops-report@jun-plugins
```

로컬 테스트: 저장소를 클론한 뒤 `claude --plugin-dir <클론 경로>`

## 구성

```
ops-logger-report/
├── .claude-plugin/{plugin,marketplace}.json
├── skills/
│   ├── monthly/                  # 보고서 생성 (메인)
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── init_profile.py   # 프로필 자동 생성
│   │   │   ├── aggregate.py      # 집계
│   │   │   ├── compose.py        # 10슬라이드 조립
│   │   │   ├── build_report.py   # 검증 + HTML 생성
│   │   │   ├── update_baselines.py
│   │   │   └── _common.py        # 설정 자동 탐색
│   │   ├── assets/renderer.html  # 데이터 주입형 렌더러
│   │   └── references/{schemas,report-spec}.md
│   └── setup/SKILL.md            # 신규 팀 온보딩
├── agents/{insight-analyst,insight-critic,taxonomy-builder}.md
└── examples/{profile,baselines}.groupware.json
```

## 산출물

10슬라이드 구성입니다.

표지 · Executive Summary · 월별 추이·일평균 · 채널별 유입·처리시간 · 유형별 분포·변화 · 조직별 유입량 · 담당자별 처리 현황 · 요청자 집중도 · 피크 패턴 분석 · 종합 시사점

## 분류체계가 아직 없는 팀

실 데이터를 쌓는 중이라 운영 분류체계를 확정하지 못한 팀이 많습니다. 이 플러그인은 그 상태를 **결함이 아니라 입력**으로 다룹니다.

1. `aggregate.py`가 분류 코드 커버리지로 `coded`/`partial`/`none` 판정
2. `coded`가 아니면 `taxonomy-builder`가 요청 원문을 읽고 6~10개 대분류를 설계하고 전 건을 배정
3. 04장에 제안 분류체계·건수와 팀이 판단할 경계 사례가 실림
4. 확정 후 `profile.json`의 `taxonomy_map`에 반영 → 다음 달부터 코드 기반 정식 집계

**첫 달부터 보고서가 나오고, 보고서를 만드는 과정이 분류체계를 확정하는 과정**이 됩니다.

## 데이터 요구사항

- 형식: `{ "<추출 SQL>": [ {행}, … ] }` 또는 행 배열
- **요청일 기준으로 추출**할 것. 로깅일 기준이면 월말 요청이 익월로 넘어가 과소집계됩니다(자동 경고)
- 처리시간 분석을 원하면 `started_at`, 요청자 집중도 분석을 원하면 요청자명을 SELECT에 포함

## 라이선스

MIT — [LICENSE](./LICENSE)
