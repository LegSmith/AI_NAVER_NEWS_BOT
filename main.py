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
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from settings import SETTINGS  # <-- settings.py에서 설정 로드

# --- 로깅 설정 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('NewsCollector')

# --- 전역 상수 ---
KST = timezone(timedelta(hours=9))


def load_search_keywords() -> list[str]:
    """keywords.json 에서 검색 키워드 목록을 로드합니다."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("keywords", [])
    except FileNotFoundError:
        logger.error(f"키워드 파일을 찾을 수 없습니다: {path}")
        return []


SEARCH_KEYWORDS = load_search_keywords()


# =========================
# 1. 공통 유틸리티 (Clean/ID)
# ==============================

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


# 2. 날짜/시간 파싱 유틸

def parse_naver_pubdate(pubdate: str) -> datetime:
    dt = parsedate_to_datetime(pubdate)
    return dt.astimezone(KST)


def parse_naver_pubdate_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(KST)


def get_collect_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    if now is None:
        now = datetime.now(KST)

    end_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now < end_dt:
        end_dt = end_dt - timedelta(days=1)

    start_dt = end_dt - timedelta(days=2)

    logger.info(f"수집 목표 범위 설정 완료: {start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}")
    return start_dt, end_dt


# ================================================
# 3. DB 관리
# ==================================================

def init_db():
    conn = sqlite3.connect(SETTINGS.db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS sent_news (news_id TEXT PRIMARY KEY, title TEXT, url TEXT, pub_date TEXT, sent_at TEXT)")
    conn.commit()
    conn.close()
    logger.info(f"DB 초기화 완료: {SETTINGS.db_path}")


def already_sent(news_id: str) -> bool:
    conn = sqlite3.connect(SETTINGS.db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sent_news WHERE news_id = ?", (news_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_sent(items: list[dict]):
    if not items:
        return

    conn = sqlite3.connect(SETTINGS.db_path)
    cur = conn.cursor()
    now = datetime.now(KST).isoformat()

    for item in items:
        cur.execute("INSERT OR IGNORE INTO sent_news (news_id, title, url, pub_date, sent_at) VALUES (?, ?, ?, ?, ?)", (
            item["news_id"],
            item["title"],
            item["url"],
            item["pub_date"],
            now
        ))
    conn.commit()
    conn.close()
    logger.info(f"DB 기록 성공: {len(items)}개의 기사가 전송 이력으로 기록되었습니다.")


# ==================================================
# 4. 네이버 뉴스 수집 로직
# =====================================================

@retry(wait=wait_exponential(multiplier=1, min=4, max=30),
       stop=stop_after_attempt(5),
       retry=retry_if_exception_type((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
def fetch_naver_news(query: str, start: int) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": SETTINGS.naver_client_id,
        "X-Naver-Client-Secret": SETTINGS.naver_client_secret,
    }
    params = {
        "query": query,
        "display": 100,
        "start": start,
        "sort": "date",
    }

    logger.info(f"[API] 네이버 API 호출 시도: Query={query}, Start={start}")

    res = requests.get(
        SETTINGS.naver_news_api_url,
        headers=headers,
        params=params,
        timeout=20,
    )
    res.raise_for_status()

    return res.json().get("items", [])


def collect_news(start_dt: datetime, end_dt: datetime) -> list[dict]:
    collected = {}
    logger.info("====================================================================")
    logger.info(f"[COLLECT] 기사 수집 시작. 목표 범위: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
    logger.info("======================================================================")

    for query in SEARCH_KEYWORDS:
        logger.info(f"[COLLECT] --> 검색어 분석 시작: {query}")
        for start in range(1, 1001, 100):
            try:
                items = fetch_naver_news(query, start=start)
            except RuntimeError:
                logger.error(f"[COLLECT] 치명적 API 에러 발생: 인증 문제일 수 있습니다. '{query}' 수집을 중단합니다.")
                break
            except requests.exceptions.HTTPError as e:
                logger.error(f"[COLLECT] HTTP 에러 발생 ({e.response.status_code}). 재시도 됩니다. (API 제한 혹은 인증)")
                time.sleep(10)
                continue
            except Exception as e:
                logger.error(f"[COLLECT] 예상치 못한 API 호출 오류 발생: {e}. 다음 키워드로 넘어갑니다.")
                break

            if not items:
                logger.warning(f"[COLLECT] 현재 페이지({start // 100 + 1})에서 결과를 받지 못했습니다. 다음 키워드로 넘어갑니다.")
                if start > 1:
                    break
                else:
                    continue

            page_dates = []
            for raw in items:
                try:
                    pub_dt = parse_naver_pubdate(raw.get("pubDate", ""))
                    page_dates.append(pub_dt)
                except Exception:
                    continue

                # 핵심 시간 필터링: start_dt보다 크고, end_dt보다 작거나 같은 범위만 수집
                if pub_dt < start_dt or pub_dt > end_dt:
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

            if page_dates and max(page_dates) < start_dt:
                logger.warning(f"[COLLECT] 수집된 기사들의 가장 최신 기사가 목표 시작 시간보다 과거이므로, {query} 수집 중단.")
                break

            time.sleep(0.3)

    final_result = list(collected.values())
    logger.info("======================================================================")
    logger.info(f"[COLLECT] ★★★ 최종 수집 및 필터링 완료 ★★★\n[INFO] 총 {len(final_result)}개의 신규 기사 수집 완료.")

    return final_result


# ======================================================
# 5. 스코어링 및 필터링
# ========================================================

def local_score(item: dict) -> int:
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    high_keywords = [
        "llm", "rag", "벡터", "gpu", "cuda", "pytorch", "tensorflow", "모델", "추론", "학습",
        "에이전트", "오픈소스", "api", "보안", "클라우드", "반도체", "nvidia", "openai", "anthropic",
        "deepmind", "mistral", "meta", "llama", "gemma", "qwen", "서빙", "성능", "최적화",
        "온디바이스", "데이터센터", "mlops", "쿠버네티스", "도커", "추론서버", "모델 경량화"
    ]
    low_keywords = [
        "주가", "급등", "급락", "투자", "채용", "행사", "체험", "이벤트", "공개", "mou", "홍보"
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
    logger.info("[SCORE] 로컬 스코어링 적용 시작... (Phase 2 개선)")
    scored_items = []
    for item in items:
        score = local_score(item)
        item["local_score"] = score
        scored_items.append(item)

    scored_items = sorted(
        scored_items,
        key=lambda x: (x.get("local_score", 0), x.get("pub_date", "")),
        reverse=True
    )

    filtered = scored_items[:SETTINGS.max_candidates_for_ai]
    logger.info(f"[SCORE] 스코어 기반으로 상위 {len(filtered)}개 후보군 선정 완료.")
    return filtered


# ========================================================
# 6. LLM 처리 (Phase 3: 구조화된 프롬프트, 단계적 모델)
# ==============================================================

def extract_json(text: str) -> dict:
    if not text:
        raise ValueError("모델 응답이 비어 있음")

    text = text.strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"JSON 추출 실패가 예상됩니다. (첫 300자 감지: {text[:300]})")

    return json.loads(match.group(0))


@retry(wait=wait_exponential(multiplier=1, min=2, max=60),
       stop=stop_after_attempt(3),
       retry=retry_if_exception_type((requests.exceptions.RequestException, RuntimeError)))
def call_ollama(prompt: str) -> str:
    logger.info(f"[LLM] ---> Ollama 호출 시도: 모델={SETTINGS.ollama_model}")
    url = f"{SETTINGS.ollama_base_url.rstrip('/')}/api/generate"

    payload = {
        "model": SETTINGS.ollama_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": SETTINGS.ollama_keep_alive,
        "options": {
            "temperature": 0,
            "num_ctx": 32768
        }
    }

    try:
        res = requests.post(
            url,
            json=payload,
            timeout=300,
        )
        res.raise_for_status()

        data = res.json()
        logger.info(f"[LLM] Ollama 통계: 모델={data.get('model')}, eval_count={data.get('eval_count')}")
        return data.get("response", "")
    except requests.exceptions.RequestException as e:
        logger.error(f"[LLM] 🔥 Ollama 호출 최종 실패 (지속적/네트워크): {e} !!!")
        raise RuntimeError(f"LLM 통신 실패: {e}.")


def ai_select_and_summarize(items: list[dict], start_dt: datetime, end_dt: datetime) -> list[dict]:
    """LLM으로 기사별 요약·중요도·개발자 관점을 생성하고 TOP N을 선별합니다."""
    if not items:
        return []

    logger.info("=============== LLM 기사 선별/요약 시작 ===============")

    max_final = SETTINGS.max_final_items

    # 1. LLM 입력용 경량 데이터 구성 (idx 부여)
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

아래 뉴스 목록 중에서 "AI 관련 + 개발자와 가장 관련 있는" 기사 TOP {max_final}개만 엄선해라.

선별 기준 (가장 중요):
- 반드시 AI/머신러닝/LLM 관련 기사여야 함. AI와 무관하면 절대 선택하지 마라.
- 실무 개발자가 직접 써먹을 수 있는 기사를 최우선으로 선택:
  - LLM, RAG, 벡터DB, 모델 학습/추론/파인튜닝, 프롬프트 엔지니어링
  - GPU, CUDA, PyTorch, TensorFlow, 모델 경량화, 추론 서버/서빙
  - MLOps, AI 인프라, 쿠버네티스/도커 기반 배포, API/SDK, 오픈소스 모델 공개
  - AI 보안/취약점, 아키텍처 설계, 성능 최적화, 장애 대응, 비용 절감
- 단순 기업 홍보, 주가/투자, 행사/MOU, 정책, 일반 소비자 서비스, 연예/마케팅성 기사는 제외하라.
- 중요도(importance)는 "개발자 실무 관련성"을 기준으로 1~5점.
- 정확히 가장 관련 높은 {max_final}개 이하만 선택. 애매하면 차라리 적게 선택하라.
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

    # 2. LLM 호출 및 파싱 (실패 시 로컬 점수 기반 폴백)
    try:
        result_text = call_ollama(prompt)
        result_json = extract_json(result_text)
    except Exception as e:
        logger.error(f"[LLM] AI 선별 실패, 로컬 점수 기반 폴백: {e}")
        selected = [item.copy() for item in items[:max_final]]
        for item in selected:
            item["importance"] = min(5, max(1, item.get("local_score", 1)))
            item["reason"] = "AI 선별 실패로 로컬 점수 기준 선별"
            item["summary"] = item["description"][:180] if item["description"] else item["title"]
            item["dev_impact"] = "기사 원문 확인 필요"
        return selected

    # 3. LLM 결과를 원본 기사에 병합
    selected = []
    for ai_item in result_json.get("items", []):
        idx = ai_item.get("idx")
        if not isinstance(idx, int) or idx < 1 or idx > len(items):
            continue

        original = items[idx - 1].copy()

        try:
            importance = int(ai_item.get("importance", 3))
        except Exception:
            importance = 3
        importance = min(5, max(1, importance))

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

    selected = sorted(selected, key=lambda x: x.get("importance", 0), reverse=True)

    logger.info(f"[LLM] 최종 선별 완료: {len(selected[:max_final])}개")
    return selected[:max_final]


# =========================
# 6-1. 디스코드 전송
# =========================

def split_message(text: str, limit: int = 1800) -> list[str]:
    """Discord 2000자 제한을 고려하여 메시지를 줄 단위로 분할합니다."""
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
    """선별된 기사를 기사별 요약·중요도·개발자 관점 형식으로 구성합니다."""
    header = (
        f"# 🤖 AI 개발자 뉴스 TOP {SETTINGS.max_final_items}\n"
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
    if not SETTINGS.discord_webhook_url:
        raise RuntimeError("discord_webhook_url 설정이 비어 있습니다. (.env의 DISCORD_WEBHOOK_URL 확인)")

    chunks = split_message(message)

    for idx, chunk in enumerate(chunks, start=1):
        res = requests.post(
            SETTINGS.discord_webhook_url,
            json={"content": chunk},
            timeout=20,
        )

        if res.status_code >= 300:
            raise RuntimeError(f"Discord 전송 실패: {res.status_code}, {res.text}")

        logger.info(f"[DISCORD] 전송 완료: chunk={idx}/{len(chunks)}")

        time.sleep(0.5)


# ==================================================
# 7. 메인 실행 로직 (통합 테스트)
# ========================================================

def main():
    logger.info("====================================================")
    logger.info("===== 네이버 뉴스 분석 및 자동 전송 시스템 실행 (최종 버전) =====")
    logger.info(f"[CONFIG] DB Path: {SETTINGS.db_path}, LLM 모델: {SETTINGS.ollama_model}")
    logger.info("=====================================================")

    init_db()  # 1. DB 초기화

    # 2. 수집 기간 결정
    now = datetime.now(KST)
    start_dt, end_dt = get_collect_window(now)

    # 3. 네트워크 수집
    raw_news_list = collect_news(start_dt, end_dt)

    if not raw_news_list:
        logger.warning("✅ 수집할 신규 기사가 없습니다. 스크립트를 종료합니다.")
        return

    # 4. 필터링 및 스코어링
    candidate_list = prefilter_candidates(raw_news_list)

    if not candidate_list:
        logger.warning("✅ 분석할 후보군이 없습니다. 스크립트를 종료합니다.")
        return

    # 5. LLM 기사 선별 및 요약 (핵심)
    final_selection = ai_select_and_summarize(candidate_list, start_dt, end_dt)

    if not final_selection:
        logger.warning("✅ LLM이 선별한 기사가 없습니다. 스크립트를 종료합니다.")
        return

    logger.info("======================================================================")
    logger.info(f"[FINAL] 최종 선별 기사 {len(final_selection)}개:")
    for item in final_selection:
        logger.info(f"  - [{item.get('importance', 0)}] {item['title']}")
    logger.info("======================================================================")

    # 6. Discord 전송
    try:
        message = build_discord_message(final_selection, start_dt, end_dt)
        send_discord(message)
    except Exception as e:
        logger.error(f"[DISCORD] 전송 실패: {e}")
        return  # 전송 실패 시 DB에 기록하지 않아 다음 실행에서 재시도 가능

    # 7. DB 최종 기록 (전송 성공 후에만 기록)
    mark_sent(final_selection)


if __name__ == "__main__":
    main()
