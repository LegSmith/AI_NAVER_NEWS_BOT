# 📰 Naver News AI Analyzer & Scheduler ✨

**AI 기반의 최신 기술 트렌드 자동 분석 및 요약 서비스**

이 프로젝트는 네이버 뉴스 API를 주기적으로 크롤링하여, 미리 정의된 핵심 기술 키워드(LLM, AI, GPU 등)에 초점을 맞춘 기사들을 수집하고, LLM을 통해 구조화된 산업 분석 보고서 및 요약본을 자동 생성하여 배포하는 시스템입니다.

**🤖 개발 환경 및 기반 기술 (🌟 MUST KNOW)**
이 시스템은 **Hermes Agent** 프레임워크를 활용하여 설계, 구축, 그리고 테스트되었으며, 핵심 모델로 **Gemma 4:e4b** 아키텍처를 기반으로 구동됩니다. 이를 통해 최신 LLM 아키텍처의 장점을 최대한 활용하고, 자동화된 복잡한 워크플로우를 구현할 수 있었습니다.

**✨ 주요 개선점 (v2.0)**
*   **Modular Architecture:** `settings.py`, `keywords.json`, `requirements.txt` 파일로 환경 설정을 완전히 분리하여 확장성이 극대화되었습니다.
*   **강건성 (Robustness):** `tenacity` 라이브러리를 적용하여 네이버/LLM API 호출 시 발생하는 네트워크/HTTP 에러에 대해 **지수적 백오프 재시도 로직**을 구현하여 운영 안정성이 확보되었습니다.
*   **고도화된 분석:** `main.py` 내에서 **System Message 기반의 프롬프트 구조화**를 도입하여, 단순 요약이 아닌 '전문 분석 보고서' 형식의 출력을 지향합니다.
*   **로깅 시스템:** 모든 단계에서 표준 `logging` 모듈을 사용하여, 로그 레벨(INFO/WARNING/ERROR)별로 추적이 가능해져 모니터링이 매우 용이합니다.

## 🚀 시작 가이드

### 1. 환경 설정 (Setup & Execution)
새로운 환경을 구축하고 필요한 의존성을 설치해야 합니다.

**A. 가상 환경 활성화 및 의존성 설치:**
```bash
# 가상 환경을 활성화합니다. (쉘 환경에 맞게 경로 확인)
# source .venv/bin/activate 

# 필요한 라이브러리 설치
pip install -r requirements.txt
```

**B. 환경 변수 설정 (필수):**
프로젝트 루트 디렉토리(`.venv/`와 같은 위치)에 **`.env` 파일**을 생성하고 필수 API 키를 기입해야 합니다.

`.env` 예시:
```dotenv
NAVER_CLIENT_ID="YOUR_NAVER_CLIENT_ID"
NAVER_CLIENT_SECRET="***"
# ... 기타 API 키들 ...
```

### 2. 실행 방법 (Execution)
모든 설정이 완료되면, `main.py`를 실행합니다.

```bash
python main.py
```

### 💡 작동 원리 상세 (Workflow Deep Dive)

1.  **대상 범위 확정:** `get_collect_window`가 현재 시점을 기준으로 **'전날 오전 9시부터 오늘 오전 9시 직전'**까지의 24시간 분석 윈도우를 반환합니다.
2.  **데이터 수집:** `collect_news`가 키워드별로 페이지를 돌며 기사를 수집하고, DB(`news_history.db`) 확인을 통해 중복을 제거합니다.
3.  **필터링:** `local_score`를 통해 중요도(기술 키워드 매칭)에 따라 가중치를 부여하고 상위 후보군을 선정합니다.
4.  **최대 단계 (AI Analysis):** `run_llm_analysis` 함수가 **System Role을 부여**한 프롬프트로 LLM을 호출하여, 보고서 생성 및 최종 선정을 시도합니다.

---
**📝 이대로 사용하시면 됩니다!**

이 문서를 바탕으로 README 디렉토리를 정리하고 Git에 커밋하는 것이 다음 단계가 될 것 같습니다. 👏 정말 큰 성과입니다!