import time
import logging
from typing import List, Optional, Dict
from google import genai
from app.core.config import settings
from app.schemas.tutor import ModelInfo, ModelListResponse

logger = logging.getLogger(__name__)

# In-memory model cache
_cached_models: Optional[List[ModelInfo]] = None
_cache_timestamp: float = 0.0

# Curated fallback models when API is unavailable or offline
FALLBACK_MODELS = [
    ModelInfo(
        id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash Lite",
        description="Fastest lightweight model optimized for high-frequency queries and code explanations.",
        category="fast",
        is_default=True,
        supported_methods=["generateContent"],
    ),
    ModelInfo(
        id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        description="Next-generation balanced model with strong reasoning, code understanding, and speed.",
        category="balanced",
        is_default=False,
        supported_methods=["generateContent"],
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        description="Production workhorse model for coding queries, document grounding, and synthesis.",
        category="balanced",
        is_default=False,
        supported_methods=["generateContent"],
    ),
    ModelInfo(
        id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        description="High-capability reasoning model for complex architectural analysis and deep debugging.",
        category="reasoning",
        is_default=False,
        supported_methods=["generateContent"],
    ),
    ModelInfo(
        id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        description="Lightweight alternative model for low-latency question answering.",
        category="fast",
        is_default=False,
        supported_methods=["generateContent"],
    ),
]


def normalize_model_id(raw_id: str) -> str:
    """Strip 'models/' prefix and leading/trailing whitespace."""
    clean = raw_id.strip()
    if clean.startswith("models/"):
        clean = clean[len("models/"):]
    return clean


def categorize_model(model_id: str) -> str:
    """Classify model into an operational tier based on identifier cues."""
    mid = model_id.lower()
    if "lite" in mid or "gemma" in mid:
        return "fast"
    if "pro" in mid or "deep-research" in mid or "argon" in mid:
        return "reasoning"
    if "preview" in mid or "exp" in mid:
        return "preview"
    if "flash" in mid:
        return "balanced"
    return "general"


def _is_relevant_text_model(model_id: str, display_name: str) -> bool:
    """Filter out non-text specialized endpoints (e.g. robotics, image gen, audio-only, transcribe)."""
    mid = model_id.lower()
    dname = display_name.lower()
    
    # Exclude audio-only, tts, robotics, lyria music, transcribe, computer use
    exclude_keywords = [
        "tts", "transcribe", "robotics", "lyria", "image-preview", 
        "banana", "native-audio", "live-translate", "computer-use", "aqa"
    ]
    if any(kw in mid or kw in dname for kw in exclude_keywords):
        return False
    return True


def discover_models_from_api(client: Optional[genai.Client] = None) -> List[ModelInfo]:
    """Query Google GenAI API for available models supporting generateContent."""
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        logger.warning("No GEMINI_API_KEY configured; returning curated fallback models.")
        return FALLBACK_MODELS

    ai_client = client or genai.Client(api_key=api_key)
    discovered: List[ModelInfo] = []
    default_id = normalize_model_id(settings.GEMINI_MODEL)

    try:
        raw_list = list(ai_client.models.list())
        for m in raw_list:
            raw_name = getattr(m, "name", "")
            clean_id = normalize_model_id(raw_name)
            display_name = getattr(m, "display_name", "") or clean_id
            description = getattr(m, "description", "")
            
            # Check supported actions/methods
            methods = (
                getattr(m, "supported_generation_methods", None) 
                or getattr(m, "supported_actions", None) 
                or []
            )
            # Ensure generateContent is supported
            if "generateContent" not in methods:
                continue

            # Exclude non-text endpoints
            if not _is_relevant_text_model(clean_id, display_name):
                continue

            category = categorize_model(clean_id)
            is_default = (clean_id == default_id)

            input_limit = getattr(m, "input_token_limit", None)
            output_limit = getattr(m, "output_token_limit", None)

            discovered.append(
                ModelInfo(
                    id=clean_id,
                    display_name=display_name,
                    description=description or f"{category.capitalize()} model for text generation and reasoning.",
                    category=category,
                    is_default=is_default,
                    supported_methods=list(methods),
                    input_token_limit=input_limit,
                    output_token_limit=output_limit,
                )
            )

        # Sort: default model first, then priority models, then alphabetically
        priority_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-pro-latest",
        ]

        def sort_key(model: ModelInfo):
            if model.id == default_id:
                return (0, 0)
            if model.id in priority_models:
                return (1, priority_models.index(model.id))
            return (2, model.display_name.lower())

        discovered.sort(key=sort_key)
        return discovered if discovered else FALLBACK_MODELS

    except Exception as exc:
        logger.error("Failed to list Gemini models from API: %s; using fallbacks", exc)
        return FALLBACK_MODELS


def get_available_models(refresh: bool = False, client: Optional[genai.Client] = None) -> ModelListResponse:
    """
    Retrieve available Gemini models with in-memory caching and manual refresh support.
    """
    global _cached_models, _cache_timestamp

    now = time.time()
    cache_expired = (now - _cache_timestamp) > settings.MODEL_CACHE_TTL_SECONDS

    if refresh or _cached_models is None or cache_expired:
        logger.info("Fetching fresh Gemini model list from API (refresh=%s)", refresh)
        _cached_models = discover_models_from_api(client=client)
        _cache_timestamp = now

    default_id = normalize_model_id(settings.GEMINI_MODEL)

    # Ensure is_default flag is correctly reflected in the response
    for m in _cached_models:
        m.is_default = (m.id == default_id)

    routing = {
        "chat": default_id,
        "rewrite": normalize_model_id(settings.GEMINI_REWRITE_MODEL),
        "advanced": normalize_model_id(settings.GEMINI_ADVANCED_MODEL),
    }

    return ModelListResponse(
        models=_cached_models,
        default_model=default_id,
        active_routing=routing,
    )


def validate_model_id(model_id: Optional[str], client: Optional[genai.Client] = None) -> str:
    """
    Validate that a given model ID exists and is supported.
    Returns the normalized model ID if valid; raises ValueError if unsupported.
    If model_id is None or empty, returns the configured default model.
    """
    if not model_id or not model_id.strip():
        return normalize_model_id(settings.GEMINI_MODEL)

    normalized = normalize_model_id(model_id)
    available_response = get_available_models(client=client)
    valid_ids = {m.id for m in available_response.models}

    if normalized in valid_ids:
        return normalized

    # Also accept if with/without 'models/' matches
    for vid in valid_ids:
        if normalized.lower() == vid.lower():
            return vid

    valid_preview = ", ".join(list(valid_ids)[:5])
    raise ValueError(
        f"Model '{model_id}' is not supported or not available for generateContent. "
        f"Available options include: {valid_preview}..."
    )

