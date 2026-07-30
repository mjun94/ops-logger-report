"""스크립트 공용 유틸 — 설정 파일 자동 탐색.

사용자가 매달 --profile / --baselines 경로를 기억해서 넘기지 않아도 되도록,
데이터 파일 위치를 기준으로 관례적인 자리에서 설정을 찾는다.
"""
import json
import os

SEARCH_NAMES = {
    "profile": ["profile.json", "ops-report.profile.json"],
    "baselines": ["baselines.json", "ops-report.baselines.json"],
}


def _candidates(data_path):
    """설정 파일을 찾을 디렉터리 목록 (가까운 순)."""
    dirs = []
    if data_path:
        d = os.path.dirname(os.path.abspath(data_path))
        dirs += [d, os.path.dirname(d)]          # 데이터 폴더, 그 상위 (예: ./data/ → ./)
        dirs.append(os.path.join(d, "..", "config"))
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
