from pydantic import BaseSettings
from typing import List

class Settings(BaseSettings):
    # --- General Settings ---
    class Config:
        env_file = ".env"

    # --- API Keys ---
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_news_api_url: str = "https://openapi.naver.com/v1/search/news.json"

    discord_webhook_url: str = ""
    
    # --- LLM Configuration ---
    llm_provider: str = "ollama"  # ollama | openai | gemini | claude
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_keep_alive: str = "0"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # --- Local & Business Logic ---
    db_path: str = "./news_history.db"
    max_final_items: int = 5
    max_candidates_for_ai: int = 20

# 전역 설정 인스턴스화
SETTINGS: Settings = Settings()