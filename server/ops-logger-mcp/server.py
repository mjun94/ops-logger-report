"""Ops Logger MCP 서버 (claude.ai 커스텀 커넥터용).

로그인: Google 계정 OAuth. claude.ai가 받은 Google 액세스 토큰을 Bearer로 보내면
tokeninfo로 검증하고, 그 이메일을 그대로 Ops Logger API의 X-AUTH-EMAIL로 쓴다.
plugins/ops-logger/skills/insert-today/scripts/ops_logger.py 와 같은 도구를 MCP로 제공한다.

환경변수
  ALLOWED_CLIENT_IDS  토큰 aud로 허용할 OAuth 클라이언트 ID (쉼표 구분, 필수)
  ALLOWED_DOMAINS     허용 이메일 도메인 (기본 vntgcorp.com,seah.co.kr)
  ALLOWED_EMAILS      있으면 이 이메일만 허용 (쉼표 구분)
  OPS_LOGGER_BASE     기본 https://api-seahworks.seah.co.kr/api
  MEMORY_BUCKET       요청회사 기억 저장 GCS 버킷 (없으면 기억 기능 끔)
"""
import datetime, hashlib, json, logging, os, re, time
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

log = logging.getLogger("ops-logger-mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE = os.environ.get("OPS_LOGGER_BASE", "https://api-seahworks.seah.co.kr/api")
ALLOWED_CLIENT_IDS = {c.strip() for c in os.environ.get("ALLOWED_CLIENT_IDS", "").split(",") if c.strip()}
ALLOWED_DOMAINS = tuple(d.strip().lower() for d in os.environ.get("ALLOWED_DOMAINS", "vntgcorp.com,seah.co.kr").split(",") if d.strip())
ALLOWED_EMAILS = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
MEMORY_BUCKET = os.environ.get("MEMORY_BUCKET", "")
HERE = os.path.dirname(os.path.abspath(__file__))
TAX = {i["code"]: i for i in json.load(open(os.path.join(HERE, "taxonomy.json"), encoding="utf-8"))["items"]}

VNTG_COMPANY = "브이엔티지"
EXTERNAL_NAME = "외부"
GROUP_DOMAINS = ("vntgcorp.com", "seah.co.kr")


# ---------- 인증 ----------
class AuthError(Exception):
    pass

_token_cache: dict[str, tuple[float, str]] = {}

async def verify_google_token(token: str) -> str:
    """Google 액세스 토큰 → 이메일. aud·도메인·검증 여부를 확인한다."""
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _token_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": token})
    if r.status_code != 200:
        raise AuthError("invalid_token")
    info = r.json()
    email = (info.get("email") or "").lower()
    if info.get("aud") not in ALLOWED_CLIENT_IDS:
        raise AuthError("invalid_token: audience")
    if not email or info.get("email_verified") not in ("true", True):
        raise AuthError("invalid_token: email")
    if not email.endswith(tuple("@" + d for d in ALLOWED_DOMAINS)):
        raise AuthError("forbidden: domain")
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        raise AuthError("forbidden: email")
    ttl = min(int(info.get("expires_in", 300)), 3600)
    _token_cache[key] = (time.time() + ttl - 30, email)
    return email


def _base_url(scope) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    proto = headers.get("x-forwarded-proto", scope.get("scheme", "https"))
    host = headers.get("x-forwarded-host") or headers.get("host", "localhost")
    return f"{proto}://{host}"


class GoogleBearerAuth:
    """/mcp 아래 요청에 Bearer 토큰을 요구하는 ASGI 미들웨어. 검증된 이메일을 scope['ops_email']에 넣는다."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        try:
            if not auth.lower().startswith("bearer "):
                raise AuthError("missing_token")
            scope["ops_email"] = await verify_google_token(auth[7:].strip())
        except AuthError as e:
            meta = f'{_base_url(scope)}/.well-known/oauth-protected-resource'
            status = 403 if str(e).startswith("forbidden") else 401
            resp = JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=status,
                                headers={"WWW-Authenticate": f'Bearer realm="ops-logger", resource_metadata="{meta}"'})
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


def protected_resource(request):
    base = _base_url(request.scope)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": ["https://accounts.google.com/"],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["openid", "https://www.googleapis.com/auth/userinfo.email"],
    })


# ---------- Ops Logger API ----------
class ApiError(Exception):
    pass

async def api(email: str, method: str, path: str, params=None, body=None):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, BASE + path, params=params, json=body,
                            headers={"X-AUTH-EMAIL": email, "Accept": "application/json"})
    if r.status_code >= 400:
        raise ApiError(f"HTTP {r.status_code} {path}: {email} 계정이 그룹웨어 관리자인지 확인. 응답 {r.text[:200]}")
    res = r.json()
    if res.get("code") != "CD_SUCCESS":
        raise ApiError(f"API 오류 {res.get('code')}: {res.get('message')}")
    return res.get("data")


_companies_cache: list[str] | None = None

async def company_list(email: str) -> list[str]:
    global _companies_cache
    if _companies_cache is None:
        data = await api(email, "GET", "/org/list", {"lvl": 3}) or []
        if isinstance(data, dict):
            data = data.get("list", [])
        _companies_cache = [o.get("org_name") for o in data if o.get("org_type") == "C" and o.get("org_name")]
    return list(_companies_cache)


async def member_search(email: str, q: str):
    data = await api(email, "GET", "/org/topMenu/search/members", {"search_txt": q, "integrated_yn": "Y"}) or []
    if isinstance(data, dict):
        data = data.get("list", [])
    exact = [m for m in data if (m.get("email") or "").lower() == q.lower()]
    return (exact or data)[:5]


async def requester_fields(email, req_email, original_company=None, external_company=None):
    ms = await member_search(email, req_email)
    if ms and (ms[0].get("email") or "").lower() == req_email.lower():
        m = ms[0]; comp = m.get("rep_org_name", "")
        return {"requester_name": m.get("name", ""), "requester_company": comp,
                "original_requester_company": (original_company or "").strip() if comp == VNTG_COMPANY else comp,
                "requester_dept": m.get("org_name", ""),
                "requester_grade": m.get("job_duty_name", ""), "requester_position": m.get("job_position_name", ""),
                "requester_contact": "", "mem_type": m.get("mem_type") or "n01"}
    ext = (external_company or req_email.split("@")[-1]).strip()
    return {"requester_name": EXTERNAL_NAME, "requester_company": ext, "original_requester_company": (original_company or "").strip(),
            "requester_dept": "", "requester_grade": "", "requester_position": "", "requester_contact": "", "mem_type": "n03",
            "request_company": ext, "request_name": EXTERNAL_NAME}


async def assignee_fields(email):
    ms = await member_search(email, email)
    if not ms:
        raise ApiError("실행자 멤버 조회 실패")
    m = ms[0]
    return {"assignee_name": m.get("name", ""), "assignee_dept": m.get("org_name", ""), "assignee_company": m.get("rep_org_name", "")}


def needs_company_check(it):
    return it.get("mem_type") == "n03" or (it.get("requester_company") or "") == VNTG_COMPANY


def mask(text):
    text = re.sub(r"01[016789]-?\d{3,4}-?\d{4}", "[연락처]", text or "")
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[연락처]", text)


def validate_codes(it):
    errs = []
    l1, l2, l3 = it.get("l1_code"), it.get("l2_code"), it.get("l3_code")
    for lvl, code in ((1, l1), (2, l2), (3, l3)):
        if code is None or code == "":
            continue
        t = TAX.get(code)
        if not t:
            errs.append(f"코드 없음: {code}"); continue
        if t["level"] != lvl: errs.append(f"레벨 불일치: {code}")
        if not t["is_active"]: errs.append(f"폐지 코드: {code}")
    if l2 and l1 and TAX.get(l2, {}).get("parent_code") != l1: errs.append(f"l2 {l2}의 상위가 l1 {l1}이 아님")
    if l3 and l2 and TAX.get(l3, {}).get("parent_code") != l2: errs.append(f"l3 {l3}의 상위가 l2 {l2}가 아님")
    if l2 and not l3 and any(v["parent_code"] == l2 and v["is_active"] for v in TAX.values()):
        errs.append(f"{l2}는 L3가 있으므로 l3_code 필수 (규칙 11)")
    return errs


async def validate_item(email, it):
    errs = validate_codes(it)
    if needs_company_check(it):
        oc = (it.get("original_requester_company") or "").strip()
        who = "외부 요청자" if it.get("mem_type") == "n03" else "브이엔티지 소속 요청자"
        if not oc: errs.append(f"{who}는 요청회사(original_requester_company) 필수 — 사용자에게 확인")
        elif oc not in await company_list(email): errs.append(f"요청회사 '{oc}'가 계열사 목록에 없음 (companies 로 확인)")
    if it.get("channel") not in ("chat", "email", "phone", "face"): errs.append("channel은 chat/email/phone/face")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", it.get("date", "")): errs.append("date는 YYYY-MM-DD")
    for k in ("processStartAt", "processEndAt"):
        v = it.get(k)
        if v and not re.fullmatch(r"\d{2}:\d{2}", v): errs.append(f"{k}는 HH:mm")
    if it.get("processStartAt") and it.get("processEndAt") and re.fullmatch(r"\d{2}:\d{2}", it["processStartAt"]) and re.fullmatch(r"\d{2}:\d{2}", it["processEndAt"]):
        if it["processEndAt"] < it["processStartAt"]: errs.append("종료가 시작보다 이름")
    if not it.get("summary"): errs.append("summary 비어 있음")
    if len(it.get("summary", "")) > 40: errs.append("summary 40자 초과")
    for k in ("raw_input", "summary"):
        if re.search(r"01[016789]-?\d{3,4}-?\d{4}", it.get(k, "") or ""): errs.append(f"{k}에 전화번호 노출 → [연락처]로 치환")
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", it.get(k, "") or ""): errs.append(f"{k}에 이메일 노출 → [연락처]로 치환")
    return errs


async def prepare(email, items):
    """requester_email → 요청자 필드 채우기, 마스킹, 검증. (ok, results, prepared)"""
    ok, results, prepared = True, [], []
    for i, it in enumerate(items, 1):
        it = dict(it)
        it["raw_input"] = mask(it.get("raw_input", "")); it["summary"] = mask(it.get("summary", ""))
        req_email = it.pop("requester_email", None)
        if req_email and not it.get("requester_name"):
            it.update(await requester_fields(email, req_email, it.get("original_requester_company"), it.get("requester_company")))
        errs = await validate_item(email, it)
        if errs: ok = False
        results.append({"n": i, "ok": not errs, "summary": it.get("summary"), "errors": errs,
                        "codes": f"{it.get('l1_code')}/{it.get('l2_code')}/{it.get('l3_code')}",
                        "time": f"{it.get('date')} {it.get('processStartAt')}-{it.get('processEndAt')}",
                        "requester": f"{it.get('requester_name')}({it.get('requester_company')})",
                        "original_requester_company": it.get("original_requester_company")})
        it["_req_email"] = req_email
        prepared.append(it)
    return ok, results, prepared


# ---------- 요청회사 기억 (GCS, 선택) ----------
def _mem_blob(email):
    from google.cloud import storage
    return storage.Client().bucket(MEMORY_BUCKET).blob(f"requester-company/{email}.json")

def load_memory(email) -> dict:
    if not MEMORY_BUCKET:
        return {}
    try:
        return json.loads(_mem_blob(email).download_as_text())
    except Exception:
        return {}

def save_memory(email, mem: dict):
    if not MEMORY_BUCKET:
        return
    try:
        _mem_blob(email).upload_from_string(json.dumps(mem, ensure_ascii=False, indent=1), content_type="application/json")
    except Exception as e:
        log.warning("memory save failed: %s", e)


# ---------- MCP 도구 ----------
mcp = FastMCP("ops-logger", stateless_http=True, json_response=True,
              # Host 헤더 검사(DNS rebinding 보호)는 localhost 전용이라 Cloud Run 도메인에서 421을 낸다. 인증은 Bearer 토큰으로 한다
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
              instructions="Ops Logger(세아웍스 운영 문의 기록) 등록 도구. 로그인한 사용자 본인 계정으로만 동작한다. "
                           "등록 전 반드시 validate_items로 검증하고 사용자 승인을 받은 뒤 insert_items(confirm=true)를 호출한다.")

def who(ctx: Context) -> str:
    req = ctx.request_context.request
    email = req.scope.get("ops_email") if req is not None else None
    if not email:
        raise ApiError("인증된 사용자 없음")
    return email


@mcp.tool()
async def me(ctx: Context) -> dict:
    """로그인한 사용자(담당자) 정보. 이름·부서·회사. 계정이 Ops Logger 관리자가 아니면 오류가 난다."""
    email = who(ctx)
    return {"email": email, **(await assignee_fields(email))}


@mcp.tool()
async def list_sr(ctx: Context, date: str = "") -> dict:
    """지정한 날짜(YYYY-MM-DD, 기본 오늘 KST)에 Ops Logger에 이미 등록된 건 목록. 중복 등록을 피하는 데 쓴다."""
    email = who(ctx)
    if not date:
        date = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    d = await api(email, "GET", "/admin/vos/sr/list", {"requested_at": date, "count": 100, "offset": 0}) or {}
    rows = d.get("list", [])
    return {"date": date, "count": d.get("tot_count", len(rows)),
            "rows": [{k: r.get(k) for k in ("id", "channel_code", "requester_name", "requester_company", "original_requester_company", "summary", "started_at", "completed_at", "l3_code", "assignee_name")} for r in rows]}


@mcp.tool()
async def search_member(ctx: Context, query: str) -> list[dict]:
    """그룹웨어 멤버 검색(이메일 또는 이름). 요청자의 이름·회사·부서·직급·직책·mem_type을 돌려준다. 결과가 없으면 외부 요청자다."""
    email = who(ctx)
    return [{k: m.get(k) for k in ("name", "email", "rep_org_name", "org_name", "job_duty_name", "job_position_name", "mem_type")} for m in await member_search(email, query)]


@mcp.tool()
async def companies(ctx: Context, query: str = "") -> list[str]:
    """계열사(법인) 이름 목록. 요청회사(original_requester_company)에는 이 목록의 이름만 쓸 수 있다. query로 부분 검색."""
    email = who(ctx)
    cs = await company_list(email)
    return [c for c in cs if query.lower() in c.lower()] if query else cs


@mcp.tool()
async def company_hint(ctx: Context, requester_email: str) -> dict:
    """브이엔티지 소속·외부 요청자에 대해 이전에 확정한 요청회사가 있으면 돌려준다. 질문의 첫 번째 선택지로 쓴다."""
    email = who(ctx)
    return {"requester_email": requester_email, "company": load_memory(email).get(requester_email.lower())}


@mcp.tool()
async def validate_items(ctx: Context, items: list[dict[str, Any]]) -> dict:
    """등록 전 검증. items 각 항목: channel(chat/email/phone/face), date(YYYY-MM-DD), processStartAt/processEndAt(HH:mm),
    summary(40자 이내), raw_input(요청자 원문), l1_code/l2_code/l3_code, requester_email,
    original_requester_company(요청회사: 브이엔티지 소속·외부 요청자는 필수), requester_company(외부일 때 회사명).
    요청자 필드를 채우고 연락처를 마스킹한 뒤 오류 목록을 돌려준다. 등록은 하지 않는다."""
    email = who(ctx)
    ok, results, _ = await prepare(email, items)
    return {"ok": ok, "results": results}


@mcp.tool()
async def insert_items(ctx: Context, items: list[dict[str, Any]], confirm: bool = False) -> dict:
    """Ops Logger에 신규 등록. validate_items와 같은 입력. 사용자가 확인 표를 승인한 뒤에만 confirm=true로 호출한다.
    검증 실패 건이 하나라도 있으면 아무것도 등록하지 않는다. 담당자는 로그인한 사용자 본인으로 기록된다."""
    email = who(ctx)
    if not confirm:
        return {"ok": False, "error": "confirm=true 가 필요합니다. 사용자 승인 후 다시 호출하세요."}
    ok, results, prepared = await prepare(email, items)
    if not ok or not prepared:
        return {"ok": False, "inserted": 0, "results": results}
    asg = await assignee_fields(email)
    date = prepared[0]["date"]
    before = ((await api(email, "GET", "/admin/vos/sr/list", {"requested_at": date, "count": 1, "offset": 0})) or {}).get("tot_count", 0)
    mem = load_memory(email); inserted = []
    for it in prepared:
        req_email = it.pop("_req_email", None)
        it.update(asg)
        res = await api(email, "PUT", "/admin/vos/sr/info", body=it)
        inserted.append({"summary": it["summary"], "result": res})
        if req_email and needs_company_check(it) and it.get("original_requester_company"):
            mem[req_email.lower()] = it["original_requester_company"]
    save_memory(email, mem)
    after = ((await api(email, "GET", "/admin/vos/sr/list", {"requested_at": date, "count": 1, "offset": 0})) or {}).get("tot_count", 0)
    return {"ok": True, "inserted": len(inserted), "date": date, "count_before": before, "count_after": after, "items": inserted}


# ---------- 앱 ----------
def health(request):
    return JSONResponse({"ok": True, "service": "ops-logger-mcp"})

mcp_app = mcp.streamable_http_app()   # /mcp 경로에 MCP 엔드포인트
app = Starlette(routes=[
    Route("/", health),
    Route("/healthz", health),
    Route("/.well-known/oauth-protected-resource", protected_resource),
    Route("/.well-known/oauth-protected-resource/mcp", protected_resource),
    Mount("/", app=GoogleBearerAuth(mcp_app)),
], lifespan=mcp_app.router.lifespan_context)

if __name__ == "__main__":
    import uvicorn
    if not ALLOWED_CLIENT_IDS:
        log.warning("ALLOWED_CLIENT_IDS 비어 있음: 모든 토큰이 거부됩니다")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), proxy_headers=True, forwarded_allow_ips="*")
