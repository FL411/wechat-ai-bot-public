class WeChatBotError(Exception):
    pass


class WindowNotFoundError(WeChatBotError):
    pass


class SendMessageError(WeChatBotError):
    pass


class WindowActivationError(WeChatBotError):
    pass


class LMStudioError(Exception):
    pass


class LMStudioConnectionError(LMStudioError):
    pass


class LMStudioTimeoutError(LMStudioError):
    pass


class LMStudioResponseError(LMStudioError):
    pass


class NetworkError(Exception):
    pass


class WebSocketError(NetworkError):
    pass


class ConfigurationError(Exception):
    pass


class SessionError(Exception):
    pass


class MemoryError(Exception):
    pass
