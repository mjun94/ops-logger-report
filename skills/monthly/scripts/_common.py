"""스크립트 공용 유틸 — 팀 루트·설정 파일 자동 탐색.

사용자가 매달 --profile / --baselines 경로를 기억해서 넘기지 않아도 되도록,
데이터 파일 위치를 기준으로 관례적인 자리에서 설정을 찾는다.

**팀 루트는 profile.json이 있는 폴더**이고, 모든 산출물 경로의 기준점이다.
스크립트를 어느 위치에서 실행해도 같은 자리에 쓰이게 하려면 cwd가 아니라
팀 루트를 기준으로 삼아야 한다.
"""
import json
import os

SEARCH_NAMES = {
    "profile": ["profile.json", "ops-report.profile.json"],
    "baselines": ["baselines.json", "ops-report.baselines.json"],
}

# 데이터 폴더에서 팀 루트까지 거슬러 올라갈 최대 단계.
# data/2026/requests_202607.json 처럼 연도 폴더가 끼어도 닿아야 하고,
# 무한히 올라가 남의 팀 profile.json을 집으면 안 되므로 상한을 둔다.
MAX_ASCEND = 4


def _candidates(data_path):
    """설정 파일을 찾을 디렉터리 목록 (가까운 순)."""
    dirs = []
    if data_path:
        cur = os.path.dirname(os.path.abspath(data_path))
        for _ in range(MAX_ASCEND + 1):          # data/2026/ → data/ → 팀 루트 → …
            dirs += [cur, os.path.join(cur, "config")]
            parent = os.path.dirname(cur)
            if parent == cur:                    # 파일시스템 루트
                break
            cur = parent
    cwd = os.getcwd()
    dirs += [cwd, os.path.join(cwd, "config"), os.path.join(cwd, "ops-report")]
    seen, out = set(), []
    for d in dirs:
        p = os.path.normpath(d)
        if p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    return out


def _display(path):
    """가능하면 현재 위치 기준 상대경로로 짧게 표기."""
    try:
        rel = os.path.relpath(path)
        return rel if not rel.startswith("../../") else path
    except ValueError:
        return path


def find_config(kind, data_path=None, explicit=None, required=False):
    """(경로, 설명) 반환. 못 찾으면 (None, 사유)."""
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit(f"지정한 {kind} 파일을 찾을 수 없습니다: {explicit}")
        return explicit, "직접 지정"
    for d in _candidates(data_path):
        for name in SEARCH_NAMES[kind]:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return _display(p), "자동 탐색"
    if required:
        raise SystemExit(
            f"{kind}.json을 찾지 못했습니다. 데이터 폴더나 현재 위치에 두거나 --{kind} 로 지정하세요.\n"
            f"처음 쓰는 팀이면 setup 스킬로 먼저 만드세요."
        )
    return None, "없음"


def find_team_root(data_path=None, explicit_profile=None):
    """팀 루트(profile.json이 있는 폴더) 절대경로.

    profile.json이 아직 없으면(setup 이전) 현재 위치를 팀 루트로 본다.
    """
    if explicit_profile:
        return os.path.dirname(os.path.abspath(explicit_profile))
    path, _ = find_config("profile", data_path=data_path)
    if path:
        return os.path.dirname(os.path.abspath(path))
    return os.getcwd()


def infer_team_root(data_path):
    """profile.json이 아직 없을 때(setup 단계) 데이터 경로에서 팀 루트를 추정.

    data 폴더를 만나면 그 상위를 팀 루트로 본다. 연도 폴더가 끼어도 같다.

        <팀 루트>/data/2026/requests_202607.json → <팀 루트>
        <팀 루트>/data/requests_202607.json      → <팀 루트>
        <팀 루트>/requests_202607.json           → <팀 루트>
    """
    d = os.path.dirname(os.path.abspath(data_path))
    parts = d.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower() in ("data", "데이터"):
            return os.sep.join(parts[:i]) or os.sep
    return d


def report_path(root, month, filename):
    """<팀 루트>/report/<대상연도>/<파일명>.

    연도는 작성일이 아니라 데이터의 대상월에서 뽑는다. 26년 12월분을
    27년 1월에 만들어도 report/2026/ 에 들어가야 한다.
    """
    return os.path.join(root, "report", month[:4], filename)


def resolve_out(path, root):
    """--out 경로를 팀 루트 기준으로 확정하고 상위 폴더를 만든다.

    절대경로는 그대로 쓰고, 상대경로는 cwd가 아니라 팀 루트에 붙인다.
    스크립트를 어디서 실행해도 산출물이 같은 자리에 쌓이게 하는 규칙이다.
    """
    p = path if os.path.isabs(path) else os.path.join(root, path)
    p = os.path.normpath(p)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return p


def load_json(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_rows(raw):
    """{'<SQL>': [...]} 또는 행 배열 → (source_key, rows)"""
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, list):
                return k, v
        raise SystemExit("JSON에서 행 배열을 찾지 못했습니다.")
    if isinstance(raw, list):
        return None, raw
    raise SystemExit("지원하지 않는 JSON 구조입니다.")
