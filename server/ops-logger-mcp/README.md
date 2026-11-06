# Ops Logger MCP 서버 (claude.ai 커스텀 커넥터)

Claude Code 플러그인 `ops-logger`의 `scripts/ops_logger.py`를 원격 MCP 서버로 옮긴 것. claude.ai(웹·데스크톱·모바일)에서
Ops Logger 당일 등록을 하려면 로컬 스크립트를 돌릴 수 없으므로 이 서버가 대신 Ops Logger API를 호출한다.

- 인증: Google 계정 OAuth. claude.ai가 받은 Google 액세스 토큰을 `tokeninfo`로 검증하고, 그 이메일을 Ops Logger `X-AUTH-EMAIL`로 쓴다.
  → 시크릿을 팀원에게 나눠 줄 필요가 없고, 등록은 항상 로그인한 본인 계정으로 들어간다
- 허용 조건: 토큰 `aud`가 `ALLOWED_CLIENT_IDS`, 이메일 도메인이 `ALLOWED_DOMAINS`(기본 vntgcorp.com, seah.co.kr), 선택적으로 `ALLOWED_EMAILS`
- 도구: `me`, `list_sr`, `search_member`, `companies`, `company_hint`, `validate_items`, `insert_items(confirm=true)`
- 분류표 `taxonomy.json`은 `plugins/ops-logger/skills/insert-today/references/taxonomy.json`의 복사본. 분류체계가 바뀌면 같이 갱신 후 재배포

## 배포 (Cloud Run, 프로젝트 vntg-ops-chatbot)

```bash
cd server/ops-logger-mcp
gcloud run deploy ops-logger-mcp --source . --project vntg-ops-chatbot --region asia-northeast3 \
  --allow-unauthenticated --min-instances 0 --max-instances 3 --memory 512Mi \
  --set-env-vars ALLOWED_CLIENT_IDS=<claude.ai용 OAuth 클라이언트 ID>,MEMORY_BUCKET=<버킷>
```

- `--allow-unauthenticated`는 Cloud Run 앞단 IAM을 끄는 것이고, 인증은 앱 안에서 Google 토큰으로 한다
- `MEMORY_BUCKET`을 주면 요청회사 확정값을 `requester-company/<이메일>.json`에 기억한다 (서비스 계정에 objectAdmin 필요)

## claude.ai 연결

1. 설정 > 커넥터 > 커스텀 커넥터 추가. URL `https://<서비스 URL>/mcp`
2. 고급 설정에 OAuth 클라이언트 ID·시크릿 입력 (Google Chat 커넥터와 같은 클라이언트). 리디렉션 URI `https://claude.ai/api/mcp/auth_callback`이 그 클라이언트에 등록돼 있어야 한다
3. 연결 시 Google 로그인 창이 뜨면 `@vntgcorp.com` 계정 선택
4. 프로젝트 지침은 `claude-web-project-instructions.md` 참고

## 로컬 실행

```bash
pip install -r requirements.txt
ALLOWED_CLIENT_IDS=<id> PORT=8080 python server.py
curl localhost:8080/.well-known/oauth-protected-resource/mcp
```
