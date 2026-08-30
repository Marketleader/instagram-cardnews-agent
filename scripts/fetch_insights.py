"""
발행 완료된 게시물의 Instagram 성과 지표(좋아요/댓글/저장/공유/도달)를
Graph API에서 가져와 history.json에 기록한다.

발행 직후에는 지표가 아직 안정화되지 않으므로, 발행 후 일정 시간
(MIN_HOURS_BEFORE_FETCH)이 지난 게시물만 대상으로 한다. 이미 조회한
게시물은 건너뛴다.

이 스크립트가 쌓아준 데이터는 learn_insights.py가 "어떤 콘텐츠가 반응이
좋았는지" 분석하는 데 사용한다.

사용법: python fetch_insights.py
필요 환경변수: IG_ACCESS_TOKEN
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "content" / "history.json"
GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MIN_HOURS_BEFORE_FETCH = 48
# 참고: Graph API가 지원하는 미디어 인사이트 지표는 계정 생성 시점/미디어
# 타입에 따라 달라질 수 있다. 문제가 생기면 에러 메시지에 나오는 사용 가능한
# 지표 목록을 참고해 이 목록을 조정할 것.
METRICS = "likes,comments,saved,shares,reach"


def load_history() -> dict:
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict) -> None:
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def fetch_media_insights(media_id: str, access_token: str) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}/{media_id}/insights",
        params={"metric": METRICS, "access_token": access_token},
        timeout=30,
    )
    body = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API 오류 ({media_id}): {json.dumps(body, ensure_ascii=False)}")
    result = {}
    for item in body.get("data", []):
        values = item.get("values", [])
        if values:
            result[item["name"]] = values[0].get("value")
    return result


def main():
    access_token = os.environ["IG_ACCESS_TOKEN"]
    history = load_history()
    now = datetime.now(timezone.utc)

    updated = 0
    for p in history["posts"]:
        if not p.get("published") or not p.get("ig_media_id"):
            continue
        if p.get("performance"):
            continue
        published_at_raw = p.get("published_at")
        if not published_at_raw:
            continue
        published_at = datetime.fromisoformat(published_at_raw)
        if now - published_at < timedelta(hours=MIN_HOURS_BEFORE_FETCH):
            continue

        try:
            metrics = fetch_media_insights(p["ig_media_id"], access_token)
        except Exception as e:
            print(f"경고: {p['post_id']} 지표 조회 실패: {e}", file=sys.stderr)
            continue

        p["performance"] = metrics
        p["performance_fetched_at"] = now.isoformat()
        updated += 1
        print(f"{p['post_id']}: {metrics}")

    if updated:
        save_history(history)
    print(f"완료: {updated}건 업데이트")


if __name__ == "__main__":
    main()
