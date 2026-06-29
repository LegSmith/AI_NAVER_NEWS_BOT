#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import html
import time
import hashlib
import sqlite3
import requests

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


# =========================
# .env 로드
# =========================

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# =========================
# 기본 설정
# =========================

KST = timezone(timedelta(hours=9))

# Naver API
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# LLM provider 선택: ollama | openai | gemini | claude
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

# Ollama (로컬 sLLM)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "0")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Google Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Anthropic Claude
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

# DB
DB_PATH = os.getenv("DB_PATH", "./news_history.db")

# AI 선별 개수
MAX_FINAL_ITEMS = int(os.getenv("MAX_FINAL_ITEMS", "5"))
MAX_CANDIDATES_FOR_AI = int(os.getenv("MAX_CANDIDATES_FOR_AI", "20"))

# 검색 키워드
SEARCH_KEYWORDS = [
    "AI",
    "인공지능",
    "생성형 AI",
    "LLM",
    "딥러닝",
    "머신러닝",
    "RAG",
    "벡터DB",
    "GPU",
    "CUDA",
    "PyTorch",
    "TensorFlow",
    "오픈소스 LLM",
    "AI 반도체",
    "온디바이스 AI",
    "모델 경량화",
    "AI 보안",
    "AI 에이전트",
    "MLOps",
]


# =========================
# 공통 유틸
# =========================

def clean_text(value: str) -> str:
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def make_news_id(item: dict) -> str:
    base = item.get("originallink") or item.get("url") or item.get("link") or item.get("title", "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def parse_naver_pubdate(pubdate: str) -> datetime:
    """
    예:
    Mon, 15 Jun 2026 08:30:00 +0900
    """
    dt = parsedate_to_datetime(pubdate)
    return dt.astimezone(KST)


def parse_naver_pubdate_iso(value: str) -> datetime:
    """
    item["pub_date"]에 저장된 ISO 포맷 문자열을 KST datetime으로 변환.
    예: 2026-06-15T08:30:00+09:00
    """
    return datetime.fromisoformat(value).astimezone(KST)


def get_collect_window(now: datetime | None = None):
    """
    실행 시점 기준 가장 최근 09:00을 종료 시각으로 잡음.

    예:
    2026-06-15 09:05 실행
    → 2026-06-14 09:00 이상 ~ 2026-06-15 09:00 미만

    2026-06-15 08:30 실행
    → 2026-06-13 09:00 이상 ~ 2026-06-14 09:00 미만
    """
    if now is None:
        now = datetime.now(KST)

    end_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)

    if now < end_dt:
        end_dt = end_dt - timedelta(days=1)

    start_dt = end_dt - timedelta(days=1)

    return start_dt, end_dt


def parse_keep_alive(value: str):
    """
    Ollama keep_alive 값 변환.
    - "0"   → 0
    - "-1"  → -1
    - "30m" → "30m"
    - "24h" → "24h"
    """
    try:
        return int(value)
    except Exception:
        return value


# =========================
# SQLite
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_news (
            news_id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            pub_date TEXT,
            sent_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def already_sent(news_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM sent_news WHERE news_id = ?", (news_id,))
    row = cur.fetchone()

    conn.close()

    return row is not None


def mark_sent(items: list[dict]):
    if not items:
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    now = datetime.now(KST).isoformat()

    for item in items:
        cur.execute("""
            INSERT OR IGNORE INTO sent_news (
                news_id,
                title,
                url,
                pub_date,
                sent_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            item["news_id"],
            item["title"],
            item["url"],
            item["pub_date"],
            now
        ))

    conn.commit()
    conn.close()


# =========================
# 네이버 뉴스 수집
# =========================

def fetch_naver_news(query: str, start: int = 1) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    params = {
        "query": query,
        "display": 100,
        "start": start,
        "sort": "date",
    }

    res = requests.get(
        NAVER_NEWS_API_URL,
        headers=headers,
        params=params,
        timeout=20,
    )

    res.raise_for_status()

    data = res.json()
    return data.get("items", [])


def collect_news(start_dt: datetime, end_dt: datetime) -> list[dict]:
    collected = {}

    print(f"[INFO] 수집 범위: {start_dt} ~ {end_dt}")

    for query in SEARCH_KEYWORDS:
        print(f"[INFO] 검색어 수집: {query}")

        for start in range(1, 1001, 100):
            try:
                items = fetch_naver_news(query, start=start)
            except Exception as e:
                print(f"[ERROR] 네이버 API 실패 query={query}, start={start}, error={e}")
                break

            if not items:
                break

            page_dates = []

            for raw in items:
                try:
                    pub_dt = parse_naver_pubdate(raw.get("pubDate", ""))
                except Exception:
                    continue

                page_dates.append(pub_dt)

                # 오늘 09:00 이후 기사는 다음 수집 대상
                if pub_dt >= end_dt:
                    continue

                # 전날 09:00 이전 기사는 이번 수집 대상 아님
                if pub_dt < start_dt:
                    continue

                title = clean_text(raw.get("title", ""))
                desc = clean_text(raw.get("description", ""))
                url = raw.get("originallink") or raw.get("link")

                item = {
                    "query": query,
                    "title": title,
                    "description": desc,
                    "url": url,
                    "naver_link": raw.get("link", ""),
                    "pub_date": pub_dt.isoformat(),
                }

                news_id = make_news_id(item)
                item["news_id"] = news_id

                if already_sent(news_id):
                    continue

                collected[news_id] = item

            # 최신순이므로 현재 페이지의 가장 최신 기사도 시작 시간보다 과거면 중단
            if page_dates and max(page_dates) < start_dt:
                break

            time.sleep(0.2)

    result = list(collected.values())

    print(f"[INFO] 수집된 신규 기사 수: {len(result)}")

    return result


# =========================
# 1차 로컬 점수화
# =========================

def local_score(item: dict) -> int:
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()

    high_keywords = [
        "llm",
        "rag",
        "vector",
        "벡터",
        "gpu",
        "cuda",
        "pytorch",
        "tensorflow",
        "모델",
        "추론",
        "학습",
        "파인튜닝",
        "에이전트",
        "오픈소스",
        "api",
        "보안",
        "취약점",
        "클라우드",
        "반도체",
        "nvidia",
        "엔비디아",
        "openai",
        "anthropic",
        "deepmind",
        "mistral",
        "meta",
        "llama",
        "gemma",
        "qwen",
        "서빙",
        "성능",
        "최적화",
        "온디바이스",
        "데이터센터",
        "mlops",
        "쿠버네티스",
        "kubernetes",
        "도커",
        "docker",
        "추론서버",
        "모델 경량화",
    ]

    low_keywords = [
        "주가",
        "급등",
        "급락",
        "투자",
        "채용",
        "행사",
        "체험",
        "이벤트",
        "출시 행사",
        "업무협약",
        "mou",
        "홍보",
        "캠페인",
        "관련주",
        "증시",
    ]

    score = 0

    for kw in high_keywords:
        if kw in text:
            score += 2

    for kw in low_keywords:
        if kw in text:
            score -= 1

    return score


def prefilter_candidates(items: list[dict]) -> list[dict]:
    for item in items:
        item["local_score"] = local_score(item)

    items = sorted(
        items,
        key=lambda x: (x.get("local_score", 0), x.get("pub_date", "")),
        reverse=True,
    )

    return items[:MAX_CANDIDATES_FOR_AI]


# =========================
# JSON 파싱
# =========================

def extract_json(text: str) -> dict:
    """
    모델 응답에서 JSON만 최대한 안전하게 추출.
    """
    if not text:
        raise ValueError("모델 응답이 비어 있음")

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```json", "", text)
        text = re.sub(r"^```", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError(f"JSON 추출 실패: {text[:300]}")

    return json.loads(match.group(0))


# =========================
# Ollama 호출
# =========================

def call_ollama(prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": parse_keep_alive(OLLAMA_KEEP_ALIVE),
        "options": {
            "temperature": 0,
            "num_ctx": 32768
        }
    }

    res = requests.post(
        url,
        json=payload,
        timeout=300,
    )

    res.raise_for_status()

    data = res.json()

    print(
        f"[INFO] Ollama usage: "
        f"model={data.get('model')}, "
        f"load_duration={data.get('load_duration')}, "
        f"prompt_eval_count={data.get('prompt_eval_count')}, "
        f"eval_count={data.get('eval_count')}"
    )

    return data.get("response", "")


# =========================
# 클라우드 LLM 호출 (OpenAI / Gemini / Claude)
# =========================

def call_openai(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 없습니다.")

    # 지연 import: openai를 쓸 때만 패키지가 필요
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )

    usage = getattr(resp, "usage", None)
    print(f"[INFO] OpenAI usage: model={OPENAI_MODEL}, usage={usage}")

    return resp.choices[0].message.content or ""


def call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 없습니다.")

    # 지연 import: gemini를 쓸 때만 google-genai 패키지가 필요
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    print(f"[INFO] Gemini usage: model={GEMINI_MODEL}, usage={getattr(resp, 'usage_metadata', None)}")

    return resp.text or ""


def call_anthropic(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 없습니다.")

    # 지연 import: claude를 쓸 때만 anthropic 패키지가 필요
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    print(f"[INFO] Anthropic usage: model={ANTHROPIC_MODEL}, usage={message.usage}")

    # content는 블록 리스트 → text 블록만 이어붙임
    return "".join(block.text for block in message.content if block.type == "text")


def call_llm(prompt: str) -> str:
    """LLM_PROVIDER 값에 따라 적절한 provider로 분기."""
    provider = LLM_PROVIDER.lower()

    if provider == "ollama":
        return call_ollama(prompt)
    if provider == "openai":
        return call_openai(prompt)
    if provider in ("gemini", "google"):
        return call_gemini(prompt)
    if provider in ("claude", "anthropic"):
        return call_anthropic(prompt)

    raise RuntimeError(f"지원하지 않는 LLM_PROVIDER: {LLM_PROVIDER}")


# =========================
# AI 선별 / 요약
# =========================

def ai_select_and_summarize(items: list[dict], start_dt: datetime, end_dt: datetime) -> list[dict]:
    if not items:
        return []

    compact_items = []

    for idx, item in enumerate(items, start=1):
        compact_items.append({
            "idx": idx,
            "title": item["title"],
            "description": item["description"],
            "url": item["url"],
            "pub_date": item["pub_date"],
            "local_score": item.get("local_score", 0),
        })

    prompt = f"""
너는 AI 개발자용 뉴스 큐레이터다.

수집 범위:
{start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')} KST

아래 뉴스 목록 중에서 "AI 관련 + 개발자와 가장 관련 있는" 기사 TOP {MAX_FINAL_ITEMS}개만 엄선해라.

선별 기준 (가장 중요):
- 반드시 AI/머신러닝/LLM 관련 기사여야 함. AI와 무관하면 절대 선택하지 마라.
- 실무 개발자가 직접 써먹을 수 있는 기사를 최우선으로 선택:
  - LLM, RAG, 벡터DB, 모델 학습/추론/파인튜닝, 프롬프트 엔지니어링
  - GPU, CUDA, PyTorch, TensorFlow, 모델 경량화, 추론 서버/서빙
  - MLOps, AI 인프라, 쿠버네티스/도커 기반 배포, API/SDK, 오픈소스 모델 공개
  - AI 보안/취약점, 아키텍처 설계, 성능 최적화, 장애 대응, 비용 절감
- 단순 기업 홍보, 주가/투자, 행사/MOU, 정책, 일반 소비자 서비스, 연예/마케팅성 기사는 제외하라.
- 중요도(importance)는 "개발자 실무 관련성"을 기준으로 1~5점.
- 정확히 가장 관련 높은 {MAX_FINAL_ITEMS}개 이하만 선택. 애매하면 차라리 적게 선택하라.
- 기사 idx는 반드시 입력 뉴스 목록의 idx 값을 그대로 사용

반환 규칙:
- 반드시 순수 JSON만 반환해라
- 마크다운 코드블록 금지
- 설명 문장 금지
- JSON 외 텍스트 금지
- items 배열이 비어도 JSON 형식은 유지해라

반환 형식:
{{
  "items": [
    {{
      "idx": 1,
      "importance": 5,
      "summary": "핵심 요약 1문장",
      "dev_impact": "AI 개발자에게 중요한 이유 1문장",
      "reason": "선별 이유 1문장"
    }}
  ]
}}

뉴스 목록:
{json.dumps(compact_items, ensure_ascii=False)}
"""

    try:
        result_text = call_llm(prompt)
        result_json = extract_json(result_text)

    except Exception as e:
        print(f"[ERROR] AI 선별 실패(provider={LLM_PROVIDER}): {e}")

        selected = items[:MAX_FINAL_ITEMS]

        for item in selected:
            item["importance"] = min(5, max(1, item.get("local_score", 1)))
            item["reason"] = "AI 선별 실패로 로컬 점수 기준 선별"
            item["summary"] = item["description"][:180] if item["description"] else item["title"]
            item["dev_impact"] = "기사 원문 확인 필요"

        return selected

    selected = []

    for ai_item in result_json.get("items", []):
        idx = ai_item.get("idx")

        if not isinstance(idx, int):
            continue

        if idx < 1 or idx > len(items):
            continue

        original = items[idx - 1].copy()

        try:
            importance = int(ai_item.get("importance", 3))
        except Exception:
            importance = 3

        if importance < 1:
            importance = 1

        if importance > 5:
            importance = 5

        original["importance"] = importance
        original["summary"] = clean_text(ai_item.get("summary", ""))
        original["dev_impact"] = clean_text(ai_item.get("dev_impact", ""))
        original["reason"] = clean_text(ai_item.get("reason", ""))

        if not original["summary"]:
            original["summary"] = original["description"][:180] if original["description"] else original["title"]

        if not original["dev_impact"]:
            original["dev_impact"] = "AI 개발자가 참고할 만한 기술 동향으로 판단됨"

        if not original["reason"]:
            original["reason"] = "AI 개발 관련성이 높아 선별됨"

        selected.append(original)

    selected = sorted(
        selected,
        key=lambda x: x.get("importance", 0),
        reverse=True,
    )

    return selected[:MAX_FINAL_ITEMS]


# =========================
# 디스코드 메시지
# =========================

def split_message(text: str, limit: int = 1800) -> list[str]:
    chunks = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    return chunks


def build_discord_message(items: list[dict], start_dt: datetime, end_dt: datetime) -> str:
    header = (
        f"# 🤖 AI 개발자 뉴스 TOP {MAX_FINAL_ITEMS}\n"
        f"🗓️ {start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')} KST\n"
    )

    if not items:
        return header + "\n오늘은 전송할 만한 AI 개발 관련 뉴스가 없습니다."

    lines = [header]

    for i, item in enumerate(items, start=1):
        importance = item.get("importance", 3)
        stars = "⭐" * importance

        # 발행시각: 날짜/시간만 간결하게
        pub = item.get("pub_date", "")
        try:
            pub = parse_naver_pubdate_iso(pub).strftime("%m-%d %H:%M")
        except Exception:
            pass

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"**{i}. {item['title']}**")
        lines.append(f"📝 {item.get('summary', '')}")
        lines.append(f"🔗 {item['url']}")
        lines.append(f"⚙️ 개발자 관점: {item.get('dev_impact', '')}")
        lines.append(f"{stars}  ·  🕒 {pub}")
        lines.append("")

    return "\n".join(lines)


def send_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL 환경변수가 없습니다.")

    chunks = split_message(message)

    for idx, chunk in enumerate(chunks, start=1):
        res = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": chunk},
            timeout=20,
        )

        if res.status_code >= 300:
            raise RuntimeError(f"Discord 전송 실패: {res.status_code}, {res.text}")

        print(f"[INFO] Discord 전송 완료: chunk={idx}/{len(chunks)}")

        time.sleep(0.5)


# =========================
# 환경 검증
# =========================

def validate_env():
    missing = []

    if not NAVER_CLIENT_ID:
        missing.append("NAVER_CLIENT_ID")

    if not NAVER_CLIENT_SECRET:
        missing.append("NAVER_CLIENT_SECRET")

    if not DISCORD_WEBHOOK_URL:
        missing.append("DISCORD_WEBHOOK_URL")

    # provider별 필수 API 키 검증
    provider = LLM_PROVIDER.lower()

    if provider == "openai" and not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    elif provider in ("gemini", "google") and not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    elif provider in ("claude", "anthropic") and not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")

    if missing:
        raise RuntimeError(f"필수 환경변수 누락: {', '.join(missing)}")


def check_llm():
    """provider가 ollama일 때만 로컬 서버/모델 상태를 점검한다.
    클라우드 provider는 키 존재 여부를 validate_env에서 이미 확인했으므로
    실제 호출 시점에 검증된다."""
    provider = LLM_PROVIDER.lower()

    if provider == "ollama":
        check_ollama()
    else:
        print(f"[INFO] LLM provider: {provider} (모델: {_current_model_name()})")


def _current_model_name() -> str:
    provider = LLM_PROVIDER.lower()
    if provider == "openai":
        return OPENAI_MODEL
    if provider in ("gemini", "google"):
        return GEMINI_MODEL
    if provider in ("claude", "anthropic"):
        return ANTHROPIC_MODEL
    return OLLAMA_MODEL


def check_ollama():
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"

    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Ollama 연결 실패: {OLLAMA_BASE_URL}, error={e}")

    data = res.json()
    models = data.get("models", [])

    model_names = set()

    for model in models:
        if model.get("name"):
            model_names.add(model.get("name"))

        if model.get("model"):
            model_names.add(model.get("model"))

    if OLLAMA_MODEL not in model_names:
        raise RuntimeError(
            f"Ollama 모델 없음: {OLLAMA_MODEL}. "
            f"현재 모델 목록: {', '.join(sorted(model_names))}"
        )

    print(f"[INFO] Ollama 연결 정상: {OLLAMA_BASE_URL}, model={OLLAMA_MODEL}")


# =========================
# 메인
# =========================

def main():
    validate_env()
    check_llm()
    init_db()

    start_dt, end_dt = get_collect_window()

    raw_items = collect_news(start_dt, end_dt)

    candidates = prefilter_candidates(raw_items)

    print(f"[INFO] AI 선별 후보 기사 수: {len(candidates)}")

    selected = ai_select_and_summarize(candidates, start_dt, end_dt)

    print(f"[INFO] 최종 선별 기사 수: {len(selected)}")

    message = build_discord_message(selected, start_dt, end_dt)

    send_discord(message)

    mark_sent(selected)

    print("[INFO] 완료")


if __name__ == "__main__":
    main()
