"""
render_cards.py가 만든 manifest.json(이미지 목록 + 캡션/해시태그)을 읽어
Instagram Graph API로 캐러셀(carousel) 카드뉴스 게시물을 발행한다.

전제:
- 이미지들은 이미 GitHub Pages 등으로 배포되어 공개 URL로 접근 가능해야 한다.
  (Instagram Graph API는 로컬 파일 업로드가 아니라 공개 image_url을 요구한다.)
- 환경변수 IG_USER_ID, IG_ACCESS_TOKEN 필요.

사용법:
  python publish_instagram.py <manifest_json_path> [--dry-run]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def wait_until_reachable(url: str, timeout_sec: int = 120, interval_sec: int = 5) -> None:
    elapsed = 0
    while elapsed < timeout_sec:
        try:
            r = requests.head(url, timeout=10)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(interval_sec)
        elapsed += interval_sec
    raise RuntimeError(f"이미지 URL에 접근할 수 없습니다 (timeout): {url}")


def graph_post(path: str, params: dict) -> dict:
    resp = requests.post(f"{GRAPH_BASE}/{path}", data=params, timeout=30)
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API 오류 ({path}): {json.dumps(body, ensure_ascii=False)}")
    return body


def graph_get(path: str, params: dict) -> dict:
    resp = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=30)
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API 오류 ({path}): {json.dumps(body, ensure_ascii=False)}")
    return body


def create_carousel_item(ig_user_id: str, access_token: str, image_url: str) -> str:
    body = graph_post(f"{ig_user_id}/media", {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": access_token,
    })
    return body["id"]


def create_carousel_container(ig_user_id: str, access_token: str, children_ids: list[str], caption: str) -> str:
    body = graph_post(f"{ig_user_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
        "access_token": access_token,
    })
    return body["id"]


def wait_until_finished(container_id: str, access_token: str, timeout_sec: int = 120, interval_sec: int = 5) -> None:
    elapsed = 0
    while elapsed < timeout_sec:
        body = graph_get(container_id, {"fields": "status_code", "access_token": access_token})
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"컨테이너 처리 실패: {body}")
        time.sleep(interval_sec)
        elapsed += interval_sec
    raise RuntimeError(f"컨테이너 처리 timeout: {container_id}")


def publish(ig_user_id: str, access_token: str, container_id: str) -> str:
    body = graph_post(f"{ig_user_id}/media_publish", {
        "creation_id": container_id,
        "access_token": access_token,
    })
    return body["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest_path")
    parser.add_argument("--dry-run", action="store_true", help="실제 IG API 호출 없이 URL/캡션만 출력")
    args = parser.parse_args()

    manifest_path = Path(args.manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    config = load_config()
    base_url = config["github_pages"]["base_url"].rstrip("/")
    folder = manifest["folder"]
    image_urls = [f"{base_url}/posts/{folder}/{name}" for name in manifest["images"]]

    caption = manifest["caption"].strip() + "\n\n" + " ".join(manifest["hashtags"])

    if args.dry_run:
        print("[DRY RUN] 다음 이미지로 캐러셀을 발행합니다:")
        for u in image_urls:
            print(" -", u)
        print("\n[DRY RUN] 캡션:\n", caption)
        return

    ig_user_id = os.environ["IG_USER_ID"]
    access_token = os.environ["IG_ACCESS_TOKEN"]

    print("이미지가 배포될 때까지 대기 중...")
    for url in image_urls:
        wait_until_reachable(url)

    print("캐러셀 아이템 컨테이너 생성 중...")
    children_ids = [create_carousel_item(ig_user_id, access_token, url) for url in image_urls]

    print("캐러셀 컨테이너 생성 중...")
    container_id = create_carousel_container(ig_user_id, access_token, children_ids, caption)

    print("처리 완료 대기 중...")
    wait_until_finished(container_id, access_token)

    print("게시 중...")
    media_id = publish(ig_user_id, access_token, container_id)

    print(f"게시 완료: media_id={media_id}")


if __name__ == "__main__":
    main()
