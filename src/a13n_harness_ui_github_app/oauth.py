"""GitHub App device authorization using fixed GitHub.com endpoints."""

from time import time

import httpx2
from a13n_harness_ui.errors import HarnessUiError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_URL = "https://github.com/login/device/code"
VERIFY_URL = "https://github.com/login/device"

AUTHORIZATION_ERRORS = {
    "device_flow_disabled": "Enable Device Flow in your GitHub App settings, then connect again.",
    "incorrect_client_credentials": "Copy the Client ID from your GitHub App settings, then connect again.",
    "access_denied": "GitHub authorization was declined. Reopen setup to request a new device code.",
    "expired_token": "The GitHub device code expired. Reopen setup to request a new code.",
    "token_expired": "The GitHub device code expired. Reopen setup to request a new code.",
    "bad_refresh_token": "GitHub refresh authorization expired or was revoked. Reconnect the GitHub App.",
    "invalid_grant": "GitHub refresh authorization expired or was revoked. Reconnect the GitHub App.",
}


class DeviceCode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device_code: str = Field(min_length=1, repr=False)
    user_code: str = Field(min_length=1)
    verification_uri: str
    expires_in: int = Field(gt=0, le=1800)
    interval: int = Field(default=5, ge=1, le=60)


class Tokens(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: str = Field(pattern=r"^ghu_[A-Za-z0-9_]+$", repr=False)
    token_type: str = Field(pattern=r"(?i)^bearer$")
    expires_in: int = Field(gt=0)
    refresh_token: str = Field(min_length=1, repr=False)
    refresh_token_expires_in: int = Field(gt=0)

    def credentials(self, client_id: str) -> dict[str, str]:
        now = time()
        return {
            "client_id": client_id,
            "token": f"Bearer {self.access_token}",
            "expires_at": str(now + self.expires_in),
            "refresh_token": self.refresh_token,
            "refresh_expires_at": str(now + self.refresh_token_expires_in),
        }


def auth_error(message: str) -> HarnessUiError:
    return HarnessUiError(message, code="github_app_authorization_failed")


class GitHubOAuth:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self.client = client

    async def _post(self, url: str, data: dict[str, str]) -> dict:
        try:
            response = await self.client.post(url, data=data, headers={"Accept": "application/json"})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (httpx2.HTTPError, ValueError):
            raise auth_error("GitHub authorization request failed. Check connectivity and reconnect.") from None

    async def start(self, client_id: str) -> DeviceCode:
        result = await self._post(DEVICE_URL, {"client_id": client_id, "scope": "offline_access"})
        if "error" in result:
            error = result.get("error")
            message = AUTHORIZATION_ERRORS.get(error) if isinstance(error, str) else None
            raise auth_error(message or "Check the GitHub App Client ID and enable Device Flow in its registration.")
        try:
            device = DeviceCode.model_validate(result)
            if device.verification_uri != VERIFY_URL:
                raise ValueError
            return device
        except (ValidationError, ValueError):
            raise auth_error("GitHub returned an invalid device authorization response.") from None

    async def poll(self, client_id: str, device_code: str) -> dict:
        return await self._post(
            TOKEN_URL,
            {
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

    async def refresh(self, client_id: str, refresh_token: str) -> Tokens:
        result = await self._post(
            TOKEN_URL,
            {"client_id": client_id, "refresh_token": refresh_token, "grant_type": "refresh_token"},
        )
        return self.tokens(result)

    @staticmethod
    def tokens(result: dict) -> Tokens:
        error = result.get("error")
        if isinstance(error, str):
            raise auth_error(
                AUTHORIZATION_ERRORS.get(error, "GitHub authorization failed. Reopen setup and connect again.")
            )
        try:
            return Tokens.model_validate(result)
        except ValidationError:
            raise auth_error(
                "GitHub returned incomplete token information. Enable expiring user tokens and reconnect."
            ) from None
