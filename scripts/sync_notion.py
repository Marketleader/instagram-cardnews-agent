"""
카드뉴스 초안/발행/성과를 Notion 데이터베이스에 하루 단위 페이지로 기록한다.

NOTION_TOKEN 또는 config.yaml의 notion.database_id가 설정되어 있지 않으면
(아직 Notion 연동 전이면) 아무 것도 하지 않고 조용히 종료한다 — 이 스크립트가
실패해도 카드뉴스 생성/발행 파이프라인 자체는 계속 동작해야 한다.

필요한 Notion 데이터베이스 속성(이름 그대로 정확히 일치해야 함).
기본 5개는 수동으로, 나머지는 setup_notion_db.py가 자동으로 추가해준다:
  - 제목       (Title)
  - 날짜       (Date)
  - 카테고리    (Select)
  - 상태       (Select, 옵션: "발행 대기중", "발행 완료")
  - post_id    (Text)
  - 소재       (Text)              [자동 추가]
  - 슬라이드수  (Number)            [자동 추가]
  - 해시태그    (Multi-select)      [자동 추가]
  - GitHub Pages 링크 (URL)        [자동 추가]
  - 발행일시    (Date)              [자동 추가]
  - media_id   (Text)              [자동 추가]
  - 좋아요/댓글/저장/공유/도달/참여점수 (Number)  [자동 추가]

사용법:
  python sync_notion.py create <content_json_path> <manifest_json_path>
  python sync_notion.py update-publish <post_id> <media_id>
  python sync_notion.py sync-performance-all
  python sync_notion.py archive-stale
"""
import datetime
import json
import os
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
HISTORY_PATH = ROOT / "content" / "history.json"
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


def engagement_score(performance: dict) -> float:
    return (
        performance.get("saved", 0) * 3
        + performance.get("shares", 0) * 3
        + performance.get("comments", 0) * 2
        + performance.get("likes", 0) * 1
    )


def create_page(token: str, database_id: str, content: dict, manifest: dict, base_url: str) -> str:
    hashtags = [{"name": h.lstrip("#")[:100]} for h in content.get("hashtags", [])][:20]
    cover_url = f"{base_url}/posts/{manifest['folder']}/{manifest['images'][0]}" if manifest.get("images") else None

    properties = {
        "제목": {"title": [{"text": {"content": content["cover"]["title"].replace("\n", " ")[:200]}}]},
        "날짜": {"date": {"start": content["created_at"][:10]}},
        "카테고리": {"select": {"name": content.get("category") or "미분류"}},
        "상태": {"select": {"name": "발행 대기중"}},
        "post_id": {"rich_text": [{"text": {"content": content["post_id"]}}]},
        "소재": {"rich_text": [{"text": {"content": content["subtopic"][:2000]}}]},
        "슬라이드수": {"number": len(manifest.get("images", []))},
        "해시태그": {"multi_select": hashtags},
    }
    if cover_url:
        properties["GitHub Pages 링크"] = {"url": cover_url}

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


def update_publish(token: str, database_id: str, post_id: str, media_id: str, published_at: str) -> None:
    page_id = find_page_by_post_id(token, database_id, post_id)
    if not page_id:
        print(f"경고: Notion에서 post_id={post_id} 페이지를 찾지 못함", file=sys.stderr)
        return
    properties = {
        "상태": {"select": {"name": "발행 완료"}},
        "발행일시": {"date": {"start": published_at}},
    }
    if media_id:
        properties["media_id"] = {"rich_text": [{"text": {"content": media_id}}]}
    notion_request("PATCH", f"pages/{page_id}", token, {"properties": properties})


def update_performance(token: str, database_id: str, post_id: str, performance: dict) -> None:
    page_id = find_page_by_post_id(token, database_id, post_id)
    if not page_id:
        print(f"경고: Notion에서 post_id={post_id} 페이지를 찾지 못함", file=sys.stderr)
        return
    properties = {
        "좋아요": {"number": performance.get("likes", 0)},
        "댓글": {"number": performance.get("comments", 0)},
        "저장": {"number": performance.get("saved", 0)},
        "공유": {"number": performance.get("shares", 0)},
        "도달": {"number": performance.get("reach", 0)},
        "참여점수": {"number": engagement_score(performance)},
    }
    notion_request("PATCH", f"pages/{page_id}", token, {"properties": properties})


def sync_performance_all(token: str, database_id: str) -> None:
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)
    updated = 0
    for p in history["posts"]:
        performance = p.get("performance")
        if not performance:
            continue
        update_performance(token, database_id, p["post_id"], performance)
        updated += 1
    print(f"Notion 성과 지표 동기화: {updated}건")


def archive_stale_pages(token: str, database_id: str) -> None:
    """content/history.json에 더 이상 없는 post_id의 Notion 페이지를 보관 처리(archive)한다.
    주제 전환 등으로 history.json에서 옛 초안을 정리했을 때, Notion에 남은 옛 페이지를
    함께 정리하기 위한 용도."""
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)
    valid_post_ids = {p["post_id"] for p in history["posts"]}

    result = notion_request("POST", f"databases/{database_id}/query", token, {})
    archived = 0
    for page in result.get("results", []):
        props = page.get("properties", {})
        rich_text = props.get("post_id", {}).get("rich_text", [])
        page_post_id = rich_text[0]["plain_text"] if rich_text else None
        if page_post_id and page_post_id not in valid_post_ids:
            notion_request("PATCH", f"pages/{page['id']}", token, {"archived": True})
            archived += 1
            print(f"보관 처리: {page_post_id}")
    print(f"Notion 옛 페이지 보관 처리: {archived}건")


def main():
    if len(sys.argv) < 2:
        print("사용법: python sync_notion.py create <content_json> <manifest_json>", file=sys.stderr)
        print("       python sync_notion.py update-publish <post_id> <media_id>", file=sys.stderr)
        print("       python sync_notion.py sync-performance-all", file=sys.stderr)
        print("       python sync_notion.py archive-stale", file=sys.stderr)
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
    elif action == "update-publish":
        post_id = sys.argv[2]
        media_id = sys.argv[3] if len(sys.argv) > 3 else ""
        published_at = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        update_publish(token, database_id, post_id, media_id, published_at)
    elif action == "sync-performance-all":
        sync_performance_all(token, database_id)
    elif action == "archive-stale":
        archive_stale_pages(token, database_id)
    else:
        print(f"알 수 없는 action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
