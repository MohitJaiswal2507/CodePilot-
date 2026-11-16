"""
Embedding Provider Abstraction for CodePilot AI.

Supports:
- Local embeddings via SentenceTransformers (e.g. all-MiniLM-L6-v2, 384 dimensions)
- Cloud embeddings via Gemini Embeddings API (e.g. gemini-embedding-2, 768 dimensions)

Gemini Embedding 2 Compliance:
- Per official Google documentation (https://ai.google.dev/gemini-api/docs/embeddings):
  - gemini-embedding-2 does NOT support the `task_type` parameter in EmbedContentConfig.
  - Task instructions must be embedded into the text prompt:
    * Documents: "title: {title or 'none'} | text: {content}"
    * Queries:   "task: search result | query: {query}"
  - output_dimensionality is configured via types.EmbedContentConfig(output_dimensionality=...).
  - Multiple text inputs generate separate, distinct embeddings (1:1 per input).
"""

import abc
import logging
import random
import time
from typing import List, Optional, Any, Callable
from google import genai
from google.genai import types

from app.core.config import settings
from app.services.llm_gateway import (
    is_transient_rate_limit_error,
    extract_retry_delay_seconds,
)

logger = logging.getLogger(__name__)


class EmbeddingProvider(abc.ABC):
    """Abstract interface for document and query text embedding providers."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality produced by this provider."""
        pass

    @abc.abstractmethod
    def embed_texts(
        self,
        texts: List[str],
        titles: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed a list of document chunks for vector indexing.
        Generates a separate embedding for every text input.
        """
        pass

    @abc.abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """
        Embed a search query for vector retrieval using compatible instructions.
        """
        pass


class LocalSentenceTransformerProvider(EmbeddingProvider):
    """Local embedding provider wrapping SentenceTransformer (e.g. all-MiniLM-L6-v2, 384d)."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.model_name)
        try:
            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = int(self._model.get_embedding_dimension())
            else:
                self._dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception:
            self._dimension = 384

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(
        self,
        texts: List[str],
        titles: Optional[List[str]] = None,
    ) -> List[List[float]]:
        if not texts:
            return []
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        cleaned = str(query).strip()
        embeddings = self._model.encode([cleaned], show_progress_bar=False)
        return embeddings.tolist()[0]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Cloud embedding provider using Google GenAI SDK (gemini-embedding-2).
    Follows official Google documentation:
    - No unsupported task_type parameter in EmbedContentConfig.
    - Instructions in prompt:
      Document chunks: 'title: <title> | text: <content>'
      Query: 'task: search result | query: <query>'
    - Dimension truncation via output_dimensionality.
    """

    SUPPORTED_DIMENSIONS = (768, 1536, 3072)

    def __init__(
        self,
        model: Optional[str] = None,
        dimension: Optional[int] = None,
        client: Optional[genai.Client] = None,
        max_retries: int = 3,
        batch_size: int = 32,
        sleep_fn: Callable[[float], Any] = time.sleep,
    ):
        raw_model = (model or settings.GEMINI_EMBEDDING_MODEL or "gemini-embedding-2").strip()
        if raw_model.startswith("models/"):
            raw_model = raw_model[len("models/"):]
        self._model = raw_model

        target_dim = dimension or settings.EMBEDDING_DIMENSION or 768
        if target_dim not in self.SUPPORTED_DIMENSIONS:
            raise ValueError(
                f"Unsupported embedding dimension {target_dim} for {self._model}. "
                f"Must be one of {self.SUPPORTED_DIMENSIONS}."
            )
        self._dimension = target_dim

        self._client = client
        self._max_retries = max_retries
        self._batch_size = max(1, batch_size)
        self._sleep_fn = sleep_fn

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured for Gemini embedding provider")
        return genai.Client(api_key=api_key)

    def _embed_batch_with_retry(
        self,
        contents: List[str],
    ) -> List[List[float]]:
        if not contents:
            return []

        client = self._get_client()
        # Official Google Documentation: do NOT pass task_type for gemini-embedding-2
        config = types.EmbedContentConfig(
            output_dimensionality=self._dimension,
        )

        attempts = 0
        backoff_delay = 1.0

        while True:
            attempts += 1
            try:
                # Convert string list into explicit list of Content objects so Google GenAI
                # treats each item as an independent text instead of multi-part segments of a single content
                content_items = [
                    types.Content(parts=[types.Part.from_text(text=item)])
                    if isinstance(item, str)
                    else item
                    for item in contents
                ]
                response = client.models.embed_content(
                    model=self._model,
                    contents=content_items,
                    config=config,
                )
                embeddings = self._extract_embeddings(response)
                if len(embeddings) != len(contents):
                    raise RuntimeError(
                        f"Gemini embed_content returned {len(embeddings)} embeddings for {len(contents)} input texts; "
                        "expected separate embeddings for each input."
                    )
                return embeddings
            except Exception as exc:
                is_transient = is_transient_rate_limit_error(exc)
                if attempts > self._max_retries or not is_transient:
                    logger.error(
                        "Gemini embedding API call failed permanently after %d attempts: %s",
                        attempts,
                        str(exc),
                    )
                    raise

                retry_after = extract_retry_delay_seconds(exc)
                chosen_delay = retry_after if retry_after is not None else backoff_delay + random.uniform(0.1, 0.5)
                logger.warning(
                    "Gemini embedding transient error (attempt %d/%d). Retrying in %.2fs. Error: %s",
                    attempts,
                    self._max_retries,
                    chosen_delay,
                    str(exc),
                )
                self._sleep_fn(chosen_delay)
                backoff_delay *= 2.0

    def _extract_embeddings(self, response: Any) -> List[List[float]]:
        """Extract float lists from Google GenAI embed_content response and validate dimension."""
        extracted: List[List[float]] = []

        if hasattr(response, "embeddings") and response.embeddings:
            for item in response.embeddings:
                vals = None
                if hasattr(item, "values") and item.values is not None:
                    vals = [float(x) for x in item.values]
                elif isinstance(item, (list, tuple)):
                    vals = [float(x) for x in item]

                if vals is not None:
                    if len(vals) != self._dimension:
                        raise ValueError(
                            f"Returned embedding dimension {len(vals)} does not match expected {self._dimension}"
                        )
                    extracted.append(vals)

        elif hasattr(response, "embedding") and response.embedding:
            emb = response.embedding
            vals = None
            if hasattr(emb, "values") and emb.values is not None:
                vals = [float(x) for x in emb.values]
            elif isinstance(emb, (list, tuple)):
                vals = [float(x) for x in emb]

            if vals is not None:
                if len(vals) != self._dimension:
                    raise ValueError(
                        f"Returned embedding dimension {len(vals)} does not match expected {self._dimension}"
                    )
                extracted.append(vals)

        return extracted

    def embed_texts(
        self,
        texts: List[str],
        titles: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed document chunks.
        Per official documentation, document chunks are formatted as:
        'title: {title} | text: {content}'
        """
        if not texts:
            return []

        # Format texts with documented retrieval prompt structure
        formatted_texts: List[str] = []
        for i, text in enumerate(texts):
            doc_title = (titles[i] if titles and i < len(titles) and titles[i] else "none").strip()
            formatted_texts.append(f"title: {doc_title} | text: {text}")

        all_embeddings: List[List[float]] = []
        # Batch requests to avoid API payload limits
        for i in range(0, len(formatted_texts), self._batch_size):
            batch = formatted_texts[i : i + self._batch_size]
            batch_embeddings = self._embed_batch_with_retry(contents=batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def embed_query(self, query: str) -> List[float]:
        """
        Embed search query.
        Per official documentation, queries are formatted as:
        'task: search result | query: {query}'
        """
        cleaned = str(query).strip()
        if not cleaned:
            return [0.0] * self._dimension

        formatted_query = f"task: search result | query: {cleaned}"
        results = self._embed_batch_with_retry(contents=[formatted_query])
        if results:
            return results[0]
        return [0.0] * self._dimension


# ---------------------------------------------------------------------------
# Provider Factory & Lifecycle
# ---------------------------------------------------------------------------

_provider_cache: dict[str, EmbeddingProvider] = {}


def get_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    """
    Retrieve or initialize the active embedding provider.
    Supported provider types: 'local' (SentenceTransformers), 'gemini' (Gemini API).
    """
    kind = (provider_type or settings.EMBEDDING_PROVIDER or "local").lower().strip()
    if kind not in _provider_cache:
        if kind == "gemini":
            _provider_cache[kind] = GeminiEmbeddingProvider()
        else:
            _provider_cache[kind] = LocalSentenceTransformerProvider()
    return _provider_cache[kind]


def reset_embedding_provider() -> None:
    """Clear cached provider instances (primarily for test isolation)."""
    _provider_cache.clear()
