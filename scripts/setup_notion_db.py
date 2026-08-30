"""
Notion 통합(integration)에 연결(공유)된 카드뉴스 데이터베이스를 자동으로 찾고,
없으면 연결된 페이지 안에 필요한 속성을 모두 갖춘 데이터베이스를 새로 만든다.
찾았거나 새로 만든 데이터베이스의 id를 config.yaml의 notion.database_id에 쓰고,
DB를 실제로 활용하기 좋도록(정렬/필터/성과 추적) 필요한 속성이 빠짐없이 있는지
확인해 없는 것만 추가한다.

사용자가 할 일은 Notion에서 페이지나 데이터베이스를 하나 만들어 통합과
"연결 추가"만 해두는 것뿐이다. 최초 1회 실행하면 되고, 다시 실행해도 안전하다
(이미 있는 속성/데이터베이스는 건드리지 않는다).

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

# DB를 실제로 활용하기 좋도록(정렬/필터/성과 추적) 갖춰야 할 속성. 기존
# 데이터베이스에 없는 것만 골라 추가하거나(extend_schema), 새로 데이터베이스를
# 만들 때(create_database_under_page) 처음부터 전부 포함시킨다.
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

BASE_PROPERTIES = {
    "제목": {"title": {}},
    "날짜": {"date": {}},
    "카테고리": {"select": {}},
    "상태": {"select": {"options": [{"name": "발행 대기중"}, {"name": "발행 완료"}]}},
    "post_id": {"rich_text": {}},
}


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _title_of(r: dict) -> str:
    props = r.get("properties", {})
    for v in props.values():
        if v.get("type") == "title":
            t = v.get("title", [])
            return t[0]["plain_text"] if t else "(제목 없음)"
    t = r.get("title", [])
    return t[0]["plain_text"] if t else "(제목 없음)"


def create_database_under_page(token: str, page_id: str, page_title: str) -> str:
    all_properties = {**BASE_PROPERTIES, **EXTENDED_PROPERTIES}
    body = {
        "parent": {"type": "page_id", "page_id": page_id},
        "title": [{"type": "text", "text": {"content": "카드뉴스 콘텐츠"}}],
        "properties": all_properties,
    }
    resp = requests.post(f"{NOTION_BASE}/databases", headers=headers(token), json=body, timeout=30)
    result = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"데이터베이스 생성 실패: {json.dumps(result, ensure_ascii=False)}")
    print(f"'{page_title}' 페이지 안에 '카드뉴스 콘텐츠' 데이터베이스를 새로 생성했습니다.")
    return result["id"]


def find_or_create_database(token: str) -> str:
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
    if results:
        if len(results) > 1:
            titles = [_title_of(r) for r in results]
            print(f"경고: 연결된 데이터베이스가 {len(results)}개 발견됨: {titles} — 첫 번째를 사용합니다.", file=sys.stderr)
        return results[0]["id"]

    # 연결된 데이터베이스가 없으면, 연결된 페이지를 찾아 그 안에 데이터베이스를 새로 만든다.
    resp_all = requests.post(f"{NOTION_BASE}/search", headers=headers(token), json={}, timeout=30)
    body_all = resp_all.json()
    connected = body_all.get("results", [])
    connected_pages = [r for r in connected if r.get("object") == "page"]

    if not connected_pages:
        raise RuntimeError(
            "이 통합(integration)에 연결된 페이지나 데이터베이스가 없습니다. "
            "Notion에서 페이지(또는 데이터베이스)를 만든 뒤 '⋯' → '연결 추가(Add connections)'로 "
            "이 통합을 선택했는지 확인하세요."
        )

    page = connected_pages[0]
    if len(connected_pages) > 1:
        titles = [_title_of(r) for r in connected_pages]
        print(f"경고: 연결된 페이지가 {len(connected_pages)}개 발견됨: {titles} — 첫 번째 안에 데이터베이스를 만듭니다.", file=sys.stderr)

    return create_database_under_page(token, page["id"], _title_of(page))


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
    database_id = find_or_create_database(token)
    extend_schema(token, database_id)
    update_config_database_id(database_id)
    print(database_id)


if __name__ == "__main__":
    main()
