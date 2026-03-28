from app.core.config import setting
from app.core.logger import logging
from app.services.api_keys import api_key_manager

logger = logging.getLogger(__name__)


def _build_error(message: str, code: str = "invalid_token") -> dict:
    return {
        "error": {
            "type": "authentication_error",
            "message": message,
            "code": code,
        }
    }


class AuthManager:
    def __init__(self) -> None:
        self._keys = {}

    async def init(self) -> None:
        self._keys = await api_key_manager.get_all_keys()
        logger.debug("[Auth] Initialized with %d API keys", len(self._keys))

    async def verify(self, credentials) -> dict:
        if credentials is None:
            return _build_error("Missing API key", "missing_token")

        api_key = credentials.credentials
        key_info = await api_key_manager.validate_key(api_key)

        if key_info is None:
            return _build_error("Invalid API key", "invalid_token")

        return {
            "api_key": api_key,
            "name": key_info.get("name", "Anonymous"),
            "grok_config": setting.grok_config,
        }

    @staticmethod
    def hasattr(obj, name: str) -> bool:
        return hasattr(obj, name)


auth_manager = AuthManager()
