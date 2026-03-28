import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import setting
from app.core.paths import LOG_ROOT, ensure_runtime_dirs

FILTER_PATTERNS = (
    "sse_starlette.sse",
    "mcp.server.streamable_http",
)


class MCPLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msgs = (record.getMessage(),)
        return not any(pat in msg for pat in FILTER_PATTERNS for msg in msgs)


class LoggerManager:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if LoggerManager._initialized:
            return
        LoggerManager._initialized = True

        ensure_runtime_dirs()

        log_dir = LOG_ROOT
        log_dir.mkdir(parents=True, exist_ok=True)

        log_level = getattr(logging, setting.global_config.get("log_level", "INFO").upper(), logging.INFO)
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        log_file = log_dir / "app.log"

        formatter = logging.Formatter(log_format)

        mcp_filter = MCPLogFilter()

        console = logging.StreamHandler(sys.stdout)
        console.setLevel(log_level)
        console.setFormatter(formatter)
        console.addFilter(mcp_filter)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.addHandler(console)
        root_logger.addHandler(file_handler)

        self._configure_third_party()

    def _configure_third_party(self) -> None:
        for name in ("uvicorn", "fastapi", "httpx", "aiohttp", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)


LoggerManager()

# Export logger for use in other modules
logger = logging.getLogger("grok2api")
