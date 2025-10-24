from __future__ import annotations

"""Utilities for fetching credit rating information.

This module allows plugging in an external credit rating provider via the
``KIWOOM_CREDIT_WRAPPER`` environment variable. The variable should point to a
callable in the form ``"some.module:callable"`` which accepts a sequence of
query strings (e.g. corp names) and returns either a mapping of query to rating
or a sequence of ratings aligned with the input order. When no provider is
configured, the service gracefully returns ``None`` for all queries.
"""

import importlib
import logging
import os
from typing import Callable, Mapping, MutableMapping, Sequence

LOGGER = logging.getLogger(__name__)

_CACHED_WRAPPER: Callable[[Sequence[str]], Mapping[str, str | None]] | None = None
_WRAPPER_LOADED = False


def _load_wrapper() -> Callable[[Sequence[str]], Mapping[str, str | None]] | None:
    """Load the user-provided credit rating wrapper if configured.

    The callable is expected to accept a sequence of query strings and return a
    mapping (preferred) or any sequence aligned with the inputs. Exceptions
    raised during dynamic import are logged and suppressed so the API can still
    function even when the optional integration is unavailable.
    """

    global _WRAPPER_LOADED, _CACHED_WRAPPER

    if _WRAPPER_LOADED:
        return _CACHED_WRAPPER

    _WRAPPER_LOADED = True
    path = os.getenv("KIWOOM_CREDIT_WRAPPER")
    if not path:
        return None

    module_name, sep, attr_name = path.partition(":")
    if not module_name or not sep or not attr_name:
        LOGGER.warning(
            "Invalid KIWOOM_CREDIT_WRAPPER value '%s'. Expected format 'module:callable'.",
            path,
        )
        return None

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Failed to import credit rating module '%s': %s", module_name, exc)
        return None

    try:
        wrapper = getattr(module, attr_name)
    except AttributeError:  # pragma: no cover - defensive
        LOGGER.warning(
            "Credit rating callable '%s' not found in module '%s'.", attr_name, module_name
        )
        return None

    if not callable(wrapper):
        LOGGER.warning(
            "Credit rating target '%s' is not callable in module '%s'.", attr_name, module_name
        )
        return None

    _CACHED_WRAPPER = wrapper  # type: ignore[assignment]
    return _CACHED_WRAPPER


def get_credit_ratings(queries: Sequence[str]) -> MutableMapping[str, str | None]:
    """Return credit ratings for the provided queries.

    Parameters
    ----------
    queries:
        A sequence of strings typically representing corp names or stock codes.

    Returns
    -------
    MutableMapping[str, str | None]
        Mapping from the original query to its credit rating. ``None`` indicates
        that no rating is available. When no wrapper is configured, the function
        returns a dictionary filled with ``None`` values.
    """

    wrapper = _load_wrapper()
    if wrapper is None:
        return {q: None for q in queries}

    try:
        result = wrapper(queries)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Credit rating wrapper execution failed: %s", exc)
        return {q: None for q in queries}

    if isinstance(result, Mapping):
        return {str(key): value for key, value in result.items()}

    if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        return {str(q): result[idx] if idx < len(result) else None for idx, q in enumerate(queries)}

    LOGGER.warning(
        "Credit rating wrapper returned unsupported type %s. Falling back to empty results.",
        type(result).__name__,
    )
    return {q: None for q in queries}