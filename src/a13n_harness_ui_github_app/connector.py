"""GitHub App accounts backed by GitHub's official Remote MCP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import time

import anyio
import httpx2
from a13n_harness_ui.composition.models import ResolvedMcpRecipe
from a13n_harness_ui.configuration.models import McpPrivateValueSource, McpRemoteTransport
from a13n_harness_ui.connector_models import ConnectorConfiguration
from a13n_harness_ui.connectors import Context, Controller, Declaration, Definition, SetupFlow, Status
from a13n_harness_ui.connectors.remote_mcp import RemoteMcp
from pydantic import BaseModel, ConfigDict, Field

from .oauth import GitHubOAuth, auth_error

GITHUB_ENDPOINT = "https://api.githubcopilot.com/mcp/"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(
        default="",
        pattern=r"^(?:Iv[A-Za-z0-9.]+|)$",
        title="GitHub App Client ID",
        description="Copy the public Client ID from your GitHub App settings page after registration.",
    )


def token_deadline(credentials: dict[str, str], key: str) -> float:
    try:
        return float(credentials.get(key, "0"))
    except ValueError:
        return 0


class GitHubApp(Definition):
    configuration_model = Settings

    def declaration(self) -> Declaration:
        return Declaration(
            key="github-app",
            name="GitHub App",
            brand="github",
            description="Repositories, issues and pull requests using your GitHub App user authorization.",
            configuration_schema={**Settings.model_json_schema(), "readOnly": True},
            setup_intents=("configure", "test"),
        )

    @asynccontextmanager
    async def open(self, context: Context) -> AsyncIterator[Controller]:
        async with httpx2.AsyncClient(timeout=15, follow_redirects=False) as client:
            yield GitHubAppController(context, GitHubOAuth(client))


class GitHubAppController(RemoteMcp):
    def __init__(self, context: Context, oauth: GitHubOAuth) -> None:
        super().__init__(context)
        self.github = oauth
        self.lock = anyio.Lock()

    def connection(self, configuration: ConnectorConfiguration) -> ResolvedMcpRecipe | None:
        settings = Settings.model_validate(configuration.settings)
        credentials = configuration.credentials
        if (
            not settings.client_id
            or credentials.get("client_id") != settings.client_id
            or not credentials.get("token")
            or credentials.get("refresh_pending")
        ):
            return None
        return ResolvedMcpRecipe(
            server_id=configuration.connector_id,
            transport=McpRemoteTransport(
                url=GITHUB_ENDPOINT,
                headers={
                    "Authorization": McpPrivateValueSource(
                        connector_id=configuration.connector_id,
                        configuration_version=configuration.version,
                        key="token",
                    )
                },
            ),
        )

    async def status(self) -> Status:
        current = await self.context.configuration()
        if not current.enabled:
            return Status(state="disabled", summary="Connection is disabled.")
        if current.credentials.get("refresh_pending"):
            return Status(state="degraded", summary="Token refresh needs attention. Reconnect to continue.")
        if self.connection(current) is None:
            return Status(state="unconfigured", summary="Connect a GitHub App using its Client ID.")
        if token_deadline(current.credentials, "expires_at") <= time() + 60:
            if token_deadline(current.credentials, "refresh_expires_at") <= time():
                return Status(state="degraded", summary="Authorization expired. Reconnect to continue.")
        return Status(state="ready", summary="Authorized. GitHub permissions are checked when connecting.")

    async def _private_value(self, source: McpPrivateValueSource) -> str:
        if source.connector_id != self.context.connector_id or source.key != "token":
            raise auth_error("GitHub authorization belongs to a different connection.")
        async with self.lock:
            current = await self.context.require_available()
            if current.version != source.configuration_version:
                raise auth_error("Connection settings changed. Send a new message to continue.")
            if self.connection(current) is None:
                raise auth_error("Reconnect the GitHub App to continue.")
            if token_deadline(current.credentials, "expires_at") > time() + 60:
                return current.credentials["token"]
            if token_deadline(current.credentials, "refresh_expires_at") <= time():
                raise auth_error("GitHub authorization expired. Reconnect to continue.")
            credentials = dict(current.credentials)
            # Refresh tokens rotate once. A durable marker fences uncertain or interrupted refreshes.
            credentials["refresh_pending"] = "true"
            version = await self.context.save_credentials(
                expected_version=current.credential_version, credentials=credentials
            )
            tokens = await self.github.refresh(credentials["client_id"], credentials["refresh_token"])
            latest = await self.context.require_available()
            if latest.version != current.version:
                raise auth_error("Connection settings changed during refresh. Reconnect to continue.")
            refreshed = tokens.credentials(credentials["client_id"])
            await self.context.save_credentials(expected_version=version, credentials=refreshed)
            return refreshed["token"]

    async def begin_setup(self, intent: str) -> SetupFlow:
        from .setup import GitHubSetup

        return GitHubSetup(self)
