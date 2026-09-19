import os
from dataclasses import dataclass


def _parse_provider_pool(value: str) -> tuple[tuple[str, str], ...]:
    providers: list[tuple[str, str]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        provider, separator, model = item.partition(":")
        providers.append((provider.strip(), (model or "").strip()))
    return tuple(providers)


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
    g4f_provider_pool: tuple[tuple[str, str], ...] = _parse_provider_pool(
        os.getenv(
            "G4F_PROVIDER_POOL",
            "Gemini:gemini-3.6-flash,Cloudflare:glm-5.2,"
            "Gemini:gemini-3.1-flash-lite,LLM7:default",
        )
    )
    g4f_max_tokens: int = int(os.getenv("G4F_MAX_TOKENS", "8000"))
    g4f_chunk_characters: int = int(os.getenv("G4F_CHUNK_CHARACTERS", "8000"))
    max_upload_bytes: int = int(
        os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))
    )


settings = Settings()