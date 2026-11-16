"""Human-driven setup and bounded device-code polling."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic, time
from typing import TYPE_CHECKING

import anyio
from a13n_harness_ui.connectors import SetupAction, SetupFlow, Step, Wait
from a13n_harness_ui.errors import HarnessUiError
from pydantic import JsonValue

from .connector import Settings
from .oauth import VERIFY_URL, DeviceCode, auth_error
from .registration import GITHUB_APP_REGISTRATION_URL

if TYPE_CHECKING:
    from .connector import GitHubAppController


class GitHubSetup(SetupFlow):
    def __init__(self, controller: GitHubAppController) -> None:
        self.controller = controller
        self.step: Step | None = None
        self.version: int | None = None
        self.credential_version: int | None = None
        self.device: DeviceCode | None = None
        self.client_id = ""
        self.deadline = 0.0
        self.next_poll = 0.0
        self.closed = False

    async def read(self) -> Step:
        current = await self.controller.context.configuration()
        if self.version is not None and current.version != self.version:
            self.device = None
            self.step = Step(
                key="changed",
                title="Connection changed",
                state="failed",
                error="Restart setup to load the current account settings.",
            )
        if self.step is not None:
            return self.step
        self.version = current.version
        self.credential_version = current.credential_version
        self.client_id = Settings.model_validate(current.settings).client_id
        actions = [
            SetupAction(
                id="register",
                label="Create GitHub App",
                kind="open_url",
                url=GITHUB_APP_REGISTRATION_URL,
            )
        ]
        configured = bool(current.credentials.get("token"))
        if configured:
            actions.extend(
                (
                    SetupAction(id="test", label="Test connection", icon="test"),
                    SetupAction(id="disconnect", label="Disconnect", kind="confirm"),
                )
            )
        actions.append(
            SetupAction(
                id="connect", label="Reconnect GitHub App" if configured else "Connect GitHub App", icon="continue"
            )
        )
        description = (
            "AHUI refreshes your user token automatically when connecting to GitHub. "
            "Use Test connection to verify access. Reconnect after authorization expires, is revoked, "
            "or a token refresh needs attention. Approve installation updates after adding App permissions."
            if configured
            else "Create the App below, enable Device Flow and expiring user tokens, "
            "install it on your repositories, then enter its Client ID. "
            "Adjust the default repository and account permissions as needed. Tokens refresh automatically."
        )
        self.step = Step(
            key="configure",
            title="Connect GitHub App",
            description=description,
            form=Settings.model_json_schema(),
            values={"client_id": self.client_id},
            actions=tuple(actions),
        )
        return self.step

    async def act(self, action: str, values: dict[str, JsonValue]) -> Step:
        step = await self.read()
        available = {item.id for item in step.actions if item.kind in {"submit", "confirm"}}
        if self.closed or action not in available:
            raise auth_error("This setup action is unavailable. Restart setup to continue.")
        if action == "test":
            try:
                await self.controller.mcp.list_tools()
            except Exception:
                raise auth_error(
                    "GitHub connection test failed. Check authorization and repository permissions."
                ) from None
            current = await self.controller.context.configuration()
            self.credential_version = current.credential_version
            self.step = step.model_copy(update={"description": "GitHub MCP connection test succeeded."})
            return self.step
        if action == "cancel":
            await self.close()
            self.step = Step(key="cancelled", title="Authorization cancelled", state="cancelled")
            return self.step
        async with self.controller.lock:
            current = await self.controller.context.require_available()
            if current.version != self.version or current.credential_version != self.credential_version:
                raise auth_error("Account changed during setup. Restart setup to continue.")
            if action == "disconnect":
                saved = await self.controller.context.configure(
                    current, expected_version=current.version, credentials={}
                )
                self.version = saved.version
                self.step = Step(key="disconnected", title="Local authorization removed", state="completed")
                return self.step
            settings = Settings.model_validate(values)
            if not settings.client_id:
                raise auth_error("Enter the GitHub App Client ID from its registration page.")
            device = await self.controller.github.start(settings.client_id)
            self.client_id = settings.client_id
            self.device = device
            self.deadline = monotonic() + device.expires_in
            self.next_poll = monotonic() + device.interval
            self.step = Step(
                key="authorize",
                title="Authorize in GitHub",
                state="waiting",
                description=f"Enter code {device.user_code} in GitHub and confirm the application and permissions.",
                actions=(
                    SetupAction(id="copy", label="Copy code", kind="copy", value=device.user_code),
                    SetupAction(id="open", label="Open GitHub", kind="open_url", url=VERIFY_URL),
                    SetupAction(id="cancel", label="Cancel", kind="confirm"),
                ),
                wait=Wait(
                    message="Waiting for GitHub authorization.",
                    poll_after_ms=1000,
                    expires_at=datetime.fromtimestamp(time() + device.expires_in, UTC),
                ),
            )
            return self.step

    async def run(self) -> None:
        while not self.closed:
            await anyio.sleep(0.5)
            if self.device is None:
                continue
            if monotonic() >= self.deadline:
                self._failed("Authorization expired. Restart setup to get a new code.")
                continue
            if monotonic() < self.next_poll:
                continue
            try:
                await self._poll()
            except HarnessUiError as exc:
                message = (
                    str(exc)
                    if exc.code == "github_app_authorization_failed"
                    else "The account changed during authorization. Reopen setup to reconnect."
                )
                self._failed(message)

    async def _poll(self) -> None:
        async with self.controller.lock:
            device = self.device
            if device is None or self.closed:
                return
            current = await self.controller.context.require_available()
            if current.version != self.version or current.credential_version != self.credential_version:
                raise auth_error("Account changed during authorization.")
            result = await self.controller.github.poll(self.client_id, device.device_code)
            error = result.get("error")
            if isinstance(error, str) and error in {"authorization_pending", "slow_down"}:
                interval = device.interval + (5 if error == "slow_down" else 0)
                self.device = device.model_copy(update={"interval": interval})
                self.next_poll = monotonic() + interval
                return
            tokens = self.controller.github.tokens(result)
            if self.closed or monotonic() >= self.deadline:
                return
            latest = await self.controller.context.require_available()
            if latest.version != self.version or latest.credential_version != self.credential_version:
                raise auth_error("Account changed during authorization.")
            saved = await self.controller.context.configure(
                latest.model_copy(update={"settings": {"client_id": self.client_id}}),
                expected_version=latest.version,
                credentials=tokens.credentials(self.client_id),
            )
            self.version = saved.version
            self.device = None
            self.step = Step(
                key="completed",
                title="GitHub App connected",
                state="completed",
                description=(
                    "User authorization saved. AHUI handles token refresh automatically. "
                    "Send a new message to use the connection. Repository access follows the App installation."
                ),
            )

    def _failed(self, message: str) -> None:
        self.device = None
        self.step = Step(key="failed", title="GitHub authorization failed", state="failed", error=message)

    async def close(self) -> None:
        self.closed = True
        self.device = None
