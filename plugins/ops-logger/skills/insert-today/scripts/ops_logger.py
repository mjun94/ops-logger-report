#!/usr/bin/env python3
"""Ops Logger 등록 보조 스크립트 (표준 라이브러리만 사용).

  ops_logger.py --email me@vntgcorp.com list-today [--date YYYY-MM-DD]
  ops_logger.py --email me@vntgcorp.com member <이메일|이름>
  ops_logger.py --email me@vntgcorp.com me
  ops_logger.py --email me@vntgcorp.com validate <items.json>
  ops_logger.py --email me@vntgcorp.com insert <items.json> [--yes]
  ops_logger.py --email me@vntgcorp.com delete <id>

items.json = [{channel,date,processStartAt,processEndAt,summary,raw_input,
               l1_code,l2_code,l3_code,requester_email?,requester_*...}, ...]
requester_email이 있으면 멤버 검색으로 requester_* 를 채운다. assignee_* 는 실행자 본인으로 채운다.
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request, datetime

BASE = os.environ.get("OPS_LOGGER_BASE", "https://api-seahworks.seah.co.kr/api")
HERE = os.path.dirname(os.path.abspath(__file__))
CONF_DIR = os.path.expanduser("~/.ops-logger")
_team_tax = os.path.join(CONF_DIR, "taxonomy.json")
TAX_PATH = os.environ.get("OPS_LOGGER_TAXONOMY") or (_team_tax if os.path.exists(_team_tax) else os.path.join(HERE, "..", "references", "taxonomy.json"))

def config_email():
    try:
        return json.load(open(os.path.join(CONF_DIR, "config.json"), encoding="utf-8")).get("email", "")
    except Exception:
        return ""
DURATIONS = {5,10,15,20,25,30,35,40,45,50,55,60,90,120}
GROUP_DOMAINS = ("vntgcorp.com", "seah.co.kr")

def api(email, method, path, params=None, body=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "X-AUTH-EMAIL": email, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {path}: 인증 이메일({email})이 그룹웨어 계정인지 확인. 서버 응답 {e.read().decode()[:200]}")
    if res.get("code") != "CD_SUCCESS":
        raise SystemExit(f"API 오류 {res.get('code')}: {res.get('message')}")
    return res.get("data")

def load_tax():
    items = json.load(open(TAX_PATH, encoding="utf-8"))["items"]
    return {i["code"]: i for i in items}

def validate_codes(tax, it):
    errs = []
    l1, l2, l3 = it.get("l1_code"), it.get("l2_code"), it.get("l3_code")
    for lvl, code in ((1,l1),(2,l2),(3,l3)):
        if code is None or code == "": continue
        t = tax.get(code)
        if not t: errs.append(f"코드 없음: {code}"); continue
        if t["level"] != lvl: errs.append(f"레벨 불일치: {code}")
        if not t["is_active"]: errs.append(f"폐지 코드: {code}")
    if l2 and l1 and tax.get(l2, {}).get("parent_code") != l1: errs.append(f"l2 {l2}의 상위가 l1 {l1}이 아님")
    if l3 and l2 and tax.get(l3, {}).get("parent_code") != l2: errs.append(f"l3 {l3}의 상위가 l2 {l2}가 아님")
    if l2 and not l3:
        has_child = any(v["parent_code"] == l2 and v["is_active"] for v in tax.values())
        if has_child: errs.append(f"{l2}는 L3가 있으므로 l3_code 필수 (규칙 11)")
    return errs

def validate_item(tax, it):
    errs = validate_codes(tax, it)
    if it.get("channel") not in ("chat","email","phone","face"): errs.append("channel은 chat/email/phone/face")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", it.get("date","")): errs.append("date는 YYYY-MM-DD")
    for k in ("processStartAt","processEndAt"):
        v = it.get(k)
        if v and not re.fullmatch(r"\d{2}:\d{2}", v): errs.append(f"{k}는 HH:mm")
    if it.get("processStartAt") and it.get("processEndAt"):
        s = datetime.datetime.strptime(it["processStartAt"], "%H:%M"); e = datetime.datetime.strptime(it["processEndAt"], "%H:%M")
        if e < s: errs.append("종료가 시작보다 이름")
    if not it.get("summary"): errs.append("summary 비어 있음")
    if len(it.get("summary","")) > 40: errs.append("summary 40자 초과")
    for k in ("raw_input","summary"):
        if re.search(r"01[016789]-?\d{3,4}-?\d{4}", it.get(k,"") or ""): errs.append(f"{k}에 전화번호 노출 → [연락처]로 치환")
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", it.get(k,"") or ""): errs.append(f"{k}에 이메일 노출 → [연락처]로 치환")
    return errs

def mask(text):
    text = re.sub(r"01[016789]-?\d{3,4}-?\d{4}", "[연락처]", text or "")
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[연락처]", text)

def member(email, q):
    data = api(email, "GET", "/org/topMenu/search/members", {"search_txt": q, "integrated_yn": "Y"}) or []
    if isinstance(data, dict): data = data.get("list", [])
    exact = [m for m in data if (m.get("email") or "").lower() == q.lower()]
    return (exact or data)[:5]

def requester_fields(email, req_email):
    ms = member(email, req_email)
    if ms and (ms[0].get("email") or "").lower() == req_email.lower():
        m = ms[0]
        return {"requester_name": m.get("name",""), "requester_company": m.get("rep_org_name",""),
                "original_requester_company": m.get("rep_org_name",""), "requester_dept": m.get("org_name",""),
                "requester_grade": m.get("job_duty_name",""), "requester_position": m.get("job_position_name",""),
                "requester_contact": "", "mem_type": m.get("mem_type") or "n01"}
    domain = req_email.split("@")[-1]
    return {"requester_name": req_email.split("@")[0], "requester_company": domain, "original_requester_company": domain,
            "requester_dept": "", "requester_grade": "", "requester_position": "", "requester_contact": "", "mem_type": "n03"}

def assignee_fields(email):
    ms = member(email, email)
    if not ms: raise SystemExit("실행자 멤버 조회 실패")
    m = ms[0]
    return {"assignee_name": m.get("name",""), "assignee_dept": m.get("org_name",""), "assignee_company": m.get("rep_org_name","")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=os.environ.get("OPS_LOGGER_EMAIL") or config_email(), help="실행자 그룹웨어 이메일 (X-AUTH-EMAIL). 기본: ~/.ops-logger/config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list-today"); p.add_argument("--date", default=datetime.date.today().isoformat())
    p = sub.add_parser("member"); p.add_argument("query")
    sub.add_parser("me")
    p = sub.add_parser("validate"); p.add_argument("file")
    p = sub.add_parser("insert"); p.add_argument("file"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("delete"); p.add_argument("id")
    a = ap.parse_args()
    if not a.email:
        import subprocess
        try: a.email = subprocess.run(["gcloud","config","get-value","account"], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception: a.email = ""
    if not a.email or not a.email.lower().endswith(GROUP_DOMAINS): raise SystemExit(f"그룹웨어 계정(@vntgcorp.com/@seah.co.kr)이 필요합니다. /ops-logger:setup 으로 저장하거나 --email 지정 (현재: {a.email or '없음'})")

    if a.cmd == "list-today":
        d = api(a.email, "GET", "/admin/vos/sr/list", {"requested_at": a.date, "count": 100, "offset": 0}) or {}
        rows = d.get("list", [])
        print(json.dumps({"date": a.date, "count": d.get("tot_count", len(rows)),
            "rows": [{k: r.get(k) for k in ("id","channel_code","requester_name","requester_company","summary","started_at","completed_at","l3_code","assignee_name")} for r in rows]}, ensure_ascii=False, indent=1))
    elif a.cmd == "member":
        print(json.dumps([{k: m.get(k) for k in ("name","email","rep_org_name","org_name","job_duty_name","job_position_name","mem_type")} for m in member(a.email, a.query)], ensure_ascii=False, indent=1))
    elif a.cmd == "me":
        print(json.dumps(assignee_fields(a.email), ensure_ascii=False, indent=1))
    elif a.cmd in ("validate", "insert"):
        tax = load_tax(); items = json.load(open(a.file, encoding="utf-8"))
        asg = assignee_fields(a.email) if a.cmd == "insert" else {}
        ok = True; prepared = []
        for i, it in enumerate(items, 1):
            it = dict(it)
            it["raw_input"] = mask(it.get("raw_input","")); it["summary"] = mask(it.get("summary",""))
            if it.get("requester_email") and not it.get("requester_name"):
                it.update(requester_fields(a.email, it["requester_email"]))
            it.pop("requester_email", None)
            errs = validate_item(tax, it)
            tag = f"[{i}] {it.get('summary','')}"
            if errs: ok = False; print(f"✗ {tag}: " + "; ".join(errs))
            else: print(f"✓ {tag} → {it.get('l1_code')}/{it.get('l2_code')}/{it.get('l3_code')} {it.get('channel')} {it.get('date')} {it.get('processStartAt')}-{it.get('processEndAt')} 요청자 {it.get('requester_name')}({it.get('requester_company')})")
            it.update(asg); prepared.append(it)
        if a.cmd == "validate" or not ok:
            sys.exit(0 if ok else 1)
        if not a.yes:
            print("--yes 없이 실행됨: 등록하지 않음"); sys.exit(0)
        before = (api(a.email, "GET", "/admin/vos/sr/list", {"requested_at": prepared[0]["date"], "count": 1, "offset": 0}) or {}).get("tot_count", 0)
        for it in prepared:
            api(a.email, "PUT", "/admin/vos/sr/info", body=it); print(f"등록: {it['summary']}")
        after = (api(a.email, "GET", "/admin/vos/sr/list", {"requested_at": prepared[0]["date"], "count": 1, "offset": 0}) or {}).get("tot_count", 0)
        print(f"당일 건수 {before} → {after} (+{after-before}, 요청 {len(prepared)})")
    elif a.cmd == "delete":
        api(a.email, "DELETE", "/admin/vos/sr/info", {"id": a.id}); print("삭제:", a.id)

if __name__ == "__main__":
    main()
