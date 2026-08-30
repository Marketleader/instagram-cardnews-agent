"""
publish 워크플로에서 발행할 콘텐츠 JSON 경로를 결정한다.
- post_id 인자가 주어지면 해당 게시물을 찾는다.
- 인자가 비어있으면 history.json에서 아직 발행되지 않은(published: false) 가장 최근 항목을 찾는다.

사용법: python resolve_draft.py [post_id]
출력: content/generated/<...>.json 경로 (stdout)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "content" / "history.json"
GENERATED_DIR = ROOT / "content" / "generated"


def main():
    post_id = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    entry = None
    if post_id:
        for p in history["posts"]:
            if p["post_id"] == post_id:
                entry = p
                break
        if entry is None:
            print(f"post_id를 찾을 수 없습니다: {post_id}", file=sys.stderr)
            sys.exit(1)
    else:
        for p in reversed(history["posts"]):
            if not p.get("published", False):
                entry = p
                break
        if entry is None:
            print("발행 대기 중인 초안이 없습니다. 먼저 초안 생성 워크플로를 실행하세요.", file=sys.stderr)
            sys.exit(1)

    content_path = GENERATED_DIR / entry["content_file"]
    if not content_path.exists():
        print(f"콘텐츠 파일을 찾을 수 없습니다: {content_path}", file=sys.stderr)
        sys.exit(1)

    print(str(content_path))


if __name__ == "__main__":
    main()
