---
name: setup
description: Ops Logger 당일 등록 플러그인 첫 설정. 실행자 그룹웨어 이메일을 저장하고 Google Chat MCP 서버(gchat)를 Claude Code에 등록한 뒤 /mcp 인증을 안내한다. 사용자가 "옵스로거 설정", "/ops-logger:setup", "gchat 등록"을 요청하거나 insert-today가 설정 없음으로 멈췄을 때 사용.
argument-hint: "[그룹웨어 이메일]"
---

# Ops Logger 당일 등록 첫 설정

한 사람이 처음 한 번만 한다. 입력은 두 가지뿐이다. 그룹웨어 이메일과 Google Chat 클라이언트 시크릿. 시크릿은 담당자(최문준)에게 1:1로 받는다.

## 1. 이메일 저장

`$ARGUMENTS`에 이메일이 없으면 묻는다. `@vntgcorp.com` 또는 `@seah.co.kr`이 아니면 다시 묻는다. 개인 Gmail은 안 된다.

```bash
mkdir -p ~/.ops-logger && python3 - <<'EOF2'
import json, os
p = os.path.expanduser("~/.ops-logger/config.json")
d = json.load(open(p)) if os.path.exists(p) else {}
d["email"] = "<이메일>"
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
print("saved", p)
EOF2
```

## 2. Google Chat MCP 서버 등록

`claude mcp get gchat`이 성공하면 이미 등록된 것이니 건너뛴다. 아니면 시크릿을 묻고(채팅에 붙여넣기) 아래를 실행한다. 시크릿은 Claude Code 키체인에만 저장되고 파일에는 남지 않는다.

```bash
MCP_CLIENT_SECRET='<시크릿>' claude mcp add -s user --transport http gchat https://chatmcp.googleapis.com/mcp/v1 \
  --client-id 430760550191-b62bj065ct17ujrio31uq4v5jmnb8pqe.apps.googleusercontent.com \
  --client-secret --callback-port 3118
claude mcp get gchat
```

실행 후 시크릿이 들어간 명령은 대화에 다시 출력하지 않는다.

## 3. 인증 안내

사용자에게 이렇게 안내하고 멈춘다.

1. 프롬프트에 `/mcp` 입력 → `gchat` 선택 → 브라우저에서 Google 로그인·동의 → "Authentication successful"
2. 같은 화면에서 Gmail(`claude.ai Gmail`)이 미인증이면 선택해 인증
3. Claude Code를 재시작하거나 새 대화에서 `/ops-logger:insert-today` 실행

## 4. 점검 (사용자가 인증 완료라고 하면)

```bash
python3 "${CLAUDE_SKILL_DIR}/../insert-today/scripts/ops_logger.py" me
python3 "${CLAUDE_SKILL_DIR}/../insert-today/scripts/ops_logger.py" list-today
```

둘 다 정상이면 설정 끝. `me`가 실패하면 이메일을, Chat 조회가 "needs you to sign in"이면 `/mcp` 재인증을 안내한다.

## 팀 분류표를 따로 쓰는 경우

그룹웨어서비스팀 외 조직은 `~/.ops-logger/`에 `taxonomy.json`, `taxonomy.md`, `classify-rules.md`를 두면 스킬이 그것을 우선 사용한다. 형식은 플러그인의 `insert-today/references/`와 같다.
