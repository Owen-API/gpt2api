from __future__ import annotations

from typing import Any

from services.openai_backend_api import OpenAIBackendAPI
from utils.helper import IMAGE_MODELS
from utils.log import logger


FALLBACK_TEXT_MODELS = (
    "auto",
    "gpt-5",
    "gpt-5-1",
    "gpt-5-2",
    "gpt-5-3",
    "gpt-5-3-mini",
    "gpt-5-5",
    "gpt-5-mini",
)


def _model_item(model: str, owned_by: str = "chatgpt") -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": owned_by,
        "permission": [],
        "root": model,
        "parent": None,
    }


def _base_model_list() -> dict[str, Any]:
    try:
        return OpenAIBackendAPI().list_models()
    except Exception as exc:
        logger.warning({"event": "models_fallback", "error": str(exc)})
        return {"object": "list", "data": [_model_item(model) for model in FALLBACK_TEXT_MODELS]}


def list_models() -> dict[str, Any]:
    result = _base_model_list()
    data = result.get("data")
    if not isinstance(data, list):
        return result
    seen = {str(item.get("id") or "").strip() for item in data if isinstance(item, dict)}
    for model in sorted(IMAGE_MODELS):
        if model not in seen:
            data.append(_model_item(model, owned_by="chatgpt2api"))
    return result
