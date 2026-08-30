"""
성과 지표(fetch_insights.py가 수집한 history.json의 "performance")가 있는
게시물들을 분석해, 어떤 콘텐츠 특성이 높은 반응(저장/공유 위주)을 이끌어냈는지
구체적이고 실행 가능한 패턴을 추출한다.

결과는 content/insights.json에 저장되며, generate_content.py가 다음 콘텐츠를
만들 때 이 인사이트를 프롬프트에 반영한다. 매 실행마다 그 시점까지의 전체
데이터를 다시 종합해 insights.json을 새로 작성한다 (계속 누적되는 목록이
아니라, 더 많은 데이터를 반영한 최신 종합본으로 교체).

사용법: python learn_insights.py
필요 환경변수: GEMINI_API_KEY
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

MIN_POSTS_WITH_DATA = 3


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_category(config: dict, p: dict) -> str | None:
    idx = p.get("category_index")
    if idx is not None and 0 <= idx < len(config["category_pool"]):
        return config["category_pool"][idx]
    return None


def engagement_score(performance: dict) -> float:
    return (
        performance.get("saved", 0) * 3
        + performance.get("shares", 0) * 3
        + performance.get("comments", 0) * 2
        + performance.get("likes", 0) * 1
    )


def collect_scored_posts(config: dict, history: dict) -> list[dict]:
    scored = []
    for p in history["posts"]:
        performance = p.get("performance")
        if not performance:
            continue
        cover_title = None
        content_file = p.get("content_file")
        if content_file:
            content_path = GENERATED_DIR / content_file
            if content_path.exists():
                with open(content_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                cover_title = content.get("cover", {}).get("title")
        scored.append({
            "subtopic": p["subtopic"],
            "category": resolve_category(config, p),
            "cover_title": cover_title,
            "performance": performance,
            "score": engagement_score(performance),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def build_prompt(config: dict, scored_posts: list[dict]) -> str:
    return f"""당신은 인스타그램 콘텐츠 성과를 분석하는 데이터 분석가입니다.
아래는 "{config['topic_theme']}" 주제 카드뉴스 게시물들과 실제 성과 지표
(좋아요/댓글/저장/공유/도달, score는 저장·공유에 가중치를 둔 종합 참여도 점수)
입니다. score가 높은 순으로 정렬되어 있습니다.

{json.dumps(scored_posts, ensure_ascii=False, indent=2)}

작업: 어떤 카테고리·후킹 방식·정보 구조·어조가 높은 반응(특히 저장·공유)을
이끌어냈는지, 반대로 낮은 반응을 보인 게시물들의 공통적인 약점은 무엇인지
분석하세요. 다음 콘텐츠 생성 시 실제로 적용할 수 있는 구체적이고 실행 가능한
지침을 5~10개 뽑아내세요. 막연한 조언("더 흥미롭게 작성하라") 대신 구체적
패턴("숫자나 금액이 커버 제목에 들어간 게시물의 저장률이 높았다" 등 실제
데이터에서 관찰되는 근거 있는 패턴)을 제시하세요. 데이터가 적어 명확한
패턴을 찾기 어려운 항목은 억지로 만들어내지 말고 생략하세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 설명, 마크다운 코드펜스 없이
순수 JSON만 출력합니다.
{{
  "insights": ["구체적 지침 1", "구체적 지침 2", "..."]
}}
"""


def call_model(config: dict, prompt: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=config.get("model", "gemini-3.6-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=3000,
        ),
    )
    text = resp.text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    return json.loads(text)


def main():
    config = load_config()
    history = load_history()
    scored_posts = collect_scored_posts(config, history)

    if len(scored_posts) < MIN_POSTS_WITH_DATA:
        print(
            f"성과 데이터가 있는 게시물이 {len(scored_posts)}건뿐입니다 "
            f"({MIN_POSTS_WITH_DATA}건 미만) — 분석을 건너뜁니다.",
            file=sys.stderr,
        )
        return

    prompt = build_prompt(config, scored_posts)
    result = call_model(config, prompt)

    output = {
        "insights": result["insights"],
        "based_on_posts": len(scored_posts),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(INSIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(str(INSIGHTS_PATH))


if __name__ == "__main__":
    main()
