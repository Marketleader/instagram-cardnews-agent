"""
주제 풀(config.yaml의 category_pool)과 과거 이력(content/history.json)을 바탕으로
아직 다루지 않은 세부 소재를 골라 카드뉴스 한 편의 텍스트 콘텐츠(JSON)를 생성한다.

출력: content/generated/<YYYYMMDD-HHMMSS>_<slug>.json
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
HISTORY_PATH = ROOT / "content" / "history.json"
GENERATED_DIR = ROOT / "content" / "generated"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"posts": []}
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict) -> None:
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40] if text else "post"


def build_prompt(config: dict, history: dict) -> str:
    used_subtopics = [p["subtopic"] for p in history["posts"][-30:]]
    min_slides = config["slides"]["min"]
    max_slides = config["slides"]["max"]

    return f"""당신은 인스타그램 카드뉴스 전문 에디터입니다.
주제 테마: "{config['topic_theme']}"
타깃 독자: {config['audience']}

아래는 이 테마 안에서 다룰 수 있는 소재 카테고리 목록입니다:
{json.dumps(config['category_pool'], ensure_ascii=False, indent=2)}

최근에 이미 다룬 세부 소재(반드시 피할 것, 겹치지 않는 새로운 각도를 선택):
{json.dumps(used_subtopics, ensure_ascii=False, indent=2) if used_subtopics else "(아직 없음)"}

작업:
1. 위 카테고리 중 하나를 골라, 그 안에서 아주 구체적인 세부 소재 하나를 정하세요.
   (예: "청년 자산형성" 카테고리라면 -> "매달 일정 금액을 저축하면 정부가 추가로 얹어주는 유형의
   청년 자산형성 상품, 신청 자격과 놓치기 쉬운 조건" 처럼 좁힐 것)
2. {min_slides}~{max_slides}장짜리 카드뉴스 슬라이드 콘텐츠를 작성하세요.
3. 반드시 아래 JSON 형식으로만 응답하세요. 다른 설명, 마크다운 코드펜스 없이 순수 JSON만 출력합니다.

중요한 제약:
- 이 계정은 실제 정부/지자체 지원 제도를 다룹니다. 구체적인 금액, 지원 대상 나이, 소득 기준,
  신청 기간 등 "확정된 수치"처럼 보이는 정보는 시기에 따라 바뀌므로, 슬라이드 본문에서는
  "정확한 금액/기간/자격은 시기에 따라 달라지니 반드시 최신 공고를 확인하라"는 취지를 outro에
  분명히 포함하세요. 존재하지 않는 제도를 지어내지 말고, 일반적으로 널리 알려진 형태의 제도
  범주(예: 자산형성 지원, 월세 지원, 창업 지원금 등) 수준에서 정보를 제공하고 구체적 수치를
  단정적으로 제시하지 마세요.
- 어조는 "친구가 알려주는 꿀팁"처럼 친근하되, 신뢰감 있게 작성하세요.
- 각 content 슬라이드의 body는 2~4문장, 슬라이드당 최대 90자 내외로 간결하게.

JSON 스키마:
{{
  "subtopic": "이번에 다루는 세부 소재 한 줄 요약",
  "cover": {{"kicker": "카테고리 라벨 (예: 청년 지원)", "title": "후킹되는 커버 제목 (두 줄 이내)", "subtitle": "부제 한 줄"}},
  "slides": [
    {{"title": "슬라이드 소제목", "body": "슬라이드 본문"}}
  ],
  "outro": {{"title": "마무리 제목", "body": "요약 + 최신 공고 확인 안내 문구", "cta": "저장하고 나중에 확인하기 같은 행동 유도 문구"}},
  "caption": "인스타그램 게시물 캡션 전체 텍스트 (이모지 적절히 사용, 3~6문단, 마지막에 해시태그 제외)",
  "hashtags": ["#정부지원금", "#태그2", "... 15~20개, # 포함"]
}}
"""


def call_model(config: dict, prompt: str) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=config.get("model", "claude-sonnet-5"),
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    return json.loads(text)


def main():
    config = load_config()
    history = load_history()
    prompt = build_prompt(config, history)
    data = call_model(config, prompt)

    slide_count = len(data["slides"])
    if not (config["slides"]["min"] <= slide_count <= config["slides"]["max"] + 2):
        print(f"경고: 슬라이드 수({slide_count})가 예상 범위를 벗어남", file=sys.stderr)

    now = datetime.now(timezone.utc)
    post_id = now.strftime("%Y%m%d-%H%M%S")
    slug = slugify(data["subtopic"])
    out_path = GENERATED_DIR / f"{post_id}_{slug}.json"

    data["post_id"] = post_id
    data["slug"] = slug
    data["created_at"] = now.isoformat()

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    history["posts"].append({
        "post_id": post_id,
        "subtopic": data["subtopic"],
        "created_at": data["created_at"],
    })
    save_history(history)

    print(str(out_path))


if __name__ == "__main__":
    main()
