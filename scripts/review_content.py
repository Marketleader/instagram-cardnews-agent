"""
generate_content.py가 만든 카드뉴스 초안을 세 명의 비판적 검토자 관점
(도메인 전문가 / 천재 크리에이티브 디렉터 / 투자자)에서 교차 검증하고,
발견된 문제를 모두 해결한 개선판으로 콘텐츠 JSON을 덮어쓴다.

검토 노트(각 관점이 지적한 문제 + 종합 총평)는 같은 폴더에
<post_id>_<slug>.review.json 으로 별도 저장해 검토 과정을 추적할 수 있게 한다.

사용법: python review_content.py <content_json_path>
출력: content_json_path (stdout) — render_cards.py에 그대로 넘길 수 있도록 입력과 동일한 경로를 출력
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_prompt(data: dict, config: dict) -> str:
    return f"""당신은 지금부터 세 명의 매우 까다로운 검토자 역할을 동시에 수행하며,
아래 카드뉴스 초안을 발행 직전 최종 관문으로서 교차 검증합니다.

1. [도메인 전문가] 대한민국 정부지원금·복지제도 정보를 다루는 이 계정의 신뢰도를 책임지는 전문가.
   확정되지 않은 금액/자격/기간을 단정적으로 제시하지 않는지, 실존하지 않는 제도를 지어내지
   않았는지, "정확한 조건은 최신 공고를 확인하라"는 안내가 충분히 명확한지 검증합니다.
2. [천재 크리에이티브 디렉터] 후킹력, 문장 리듬, 군더더기, 감성 임팩트를 극한까지 끌어올리는
   업계 최고의 에디터. 첫 슬라이드에서 스크롤을 멈추게 하는지, 진부한 표현이나 늘어지는
   문장은 없는지, 타깃 독자("{config['audience']}")의 말투와 눈높이에 맞는지 가차없이 지적합니다.
   특히 "꼭 챙기세요!", "반드시 확인하세요!" 같은 가르치거나 다그치는 명령형 어투가 섞여
   있다면 반드시 지적하고, "이런 방법도 있으니 살펴보셔도 좋아요" 식의 따뜻한 권유형 어투로
   고칠 것을 요구합니다.
3. [투자자] 이 콘텐츠 제작·홍보에 실제로 돈을 투자할지 결정하는 냉정한 투자자. 저장/공유될
   가능성, 다른 정부지원금 콘텐츠와의 차별화, 정보 밀도 대비 슬라이드 수의 효율성, 리스크
   대비 기대 성과를 기준으로 판단합니다.

검토 대상 카드뉴스 초안 (JSON):
{json.dumps(data, ensure_ascii=False, indent=2)}

작업:
1. 세 관점 각각에서 발견한 구체적 문제점을 나열하세요. 정말 문제가 없다면 배열에
   "특이사항 없음"이라는 문자열 하나만 담으세요. 막연한 칭찬이 아니라 구체적으로 무엇이
   왜 문제인지 지적해야 합니다.
2. 발견한 모든 문제를 실제로 해결한 최종 개선판을 작성하세요. 슬라이드 수와 전체 구조
   (cover/slides/outro/caption/hashtags)는 원본과 동일하게 유지하되, 문구는 자유롭게
   다듬으세요. 정보 정확성에 대한 제약(구체적 수치 단정 금지, 최신 공고 확인 안내 포함)은
   원본 생성 시 규칙과 동일하게 지켜야 합니다.
3. 반드시 아래 JSON 형식으로만 응답하세요. 다른 설명, 마크다운 코드펜스 없이 순수 JSON만
   출력합니다.

JSON 스키마:
{{
  "review": {{
    "expert_notes": ["전문가가 지적한 문제점들"],
    "genius_notes": ["크리에이티브 디렉터가 지적한 문제점들"],
    "investor_notes": ["투자자가 지적한 문제점들"],
    "verdict": "종합 한 줄 총평"
  }},
  "revised": {{
    "cover": {{"kicker": "...", "title": "...", "subtitle": "..."}},
    "slides": [{{"title": "...", "body": "..."}}],
    "outro": {{"title": "...", "body": "...", "cta": "..."}},
    "caption": "...",
    "hashtags": ["..."]
  }}
}}
"""


def call_model(config: dict, prompt: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=config.get("model", "gemini-3.6-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=8000,
        ),
    )
    text = resp.text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    # strict=False: 모델이 문자열 안에 이스케이프 없는 개행 등 제어 문자를
    # 그대로 넣는 경우가 있어, 엄격 모드에서는 파싱이 깨진다.
    return json.loads(text, strict=False)


def main():
    if len(sys.argv) != 2:
        print("사용법: python review_content.py <content_json_path>", file=sys.stderr)
        sys.exit(1)

    content_path = Path(sys.argv[1])
    with open(content_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    config = load_config()
    prompt = build_prompt(data, config)
    result = call_model(config, prompt)

    revised = result["revised"]
    data["cover"] = revised["cover"]
    data["slides"] = revised["slides"]
    data["outro"] = revised["outro"]
    data["caption"] = revised["caption"]
    data["hashtags"] = revised["hashtags"]

    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    review_path = content_path.with_name(content_path.stem + ".review.json")
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(result["review"], f, ensure_ascii=False, indent=2)

    print(str(content_path))


if __name__ == "__main__":
    main()
