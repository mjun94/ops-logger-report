#!/usr/bin/env python3
"""운영 로그 월간 추출 JSON을 집계해 보고서용 통계 JSON을 산출한다.

사용법:
    python3 aggregate.py <데이터.json> [옵션]

옵션:
    --profile <profile.json>   팀 프로필 (필드 매핑·분류체계·추적지표). 없으면 기본값 추정
    --taxonomy <taxonomy.json> taxonomy-builder 에이전트가 만든 유형 배정 결과
    --month YYYY-MM            대상 월 (기본: 데이터에서 최빈 월)
    --holidays 2026-06-03,...  해당 월 공휴일·임시공휴일 (실운영일 계산)
    --export-corpus            유형 분류용 텍스트 코퍼스를 함께 출력
    --out <경로>               파일로 저장 (기본: 표준출력)

설계 원칙:
- 숫자는 전부 이 스크립트가 결정적으로 계산한다. LLM은 해석만 담당한다.
- 팀마다 다른 것(필드명·자사명·분류체계·추적지표)은 프로필로 주입받는다.
- 분류체계 성숙도를 자동 판정한다: coded(확정) / partial(부분) / none(미확정).
- 외부 의존성 없음 (표준 라이브러리만).
"""
import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import extract_rows, find_config, find_taxonomy_doc, find_team_root, load_json, resolve_out  # noqa: E402

KST = timezone(timedelta(hours=9))
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

# vos_sr_requests 기본 매핑. 프로필로 덮어쓸 수 있다.
DEFAULT_PROFILE = {
    "team": None,
    "org": None,
    "fields": {
        "requested_at": "requested_at",
        "started_at": "started_at",
        "completed_at": "completed_at",
        "channel": "channel_code",
        "assignee": "assignee_name",
        "requester_org": "original_requester_company",
        "received_org": "requester_company",
        "requester_dept": "requester_dept",
        "requester_name": None,
        "text": ["raw_input", "summary"],
        "taxonomy": {"l1": "l1_code", "l2": "l2_code", "l3": "l3_code"},
    },
    # 값이 UTC로 저장된 필드 목록 (KST 변환 대상)
    "utc_fields": ["completed_at", "created_at"],
    # 자사(내부 조직)명. 대행 접수 분해에 사용. null이면 분해 생략
    "self_org": None,
    # 05장 분석 축. "auto"는 원요청 조직 종류 수로 판단하고, 1종이면 요청자 부서로 바꾼다.
    # "company"/"dept"로 고정할 수도 있다.
    "org_dimension": "auto",
    # {"01": "GWS 운영", ...} 형태. 비어 있으면 코드값 그대로 사용
    "taxonomy_map": {},
    # [{"label": "비밀번호 초기화", "level": "l3", "code": "020601"}]
    "watch_metrics": [],
    "route_channels": ["chat", "phone"],
}


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_ts(value, is_utc):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc if is_utc else KST)
    return dt.astimezone(KST)


def stats_block(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.mean(vals), 1),
        "median": round(statistics.median(vals), 1),
        "over_60min": sum(1 for v in vals if v >= 60),
        "max": round(max(vals), 1),
    }


class Aggregator:
    def __init__(self, rows, profile, taxonomy=None):
        self.profile = profile
        self.f = profile["fields"]
        self.utc = set(profile.get("utc_fields") or [])
        self.rows = rows
        self.taxonomy = taxonomy or {}
        self.durations = []

    # ---------- 필드 접근 ----------
    def get(self, row, key):
        name = self.f.get(key)
        if not name:
            return None
        return row.get(name)

    def ts(self, row, key):
        name = self.f.get(key)
        if not name:
            return None
        return parse_ts(row.get(name), is_utc=name in self.utc)

    def text_of(self, row):
        parts = []
        for name in self.f.get("text") or []:
            v = row.get(name)
            if v:
                parts.append(str(v))
        return " / ".join(dict.fromkeys(parts))

    def requester_org(self, row):
        return self.get(row, "requester_org") or self.get(row, "received_org") or "미상"

    def requester_dept(self, row):
        return self.get(row, "requester_dept") or "미상"

    def distinct_values(self, fn):
        """"미상"을 뺀 실제 값 종류 수. 분석 축이 의미 있는지 판단하는 데 쓴다."""
        return len({fn(r) for r in self.rows} - {"미상"})

    # ---------- 파생값 ----------
    def compute_durations(self):
        for row in self.rows:
            start, end = self.ts(row, "started_at"), self.ts(row, "completed_at")
            if start and end:
                minutes = (end - start).total_seconds() / 60
                self.durations.append(round(minutes, 1) if minutes >= 0 else None)
            else:
                self.durations.append(None)

    def taxonomy_mode(self):
        """분류체계 성숙도 판정: coded / partial / none"""
        l1_field = (self.f.get("taxonomy") or {}).get("l1")
        if not l1_field:
            return "none", 0.0, 0
        coded = sum(1 for r in self.rows if r.get(l1_field))
        ratio = coded / len(self.rows) if self.rows else 0.0
        mode = "coded" if ratio >= 0.9 else ("partial" if ratio > 0 else "none")
        return mode, round(ratio * 100, 1), coded

    def effective_types(self):
        """코드 우선, 없으면 taxonomy-builder 배정값으로 보완한 유형 라벨."""
        l1_field = (self.f.get("taxonomy") or {}).get("l1")
        tmap = self.profile.get("taxonomy_map") or {}
        assigned = self.taxonomy.get("assignments") or []
        proposed = {t["code"]: t["name"] for t in self.taxonomy.get("taxonomy") or []}

        labels, sources = [], []
        for i, row in enumerate(self.rows):
            code = row.get(l1_field) if l1_field else None
            if code:
                labels.append(tmap.get(str(code), str(code)))
                sources.append("coded")
                continue
            a = assigned[i] if i < len(assigned) else None
            if a:
                labels.append(proposed.get(a, a))
                sources.append("inferred")
            else:
                labels.append("미분류")
                sources.append("none")
        return labels, sources

    # ---------- 집계 ----------
    def by_dimension(self, key_fn):
        buckets = defaultdict(list)
        for i, row in enumerate(self.rows):
            buckets[key_fn(row)].append(self.durations[i])
        return {
            k: {"count": len(v), "duration": stats_block(v)}
            for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))
        }

    def route_breakdown(self):
        """자사 접수 건을 '계열사 대행' vs '순수 내부'로 분해."""
        self_org = self.profile.get("self_org")
        if not self_org:
            return None
        received = [r for r in self.rows if self.get(r, "received_org") == self_org]
        proxy = [r for r in received if self.requester_org(r) != self_org]
        if not proxy:
            return None          # 대행 접수가 없으면 분해할 게 없다 (한 회사만 담당하는 팀 등)
        by_channel = {}
        for ch in self.profile.get("route_channels") or []:
            sub = [r for r in self.rows if (self.get(r, "channel") or "") == ch]
            if not sub:
                continue
            recv = [r for r in sub if self.get(r, "received_org") == self_org]
            by_channel[ch] = {
                "total": len(sub),
                "direct": len(sub) - len(recv),
                "proxy_via_self": sum(1 for r in recv if self.requester_org(r) != self_org),
                "self_internal": sum(1 for r in recv if self.requester_org(r) == self_org),
            }
        return {
            "self_org": self_org,
            "received_total": len(received),
            "proxy_for_others": len(proxy),
            "pure_internal": len(received) - len(proxy),
            "by_channel": by_channel,
        }

    def watch_metrics(self):
        out = []
        tax_fields = self.f.get("taxonomy") or {}
        for m in self.profile.get("watch_metrics") or []:
            field = tax_fields.get(m.get("level", "l3"))
            if not field:
                continue
            n = sum(1 for r in self.rows if str(r.get(field) or "") == str(m.get("code")))
            out.append({
                "label": m.get("label"),
                "level": m.get("level"),
                "code": m.get("code"),
                "count": n,
                "share_pct": round(n / len(self.rows) * 100, 1) if self.rows else 0,
            })
        return out

    def concentration(self, assignees, top_n=2):
        """담당자별 요청자 분산도. 요청자명이 없으면 조직+부서로 대체 집계."""
        name_field = self.f.get("requester_name")
        basis = "요청자명" if name_field else "요청조직+부서(대체)"
        out = {}
        for assignee in list(assignees.keys())[:top_n]:
            sub = [r for r in self.rows if (self.get(r, "assignee") or "미지정") == assignee]
            if not sub:
                continue
            if name_field:
                keys = [f"{self.requester_org(r)} {r.get(name_field)}" for r in sub]
            else:
                keys = [f"{self.requester_org(r)} {self.get(r, 'requester_dept') or '?'}" for r in sub]
            c = Counter(keys)
            top5 = c.most_common(5)
            out[assignee] = {
                "basis": basis,
                "handled": len(sub),
                "unique_requesters": len(c),
                "per_requester": round(len(sub) / len(c), 1),
                "top5": [{"requester": k, "count": n} for k, n in top5],
                "top5_share_pct": round(sum(n for _, n in top5) / len(sub) * 100, 1),
            }
        return out

    def calendar(self, month, holidays):
        req = self.f["requested_at"]
        daily = Counter(str(r.get(req))[:10] for r in self.rows if r.get(req))
        weekday = Counter()
        for day, n in daily.items():
            try:
                weekday[WEEKDAY_KO[datetime.strptime(day, "%Y-%m-%d").weekday()]] += n
            except ValueError:
                continue
        # 실운영일 = 해당 월 평일 − 공휴일
        year, mon = int(month[:4]), int(month[5:7])
        cur, weekdays = datetime(year, mon, 1), []
        while cur.month == mon:
            if cur.weekday() < 5:
                weekdays.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        working = [d for d in weekdays if d not in set(holidays)]
        return {
            "daily": dict(sorted(daily.items())),
            "weekday": {d: weekday[d] for d in WEEKDAY_KO if weekday.get(d)},
            "weekday_avg": {
                d: round(weekday[d] / sum(1 for w in working
                                          if WEEKDAY_KO[datetime.strptime(w, "%Y-%m-%d").weekday()] == d), 1)
                for d in WEEKDAY_KO if weekday.get(d)
                and any(WEEKDAY_KO[datetime.strptime(w, "%Y-%m-%d").weekday()] == d for w in working)
            },
            "weekday_count": {
                d: sum(1 for w in working if WEEKDAY_KO[datetime.strptime(w, "%Y-%m-%d").weekday()] == d)
                for d in WEEKDAY_KO[:5]
            },
            "calendar_weekdays": len(weekdays),
            "holidays": sorted(set(holidays)),
            "working_days": len(working),
            "peak_days": [{"date": d, "count": n}
                          for d, n in sorted(daily.items(), key=lambda x: -x[1])[:3]],
        }

    def hourly(self):
        has_started = any(self.ts(r, "started_at") for r in self.rows)
        key = "started_at" if has_started else "completed_at"
        basis = "started_at" if has_started else "completed_at(KST 변환) 근사"
        counter = Counter()
        for row in self.rows:
            ts = self.ts(row, key)
            if ts:
                counter[ts.hour] += 1
        return basis, {f"{h:02d}": counter[h] for h in sorted(counter)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--profile")
    ap.add_argument("--taxonomy")
    ap.add_argument("--month")
    ap.add_argument("--holidays", default="")
    ap.add_argument("--export-corpus", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    profile_path, how = find_config("profile", args.data, args.profile)
    profile = deep_merge(DEFAULT_PROFILE, load_json(profile_path) or {})
    print(f"프로필: {profile_path} ({how})" if profile_path
          else "프로필 없음 — 기본 필드 매핑으로 진행합니다.", file=sys.stderr)
    root = find_team_root(args.data, args.profile)
    print(f"팀 루트: {root}", file=sys.stderr)
    taxonomy = load_json(args.taxonomy) if args.taxonomy else None
    taxonomy_doc = find_taxonomy_doc(root)
    print(f"분류체계 문서: {taxonomy_doc}" if taxonomy_doc
          else "분류체계 문서 없음 (팀 루트/taxonomy.md)", file=sys.stderr)

    with open(args.data, encoding="utf-8") as f:
        source_key, rows = extract_rows(json.load(f))
    if not rows:
        sys.exit("데이터 행을 찾지 못했습니다. JSON 구조를 확인하세요.")

    req_field = profile["fields"]["requested_at"]
    if req_field not in rows[0]:
        sys.exit(
            f"요청일 필드 '{req_field}'가 데이터에 없습니다.\n"
            f"데이터의 필드: {', '.join(list(rows[0].keys())[:12])}\n"
            f"→ 처음 쓰는 팀이면 init_profile.py로 프로필을 먼저 만드세요."
        )

    month_dist = Counter(str(r.get(req_field))[:7] for r in rows if r.get(req_field))
    month = args.month or month_dist.most_common(1)[0][0]
    rows = [r for r in rows if str(r.get(req_field) or "")[:7] == month]
    if not rows:
        sys.exit(f"{month} 데이터가 없습니다. --month를 확인하세요.")

    agg = Aggregator(rows, profile, taxonomy)
    agg.compute_durations()

    # 05장 분석 축 — 여러 조직(계열사·고객사)을 상대하는 팀은 조직별로,
    # 한 회사만 담당하는 팀은 조직별 집계가 막대 하나로 무의미하므로 요청자 부서별로 본다.
    org_mode = (profile.get("org_dimension") or "auto").lower()
    n_org = agg.distinct_values(agg.requester_org)
    n_dept = agg.distinct_values(agg.requester_dept)
    if org_mode in ("company", "dept"):
        org_dimension, org_reason = org_mode, "프로필 지정"
    elif n_org <= 1:
        org_dimension = "dept"
        org_reason = f"원요청 조직 {n_org}종 — 한 회사만 담당하는 팀으로 판단해 요청자 부서로 전환"
    else:
        org_dimension, org_reason = "company", f"원요청 조직 {n_org}종"
    org_key = agg.requester_dept if org_dimension == "dept" else agg.requester_org
    mode, coverage, coded_n = agg.taxonomy_mode()
    labels, sources = agg.effective_types()

    type_counter = Counter(labels)
    assignees = agg.by_dimension(lambda r: agg.get(r, "assignee") or "미지정")
    holidays = [h.strip() for h in args.holidays.split(",") if h.strip()]
    cal = agg.calendar(month, holidays)
    hour_basis, hourly = agg.hourly()

    duration_all = stats_block(agg.durations)
    has_started = any(agg.ts(r, "started_at") for r in rows)
    sql_text = " ".join(str(source_key).split()) if source_key else None
    undercount_risk = bool(sql_text and "created_at" in sql_text and "requested_at" not in sql_text.split("WHERE")[-1])

    result = {
        "meta": {
            "source_file": args.data,
            "extraction_query": sql_text,
            "team": profile.get("team"),
            "org": profile.get("org"),
            "month": month,
            "month_distribution": dict(sorted(month_dist.items())),
            # organizations를 어떤 축으로 집계했는지. compose가 라벨과 전월 비교 가능 여부를 정한다.
            "org_dimension": org_dimension,
            "org_dimension_reason": org_reason,
            "taxonomy": {
                "mode": mode,
                "coverage_pct": coverage,
                "coded_rows": coded_n,
                "inferred_rows": sum(1 for s in sources if s == "inferred"),
                "unclassified_rows": sum(1 for s in sources if s == "none"),
                # 팀이 문서로 확정한 분류체계(팀 루트/taxonomy.md) 존재 여부.
                # 있으면 taxonomy-builder는 도출 대신 이 문서 기준 배정 모드로 동작한다.
                "doc_found": bool(taxonomy_doc),
                "doc_path": taxonomy_doc,
                # 배정 출처: "doc"(팀 확정 문서 기준 배정) / "derived"(데이터에서 도출한 제안)
                "source": (taxonomy or {}).get("source"),
                "proposed_taxonomy": (taxonomy or {}).get("taxonomy"),
            },
            "flags": {
                # 프로필 없이도 기본 필드 매핑으로 집계가 통과할 수 있다.
                # 그 경우 팀명·분류체계·해석 관점이 전부 비므로 스킬이 셋업을 먼저 돌려야 한다.
                "profile_found": bool(profile_path),
                # 조직도 부서도 한 종류뿐이면 05장은 막대 하나다. 해석하지 말라는 신호.
                "org_dimension_degenerate": n_org <= 1 and n_dept <= 1,
                "has_started_at": has_started,
                "duration_available": duration_all is not None,
                "requester_name_available": bool(profile["fields"].get("requester_name")),
                "hourly_basis": hour_basis,
                "baseline_required": True,
                # 아래 두 문구는 09장 집계 기준 안내에 각주로 실린다 — 보고서 문체(명사형 종결)를 따른다.
                "undercount_risk": (
                    "추출 쿼리가 로깅일(created_at) 기준으로 보임. 월말 요청이 익월 로깅으로 "
                    "누락돼 과소집계 가능성 있음. 요청일 기준 재추출 권장."
                    if undercount_risk else None
                ),
                "duration_warning": (
                    None if has_started else
                    "started_at 부재로 처리시간 산출 불가. 다른 필드로 대체 계산 금지."
                ),
            },
        },
        "total": len(rows),
        "working_days": cal["working_days"],
        "daily_avg": round(len(rows) / cal["working_days"], 1) if cal["working_days"] else None,
        "duration_overall": duration_all,
        "channels": agg.by_dimension(lambda r: agg.get(r, "channel") or "미상"),
        "types": {
            name: {
                "count": n,
                "share_pct": round(n / len(rows) * 100, 1),
                "duration": stats_block([agg.durations[i] for i, l in enumerate(labels) if l == name]),
            }
            for name, n in type_counter.most_common()
        },
        "type_sources": dict(Counter(sources)),
        "watch_metrics": agg.watch_metrics(),
        "organizations": agg.by_dimension(org_key),
        "route": agg.route_breakdown(),
        "assignees": assignees,
        "requester_concentration": agg.concentration(assignees),
        "calendar": cal,
        "hourly": hourly,
    }

    if args.export_corpus or mode != "coded":
        tax_fields = profile["fields"].get("taxonomy") or {}
        l1_field = tax_fields.get("l1")
        result["text_corpus"] = [
            {
                "i": i,
                "text": agg.text_of(r),
                "coded_l1": r.get(l1_field) if l1_field else None,
                "org": agg.requester_org(r),
                "assignee": agg.get(r, "assignee"),
            }
            for i, r in enumerate(rows)
        ]

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out = resolve_out(args.out, root)
        with open(out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"저장: {out} ({len(rows)}건, 분류체계 모드={mode}, 커버리지={coverage}%)")
        print(f"05장 분석 축: {org_dimension} — {org_reason}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
