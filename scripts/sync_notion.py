"""
카드뉴스 초안/발행 상태를 Notion 데이터베이스에 하루 단위 페이지로 기록한다.

NOTION_TOKEN 또는 config.yaml의 notion.database_id가 설정되어 있지 않으면
(아직 Notion 연동 전이면) 아무 것도 하지 않고 조용히 종료한다 — 이 스크립트가
실패해도 카드뉴스 생성/발행 파이프라인 자체는 계속 동작해야 한다.

필요한 Notion 데이터베이스 속성(이름 그대로 정확히 일치해야 함):
  - 제목   (제목/Title 속성)
  - 날짜   (날짜/Date 속성)
  - 카테고리 (선택/Select 속성)
  - 상태   (선택/Select 속성, 옵션: "발행 대기중", "발행 완료")
  - post_id (텍스트/Text 속성)

사용법:
  python sync_notion.py create <content_json_path> <manifest_json_path>
  python sync_notion.py update-status <post_id> <status>
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


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_configured(config: dict) -> bool:
    return bool(os.environ.get("NOTION_TOKEN")) and bool(config.get("notion", {}).get("database_id"))


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    resp = requests.request(method, f"{NOTION_BASE}/{path}", headers=headers(token), json=payload, timeout=30)
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API 오류 ({path}): {json.dumps(body, ensure_ascii=False)}")
    return body


def text_block(kind: str, text: str) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": [{"text": {"content": text[:2000]}}]}}


def image_blocks(base_url: str, folder: str, filenames: list[str]) -> list[dict]:
    return [
        {
            "object": "block",
            "type": "image",
            "image": {"type": "external", "external": {"url": f"{base_url}/posts/{folder}/{name}"}},
        }
        for name in filenames
    ]


def create_page(token: str, database_id: str, content: dict, manifest: dict, base_url: str) -> str:
    properties = {
        "제목": {"title": [{"text": {"content": content["cover"]["title"].replace("\n", " ")[:200]}}]},
        "날짜": {"date": {"start": content["created_at"][:10]}},
        "카테고리": {"select": {"name": content.get("category") or "미분류"}},
        "상태": {"select": {"name": "발행 대기중"}},
        "post_id": {"rich_text": [{"text": {"content": content["post_id"]}}]},
    }
    children = [
        text_block("heading_2", "소재"),
        text_block("paragraph", content["subtopic"]),
        text_block("heading_2", "슬라이드"),
        *image_blocks(base_url, manifest["folder"], manifest["images"]),
        text_block("heading_2", "캡션"),
        text_block("paragraph", content["caption"]),
        text_block("paragraph", " ".join(content["hashtags"])),
    ]
    body = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children,
    }
    result = notion_request("POST", "pages", token, body)
    return result["id"]


def find_page_by_post_id(token: str, database_id: str, post_id: str) -> str | None:
    body = {"filter": {"property": "post_id", "rich_text": {"equals": post_id}}}
    result = notion_request("POST", f"databases/{database_id}/query", token, body)
    results = result.get("results", [])
    return results[0]["id"] if results else None


def update_status(token: str, database_id: str, post_id: str, status: str) -> None:
    page_id = find_page_by_post_id(token, database_id, post_id)
    if not page_id:
        print(f"경고: Notion에서 post_id={post_id} 페이지를 찾지 못함", file=sys.stderr)
        return
    notion_request("PATCH", f"pages/{page_id}", token, {"properties": {"상태": {"select": {"name": status}}}})


def main():
    if len(sys.argv) < 2:
        print("사용법: python sync_notion.py create <content_json> <manifest_json>", file=sys.stderr)
        print("       python sync_notion.py update-status <post_id> <status>", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    if not is_configured(config):
        print("Notion 연동이 아직 설정되지 않았습니다 (NOTION_TOKEN 또는 notion.database_id 없음) — 건너뜁니다.")
        return

    token = os.environ["NOTION_TOKEN"]
    database_id = config["notion"]["database_id"]
    action = sys.argv[1]

    if action == "create":
        content_path = Path(sys.argv[2])
        manifest_path = Path(sys.argv[3])
        with open(content_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        base_url = config["github_pages"]["base_url"].rstrip("/")
        page_id = create_page(token, database_id, content, manifest, base_url)
        print(page_id)
    elif action == "update-status":
        post_id = sys.argv[2]
        status = sys.argv[3]
        update_status(token, database_id, post_id, status)
    else:
        print(f"알 수 없는 action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
