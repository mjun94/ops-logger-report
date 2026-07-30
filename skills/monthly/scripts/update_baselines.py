#!/usr/bin/env python3
"""당월 확정 수치를 baselines.json에 기록한다 (다음 달 전월 비교의 근거).

사용법:
    python3 update_baselines.py stats.json [--narrative narrative.json] [--baselines baselines.json]

같은 달이 이미 있으면 덮어쓴다. 보고서 생성 마지막 단계에서 자동 실행되므로
사용자가 손으로 표를 옮겨 적을 필요가 없다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import find_config, find_team_root, load_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stats")
    ap.add_argument("--narrative")
    ap.add_argument("--baselines")
    args = ap.parse_args()

    stats = load_json(args.stats)
    narrative = load_json(args.narrative) if args.narrative else {}
    # 원본 데이터 경로를 기준으로 찾는다. stats.json은 report-work/ 안이라 기준이 될 수 없다.
    src = (stats.get("meta") or {}).get("source_file") or args.stats
    path, how = find_config("baselines", src, args.baselines)
    if not path:
        path = os.path.join(find_team_root(src), "baselines.json")
        how = "새로 생성"
    data = load_json(path) if os.path.isfile(path) else {"months": []}
    data.setdefault("months", [])

    dur = stats.get("duration_overall") or {}
    entry = {
        "month": stats["meta"]["month"],
        "total": stats["total"],
        "working_days": stats.get("working_days"),
        "daily_avg": stats.get("daily_avg"),
    }
    if dur:
        entry["duration_mean"] = dur.get("mean")
        entry["duration_median"] = dur.get("median")
    entry["channels"] = {k: v["count"] for k, v in (stats.get("channels") or {}).items()}
    entry["types"] = {k: v["count"] for k, v in (stats.get("types") or {}).items()}
    entry["organizations"] = {k: v["count"] for k, v in (stats.get("organizations") or {}).items()}
    entry["assignees"] = {k: v["count"] for k, v in (stats.get("assignees") or {}).items()}
    watch = {w["label"]: w["count"] for w in (stats.get("watch_metrics") or []) if w.get("label")}
    if watch:
        entry["watch"] = watch
    if narrative.get("next_month_watch"):
        entry["next_month_watch"] = narrative["next_month_watch"]
    tax = stats["meta"].get("taxonomy") or {}
    if tax.get("mode") and tax["mode"] != "coded":
        entry["taxonomy_mode"] = tax["mode"]

    months = [m for m in data["months"] if m.get("month") != entry["month"]]
    replaced = len(months) != len(data["months"])
    months.append(entry)
    data["months"] = sorted(months, key=lambda m: m.get("month", ""))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"베이스라인 {'갱신' if replaced else '추가'}: {path} ({how})")
    print(f"  {entry['month']} · {entry['total']}건 · 누적 {len(data['months'])}개월")
    if narrative.get("next_month_watch"):
        print(f"  다음 달 확인 포인트 {len(narrative['next_month_watch'])}건 기록됨")


if __name__ == "__main__":
    main()
