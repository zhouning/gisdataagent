from __future__ import annotations


class GwmApiError(Exception):
    def __init__(self, code: str, status_code: int, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status_code = status_code
        self.detail = detail
