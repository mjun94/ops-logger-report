# Ops Logger API 요약 (스킬용)

전체 명세: Confluence 그룹웨어팀 > "Ops Logger 연동 API 스펙", vault `10_Work/Projects/2026/운영 가시화 Task/files/ops-logger-api.md`.

| 항목 | 값 |
|---|---|
| Base | `https://api-seahworks.seah.co.kr/api` |
| 인증 | 헤더 `X-AUTH-EMAIL: <실행자 그룹웨어 이메일>` (서버가 mem_id·부서코드를 세션에서 채움) |
| 등록 | `PUT /admin/vos/sr/info` JSON body, `id` 없음 |
| 당일 등록분 | `GET /admin/vos/sr/list?requested_at=YYYY-MM-DD&count=100&offset=0` → `data.list[]` (id·summary·requester_name·channel_code·started_at) |
| 요청자 검색 | `GET /org/topMenu/search/members?search_txt=<이메일 또는 이름>&integrated_yn=Y` → name·rep_org_name(회사)·org_name(부서)·job_duty_name(직급)·job_position_name(직책)·email·mem_type |
| 외부 회사 검색 | `GET /org/list?search_txt=<회사명>&lvl=3` → rep_org_name |
| 삭제 | `DELETE /admin/vos/sr/info?id=<id>` (소프트 삭제) |
| 응답 | `{"code":"CD_SUCCESS",...}`. 등록 응답에 id 없음 → 리스트 재조회로 확인 |

## 등록 body 필드

| 필드 | 값 | 비고 |
|---|---|---|
| `channel` | `chat` / `email` / `phone` / `face` | 필수 |
| `date` | `YYYY-MM-DD` | 필수. 없으면 시각 3종 모두 저장 안 됨 |
| `processStartAt` / `processEndAt` | `HH:mm` | 형식 오류 시 조용히 null |
| `summary` | 30자 이내 | 분류 결과 |
| `raw_input` | 원문 (연락처 마스킹 후) | |
| `l1_code` / `l2_code` / `l3_code` | 분류표 코드, 한 계통 | L3 없는 L2는 l3 null |
| `requester_name` / `requester_company` / `original_requester_company` / `requester_dept` / `requester_grade` / `requester_position` / `requester_contact` | 멤버 검색 결과 | 그룹 외 요청자는 `mem_type` `n03`, 회사는 `/org/list` 결과 |
| `mem_type` | `n01` 임직원 / `n03` 외부 | 멤버 검색 결과 |
| `assignee_name` / `assignee_dept` / `assignee_company` | 실행자 본인 | 멤버 검색(본인 이메일) 결과 |

## 소요 시간 선택지 (웹 등록 모달과 동일)

5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 90, 120 분
