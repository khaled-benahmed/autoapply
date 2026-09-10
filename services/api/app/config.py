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
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_model: str = os.getenv(
        "OPENROUTER_MODEL",
        "minimax/minimax-m3:free",
    )


settings = Settings()