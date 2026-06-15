from __future__ import annotations


class AIServiceError(Exception):
    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider


class AIConfigurationError(AIServiceError):
    pass


class AIValidationError(AIServiceError):
    pass


class AIRemoteError(AIServiceError):
    pass


class AIProviderError(AIRemoteError):
    pass


class AIRateLimitError(AIRemoteError):
    pass


class AITimeoutError(AIRemoteError):
    pass
