import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://autoapply:autoapply@localhost:5432/autoapply",
    )
    storage_endpoint: str = os.getenv("STORAGE_ENDPOINT", "http://localhost:9000")
    storage_access_key: str = os.getenv("STORAGE_ACCESS_KEY", "autoapply")
    storage_secret_key: str = os.getenv("STORAGE_SECRET_KEY", "autoapply-secret")
    storage_bucket: str = os.getenv("STORAGE_BUCKET", "autoapply-documents")
    extraction_provider: str = os.getenv("EXTRACTION_PROVIDER", "g4f")
    nvidia_api_key: str | None = os.getenv("NVIDIA_API_KEY")
    nvidia_model: str = os.getenv(
        "NVIDIA_MODEL",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
    )
    nvidia_base_url: str = os.getenv(
        "NVIDIA_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
    )
    nvidia_timeout_seconds: float = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "180"))
    nvidia_max_tokens: int = int(os.getenv("NVIDIA_MAX_TOKENS", "8000"))
    nvidia_max_retries: int = int(os.getenv("NVIDIA_MAX_RETRIES", "0"))
    g4f_provider: str = os.getenv("G4F_PROVIDER", "LLM7")
    g4f_model: str = os.getenv("G4F_MODEL", "default")
    g4f_chunk_characters: int = int(os.getenv("G4F_CHUNK_CHARACTERS", "8000"))


settings = Settings()