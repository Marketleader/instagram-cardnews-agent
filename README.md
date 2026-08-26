# Instagram 카드뉴스 자동 생산·배포 에이전트

**주제**: 몰라서 못 받는 대한민국 정부지원금·혜택 정보 (`config.yaml`에서 변경 가능)

매일 자동으로
1. Claude가 아직 다루지 않은 세부 소재를 골라 카드뉴스 텍스트를 생성하고
2. HTML 템플릿을 카드 이미지(PNG)로 렌더링하고
3. GitHub Pages에 이미지를 배포해 공개 URL을 만들고
4. Instagram Graph API로 캐러셀 게시물을 자동 발행합니다.

GitHub Actions에서 스케줄 실행되므로 개인 PC를 켜둘 필요가 없습니다.

---

## 1. 아키텍처

```
GitHub Actions (매일 지정 시각)
  ├─ scripts/generate_content.py  → Claude API로 카드뉴스 텍스트(JSON) 생성
  ├─ scripts/render_cards.py      → Playwright로 HTML→PNG 카드 이미지 생성 (docs/posts/...)
  ├─ git commit & push            → GitHub Pages가 이미지를 공개 URL로 서빙
  └─ scripts/publish_instagram.py → Instagram Graph API로 캐러셀 게시
```

콘텐츠 이력은 `content/history.json`에 누적되어, 이후 생성 시 같은 소재를 반복하지 않도록 모델에게 전달됩니다.

---

## 2. 사전 준비: Instagram Graph API 연동 (처음부터 시작하는 경우)

Graph API로 자동 게시하려면 **Instagram 비즈니스(또는 크리에이터) 계정 + 연결된 Facebook 페이지 + Meta 개발자 앱 + Access Token**이 필요합니다. 순서대로 진행하세요.

### 2-1. Instagram 계정을 비즈니스 계정으로 전환
- 인스타그램 앱 → 설정 → 계정 유형 전환 → "비즈니스 계정" (또는 "크리에이터 계정") 선택

### 2-2. Facebook 페이지와 연결
- Facebook 페이지가 없다면 새로 하나 만드세요 (개인 프로필과 별개).
- 인스타그램 앱 → 설정 → 계정 센터(Accounts Center) → 연결된 계정에서 방금 만든 Facebook 페이지와 연결합니다.

### 2-3. Meta for Developers 앱 생성
1. https://developers.facebook.com/apps 에서 "앱 만들기"
2. 앱 유형: **Business** 선택
3. 생성된 앱의 대시보드에서 제품 추가 → **Instagram Graph API** 추가 (또는 "Instagram" 제품)

### 2-4. Access Token 발급 (테스트용 단기 토큰)
1. https://developers.facebook.com/tools/explorer 접속
2. 우측 상단에서 방금 만든 앱 선택
3. "User or Page" → User Token 선택 후 아래 권한(permission) 체크:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
4. "Generate Access Token" 클릭 → 로그인/권한 승인
5. 발급된 토큰을 복사 (일단 단기 토큰, 1~2시간 유효)

### 2-5. 단기 토큰 → 장기 토큰(60일) 교환
터미널에서 (앱 ID/시크릿은 앱 대시보드 > 설정 > 기본 설정에서 확인):

```bash
curl -X GET "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id={앱ID}&client_secret={앱시크릿}&fb_exchange_token={2-4에서받은토큰}"
```

응답의 `access_token`이 60일짜리 장기 토큰입니다. 이것을 `IG_ACCESS_TOKEN`으로 사용합니다.

> **권장**: 60일마다 수동 갱신하기 번거로우면, Business Manager(business.facebook.com)에서 **System User**를 만들고 System User 토큰을 발급하면 만료 없이 사용할 수 있습니다 (Business Manager > 설정 > 사용자 > 시스템 사용자 > 토큰 생성, 동일한 권한 부여). 장기 운영 시 이 방식을 강력히 권장합니다.

### 2-6. IG_USER_ID 조회

```bash
# 1) 내 계정에 연결된 페이지 목록
curl "https://graph.facebook.com/v21.0/me/accounts?access_token={장기토큰}"

# 2) 위에서 얻은 page id로 연결된 IG 비즈니스 계정 ID 조회
curl "https://graph.facebook.com/v21.0/{page-id}?fields=instagram_business_account&access_token={장기토큰}"
```

`instagram_business_account.id` 값이 `IG_USER_ID`입니다.

### 2-7. 앱 심사(App Review)에 대해
- 앱이 "개발 모드"여도 **본인이 관리자/개발자/테스터로 등록된 계정**에는 심사 없이 게시할 수 있습니다. 자기 계정에만 쓸 계획이라면 지금 단계로 충분합니다.
- 만약 이 에이전트로 **다른 사람 소유의 인스타그램 계정**에 게시하려면 `instagram_content_publish`에 대한 Advanced Access 심사를 통과해야 합니다.

---

## 3. GitHub 저장소 설정

1. 이 폴더를 GitHub 새 저장소로 push 하세요.
   ```bash
   git init
   git add .
   git commit -m "init: instagram cardnews agent"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
2. **GitHub Pages 활성화**: 저장소 Settings → Pages → Source를 "Deploy from a branch"로, Branch를 `main` / `docs` 로 설정 → 저장.
   - 몇 분 후 `https://<your-username>.github.io/<repo-name>/` 가 열리는지 확인하세요.
3. `config.yaml`의 `github_pages.base_url`을 위에서 확인한 실제 URL로 수정 후 커밋/푸시.
4. **Secrets 등록**: 저장소 Settings → Secrets and variables → Actions → New repository secret
   - `ANTHROPIC_API_KEY`
   - `IG_USER_ID`
   - `IG_ACCESS_TOKEN`

---

## 4. 로컬에서 먼저 테스트하기

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium

copy .env.example .env        # 값 채워넣기 (ANTHROPIC_API_KEY만 있으면 dry-run 가능)

python scripts\main.py --dry-run
```

`docs/posts/<날짜>_<slug>/` 폴더에 카드 이미지 PNG들이 생성되고, IG 실제 게시 없이 콘솔에 이미지 URL과 캡션만 출력됩니다. 이미지가 마음에 드는지 직접 열어서 확인하세요.

---

## 5. 실제 게시 테스트 (GitHub Actions)

1. 저장소 Actions 탭 → "Daily Instagram Card News" 워크플로 선택 → "Run workflow"
2. 먼저 `dry_run`을 `true`로 실행 → 로그에서 이미지 URL/캡션이 잘 나오는지 확인
3. 문제없으면 `dry_run`을 `false`로 다시 실행 → 실제로 인스타그램에 게시됩니다
4. 이후에는 `.github/workflows/daily-post.yml`의 cron 스케줄에 따라 매일 자동 실행됩니다 (기본: 매일 21:00 KST → 필요시 cron 값 수정)

---

## 6. 커스터마이징

- **주제/카테고리**: `config.yaml`의 `topic_theme`, `category_pool` 수정
- **디자인**: `config.yaml`의 `brand` (색상), `templates/card.html.jinja` (레이아웃)
- **슬라이드 수**: `config.yaml`의 `slides.min` / `slides.max`
- **게시 시각**: `.github/workflows/daily-post.yml`의 `cron` 값 (UTC 기준, KST = UTC+9)
- **다른 주제로 완전 교체**: `topic_theme`, `audience`, `category_pool`만 바꾸면 나머지 파이프라인은 그대로 재사용됩니다.

---

## 7. 운영 시 주의사항

- **정보 정확성**: 정부지원금 관련 콘텐츠는 구체적 금액·자격·기간을 단정적으로 제시하지 않고 "최신 공고 확인" 안내를 포함하도록 프롬프트를 설계했습니다. 그래도 정기적으로 실제 게시물을 직접 검수하는 것을 권장합니다. 잘못된 정보는 신뢰도와 법적 책임 문제로 이어질 수 있습니다.
- **토큰 만료**: 장기 토큰(60일) 방식이면 만료 전 갱신 필요. System User 토큰 사용을 권장합니다 (2-5 참고).
- **게시 빈도**: Instagram Graph API는 24시간당 최대 25건 게시 제한이 있습니다. 하루 1건 스케줄이면 문제없습니다.
- **Meta 정책 준수**: 스팸성/오해 소지 콘텐츠, 저작권 침해 이미지 사용 금지. 이 템플릿은 순수 코드 생성 이미지만 사용합니다.
- **첫 실행 전 반드시 dry-run으로 이미지/캡션 품질을 확인**하세요.

---

## 8. 파일 구조

```
instagram-cardnews-agent/
├── config.yaml                 # 주제, 브랜드, 스케줄 등 전체 설정
├── .env.example                 # 로컬 테스트용 환경변수 템플릿
├── requirements.txt
├── content/
│   ├── history.json             # 이미 다룬 소재 이력 (중복 방지)
│   └── generated/                # 생성된 카드뉴스 텍스트(JSON) 아카이브
├── templates/
│   └── card.html.jinja           # 카드 슬라이드 HTML 템플릿
├── scripts/
│   ├── generate_content.py       # Claude로 텍스트 생성
│   ├── render_cards.py           # HTML→PNG 렌더링
│   ├── publish_instagram.py      # IG Graph API 발행
│   └── main.py                   # 로컬 테스트용 오케스트레이터
├── docs/                          # GitHub Pages 루트 (이미지 공개 호스팅)
│   └── posts/<post_id>_<slug>/   # 슬라이드 PNG + manifest.json
└── .github/workflows/daily-post.yml
```
