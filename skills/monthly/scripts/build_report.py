#!/usr/bin/env python3
"""report.json(수치+서술) + renderer.html → 최종 보고서 HTML.

사용법:
    python3 build_report.py <report.json> [--stats stats.json] [--out <경로>]

--out을 생략하면 compose.py가 report.json의 meta.output_path에 넣어 둔
<팀 루트>/report/<대상연도>/<파일명>.html 로 쓴다. 없는 폴더는 만든다.

에이전트는 report.json만 작성한다. HTML을 직접 편집하지 않는다.
빌드 시 구조·정합성을 자동 검증하고, 문제가 있으면 종료 코드 1로 실패시킨다.
"""
import argparse
import json
import os
import re
import sys

BLOCK_TYPES = {"kpi", "compare", "table", "charts", "insight", "callouts", "takeaway", "heading", "note", "html"}

# 보고서는 명사형 종결(보고서체)로 쓴다. ~습니다/~합니다체가 남았는지 잡는다.
PROSE_END = re.compile(r"(니다|하세요|해요)[.!?)\s]*$")
# 사람이 읽는 산문이 담기는 키. 라벨·수치·id는 검사하지 않는다.
PROSE_KEYS = {"lead", "subtitle", "body", "note", "text"}
# lead는 한 문장이 원칙. HTML 제거 후 이 길이를 넘으면 해석이 섞였다는 신호다.
LEAD_MAX = 140


def _plain(s):
    """HTML 태그를 벗긴 순수 텍스트."""
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _prose_strings(node, path, out):
    """report.json에서 사람이 읽는 문장만 (경로, 값)으로 모은다."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            if isinstance(v, str):
                if k in PROSE_KEYS:
                    out.append((p, v))
            elif k == "items" and isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, str):
                        out.append((f"{p}[{i}]", item))
                    else:
                        _prose_strings(item, f"{p}[{i}]", out)
            else:
                _prose_strings(v, p, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _prose_strings(v, f"{path}[{i}]", out)


def check_tone(report):
    """문체·lead 길이 경고. 빌드를 막지는 않는다 — 문장 판단은 사람과 critic의 몫."""
    warnings = []
    found = []
    _prose_strings(report, "", found)
    prose = [(p, _plain(s)) for p, s in found if _plain(s)]

    bad = [(p, t) for p, t in prose if PROSE_END.search(t)]
    if bad:
        warnings.append(
            f"보고서체(명사형 종결)가 아닌 문장 {len(bad)}개 — "
            + "; ".join(f"{p}: \"{t[:40]}…\"" for p, t in bad[:3])
            + (f" (외 {len(bad) - 3}개)" if len(bad) > 3 else "")
        )
    long_leads = [(p, t) for p, t in prose
                  if p.endswith(".lead") and len(t) > LEAD_MAX]
    if long_leads:
        warnings.append(
            f"lead가 {LEAD_MAX}자를 넘습니다 ({len(long_leads)}개) — 해석은 insights로 옮기세요: "
            + "; ".join(f"{p}({len(t)}자)" for p, t in long_leads)
        )
    return warnings


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
    warnings += check_tone(report)
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

    # 경로 우선순위: 직접 지정 → compose.py가 정한 report/<연도>/ 경로 → 파일명만
    out = args.out or meta.get("output_path") or meta.get("filename") or "운영 보고서.html"
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    slides = len(report.get("slides") or []) + (1 if report.get("cover") else 0)
    print(f"생성 완료: {out} (슬라이드 {slides}장, 총 {meta.get('total')}건)")


if __name__ == "__main__":
    main()
