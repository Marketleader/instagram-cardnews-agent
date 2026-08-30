"""
주어진 콘텐츠 JSON 경로에 해당하는 history.json 항목을 published=true로 표시한다.

사용법: python mark_published.py <content_json_path>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "content" / "history.json"


def main():
    content_file = Path(sys.argv[1]).name

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    found = False
    for p in history["posts"]:
        if p.get("content_file") == content_file:
            p["published"] = True
            found = True
            break

    if not found:
        print(f"경고: history에서 항목을 찾지 못함: {content_file}", file=sys.stderr)

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
