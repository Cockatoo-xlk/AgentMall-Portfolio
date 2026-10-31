class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def not_found():
    return DomainError(404, "NOT_FOUND", "对象不存在或不可访问")
