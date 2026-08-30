"""
Notion 통합(integration)에 연결(공유)된 카드뉴스 데이터베이스를 자동으로 찾아
config.yaml의 notion.database_id를 채우고, DB를 실제로 활용하기 좋도록
(정렬/필터/성과 추적) 필요한 속성을 스키마에 추가한다.

최초 1회 실행하면 되고, 다시 실행해도 안전하다 (이미 있는 속성은 건드리지 않고
건너뛴다). 사용자가 Notion에서 데이터베이스를 만들고 통합과 "연결 추가"까지
완료한 뒤 실행해야 한다.

사용법: python setup_notion_db.py
필요 환경변수: NOTION_TOKEN
"""
import json
import os
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

# 기본 5개 속성(제목/날짜/카테고리/상태/post_id)은 README 안내에 따라 사용자가
# 수동으로 만든다고 가정하고, 여기서는 "DB로 최적화 활용"하기 위한 나머지
# 속성만 자동으로 추가한다.
EXTENDED_PROPERTIES = {
    "소재": {"rich_text": {}},
    "슬라이드수": {"number": {"format": "number"}},
    "해시태그": {"multi_select": {}},
    "GitHub Pages 링크": {"url": {}},
    "발행일시": {"date": {}},
    "media_id": {"rich_text": {}},
    "좋아요": {"number": {"format": "number"}},
    "댓글": {"number": {"format": "number"}},
    "저장": {"number": {"format": "number"}},
    "공유": {"number": {"format": "number"}},
    "도달": {"number": {"format": "number"}},
    "참여점수": {"number": {"format": "number"}},
}


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def find_database(token: str) -> str:
    resp = requests.post(
        f"{NOTION_BASE}/search",
        headers=headers(token),
        json={"filter": {"property": "object", "value": "database"}},
        timeout=30,
    )
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion 검색 실패: {json.dumps(body, ensure_ascii=False)}")

    results = body.get("results", [])
    if not results:
        # 진단: 데이터베이스가 아니라 무엇이 연결되어 있는지 확인 (필터 없이 전체 검색)
        resp_all = requests.post(f"{NOTION_BASE}/search", headers=headers(token), json={}, timeout=30)
        body_all = resp_all.json()
        connected = body_all.get("results", [])
        if not connected:
            raise RuntimeError(
                "이 통합(integration)에 연결된 것이 아무 것도 없습니다. "
                "Notion에서 데이터베이스를 만든 뒤 '⋯' → '연결 추가(Add connections)'로 "
                "이 통합을 선택했는지 확인하세요."
            )
        kinds = [r.get("object") for r in connected]

        def title_of(r):
            props = r.get("properties", {})
            for v in props.values():
                if v.get("type") == "title":
                    t = v.get("title", [])
                    return t[0]["plain_text"] if t else "(제목 없음)"
            t = r.get("title", [])
            return t[0]["plain_text"] if t else "(제목 없음)"

        details = [f"{title_of(r)} ({r.get('object')})" for r in connected]
        raise RuntimeError(
            f"통합에 연결된 항목은 있지만 데이터베이스가 아닙니다: {details}. "
            "일반 페이지가 아니라 '데이터베이스(Database)'를 만들어서 연결했는지 확인하세요 "
            "(페이지 안에 데이터베이스를 인라인으로 만든 경우, 그 데이터베이스 블록 자체에 "
            "따로 '연결 추가'를 해야 할 수 있습니다). 연결된 object 타입: "
            f"{kinds}"
        )
    if len(results) > 1:
        def title_of(r):
            t = r.get("title", [])
            return t[0]["plain_text"] if t else "(제목 없음)"
        titles = [title_of(r) for r in results]
        print(f"경고: 연결된 데이터베이스가 {len(results)}개 발견됨: {titles} — 첫 번째를 사용합니다.", file=sys.stderr)
    return results[0]["id"]


def extend_schema(token: str, database_id: str) -> None:
    resp = requests.get(f"{NOTION_BASE}/databases/{database_id}", headers=headers(token), timeout=30)
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"DB 조회 실패: {json.dumps(body, ensure_ascii=False)}")

    existing = set(body.get("properties", {}).keys())
    to_add = {name: schema for name, schema in EXTENDED_PROPERTIES.items() if name not in existing}
    if not to_add:
        print("추가할 새 속성 없음 (이미 모두 존재).")
        return

    resp = requests.patch(
        f"{NOTION_BASE}/databases/{database_id}",
        headers=headers(token),
        json={"properties": to_add},
        timeout=30,
    )
    result = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"스키마 갱신 실패: {json.dumps(result, ensure_ascii=False)}")
    print(f"속성 {len(to_add)}개 추가됨: {list(to_add.keys())}")


def update_config_database_id(database_id: str) -> None:
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)
    current = (config.get("notion") or {}).get("database_id", "")
    if current == database_id:
        print("config.yaml의 notion.database_id가 이미 최신입니다.")
        return

    if 'database_id: ""' in config_text:
        config_text = config_text.replace('database_id: ""', f'database_id: "{database_id}"', 1)
    elif current:
        config_text = config_text.replace(f'database_id: "{current}"', f'database_id: "{database_id}"', 1)
    else:
        config_text = config_text.rstrip() + f'\n\nnotion:\n  database_id: "{database_id}"\n'

    CONFIG_PATH.write_text(config_text, encoding="utf-8")
    print(f"config.yaml의 notion.database_id를 {database_id}로 갱신함.")


def main():
    token = os.environ["NOTION_TOKEN"]
    database_id = find_database(token)
    extend_schema(token, database_id)
    update_config_database_id(database_id)
    print(database_id)


if __name__ == "__main__":
    main()
