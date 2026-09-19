import unittest
from unittest.mock import patch

from app.embeddings import FastEmbedProvider, NullEmbedder, get_embedder


class NullEmbedderTests(unittest.TestCase):
    def test_null_embedder_returns_no_vectors(self) -> None:
        self.assertEqual(NullEmbedder().embed(["a", "b"]), [])

    def test_get_embedder_null_via_env(self) -> None:
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "null"}):
            embedder = get_embedder()
        self.assertIsInstance(embedder, NullEmbedder)

    def test_get_embedder_fastembed_without_package_falls_back(self) -> None:
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "auto"}), patch.dict(
            "sys.modules", {"fastembed": None}
        ):
            embedder = get_embedder()
        self.assertIsInstance(embedder, NullEmbedder)

    def test_get_embedder_explicit_fastembed_missing_raises(self) -> None:
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "fastembed"}), patch.dict(
            "sys.modules", {"fastembed": None}
        ):
            with self.assertRaises(ImportError):
                get_embedder()


class FastEmbedProviderTests(unittest.TestCase):
    def test_provider_is_lazy(self) -> None:
        import sys

        with patch.dict(sys.modules, {"fastembed": None}):
            provider = FastEmbedProvider()
            self.assertIsNone(provider._client)