class TryglawError(Exception):
    pass


class RouteNotConfiguredError(TryglawError):
    def __init__(self, system: str, environment: str, reason: str | None = None):
        self.system = system
        self.environment = environment
        self.reason = reason
        detail = f"No route configured for {system}/{environment}"
        if reason:
            detail += f" ({reason})"
        super().__init__(detail)


class ConfigurationError(TryglawError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Configuration error: {detail}")


class MokoszUnavailableError(TryglawError):
    def __init__(self, mokosz_id: str):
        self.mokosz_id = mokosz_id
        super().__init__(f"Mokosz {mokosz_id} is not connected")


class TargetTimeoutError(TryglawError):
    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__(f"Target timeout for request {request_id}")
