---
name: insert-date
description: 지정한 지난 날짜에 내가 응대한 Google Chat·Gmail 문의를 모아 보여주고, 고른 건을 요약·분류·요청자 식별까지 마쳐 Ops Logger에 등록한다. "/ops-logger:insert-date 20261104", "어제 옵스로거 정리", "11월 4일 SR 등록", "지난주에 빠진 문의 등록" 요청에 사용. 오늘 건은 /ops-logger:insert-today.
argument-hint: "YYYYMMDD"
allowed-tools: Bash, Read, AskUserQuestion, mcp__gchat__search_messages, mcp__gchat__search_conversations, mcp__gchat__list_messages, mcp__claude_ai_Gmail__search_threads, mcp__claude_ai_Gmail__get_thread
---

지난 날짜의 운영 문의를 Ops Logger에 등록한다. 절차는 `insert-today`와 같고 **수집 날짜만 다르다**. 등록을 하루 이상 빠뜨렸을 때, 또는 전날 퇴근 전에 못 돌렸을 때 쓴다.

입력: $ARGUMENTS (`--dry`면 등록 대신 검증까지만)

## 1. 날짜 정하기

`$ARGUMENTS`에서 날짜 하나를 읽어 `YYYY-MM-DD`로 맞춘다.

- `20261104` · `2026-11-04` · `2026.11.04` → `2026-11-04`
- `11/04` · `11월 4일`처럼 연도가 없으면 올해. 그 날짜가 아직 안 왔으면 작년
- `어제` · `그저께` · `지난 금요일` → 오늘(KST) 기준으로 계산
- 날짜가 없으면 `AskUserQuestion`으로 묻는다. 옵션: 어제, 그저께, 직접 입력
- 오늘 날짜면 `/ops-logger:insert-today`와 같은 결과다. 안내만 하고 그대로 진행한다
- 미래 날짜면 멈춘다
- 지난달 이전 날짜면 "그 달 월간 보고서(ops-report)가 이미 나갔을 수 있다"고 한 줄 알리고 진행한다

후보 목록·확인 표·등록 결과 앞머리에 **날짜와 요일**을 항상 적는다 (예: `2026-11-04 (화) 수집 결과`). 오늘이 아닌 날짜에 등록한다는 것을 사용자가 보고 있어야 한다.

## 2. 수집 범위

KST 그 날 00:00~24:00. UTC로는 `<전날>T15:00:00Z` ~ `<당일>T15:00:00Z`.

- Chat DM·스페이스·그룹: `mcp__gchat__search_messages`의 `searchParameters`에 `startTime`과 **`endTime` 둘 다** 넣는다. `endTime`을 빼면 그 뒤 날짜 메시지가 섞인다. 나머지는 `insert-today` 1단계와 같다
- Gmail: `after:<당일 YYYY/MM/DD> before:<다음날 YYYY/MM/DD> (in:sent OR in:inbox)`
- 그 날 등록분: `python3 "${CLAUDE_SKILL_DIR}/../insert-today/scripts/ops_logger.py" list-today --date <날짜>`. 며칠 지난 날짜는 이미 웹에서 등록했을 가능성이 높으니 "등록됨" 대조를 더 꼼꼼히 한다

## 3. 이후 절차

`${CLAUDE_SKILL_DIR}/../insert-today/SKILL.md`를 읽고 **2단계(후보 추리기)부터 7단계(등록)까지 그대로** 따른다. 그 문서의 "오늘"·"당일"은 모두 지정한 날짜로 읽는다. 참조 문서(`references/`)와 스크립트(`scripts/ops_logger.py`)도 `${CLAUDE_SKILL_DIR}/../insert-today/` 아래 것을 쓴다. 요청회사 확인, 1 문의 = 1건, 승인 전 등록 금지 규칙이 전부 그대로 적용된다.

지난 날짜라서 추가로 지킬 것:

- `date`는 지정한 날짜다. 첫 요청 메시지가 지정 날짜 안에 있는 문의만 후보다. 전날 시작해 이 날 끝난 문의는 전날 건이므로 넣지 않는다 (필요하면 전날 날짜로 다시 실행)
- 답변이 다음날로 넘어간 문의는 `processEndAt`을 지정 날짜 안에 둔다. 그 날 마지막 답변 시각이 있으면 그 시각, 없으면 시작 + 소요
- 사용자가 "오늘도 같이" 하자고 하면 이 실행을 마친 뒤 `/ops-logger:insert-today`를 따로 돌린다. 한 번에 두 날짜를 섞지 않는다

## 하지 말 것

- 지정 날짜 밖의 메시지를 후보에 넣지 않는다
- 날짜를 추측해서 진행하지 않는다. 애매하면 묻는다
- `insert-today`의 "하지 말 것" 전부
