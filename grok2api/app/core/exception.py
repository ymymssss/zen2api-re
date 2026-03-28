from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


class GrokApiException(Exception):
    def __init__(
        self,
        message: str = "Grok API error",
        error_code: str = "api_error",
        details: str = "",
        context: dict = None,
        status_code: int = 500,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.details = details
        self.context = context or {}
        self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error": {
                "type": "error",
                "message": self.message,
                "code": self.error_code,
                "details": self.details,
            }
        }


NO_AUTH_TOKEN = "no_auth_token"
INVALID_TOKEN = "invalid_token"
HTTP_ERROR = "http_error"
NETWORK_ERROR = "network_error"
JSON_ERROR = "json_error"
API_ERROR = "api_error"
STREAM_ERROR = "stream_error"
NO_RESPONSE = "no_response"
TOKEN_SAVE_ERROR = "token_save_error"
NO_AVAILABLE_TOKEN = "no_available_token"

GROK_STATUS_MAP = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
    500: "internal_server_error",
}

GROK_TYPE_MAP = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "permission_error": 403,
    "not_found_error": 404,
    "rate_limit_error": 429,
    "internal_server_error": 500,
}


def build_error_response(
    error_type: str = "invalid_request_error",
    message: str = "An error occurred",
    code: str = "error",
    param: str = None,
) -> dict:
    return {
        "error": {
            "type": error_type,
            "message": message,
            "code": code,
            "param": param,
        }
    }


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            error_type="http_error",
            message=str(exc.detail),
            code="HTTP_ERROR",
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    return JSONResponse(
        status_code=400,
        content=build_error_response(
            error_type="invalid_request_error",
            message=str(errors),
            code="invalid_request_error",
        ),
    )


async def grok_exception_handler(request: Request, exc: GrokApiException) -> JSONResponse:
    http_status = GROK_TYPE_MAP.get(exc.error_code, 500)
    return JSONResponse(
        status_code=http_status,
        content=exc.to_dict(),
    )
