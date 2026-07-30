#!/usr/bin/env python3
"""report.json(수치+서술) + renderer.html → 최종 보고서 HTML.

사용법:
    python3 build_report.py <report.json> --out "Ops Logger 7월 보고서(26.08.03).html" [--stats stats.json]

에이전트는 report.json만 작성한다. HTML을 직접 편집하지 않는다.
빌드 시 구조·정합성을 자동 검증하고, 문제가 있으면 종료 코드 1로 실패시킨다.
"""
import argparse
import json
import os
import sys

BLOCK_TYPES = {"kpi", "compare", "table", "charts", "insight", "callouts", "takeaway", "heading", "note", "html"}


def validate(report, stats=None):
    errors, warnings = [], []
    meta = report.get("meta") or {}
    if not meta.get("title"):
        errors.append("meta.title이 없습니다.")

    if stats:
        if meta.get("total") is not None and int(meta["total"]) != int(stats.get("total", -1)):
            errors.append(
                f"meta.total({meta['total']})이 집계 총건수({stats.get('total')})와 다릅니다."
            )
        flags = (stats.get("meta") or {}).get("flags") or {}
        if not flags.get("duration_available"):
            blob = json.dumps(report, ensure_ascii=False)
            if "처리시간" in blob and "산출 불가" not in blob and "—" not in blob:
                warnings.append(
                    "처리시간을 산출할 수 없는 데이터인데 보고서에 처리시간 서술이 있습니다. 각주를 확인하세요."
                )
        if flags.get("undercount_risk"):
            blob = json.dumps(report, ensure_ascii=False)
            if "누락" not in blob and "과소" not in blob:
                warnings.append("과소집계 위험이 감지됐는데 보고서에 관련 각주가 없습니다.")

    seen_ids = set()
    for si, sl in enumerate(report.get("slides") or []):
        sid = sl.get("id")
        if not sid:
            errors.append(f"slides[{si}]에 id가 없습니다.")
        elif sid in seen_ids:
            errors.append(f"슬라이드 id 중복: {sid}")
        else:
            seen_ids.add(sid)

        for bi, b in enumerate(sl.get("blocks") or []):
            where = f"slides[{si}:{sid}].blocks[{bi}]"
            btype = b.get("type")
            if btype not in BLOCK_TYPES:
                errors.append(f"{where}: 알 수 없는 블록 타입 '{btype}'")
                continue
            if btype == "table":
                cols = len(b.get("columns") or [])
                for ri, row in enumerate(b.get("rows") or []):
                    if len(row) != cols:
                        errors.append(f"{where}.rows[{ri}]: 셀 {len(row)}개 (헤더 {cols}개와 불일치)")
                if b.get("total") and len(b["total"]) != cols:
                    errors.append(f"{where}.total: 셀 {len(b['total'])}개 (헤더 {cols}개와 불일치)")
            if btype == "charts":
                for ci, card in enumerate(b.get("cards") or []):
                    ch = card.get("chart") or {}
                    labels = ch.get("labels") or []
                    for di, ds in enumerate(ch.get("datasets") or []):
                        if len(ds.get("data") or []) != len(labels):
                            errors.append(
                                f"{where}.cards[{ci}].chart.datasets[{di}]: "
                                f"데이터 {len(ds.get('data') or [])}개 ≠ 라벨 {len(labels)}개"
                            )
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--out", help="생략하면 보고서 제목·작성일로 자동 명명")
    ap.add_argument("--stats")
    ap.add_argument("--renderer")
    ap.add_argument("--skip-validation", action="store_true")
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    stats = None
    if args.stats:
        with open(args.stats, encoding="utf-8") as f:
            stats = json.load(f)

    if not args.skip_validation:
        errors, warnings = validate(report, stats)
        for w in warnings:
            print(f"[경고] {w}", file=sys.stderr)
        if errors:
            print("[실패] 보고서 정합성 오류:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)

    renderer = args.renderer or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "renderer.html")
    with open(renderer, encoding="utf-8") as f:
        html = f.read()

    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    meta = report.get("meta") or {}
    title = meta.get("title", "운영 보고서")
    html = html.replace("__REPORT_JSON__", payload).replace("__REPORT_TITLE__", title)

    out = args.out or meta.get("filename") or "운영 보고서.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    slides = len(report.get("slides") or []) + (1 if report.get("cover") else 0)
    print(f"생성 완료: {out} (슬라이드 {slides}장, 총 {meta.get('total')}건)")


if __name__ == "__main__":
    main()
