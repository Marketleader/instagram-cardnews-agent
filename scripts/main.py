"""
전체 파이프라인 오케스트레이터: 콘텐츠 생성 -> 이미지 렌더링 -> (git push는 워크플로에서 처리) -> IG 게시

로컬 테스트:
  python scripts/main.py --dry-run
GitHub Actions 실행:
  python scripts/main.py
"""
import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def run(cmd: list[str]) -> str:
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip().splitlines()[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    content_path = run([sys.executable, "scripts/generate_content.py"])
    print(f"콘텐츠 생성 완료: {content_path}")

    manifest_path = run([sys.executable, "scripts/render_cards.py", content_path])
    print(f"이미지 렌더링 완료: {manifest_path}")

    publish_cmd = [sys.executable, "scripts/publish_instagram.py", manifest_path]
    if args.dry_run:
        publish_cmd.append("--dry-run")

    print("$", " ".join(publish_cmd))
    result = subprocess.run(publish_cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
