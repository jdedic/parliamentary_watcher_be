import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger("chat_audit")

_SESSION_CHAT_PATH = re.compile(r"^/api/v1/sessions/(?P<session_id>[^/]+)/chat/?$")
_AUTH_CHAT_PATH = re.compile(r"^/api/v1/auth/chat/?$")

ACCESS_KEY_ID_STATE = "chat_access_key_id"


def _match(path: str) -> tuple[str, str | None] | None:
    if m := _SESSION_CHAT_PATH.match(path):
        return "session_chat", m.group("session_id")
    if _AUTH_CHAT_PATH.match(path):
        return "auth_chat", None
    return None


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class ChatAuditMiddleware:
    """
    Logs one `chat_attempt` line per request to the chat endpoints, whatever the outcome.

    Implemented as middleware rather than in the routes because 401/403 (auth dependency)
    and 429 (slowapi) are raised before the route body runs, so the route never sees them.
    The key itself is never logged — only its DB id once the auth layer has resolved it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        matched = _match(scope.get("path", ""))
        if matched is None:
            await self.app(scope, receive, send)
            return

        endpoint, session_id = matched
        state = scope.setdefault("state", {})
        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            client = scope.get("client")
            fields = {
                "endpoint": endpoint,
                "session_id": session_id,
                "status": status_code,
                "ip": client[0] if client else None,
                # Spoofable by the client; kept only to identify users behind a proxy.
                "forwarded_for": _header(scope, b"x-forwarded-for"),
                "user_agent": _header(scope, b"user-agent"),
                "key_present": endpoint == "auth_chat" or _header(scope, b"x-chat-key") is not None,
                "access_key_id": state.get(ACCESS_KEY_ID_STATE),
                "latency_ms": int((time.perf_counter() - start) * 1000),
            }
            if status_code >= 500:
                logger.error("chat_attempt", **fields)
            elif status_code >= 400:
                logger.warning("chat_attempt", **fields)
            else:
                logger.info("chat_attempt", **fields)
