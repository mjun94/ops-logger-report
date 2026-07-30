#!/usr/bin/env python3
"""stats.json + narrative.json (+profile/baselines) → report.json

6월 보고서와 동일한 10슬라이드 목차를 고정 생성한다.
    00 표지 / 01 Executive Summary / 02 월별 추이·일평균 / 03 채널별 유입·처리시간
    04 유형별 분포·변화 / 05 조직별 유입량 / 06 담당자별 처리 현황
    07 요청자 집중도 / 08 피크 패턴 분석 / 09 종합 시사점

숫자·표·차트 레이아웃은 전부 이 스크립트가 만든다.
에이전트는 narrative.json(해석 텍스트)만 작성한다.

사용법:
    python3 compose.py stats.json narrative.json --out report.json \
        [--profile profile.json] [--baselines baselines.json] [--authored 2026.08.03]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import find_config, load_json  # noqa: E402

CH_LABELS = {"chat": "Chat", "phone": "Phone", "email": "Email", "face": "Face (대면)"}
TONES = ["older", "old", "prev"]  # 과거월 색상 (오래된 순)
BAR_COLORS = {
    "older": "rgba(148,163,184,0.45)",
    "old": "rgba(148,163,184,0.6)",
    "prev": "rgba(99,102,241,0.6)",
    "current": "rgba(2,72,255,0.78)",
}


def mlabel(month):
    return f"{int(month[5:7])}월"


def num(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, float):
        v = round(v, 1)
        return (f"{int(v)}" if v == int(v) and unit != "분" else f"{v}") + unit
    return f"{v}{unit}"


def pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def delta_pill(cur, prev):
    """증감 방향 pill. 증가=좋음/나쁨 판단은 하지 않고 방향과 폭만 표시한다.
    좋다·나쁘다는 해석의 영역이므로 narrative가 pill을 직접 지정해 덮어쓸 수 있다."""
    if prev in (None, 0) or cur is None:
        return {"text": "비교 없음", "tone": "gray"}
    d = pct(cur - prev, prev)
    if abs(d) < 3:
        return {"text": "보합", "tone": "gray"}
    return {"text": f"{'▲' if d > 0 else '▼'} {abs(d):.1f}%", "tone": "brand" if d > 0 else "prev"}


class Composer:
    def __init__(self, stats, narrative, profile, baselines, authored):
        self.s = stats
        self.n = narrative or {}
        self.p = profile or {}
        self.authored = authored
        self.month = stats["meta"]["month"]
        self.ml = mlabel(self.month)
        self.total = stats["total"]
        self.ch_labels = {**CH_LABELS, **(self.p.get("channel_labels") or {})}
        self.org_label = self.p.get("org_dimension_label", "조직별")
        # 과거월 (오래된 순), 최대 3개
        self.base = sorted((baselines or {}).get("months", []), key=lambda m: m["month"])
        self.base = [b for b in self.base if b["month"] < self.month][-3:]
        self.prev = self.base[-1] if self.base else None

    # ---------- 공통 ----------
    def slide_narr(self, key):
        return (self.n.get("slides") or {}).get(key) or {}

    def insight_block(self, key, default_title="시사점"):
        d = self.slide_narr(key)
        items = d.get("insights") or []
        if not items:
            return None
        return {"type": "insight", "tone": d.get("tone", ""), "title": d.get("insight_title", default_title), "items": items}

    def month_cols(self, extra_current="당월"):
        cols = [{"label": mlabel(b["month"]), "cls": "num"} for b in self.base]
        cols.append({"label": self.ml, "cls": "num"})
        return cols

    def dur(self, block, field="mean"):
        return None if not block else block.get(field)

    def p_parent(self, watch):
        """추적 지표를 어느 상위 유형 아래 붙일지. 프로필에 parent가 없으면 코드 앞 2자리로 추정."""
        code = str(watch.get("code") or "")
        return (self.p.get("taxonomy_map") or {}).get(code[:2])

    # ---------- 00 표지 ----------
    def cover(self):
        meta = self.s["meta"]
        title = self.p.get("report_title", "운영 현황 보고")
        return {
            "pretitle": f"{meta.get('org') or ''}{' · ' if meta.get('org') and meta.get('team') else ''}{meta.get('team') or ''}",
            "title_html": self.n.get("cover_title_html")
            or f"{title.split('—')[0].strip()}<br /><em>{self.month[:4]}년 {int(self.month[5:7])}월 보고</em>",
            "subtitle": self.n.get("cover_subtitle", ""),
            "nav": "표지",
            "meta": [
                {"k": "분석 기간", "v": f"{self.month.replace('-', '.')}.01 — {self.month.replace('-', '.')}.말"},
                {"k": "분석 대상", "v": f"{self.total}건"},
                {"k": "집계 기준", "v": "요청일 기준"},
                {"k": "작성일", "v": self.authored},
            ],
        }

    # ---------- 01 Executive Summary ----------
    def s_summary(self):
        d = self.s
        chan = d["channels"]
        top_ch = next(iter(chan), None)
        dur = d.get("duration_overall")
        kpis = [
            {"label": f"{self.ml} 총 건수", "value": self.total, "unit": "건", "tone": "brand",
             "sub": (f"전월 대비 {self.total - self.prev['total']:+d}건 ({pct(self.total - self.prev['total'], self.prev['total']):+.1f}%)"
                     if self.prev else "첫 보고 · 비교 기준 없음")},
            {"label": "평일 일평균 (실운영일)", "value": num(d.get("daily_avg")), "unit": "건", "tone": "warn",
             "sub": f"실운영 {d['working_days']}일 기준" + (f" · 전월 {self.prev.get('daily_avg')}건" if self.prev else "")},
        ]
        if dur:
            kpis += [
                {"label": "처리 중앙값", "value": num(dur["median"]), "unit": "분", "tone": "good",
                 "sub": (f"전월 {self.prev.get('duration_median')}분" if self.prev else "")},
                {"label": "처리 평균", "value": num(dur["mean"]), "unit": "분", "tone": "good",
                 "sub": (f"전월 {self.prev.get('duration_mean')}분" if self.prev else "")},
            ]
        else:
            kpis.append({"label": "처리시간", "value": "—", "sub": "started_at 부재로 산출 불가 (본문 각주 참조)"})
        if top_ch:
            kpis.append({"label": f"{self.ch_labels.get(top_ch, top_ch)} 비중", "value": num(pct(chan[top_ch]["count"], self.total)),
                         "unit": "%", "sub": f"{chan[top_ch]['count']}건"})
        top_type = next(iter(d["types"]), None)
        if top_type:
            kpis.append({"label": f"{top_type} 비중", "value": num(d["types"][top_type]["share_pct"]), "unit": "%",
                         "sub": f"{d['types'][top_type]['count']}건 · 최다 유형"})

        blocks = [{"type": "kpi", "items": kpis[:6]}]
        ins = self.n.get("summary_insights") or {}
        if ins.get("items"):
            blocks.append({"type": "insight", "tone": ins.get("tone", "bad"), "title": "핵심 해석", "items": ins["items"]})
        return {"id": "summary", "nav": "Executive Summary", "tag": "01 — EXECUTIVE SUMMARY",
                "h2": f"한 눈에 보는 {self.ml}", "lead": self.n.get("summary_lead", ""), "blocks": blocks}

    # ---------- 02 월별 추이 ----------
    def s_trend(self):
        d, blocks = self.s, []
        months = self.base + [{"month": self.month, "total": self.total, "working_days": d["working_days"],
                               "daily_avg": d.get("daily_avg"),
                               "duration_mean": self.dur(d.get("duration_overall")),
                               "duration_median": self.dur(d.get("duration_overall"), "median")}]

        def card(label, key, unit, invert=False):
            rows = []
            for i, m in enumerate(months):
                tone = "current" if i == len(months) - 1 else TONES[max(0, 3 - (len(months) - 1 - i))]
                rows.append({"name": mlabel(m["month"]), "val": num(m.get(key)), "unit": unit, "tone": tone})
            cur, prv = months[-1].get(key), (months[-2].get(key) if len(months) > 1 else None)
            dl = {"text": "─ 비교 기준 없음", "tone": "neutral"}
            if cur is not None and prv:
                diff = pct(cur - prv, prv)
                dl = {"text": f"{'▲' if diff > 0 else '▼'} {abs(diff):.1f}% vs 전월",
                      "tone": ("up" if (diff > 0) != invert else "down")}
            return {"label": label, "rows": rows, "delta": dl}

        cards = [card("월별 총 건수", "total", "건"), card("일평균 (실운영일)", "daily_avg", "건/일")]
        if d.get("duration_overall"):
            cards += [card("처리 평균 시간", "duration_mean", "분", invert=True),
                      card("처리 중앙값 시간", "duration_median", "분", invert=True)]
        blocks.append({"type": "compare", "cards": cards})

        # 일별 차트 (평일만)
        cal = d["calendar"]
        holidays = set(cal.get("holidays") or [])
        peaks = {p["date"] for p in cal["peak_days"][:2]}
        labels, data, colors = [], [], []
        for day, n in cal["daily"].items():
            dt = datetime.strptime(day, "%Y-%m-%d")
            if dt.weekday() >= 5 and n == 0:
                continue
            labels.append(f"{dt.month}/{dt.day}")
            data.append(n)
            colors.append("rgba(220,38,38,0.75)" if day in peaks
                          else "rgba(217,119,6,0.6)" if day in holidays else "rgba(2,72,255,0.55)")
        charts = [{"title": f"일별 건수 추이 ({self.ml})",
                   "sub": (f"공휴일 {', '.join(sorted(holidays))} 제외 · 피크일 강조" if holidays else "피크일 강조"),
                   "chart": {"kind": "bar", "labels": labels,
                             "datasets": [{"label": "건수", "data": data, "colors": colors}]}}]
        mchart_ds = [{"label": "건수", "data": [m["total"] for m in months],
                      "colors": [BAR_COLORS["current"] if i == len(months) - 1 else BAR_COLORS[TONES[max(0, 3 - (len(months) - 1 - i))]]
                                 for i in range(len(months))]}]
        if d.get("duration_overall") and any(m.get("duration_mean") for m in months):
            mchart_ds.append({"label": "평균 처리시간(분)", "data": [m.get("duration_mean") for m in months],
                              "type": "line", "tone": "good"})
        charts.append({"title": "월별 건수 & 평균 처리시간" if len(mchart_ds) > 1 else "월별 건수",
                       "sub": "막대=건수" + (", 선=평균 처리시간(분)" if len(mchart_ds) > 1 else ""),
                       "chart": {"kind": "bar", "labels": [mlabel(m["month"]) for m in months], "datasets": mchart_ds}})
        blocks.append({"type": "charts", "cards": charts})

        cols = ["구분"] + self.month_cols() + ["비고"]
        notes = (self.slide_narr("trend").get("table_notes") or {})
        rows = [
            ["총 건수"] + [{"v": m["total"], "cls": "num" + (" brand" if i == len(months) - 1 else "")} for i, m in enumerate(months)] + [notes.get("total", "")],
            ["실운영일"] + [{"v": m.get("working_days", "—"), "cls": "num" + (" brand" if i == len(months) - 1 else "")} for i, m in enumerate(months)] + [notes.get("working_days", "")],
            ["일평균 건수"] + [{"v": num(m.get("daily_avg")), "cls": "num" + (" brand" if i == len(months) - 1 else "")} for i, m in enumerate(months)] + [notes.get("daily_avg", "")],
        ]
        if d.get("duration_overall"):
            rows += [
                ["평균 처리시간(분)"] + [{"v": num(m.get("duration_mean")), "cls": "num" + (" brand" if i == len(months) - 1 else "")} for i, m in enumerate(months)] + [notes.get("duration_mean", "")],
                ["중앙값 처리시간(분)"] + [{"v": num(m.get("duration_median")), "cls": "num" + (" brand" if i == len(months) - 1 else "")} for i, m in enumerate(months)] + [notes.get("duration_median", "")],
            ]
        blocks.append({"type": "table", "columns": cols, "rows": rows,
                       "note": self.slide_narr("trend").get("note", "")})

        extra = self.slide_narr("trend").get("extra_table")
        if extra:
            blocks.append({"type": "table", "heading": extra.get("heading", ""), "columns": extra["columns"],
                           "rows": extra["rows"], "note": extra.get("note", "")})
        b = self.insight_block("trend")
        if b:
            blocks.append(b)
        return {"id": "trend", "nav": "월별 추이·일평균", "tag": "02 — 월별 추이",
                "h2": f"{self.ml} 처리 건수 & 운영일당 수요", "lead": self.slide_narr("trend").get("lead", ""), "blocks": blocks}

    # ---------- 03 채널별 ----------
    def s_channel(self):
        d = self.s
        chan = d["channels"]
        keys = list(chan.keys())
        cols = ["채널"] + self.month_cols() + ([{"label": "처리시간", "cls": "num"}] if d.get("duration_overall") else [])
        rows = []
        for k in keys:
            row = [self.ch_labels.get(k, k)]
            for b in self.base:
                v = (b.get("channels") or {}).get(k)
                row.append({"v": f"{v} ({pct(v, b['total'])}%)" if v is not None else "—", "cls": "num"})
            row.append({"v": f"{chan[k]['count']} ({pct(chan[k]['count'], self.total)}%)", "cls": "num brand"})
            if d.get("duration_overall"):
                row.append({"v": num(self.dur(chan[k].get("duration")), "분"), "cls": "num"})
            rows.append(row)
        total_row = ["합계"] + [{"v": b["total"], "cls": "num"} for b in self.base] + [{"v": self.total, "cls": "num"}]
        if d.get("duration_overall"):
            total_row.append({"v": num(d["duration_overall"]["mean"], "분"), "cls": "num"})

        ds = []
        for i, b in enumerate(self.base):
            ds.append({"label": mlabel(b["month"]), "data": [(b.get("channels") or {}).get(k, 0) for k in keys],
                       "tone": TONES[max(0, 3 - (len(self.base) - i))]})
        ds.append({"label": self.ml, "data": [chan[k]["count"] for k in keys], "tone": "current"})
        charts = [{"title": "채널별 건수 비교", "sub": "월별 절대 건수",
                   "chart": {"kind": "bar", "labels": [self.ch_labels.get(k, k) for k in keys], "datasets": ds}}]
        if d.get("duration_overall"):
            charts.append({"title": f"채널별 평균 처리시간 ({self.ml})", "sub": "대면은 현장 상담 특성상 구조적으로 길다",
                           "chart": {"kind": "bar", "labels": [self.ch_labels.get(k, k) for k in keys],
                                     "datasets": [{"label": "평균 처리시간(분)",
                                                   "data": [self.dur(chan[k].get("duration")) or 0 for k in keys],
                                                   "colors": ["rgba(2,72,255,0.6)", "rgba(17,163,108,0.6)",
                                                              "rgba(99,102,241,0.6)", "rgba(220,38,38,0.6)"][:len(keys)]}]}})
        blocks = [{"type": "table", "columns": cols, "rows": rows, "total": total_row},
                  {"type": "charts", "cards": charts}]

        route = d.get("route")
        if route and route.get("by_channel"):
            rcols = ["채널", {"label": "전체", "cls": "num"}, {"label": "직접 요청", "cls": "num"},
                     {"label": f"{route['self_org']} 경유(대행)", "cls": "num"}, {"label": f"{route['self_org']} 내부", "cls": "num"}]
            rrows = [[self.ch_labels.get(ch, ch), {"v": v["total"], "cls": "num"},
                      {"v": f"{v['direct']} ({pct(v['direct'], v['total'])}%)", "cls": "num"},
                      {"v": f"{v['proxy_via_self']} ({pct(v['proxy_via_self'], v['total'])}%)", "cls": "num"},
                      {"v": f"{v['self_internal']} ({pct(v['self_internal'], v['total'])}%)", "cls": "num"}]
                     for ch, v in route["by_channel"].items()]
            blocks.append({"type": "table", "heading": f"유입 경로 세분화 ({self.ml})", "columns": rcols, "rows": rrows,
                           "note": "요청자 소속과 원요청 조직을 함께 사용해 직접 요청과 대행 요청을 분리했습니다."})
        b = self.insight_block("channel")
        if b:
            blocks.append(b)
        return {"id": "channel", "nav": "채널별 유입·처리시간", "tag": "03 — 채널별 분석",
                "h2": "채널별 유입 & 처리시간", "lead": self.slide_narr("channel").get("lead", ""), "blocks": blocks}

    # ---------- 04 유형별 ----------
    def s_type(self):
        d = self.s
        tax = d["meta"]["taxonomy"]
        types = d["types"]
        keys = list(types.keys())
        blocks = []

        if tax["mode"] != "coded":
            src = d.get("type_sources") or {}
            coded_n, inferred_n = src.get("coded", 0), src.get("inferred", 0)
            if coded_n:
                lead = (f"<strong>운영 분류체계가 아직 확정되지 않은 상태입니다</strong> (코드 부여 {tax['coverage_pct']}%). "
                        f"코드가 있는 {coded_n}건은 그대로 쓰고, 나머지 {inferred_n}건은 요청 원문을 근거로 유형을 추정해 집계했습니다.")
            else:
                lead = (f"<strong>운영 분류체계가 아직 없는 상태입니다.</strong> "
                        f"{inferred_n}건 전부를 요청 원문에서 유형을 도출해 집계했습니다.")
            items = [lead, "추정 분류는 <strong>참고치</strong>입니다. 아래 제안 분류체계를 확정하면 다음 달부터 코드 기반 정식 집계로 전환됩니다."]
            if tax.get("unclassified_rows"):
                items.append(f"원문이 짧거나 맥락이 부족해 판단하지 못한 {tax['unclassified_rows']}건은 미분류로 남겼습니다.")
            blocks.append({"type": "insight", "tone": "warn", "title": "분류체계 안내", "items": items})

        # 소수 유형은 프로필 지정에 따라 '기타'로 묶는다 (6월 보고서와 동일한 표 구성)
        other = [k for k in (self.p.get("type_group_other") or []) if k in types]
        main_keys = [k for k in keys if k not in other]
        narr = self.slide_narr("type")
        notes = narr.get("type_notes") or {}
        pills = narr.get("type_pills") or {}
        watch_by_parent = {}
        for w in d.get("watch_metrics") or []:
            watch_by_parent.setdefault(w.get("parent") or self.p_parent(w), []).append(w)

        def cells(cur, get_prev, label, indent=False, note="", pill=None):
            row = [{"v": label, "indent": True} if indent else label]
            for b in self.base:
                v = get_prev(b)
                row.append({"v": f"{v} ({pct(v, b['total'])}%)" if v is not None else "—", "cls": "num"})
            row.append({"v": f"{cur} ({pct(cur, self.total)}%)",
                        "cls": "num" if indent else "num brand"})
            prev_v = get_prev(self.prev) if self.prev else None
            row.append({"v": note, "pill": pill or delta_pill(cur, prev_v)})
            return row

        cols = ["유형"] + self.month_cols() + ["추이"]
        rows = []
        for k in main_keys:
            rows.append(cells(types[k]["count"], lambda b, k=k: (b.get("types") or {}).get(k),
                              k, note=notes.get(k, ""), pill=pills.get(k)))
            for w in watch_by_parent.get(k, []):
                if w["count"]:
                    rows.append(cells(w["count"], lambda b, w=w: (b.get("watch") or {}).get(w["label"]),
                                      f"└ {w['label']}", indent=True,
                                      note=notes.get(w["label"], ""), pill=pills.get(w["label"])))
        if other:
            osum = sum(types[k]["count"] for k in other)
            rows.append(cells(osum,
                              lambda b: (sum((b.get("types") or {}).get(k, 0) for k in other) or None),
                              f"기타 ({'·'.join(other)})", note=notes.get("기타", ""), pill=pills.get("기타")))
        blocks.append({"type": "table", "columns": cols, "rows": rows,
                       "total": ["합계"] + [{"v": b["total"], "cls": "num"} for b in self.base]
                       + [{"v": self.total, "cls": "num"}, ""]})

        ds = []
        top_keys = keys[:4]
        for i, b in enumerate(self.base):
            ds.append({"label": mlabel(b["month"]), "data": [(b.get("types") or {}).get(k, 0) for k in top_keys],
                       "tone": TONES[max(0, 3 - (len(self.base) - i))]})
        ds.append({"label": self.ml, "data": [types[k]["count"] for k in top_keys], "tone": "current"})
        blocks.append({"type": "charts", "cards": [
            {"title": "주요 유형 추이", "sub": "상위 4개 유형 절대 건수",
             "chart": {"kind": "bar", "labels": top_keys, "datasets": ds}},
            {"title": f"{self.ml} 유형 구성비", "sub": f"{keys[0]} 등 상위 유형 비중" if keys else "",
             "chart": {"kind": "doughnut", "labels": keys, "datasets": [{"data": [types[k]["count"] for k in keys]}]}},
        ]})

        proposed = tax.get("proposed_taxonomy")
        if proposed:
            blocks.append({"type": "table", "heading": "데이터 기반 분류체계 제안",
                           "columns": ["코드", "유형명", "정의", {"label": "해당 건수", "cls": "num"}],
                           "rows": [[t.get("code", ""), t.get("name", ""), t.get("definition", ""),
                                     {"v": types.get(t.get("name"), {}).get("count", 0), "cls": "num brand"}] for t in proposed],
                           "note": "실 데이터에서 도출한 제안입니다. 팀 검토 후 확정하면 다음 달부터 코드 기반으로 집계됩니다."})
        b = self.insight_block("type")
        if b:
            blocks.append(b)
        return {"id": "type", "nav": "유형별 분포·변화", "tag": "04 — 유형별 분석",
                "h2": "유형별 분포 & 전월 비교", "lead": self.slide_narr("type").get("lead", ""), "blocks": blocks}

    # ---------- 05 조직별 ----------
    def s_company(self):
        d = self.s
        orgs = d["organizations"]
        top = list(orgs.items())[:10]
        charts = [{"title": f"{self.org_label} 유입량 ({self.ml}, 상위 {len(top)})", "sub": "원요청 조직 기준",
                   "size": "tall",
                   "chart": {"kind": "bar", "horizontal": True, "labels": [k for k, _ in top],
                             "datasets": [{"label": "건수", "data": [v["count"] for _, v in top], "tone": "brand"}]}}]
        route = d.get("route")
        if route and route.get("received_total"):
            charts.append({"title": f"{route['self_org']} 접수 {route['received_total']}건 분해",
                           "sub": "타 조직 대행 vs 순수 내부", "size": "tall",
                           "chart": {"kind": "doughnut", "legend": "bottom",
                                     "labels": [f"대행 {route['proxy_for_others']}", f"내부 {route['pure_internal']}"],
                                     "colors": ["#0248ff", "#94a3b8"],
                                     "datasets": [{"data": [route["proxy_for_others"], route["pure_internal"]]}]}})
        cols = [self.org_label.replace("별", "")] + ([{"label": mlabel(self.prev["month"]), "cls": "num"}] if self.prev else []) \
            + [{"label": self.ml, "cls": "num"}] + ([{"label": "평균 처리", "cls": "num"}] if d.get("duration_overall") else []) + ["주요 특징"]
        notes = self.slide_narr("company").get("org_notes") or {}
        rows = []
        for k, v in top:
            row = [k]
            if self.prev:
                pv = (self.prev.get("organizations") or {}).get(k)
                row.append({"v": pv if pv is not None else "—", "cls": "num"})
            row.append({"v": v["count"], "cls": "num brand"})
            if d.get("duration_overall"):
                row.append({"v": num(self.dur(v.get("duration")), "분"), "cls": "num"})
            row.append(notes.get(k, ""))
            rows.append(row)
        blocks = [{"type": "charts", "cards": charts}, {"type": "table", "columns": cols, "rows": rows}]
        b = self.insight_block("company")
        if b:
            blocks.append(b)
        return {"id": "company", "nav": f"{self.org_label} 유입량", "tag": f"05 — {self.org_label} 분석",
                "h2": f"{self.org_label} 유입량 & 변화", "lead": self.slide_narr("company").get("lead", ""), "blocks": blocks}

    # ---------- 06 담당자별 ----------
    def s_assignee(self):
        d = self.s
        asg = d["assignees"]
        cols = ["담당자"] + ([{"label": mlabel(self.prev["month"]), "cls": "num"}] if self.prev else []) \
            + [{"label": self.ml, "cls": "num"}, {"label": "비중", "cls": "num"}] \
            + ([{"label": "평균", "cls": "num"}, {"label": "중앙값", "cls": "num"}] if d.get("duration_overall") else [])
        rows = []
        for k, v in asg.items():
            row = [k]
            if self.prev:
                pv = (self.prev.get("assignees") or {}).get(k)
                row.append({"v": pv if pv is not None else "—", "cls": "num"})
            row += [{"v": v["count"], "cls": "num brand"}, {"v": f"{pct(v['count'], self.total)}%", "cls": "num"}]
            if d.get("duration_overall"):
                row += [{"v": num(self.dur(v.get("duration")), "분"), "cls": "num"},
                        {"v": num(self.dur(v.get("duration"), "median"), "분"), "cls": "num"}]
            rows.append(row)
        total = ["합계"] + ([{"v": self.prev["total"], "cls": "num"}] if self.prev else []) \
            + [{"v": self.total, "cls": "num"}, {"v": "100%", "cls": "num"}]
        if d.get("duration_overall"):
            total += [{"v": num(d["duration_overall"]["mean"], "분"), "cls": "num"},
                      {"v": num(d["duration_overall"]["median"], "분"), "cls": "num"}]

        blocks = [
            {"type": "table", "columns": cols, "rows": rows, "total": total,
             "note": ("평균은 장기 과제 몇 건에 크게 흔들립니다. 담당자 비교는 중앙값이 더 정확합니다."
                      if d.get("duration_overall") else "")},
            {"type": "charts", "cards": [{"title": f"담당자별 처리 비중 ({self.ml})",
                                          "sub": f"상위 2인 합산 {pct(sum(v['count'] for v in list(asg.values())[:2]), self.total)}%",
                                          "chart": {"kind": "doughnut",
                                                    "labels": [f"{k} {v['count']}" for k, v in asg.items()],
                                                    "datasets": [{"data": [v["count"] for v in asg.values()]}]}}]},
        ]
        absence = self.slide_narr("assignee").get("absence")
        if absence:
            blocks.append({"type": "table", "heading": f"{self.ml} 담당자 부재 일정 — 배경 참고",
                           "columns": ["담당자", "부재 일정", {"label": "영향 영업일", "cls": "num"}],
                           "rows": absence})
        b = self.insight_block("assignee")
        if b:
            blocks.append(b)
        return {"id": "assignee", "nav": "담당자별 처리 현황", "tag": "06 — 담당자별 처리 현황",
                "h2": "담당자별 처리 건수 & 부재 영향", "lead": self.slide_narr("assignee").get("lead", ""), "blocks": blocks}

    # ---------- 07 요청자 집중도 ----------
    def s_requester(self):
        conc = self.s.get("requester_concentration") or {}
        if not conc:
            return None
        kpis = []
        for name, c in conc.items():
            kpis.append({"label": f"{name} 고유 요청자", "value": c["unique_requesters"], "unit": "명",
                         "sub": f"{c['handled']}건 · 상위 5 {c['top5_share_pct']}%"})
        if conc:
            first = next(iter(conc.values()))
            if first["top5"]:
                kpis.append({"label": "최다 요청자", "value": first["top5"][0]["count"], "unit": "건",
                             "sub": first["top5"][0]["requester"]})
            kpis.append({"label": "요청자당 평균", "value": " / ".join(str(c["per_requester"]) for c in conc.values()),
                         "sub": " / ".join(conc.keys()) + " (건/명)"})
        rows = [[name, {"v": c["handled"], "cls": "num"}, {"v": c["unique_requesters"], "cls": "num"},
                 {"v": f"{c['per_requester']}건", "cls": "num"}, {"v": f"{c['top5_share_pct']}%", "cls": "num"},
                 ", ".join(f"{t['requester']} {t['count']}" for t in c["top5"][:3])]
                for name, c in conc.items()]
        basis = next(iter(conc.values()))["basis"]
        blocks = [
            {"type": "kpi", "items": kpis[:4]},
            {"type": "table",
             "columns": ["담당자", {"label": "처리 건수", "cls": "num"}, {"label": "고유 요청자", "cls": "num"},
                         {"label": "요청자당", "cls": "num"}, {"label": "상위 5 비중", "cls": "num"}, "상위 요청자"],
             "rows": rows, "note": f"집계 단위: {basis}"},
        ]
        b = self.insight_block("requester")
        if b:
            blocks.append(b)
        return {"id": "requester", "nav": "요청자 집중도", "tag": "07 — 요청자 집중도",
                "h2": "담당자별 요청자 분산도", "lead": self.slide_narr("requester").get("lead", ""), "blocks": blocks}

    # ---------- 08 피크 패턴 ----------
    def s_peak(self):
        d = self.s
        cal = d["calendar"]
        wd, wc = cal["weekday"], cal.get("weekday_count") or {}
        busiest = max(wd, key=wd.get) if wd else None
        quietest = min(wd, key=wd.get) if wd else None
        peak = cal["peak_days"][0] if cal["peak_days"] else None
        kpis = []
        if peak:
            dt = datetime.strptime(peak["date"], "%Y-%m-%d")
            kpis.append({"label": f"{self.ml} 최고 피크일", "value": peak["count"], "unit": "건", "tone": "brand",
                         "sub": f"{dt.month}월 {dt.day}일 ({'월화수목금토일'[dt.weekday()]})"})
        if busiest:
            kpis.append({"label": "가장 바쁜 요일", "value": busiest, "unit": "요일",
                         "sub": f"{wd[busiest]}건 ({pct(wd[busiest], self.total)}% / 평균 {cal['weekday_avg'].get(busiest, '—')}건/일)"})
        if quietest:
            kpis.append({"label": "가장 적은 요일", "value": quietest, "unit": "요일",
                         "sub": f"{wd[quietest]}건 ({pct(wd[quietest], self.total)}% / 평균 {cal['weekday_avg'].get(quietest, '—')}건/일)"})
        kpis.append({"label": "실운영일", "value": cal["working_days"], "unit": "일",
                     "sub": f"평일 {cal['calendar_weekdays']}일 − 공휴일 {len(cal.get('holidays') or [])}일", "tone": "warn"})

        hourly = d["hourly"]
        hvals = list(hourly.values())
        hi = sorted(range(len(hvals)), key=lambda i: -hvals[i])[:2]
        blocks = [
            {"type": "kpi", "items": kpis[:4]},
            {"type": "charts", "cards": [
                {"title": f"요일별 건수 ({self.ml})",
                 "sub": " · ".join(f"{k} {wc.get(k, 0)}일" for k in wd) if wc else "",
                 "chart": {"kind": "bar", "labels": list(wd.keys()),
                           "highlight": [list(wd.keys()).index(busiest)] if busiest else [],
                           "datasets": [{"label": "건수", "data": list(wd.values()), "tone": "muted"}]}},
                {"title": f"시간대별 유입 ({d['meta']['flags']['hourly_basis']}, KST)",
                 "sub": "출근 직후·점심 직후 피크 확인",
                 "chart": {"kind": "bar", "labels": list(hourly.keys()), "highlight": hi,
                           "datasets": [{"label": "건수", "data": hvals, "tone": "muted"}]}},
            ]},
        ]
        callouts = self.slide_narr("peak").get("callouts")
        if callouts:
            blocks.append({"type": "callouts", "items": callouts})
        b = self.insight_block("peak")
        if b:
            blocks.append(b)
        return {"id": "peak", "nav": "피크 패턴 분석", "tag": "08 — 피크 패턴 분석",
                "h2": "요일·시간대·피크일 패턴", "lead": self.slide_narr("peak").get("lead", ""), "blocks": blocks}

    # ---------- 09 종합 시사점 ----------
    def s_takeaway(self):
        blocks = []
        cards = self.n.get("takeaways") or []
        if cards:
            blocks.append({"type": "takeaway", "cards": cards[:3]})
        basis = [f"본 보고서는 <strong>요청일 기준 {self.total}건</strong>으로 집계했습니다."]
        flags = self.s["meta"]["flags"]
        if flags.get("undercount_risk"):
            basis.append(f"<strong>주의</strong> — {flags['undercount_risk']}")
        if flags.get("duration_warning"):
            basis.append(f"<strong>처리시간 미산출</strong> — {flags['duration_warning']}")
        else:
            basis.append("처리시간은 담당자 처리 시작~완료 시각 기준이며, 모든 지표는 한국 표준시(KST)로 산정했습니다.")
        tax = self.s["meta"]["taxonomy"]
        if tax["mode"] != "coded":
            basis.append(f"유형 분류는 코드 {tax['coverage_pct']}% + 원문 추정 {tax['inferred_rows']}건을 합산한 참고치입니다.")
        basis += self.n.get("basis_notes") or []
        blocks.append({"type": "insight", "title": "집계 기준 안내", "items": basis})
        watch = self.n.get("next_month_watch") or []
        if watch:
            blocks.append({"type": "insight", "tone": "warn", "title": "다음 달 확인 포인트", "items": watch})
        return {"id": "takeaway", "nav": "종합 시사점", "tag": "09 — 종합 시사점", "h2": "종합 시사점",
                "lead": self.n.get("takeaway_lead", f"{self.ml} 데이터에서 확인된 주요 현상과 대응 방향입니다."),
                "blocks": blocks}

    def build(self):
        meta = self.s["meta"]
        slides = [self.s_summary(), self.s_trend(), self.s_channel(), self.s_type(),
                  self.s_company(), self.s_assignee(), self.s_requester(), self.s_peak(), self.s_takeaway()]
        title = f"{self.p.get('report_title', '운영 현황 보고')} — {self.month[:4]}년 {int(self.month[5:7])}월 보고"
        return {
            "meta": {"org": meta.get("org"), "team": meta.get("team"), "title": title,
                     "nav_title": f"{self.p.get('short_title', '운영 보고')} {self.ml}",
                     "period": f"{self.month.replace('-', '.')}", "total": self.total, "basis": "요청일 기준",
                     "filename": f"{self.p.get('short_title', '운영 보고')} {self.ml} 보고서"
                                 f"({self.authored.replace('20', '', 1) if self.authored.startswith('20') else self.authored}).html"},
            "cover": self.cover(),
            "slides": [s for s in slides if s],
            "footer": f"{self.ml} 운영 보고 · {meta.get('org') or ''} {meta.get('team') or ''} · {self.authored} · 총 {self.total}건",
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stats")
    ap.add_argument("narrative")
    ap.add_argument("--profile")
    ap.add_argument("--baselines")
    ap.add_argument("--authored", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    stats = load_json(args.stats)
    narrative = load_json(args.narrative) or {}
    src = (stats.get("meta") or {}).get("source_file") or args.stats

    ppath, phow = find_config("profile", src, args.profile)
    bpath, bhow = find_config("baselines", src, args.baselines)
    profile = load_json(ppath) or {}
    baselines = load_json(bpath) or {}
    print(f"프로필:     {ppath or '없음 (기본값)'} ({phow})", file=sys.stderr)
    n_months = len(baselines.get("months") or [])
    print(f"베이스라인: {bpath or '없음 (첫 보고서로 생성)'} ({bhow}, {n_months}개월)", file=sys.stderr)

    authored = args.authored or datetime.now().strftime("%Y.%m.%d")
    report = Composer(stats, narrative, profile, baselines, authored).build()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"조립 완료: {args.out} (슬라이드 {len(report['slides']) + 1}장, 총 {report['meta']['total']}건)")


if __name__ == "__main__":
    main()
