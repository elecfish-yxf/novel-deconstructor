from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(PROJECT_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = ""
    openai_temperature: float = 0.3
    openai_max_tokens: int = 8192
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    doubao_api_key: str = ""
    ark_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "doubao-seed-2-0-pro-260215"

    app_storage_dir: str = "./storage"
    app_upload_dir: str = "./uploads"
    app_output_dir: str = "./outputs"
    app_knowledge_dir: str = "./storage/knowledge"
    app_database_url: str = "sqlite:///./storage/novel_deconstructor.db"
    app_require_auth: bool = False
    app_auth_session_days: int = 30

    max_upload_size_mb: int = 20
    max_chapter_chars: int = 12000
    chunk_overlap_chars: int = 800
    knowledge_chunk_size: int = 900
    knowledge_chunk_overlap: int = 120
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "novel_knowledge"
    qdrant_vector_size: int = 1024
    qdrant_distance: str = "Cosine"

    retrieval_mode: str = "keyword"
    retrieval_top_k: int = 12
    retrieval_candidate_k: int = 80
    retrieval_keyword_weight: float = 0.35
    retrieval_vector_weight: float = 0.65
    retrieval_scope_filter_enabled: bool = True
    retrieval_diversity_enabled: bool = True
    retrieval_max_per_source: int = 3
    retrieval_max_per_card_type: int = 5
    retrieval_index_startup_limit: int = 200

    embedding_provider: str = "fake"
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_vector_size: int = 1024
    embedding_batch_size: int = 32
    embedding_timeout_seconds: int = 60

    default_concurrency: int = 1
    allow_absolute_output_path: bool = False
    enable_directory_picker: bool = True

    llm_timeout_seconds: int = 120
    llm_retry_count: int = 2
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    oh_story_repo_url: str = "https://github.com/HeRiki/oh-story-codex.git"

    @property
    def storage_dir(self) -> Path:
        return Path(self.app_storage_dir)

    @property
    def upload_dir(self) -> Path:
        return Path(self.app_upload_dir)

    @property
    def output_dir(self) -> Path:
        return Path(self.app_output_dir)

    @property
    def knowledge_dir(self) -> Path:
        return Path(self.app_knowledge_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
