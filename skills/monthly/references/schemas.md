# 설정 파일 스키마

팀별 데이터는 **플러그인 밖(팀 폴더)** 에 둔다. 플러그인은 도구만 담는다.

## profile.json — 팀 프로필

기본값과 병합되므로 다른 항목만 쓰면 된다.

```json
{
  "team": "그룹웨어운영팀",
  "org": "SAMPLE",
  "report_title": "Ops Logger 기반 서비스 운영 가시화",
  "short_title": "Ops Logger",
  "org_dimension_label": "계열사별",
  "dept_dimension_label": "부서별",
  "org_dimension": "auto",
  "self_org": "샘플테크",

  "fields": {
    "requested_at": "requested_at",
    "started_at": "started_at",
    "completed_at": "completed_at",
    "channel": "channel_code",
    "assignee": "assignee_name",
    "requester_org": "original_requester_company",
    "received_org": "requester_company",
    "requester_dept": "requester_dept",
    "requester_name": null,
    "text": ["raw_input", "summary"],
    "taxonomy": { "l1": "l1_code", "l2": "l2_code", "l3": "l3_code" }
  },
  "utc_fields": ["completed_at", "created_at"],
  "channel_labels": { "chat": "Chat", "phone": "Phone", "email": "Email", "face": "Face (대면)" },

  "taxonomy_map": { "01": "GWS 운영", "02": "계정·조직 관리" },
  "type_group_other": ["업무 미팅", "감사·컴플라이언스", "미분류"],
  "watch_metrics": [
    { "label": "비밀번호 초기화", "level": "l3", "code": "020601", "parent": "계정·조직 관리" }
  ],
  "insight_frame": ["매월 유지할 해석 관점 문장"]
}
```

| 키 | 설명 |
|---|---|
| `org_dimension` | 05장 분석 축. `auto`(기본)·`company`·`dept`. `auto`는 원요청 조직이 1종뿐이면 **요청자 부서**로 바꾼다 — 한 회사만 담당하는 부서는 조직별 집계가 막대 하나라 무의미하다. 고정하면 담당 회사가 늘어도 축이 안 바뀌므로 `auto` 권장 |
| `org_dimension_label` / `dept_dimension_label` | 각 축의 표기. 축에 맞는 쪽만 쓰인다 |
| `self_org` | 자사명. 타 조직 대행 접수를 분해할 때 쓴다. 없으면 `null` → 분해 생략. 대행 접수가 0건이면 축과 무관하게 분해를 생략한다 |
| `taxonomy_map` | 코드 → 유형명. 비어 있으면 코드값을 그대로 표기 |
| `type_group_other` | 유형표에서 "기타"로 묶을 유형명 목록 |
| `watch_metrics.parent` | 유형표에서 어느 상위 유형 아래 들여쓴 행으로 붙일지. 생략하면 코드 앞 2자리로 추정 |
| `insight_frame` | insight-analyst에게 그대로 전달되는 팀 고유 해석 관점 |

## baselines.json — 과거월 확정 수치

전월 비교의 **유일한 근거**다. 과거 보고서에 공표된 숫자를 옮겨 적고, 집계로 재계산하지 않는다. `compose.py`는 당월 직전 3개월까지 사용한다.

```json
{
  "months": [
    {
      "month": "2026-05",
      "total": 447,
      "working_days": 18,
      "daily_avg": 24.8,
      "duration_mean": 11.6,
      "duration_median": 5.0,
      "channels": { "chat": 289, "phone": 92 },
      "types": { "그룹웨어 포털 운영": 156, "전자결재 운영": 121 },
      "organizations": { "계열사 A": 82 },
      "org_dimension": "company",
      "assignees": { "담당자 A": 198 },
      "watch": { "비밀번호 초기화": 47 },
      "next_month_watch": ["다음 달 확인할 항목"]
    }
  ]
}
```

`month`와 `total` 외에는 모두 선택이다. 없는 항목은 표에서 `—`로 표시된다.

`org_dimension`은 `organizations`를 어떤 축으로 집계했는지 남긴다. 축이 다른 달끼리는 이름이 맞지 않으므로 05장 전월 비교 열을 자동으로 뺀다. 없으면 `company`로 본다(구 데이터 호환).

**매월 보고서 확정 후 당월 항목을 추가하는 것이 이 파이프라인의 유일한 수작업이다.** 빠뜨리면 다음 달 비교가 끊긴다.

## taxonomy.json — 도출된 분류체계

`taxonomy-builder` 에이전트가 생성한다. `assignments`는 `stats.json`의 `text_corpus`와 같은 길이·순서여야 한다.

```json
{
  "taxonomy": [
    { "code": "A", "name": "계정·권한 관리", "definition": "…", "keywords": ["계정"], "examples": ["…"] }
  ],
  "assignments": ["A", "B", null],
  "l2_suggestions": { "A": ["입·퇴사 처리", "인증 관리"] },
  "coverage_note": "342건 중 331건 배정",
  "confidence": "medium",
  "review_points": ["팀이 확정 전에 판단할 경계 사례"]
}
```

## narrative.json — 시사점

`insight-analyst` 에이전트가 생성한다. 스키마와 작성 규칙은 해당 에이전트 정의에 있다. 숫자·표·차트는 `compose.py`가 만들므로 여기에는 **해석 텍스트만** 담긴다.
