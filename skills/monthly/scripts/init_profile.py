#!/usr/bin/env python3
"""데이터를 진단해 팀 프로필(profile.json) 초안과 베이스라인 골격을 자동 생성한다.

사용법:
    python3 init_profile.py <데이터.json> [--out-dir .] [--team 팀명] [--org 조직명] [--force]

필드 매핑·UTC 여부·채널 목록·자사명·분류체계 성숙도를 데이터에서 추론한다.
추론할 수 없는 항목(팀명·보고서 제목·해석 관점)만 사람이 채우면 된다.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import extract_rows  # noqa: E402

# 필드 후보 (앞쪽일수록 우선)
ALIASES = {
    "requested_at": ["requested_at", "request_date", "req_date", "request_at", "reg_date", "요청일", "접수일"],
    "started_at": ["started_at", "start_at", "start_time", "work_start", "처리시작"],
    "completed_at": ["completed_at", "complete_at", "end_at", "done_at", "finish_at", "처리완료"],
    "channel": ["channel_code", "channel", "inflow_channel", "route", "유입경로", "채널"],
    "assignee": ["assignee_name", "assignee", "handler", "charge_name", "worker", "담당자"],
    "requester_org": ["original_requester_company", "requester_company", "company", "org_name", "요청회사"],
    "received_org": ["requester_company", "received_company", "접수회사"],
    "requester_dept": ["requester_dept", "dept", "department", "team_name", "부서"],
    "requester_name": ["requester_name", "requester", "user_name", "요청자"],
}
TEXT_FIELDS = ["raw_input", "summary", "content", "title", "description", "body", "요청내용", "제목"]
TAX_FIELDS = {
    "l1": ["l1_code", "category1", "large_code", "type1", "대분류"],
    "l2": ["l2_code", "category2", "middle_code", "type2", "중분류"],
    "l3": ["l3_code", "category3", "small_code", "type3", "소분류"],
}
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T.*(Z|\+00:00)$")


def pick(keys, candidates):
    for c in candidates:
        if c in keys:
            return c
    return None


def nonempty_ratio(rows, field):
    return sum(1 for r in rows if r.get(field)) / len(rows) if rows else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--team", default=None)
    ap.add_argument("--org", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        source_key, rows = extract_rows(json.load(f))
    if not rows:
        sys.exit("데이터가 비어 있습니다.")
    keys = list(rows[0].keys())

    fields, unmapped = {}, []
    for logical, cands in ALIASES.items():
        found = pick(keys, cands)
        fields[logical] = found
        if not found and logical in ("requested_at",):
            unmapped.append(logical)
    # requester_org와 received_org가 같은 필드로 잡히면 원요청 정보가 없는 것
    if fields["requester_org"] == fields["received_org"]:
        fields["requester_org"] = fields["received_org"]

    text = [f for f in TEXT_FIELDS if f in keys]
    taxonomy = {lvl: pick(keys, c) for lvl, c in TAX_FIELDS.items()}

    # UTC 필드 판정: 값이 Z 또는 +00:00으로 끝나면 UTC 저장
    utc_fields = []
    for f in keys:
        vals = [r.get(f) for r in rows[:200] if isinstance(r.get(f), str)]
        if vals and sum(1 for v in vals if ISO_UTC.match(v)) > len(vals) * 0.8:
            utc_fields.append(f)

    # 채널 라벨
    channel_labels = {}
    if fields["channel"]:
        for v in Counter(r.get(fields["channel"]) for r in rows if r.get(fields["channel"])):
            channel_labels[v] = str(v).capitalize()

    # 자사명 추정: 접수조직 ≠ 원요청조직인 건에서 가장 흔한 접수조직 = 대행 접수 주체
    self_org, self_evidence = None, ""
    if fields["received_org"] and fields["requester_org"] and fields["received_org"] != fields["requester_org"]:
        proxy = Counter(r.get(fields["received_org"]) for r in rows
                        if r.get(fields["received_org"]) and r.get(fields["requester_org"])
                        and r[fields["received_org"]] != r[fields["requester_org"]])
        if proxy:
            self_org, n = proxy.most_common(1)[0]
            self_evidence = f"타 조직 대행 접수 {n}건의 접수 주체"

    # 분류체계 성숙도
    l1 = taxonomy.get("l1")
    coverage = round(nonempty_ratio(rows, l1) * 100, 1) if l1 else 0.0
    mode = "coded" if coverage >= 90 else ("partial" if coverage > 0 else "none")
    codes = sorted({str(r.get(l1)) for r in rows if r.get(l1)}) if l1 else []

    # 추출 기준 경고
    sql = " ".join(str(source_key).split()) if source_key else ""
    undercount = bool(sql and "created_at" in sql and fields["requested_at"] and fields["requested_at"] not in sql.split("WHERE")[-1])

    profile = {
        "team": args.team or "TODO: 팀명",
        "org": args.org or "TODO: 조직명",
        "report_title": "TODO: 보고서 제목 (표지에 표기)",
        "short_title": "운영 보고",
        "org_dimension_label": "조직별",
        "self_org": self_org,
        "fields": {k: v for k, v in fields.items() if v} | {"text": text} |
                  ({"taxonomy": {k: v for k, v in taxonomy.items() if v}} if any(taxonomy.values()) else {}),
        "utc_fields": utc_fields,
        "channel_labels": channel_labels,
        "taxonomy_map": {c: f"TODO: {c} 유형명" for c in codes} if codes else {},
        "type_group_other": [],
        "watch_metrics": [],
        "insight_frame": ["TODO: 이 팀 보고서에서 매월 유지할 해석 관점"],
    }
    profile["fields"] = {k: v for k, v in profile["fields"].items() if v}

    os.makedirs(args.out_dir, exist_ok=True)
    ppath = os.path.join(args.out_dir, "profile.json")
    bpath = os.path.join(args.out_dir, "baselines.json")
    if os.path.exists(ppath) and not args.force:
        sys.exit(f"이미 존재합니다: {ppath} (덮어쓰려면 --force)")
    with open(ppath, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    if not os.path.exists(bpath):
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump({"months": []}, f, ensure_ascii=False, indent=2)

    # 사람이 읽을 진단 리포트
    print(f"프로필 초안 생성: {ppath}")
    print(f"베이스라인 골격:  {bpath}\n")
    print(f"데이터 {len(rows)}건 · 필드 {len(keys)}개\n")
    print("[자동 매핑된 필드]")
    for k, v in fields.items():
        if v:
            print(f"  {k:16s} → {v}")
    if text:
        print(f"  {'text':16s} → {', '.join(text)}")
    for lvl, v in taxonomy.items():
        if v:
            print(f"  {'taxonomy.' + lvl:16s} → {v}")
    missing = [k for k, v in fields.items() if not v]
    if missing:
        print("\n[매핑하지 못한 필드] — 데이터에 없으면 그대로 두면 됩니다")
        for k in missing:
            print(f"  {k}")
    print("\n[진단]")
    print(f"  분류체계     : {mode} (커버리지 {coverage}%, 코드 {len(codes)}종)")
    print(f"  처리시간 산출: {'가능' if fields['started_at'] and fields['completed_at'] else '불가 (started_at 없음)'}")
    print(f"  요청자 집중도: {'요청자명 기준' if fields['requester_name'] else '조직+부서 대체 집계'}")
    if utc_fields:
        print(f"  UTC 저장 필드: {', '.join(utc_fields)}")
    if self_org:
        print(f"  자사명 추정  : {self_org} ({self_evidence})")
    if undercount:
        print("  ⚠ 추출 쿼리가 로깅일 기준으로 보입니다. 요청일 기준 재추출을 권합니다.")
    todo = [k for k in ("team", "org", "report_title", "short_title", "org_dimension_label", "insight_frame")
            if isinstance(profile.get(k), str) and profile[k].startswith("TODO")
            or k in ("insight_frame", "short_title", "org_dimension_label")]
    if codes:
        todo.append("taxonomy_map")
    print("\n[사람이 채울 항목]")
    print(f"  {' / '.join(dict.fromkeys(todo))}")
    print("  → profile.json에서 TODO를 검색하면 됩니다.")


if __name__ == "__main__":
    main()
