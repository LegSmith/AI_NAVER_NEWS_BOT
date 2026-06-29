# 🤖 AI 개발자 뉴스 봇 (NAVER → Discord)

네이버 뉴스에서 **AI 관련 기사를 수집**하고, 로컬 LLM(Ollama)으로 **개발자와 가장 관련 있는 TOP 5**를 선별·요약해 **Discord 채널로 전송**하는 봇입니다.

매일 한 번 실행하면 직전 24시간(오전 9시 기준)의 AI 뉴스 중 실무 개발자에게 쓸모 있는 것만 추려서 보내줍니다.

---

## ✨ 주요 기능

- 📰 **네이버 뉴스 수집** — 19개 AI 키워드(LLM, RAG, GPU, MLOps 등)로 최신 기사 수집
- 🧹 **로컬 사전 필터링** — 키워드 기반 점수화로 후보 20개 추림 (LLM 비용/시간 절감)
- 🧠 **LLM 큐레이션** — "개발자 실무 관련성" 기준으로 **TOP 5 선별 + 1줄 요약** (Ollama/OpenAI/Gemini/Claude 선택 가능)
- 🔁 **중복 방지** — SQLite로 이미 보낸 기사 기록, 재전송 방지
- 💬 **Discord 전송** — 제목/요약/링크 중심의 가독성 좋은 포맷으로 전송

---

## 🗂️ 동작 흐름

```
네이버 뉴스 API
   │  (키워드별 최신순 수집, 24h 윈도우)
   ▼
수집 + 중복 제거 (SQLite)
   │
   ▼
로컬 점수화 → 후보 TOP 20 (prefilter)
   │
   ▼
LLM 선별/요약 → 개발자 관련 TOP 5
   (Ollama / OpenAI / Gemini / Claude 중 택1)
   │
   ▼
Discord 웹훅 전송
   │
   ▼
전송 기록 저장 (SQLite, 다음날 중복 방지)
```

---

## 📦 요구 사항

- Python 3.12+
- 네이버 검색 API 키 ([developers.naver.com](https://developers.naver.com))
- Discord 웹훅 URL
- LLM provider 중 하나:
  - [Ollama](https://ollama.com/) 로컬 실행 (기본값, 무료) **또는**
  - OpenAI / Google Gemini / Anthropic Claude API 키 (클라우드)

---

## 🚀 설치 & 실행

### 1. 저장소 클론 및 가상환경

```bash
git clone <repo-url>
cd MAIL_NAVER_NEWS

python3 -m venv .venv
source .venv/bin/activate

# 공통(필수)
pip install requests python-dotenv

# 사용할 LLM provider의 SDK만 추가로 설치 (택1)
# pip install openai          # LLM_PROVIDER=openai
# pip install google-genai    # LLM_PROVIDER=gemini
# pip install anthropic       # LLM_PROVIDER=claude
# (ollama는 별도 SDK 불필요 — 로컬 서버만 띄우면 됨)
```

### 2. 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `NAVER_CLIENT_ID` | 네이버 API Client ID | (필수) |
| `NAVER_CLIENT_SECRET` | 네이버 API Client Secret | (필수) |
| `DISCORD_WEBHOOK_URL` | Discord 웹훅 URL | (필수) |
| `MAX_FINAL_ITEMS` | 최종 전송 기사 수 (TOP N) | `5` |
| `MAX_CANDIDATES_FOR_AI` | LLM 선별 후보 수 | `20` |
| `DB_PATH` | SQLite DB 경로 | `./news_history.db` |
| `LLM_PROVIDER` | LLM 제공자 (`ollama`/`openai`/`gemini`/`claude`) | `ollama` |

> ⚠️ `.env`에는 실제 키/웹훅이 들어가므로 **절대 깃에 커밋하지 마세요.** (`.gitignore`에 이미 포함되어 있습니다.)

### 3. LLM provider 선택

`LLM_PROVIDER` 값에 따라 필요한 변수만 채우면 됩니다. (sLLM이든 클라우드든 동일한 파이프라인으로 동작)

#### 🖥️ Ollama (로컬 sLLM, 기본값)

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_KEEP_ALIVE=0      # 0=즉시 해제, -1=무한, "30m"/"24h" 가능
```
```bash
ollama pull gemma3:4b   # 모델 준비
```

#### ☁️ OpenAI

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

#### ☁️ Google Gemini

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash
```

#### ☁️ Anthropic Claude

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-8
```

> 클라우드 provider는 해당 SDK 설치가 필요합니다 (`pip install openai` / `google-genai` / `anthropic`).
> 코드가 **지연 import** 구조라, 선택한 provider의 패키지만 설치하면 됩니다.

### 4. 실행

```bash
python main.py
```

---

## ⏰ 매일 자동 실행 (cron 예시)

매일 오전 9시 5분에 실행:

```bash
crontab -e
```

```cron
5 9 * * * cd /path/to/MAIL_NAVER_NEWS && .venv/bin/python main.py >> logs/cron.log 2>&1
```

---

## 📨 Discord 출력 예시

```
🤖 AI 개발자 뉴스 TOP 5
🗓️ 2026-06-28 09:00 ~ 2026-06-29 09:00 KST

━━━━━━━━━━━━━━━━━━━━
1. 기사 제목
📝 핵심 요약 한 줄
🔗 https://...
⚙️ 개발자 관점: 이 기사가 개발자에게 중요한 이유
⭐⭐⭐⭐⭐  ·  🕒 06-28 14:30
```

---

## 🛠️ 선별 기준 커스터마이징

- **검색 키워드**: `main.py`의 `SEARCH_KEYWORDS` 리스트
- **로컬 점수 가중치**: `local_score()`의 `high_keywords` / `low_keywords`
- **LLM 선별 프롬프트**: `ai_select_and_summarize()` 내부 프롬프트
- **전송 개수**: `.env`의 `MAX_FINAL_ITEMS`

---

## 📁 프로젝트 구조

```
MAIL_NAVER_NEWS/
├── main.py            # 전체 파이프라인
├── .env               # 실제 환경변수 (git 제외)
├── .env.example       # 환경변수 템플릿
├── .gitignore
├── README.md
├── news_history.db    # 전송 기록 (git 제외, 자동 생성)
└── logs/              # 로그 (git 제외)
```
