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
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
HISTORY_PATH = ROOT / "content" / "history.json"
GENERATED_DIR = ROOT / "content" / "generated"
INSIGHTS_PATH = ROOT / "content" / "insights.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"posts": []}
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_insights() -> list[str]:
    """learn_insights.py가 성과 데이터에서 뽑아낸 인사이트를 불러온다 (없으면 빈 리스트)."""
    if not INSIGHTS_PATH.exists():
        return []
    with open(INSIGHTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("insights", [])


def save_history(history: dict) -> None:
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40] if text else "post"


MAX_SUBTOPICS_PER_CATEGORY_SHOWN = 15
SATURATED_THRESHOLD = 5


def category_coverage(config: dict, history: dict) -> list[dict]:
    """카테고리별 지금까지의 발행 현황(건수 + 다룬 세부 소재)을 계산한다."""
    coverage = []
    for idx, cat in enumerate(config["category_pool"]):
        posts_in_cat = [p for p in history["posts"] if p.get("category_index") == idx]
        coverage.append({
            "index": idx,
            "category": cat,
            "count": len(posts_in_cat),
            "covered_subtopics": [p["subtopic"] for p in posts_in_cat][-MAX_SUBTOPICS_PER_CATEGORY_SHOWN:],
        })
    return coverage


def build_prompt(config: dict, history: dict, insights: list[str] | None = None) -> str:
    min_slides = config["slides"]["min"]
    max_slides = config["slides"]["max"]
    coverage = category_coverage(config, history)

    coverage_lines = []
    for c in coverage:
        status = "포화 — 신중히 선택" if c["count"] >= SATURATED_THRESHOLD else (
            "아직 적음 — 우선 고려" if c["count"] <= 1 else "보통"
        )
        subtopics = json.dumps(c["covered_subtopics"], ensure_ascii=False) if c["covered_subtopics"] else "[]"
        coverage_lines.append(
            f'{c["index"]}: "{c["category"]}" (누적 {c["count"]}건, {status})\n'
            f'   이미 다룬 세부 소재: {subtopics}'
        )
    coverage_block = "\n".join(coverage_lines)

    insights_block = ""
    if insights:
        insights_lines = "\n".join(f"- {i}" for i in insights)
        insights_block = f"""
아래는 과거 실제 게시물의 성과(저장/공유/댓글 등)를 분석해 뽑아낸 인사이트입니다.
가능한 범위에서 실제로 반영하세요 (단, 위의 정보 정확성 제약보다 우선하지는 마세요):
{insights_lines}
"""

    return f"""당신은 인스타그램 카드뉴스 전문 에디터입니다.
주제 테마: "{config['topic_theme']}"
타깃 독자: {config['audience']}

아래는 카테고리별 지금까지의 누적 발행 현황입니다 (인덱스: 카테고리명, 건수, 이미 다룬 세부 소재 목록):
{coverage_block}
{insights_block}
작업:
1. 카테고리를 고르세요.
   - 건수가 적은("아직 적음") 카테고리를 우선 고려하세요. 특정 카테고리에 콘텐츠가 쏠리지
     않도록 다양성을 유지하는 것이 중요합니다.
   - "포화" 카테고리는 가능하면 피하세요. 다룰 만한 새로운 세부 소재가 정말 없는 경우가
     아니라면 다른 카테고리를 선택하세요.
   - 부득이하게 포화된 카테고리를 다시 선택해야 한다면, 반드시 그 카테고리의 "이미 다룬
     세부 소재" 목록을 검토하여: (a) 그 목록과 명백히 겹치지 않는 완전히 새로운 각도를
     고르거나, (b) 기존 소재들이 놓치고 있을 법한 조건·예외 케이스·놓치기 쉬운 주의사항·
     실전 신청 팁 등 더 깊고 구체적인 정보를 반드시 추가하여 기존 게시물 대비 실질적으로
     더 유용해야 합니다. 표현만 바꾼 재탕(사실상 동일한 내용의 반복)은 금지합니다.
2. 고른 카테고리 안에서 아주 구체적인 세부 소재 하나를 정하세요. 반드시 해당 카테고리의
   "이미 다룬 세부 소재" 목록과 겹치지 않아야 합니다.
   (예: "청년 자산형성" 카테고리라면 -> "매달 일정 금액을 저축하면 정부가 추가로 얹어주는 유형의
   청년 자산형성 상품, 신청 자격과 놓치기 쉬운 조건" 처럼 좁힐 것)
3. {min_slides}~{max_slides}장짜리 카드뉴스 슬라이드 콘텐츠를 작성하세요.
4. 반드시 아래 JSON 형식으로만 응답하세요. 다른 설명, 마크다운 코드펜스 없이 순수 JSON만 출력합니다.

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
  "category_index": 0,
  "subtopic": "이번에 다루는 세부 소재 한 줄 요약",
  "cover": {{"kicker": "카테고리 라벨 (예: 청년 지원)", "title": "후킹되는 커버 제목 (두 줄 이내)", "subtitle": "부제 한 줄"}},
  "slides": [
    {{"title": "슬라이드 소제목", "body": "슬라이드 본문"}}
  ],
  "outro": {{"title": "마무리 제목", "body": "요약 + 최신 공고 확인 안내 문구", "cta": "저장하고 나중에 확인하기 같은 행동 유도 문구"}},
  "caption": "인스타그램 게시물 캡션 전체 텍스트 (이모지 적절히 사용, 3~6문단, 마지막에 해시태그 제외)",
  "hashtags": ["#정부지원금", "#태그2", "... 15~20개, # 포함"]
}}
("category_index"는 위 카테고리 목록의 인덱스 번호와 정확히 일치해야 합니다.)
"""


def call_model(config: dict, prompt: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=config.get("model", "gemini-3.6-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=6000,
        ),
    )
    text = resp.text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    # strict=False: 모델이 문자열 안에 이스케이프 없는 개행 등 제어 문자를
    # 그대로 넣는 경우가 있어, 엄격 모드에서는 파싱이 깨진다.
    return json.loads(text, strict=False)


def main():
    config = load_config()
    history = load_history()
    insights = load_insights()
    prompt = build_prompt(config, history, insights)
    data = call_model(config, prompt)

    slide_count = len(data["slides"])
    if not (config["slides"]["min"] <= slide_count <= config["slides"]["max"] + 2):
        print(f"경고: 슬라이드 수({slide_count})가 예상 범위를 벗어남", file=sys.stderr)

    category_index = data.get("category_index")
    if not isinstance(category_index, int) or not (0 <= category_index < len(config["category_pool"])):
        print(f"경고: category_index({category_index})가 유효하지 않음, 미분류로 기록", file=sys.stderr)
        category_index = None
    data["category_index"] = category_index
    data["category"] = config["category_pool"][category_index] if category_index is not None else None

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
        "category_index": category_index,
        "created_at": data["created_at"],
        "content_file": out_path.name,
        "published": False,
    })
    save_history(history)

    print(str(out_path))


if __name__ == "__main__":
    main()
