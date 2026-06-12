import httpx
from django.conf import settings

REQUEST_TIMEOUT = 10.0


class AgentClientError(Exception):
    """agent-service call failed (transport, config, or non-2xx)."""


def _base_and_token() -> tuple[str, str]:
    base = getattr(settings, "AGENT_SERVICE_BASE_URL", "").rstrip("/")
    token = getattr(settings, "AGENT_SERVICE_TOKEN", "")
    if not base or not token:
        raise AgentClientError("agent-service client not configured")
    return base, token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def agent_get(path: str) -> dict:
    base, token = _base_and_token()
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
            resp = c.get(base + path, headers=_headers(token))
    except httpx.HTTPError as exc:
        raise AgentClientError(f"transport error: {exc}") from exc
    if resp.status_code // 100 != 2:
        raise AgentClientError(f"status {resp.status_code}")
    return resp.json()


def agent_post(path: str, json: dict | None = None) -> dict:
    base, token = _base_and_token()
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
            resp = c.post(base + path, headers=_headers(token), json=json or {})
    except httpx.HTTPError as exc:
        raise AgentClientError(f"transport error: {exc}") from exc
    if resp.status_code // 100 != 2:
        raise AgentClientError(f"status {resp.status_code}")
    return resp.json() if resp.content else {}


def agent_put(path: str, json: dict | None = None) -> dict:
    base, token = _base_and_token()
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
            resp = c.put(base + path, headers=_headers(token), json=json or {})
    except httpx.HTTPError as exc:
        raise AgentClientError(f"transport error: {exc}") from exc
    if resp.status_code // 100 != 2:
        raise AgentClientError(f"status {resp.status_code}")
    return resp.json() if resp.content else {}
