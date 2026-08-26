"""
generate_content.py가 만든 JSON을 받아 카드뉴스 슬라이드 이미지를 렌더링한다.
HTML을 Jinja2로 채운 뒤 Playwright(Chromium)로 스크린샷을 찍어 PNG로 저장한다.

출력: docs/posts/<post_id>_<slug>/slide_01.png ... slide_NN.png
      같은 폴더에 manifest.json (이미지 파일명 순서 + 캡션/해시태그) 저장
"""
import json
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
TEMPLATES_DIR = ROOT / "templates"
DOCS_POSTS_DIR = ROOT / "docs" / "posts"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_slide_contexts(data: dict, config: dict) -> list[dict]:
    slides = []
    n_content = len(data["slides"])
    total = n_content + 2  # cover + content... + outro

    slides.append({
        "kind": "cover",
        "kicker": data["cover"]["kicker"],
        "title": data["cover"]["title"],
        "subtitle": data["cover"].get("subtitle", ""),
        "index_display": 1,
        "total": total,
    })

    for i, s in enumerate(data["slides"], start=1):
        slides.append({
            "kind": "content",
            "index": i,
            "title": s["title"],
            "body": s["body"],
            "index_display": i + 1,
            "total": total,
        })

    slides.append({
        "kind": "outro",
        "title": data["outro"]["title"],
        "body": data["outro"]["body"],
        "cta": data["outro"]["cta"],
        "index_display": total,
        "total": total,
    })
    return slides


def main():
    if len(sys.argv) != 2:
        print("사용법: python render_cards.py <content_json_path>", file=sys.stderr)
        sys.exit(1)

    content_path = Path(sys.argv[1])
    with open(content_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    config = load_config()
    brand = config["brand"]
    width = config["image"]["width"]
    height = config["image"]["height"]

    out_dir = DOCS_POSTS_DIR / f"{data['post_id']}_{data['slug']}"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("card.html.jinja")

    slide_contexts = build_slide_contexts(data, config)
    filenames = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})

        for i, ctx in enumerate(slide_contexts, start=1):
            html = template.render(
                width=width,
                height=height,
                brand=brand,
                brand_tag=data.get("cover", {}).get("kicker", "정보카드"),
                **ctx,
            )
            page.set_content(html)
            filename = f"slide_{i:02d}.png"
            page.screenshot(path=str(out_dir / filename))
            filenames.append(filename)

        browser.close()

    manifest = {
        "post_id": data["post_id"],
        "slug": data["slug"],
        "folder": out_dir.name,
        "images": filenames,
        "caption": data["caption"],
        "hashtags": data["hashtags"],
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(str(out_dir / "manifest.json"))


if __name__ == "__main__":
    main()
