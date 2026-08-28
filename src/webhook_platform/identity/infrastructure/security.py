from __future__ import annotations

from datetime import datetime

from webhook_platform.config.settings import Settings
from webhook_platform.shared.infrastructure import security


class DefaultIdentitySecurity:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def hash_password(self, password: str) -> str:
        return security.hash_password(password)

    def verify_password(self, password: str, encoded: str) -> bool:
        return security.verify_password(password, encoded)

    def create_access_token(self, user_id: str) -> tuple[str, datetime]:
        return security.create_access_token(self.settings, user_id)

    def new_refresh_token(self) -> str:
        return security.new_refresh_token()

    def token_hash(self, token: str) -> str:
        return security.token_hash(token)
