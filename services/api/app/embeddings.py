import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)


class TextEmbedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class NullEmbedder:
    """Deterministic no-op embedder: signals "no dense vectors available"."""
    name = "null"
    dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class FastEmbedProvider:
    """Local ONNX embeddings through fastembed (CPU, no torch), lazy model load.

    The model is only downloaded/loaded on the first ``embed`` call so that the
    API boots without it and degrades gracefully if the model is unavailable.
    """

    name = "fastembed"
    dim = 384

    def __init__(
        self,
        model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dim: int = 384,
    ) -> None:
        self._model = model
        self.dim = dim
        self._client = None

    def _ensure_model(self):
        if self._client is None:
            from fastembed import TextEmbedding

            self._client = TextEmbedding(model_name=self._model)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_model()
        return [list(vector) for vector in client.embed(texts)]


def get_embedder() -> TextEmbedder:
    provider = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
    if provider == "null":
        return NullEmbedder()
    if provider in ("auto", "fastembed"):
        try:
            import fastembed  # noqa: F401  (import-time check only; model is lazy)

            return FastEmbedProvider()
        except ImportError:
            if provider == "fastembed":
                raise
            logger.warning("fastembed is not installed; falling back to keyword-only search")
            return NullEmbedder()
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider!r}")