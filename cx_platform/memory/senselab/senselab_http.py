"""HTTP transport for the SenseLab memory adapter."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

import httpx

from ..port import MemoryConfigurationError, MemoryResponseError, MemoryUnavailable

SENSELAB_DEFAULT_URL = "https://amfs-login.sense-lab.ai"


class SenseLabHTTPClient:
    """Send authenticated requests to the documented SenseLab REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip():
            raise MemoryConfigurationError("SenseLab URL is required")
        if not api_key.strip():
            raise MemoryConfigurationError("SenseLab API key is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={"X-AMFS-API-Key": api_key},
            timeout=timeout_seconds,
        )
        self._client.headers.setdefault("X-AMFS-API-Key", api_key)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        """Execute one request and map transport failures to CX errors."""

        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MemoryUnavailable("SenseLab memory request failed") from exc

        if response.is_error:
            detail = response.text[:200]
            raise MemoryUnavailable(
                f"SenseLab memory request returned HTTP {response.status_code}: {detail}"
            )

        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MemoryResponseError("SenseLab returned invalid JSON") from exc

    def close(self) -> None:
        """Close the client when this adapter created it."""

        if self._owns_client:
            self._client.close()


__all__ = ["SENSELAB_DEFAULT_URL", "SenseLabHTTPClient"]
