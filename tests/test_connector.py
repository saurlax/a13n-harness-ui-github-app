"""Exercise registration, device setup and refresh against HTTP fixtures."""

from importlib.metadata import entry_points
from pathlib import Path
from time import monotonic, time
from urllib.parse import parse_qs, urlparse

import anyio
import httpx2
import pytest
from a13n_harness_ui.configuration.models import McpPrivateValueSource
from a13n_harness_ui.connector_models import ConnectorConfiguration
from a13n_harness_ui.connectors import Capture, Context, Definition
from a13n_harness_ui.connectors.catalog import Catalog
from a13n_harness_ui.errors import HarnessUiError

from a13n_harness_ui_github_app import GitHubApp
from a13n_harness_ui_github_app.connector import GitHubAppController
from a13n_harness_ui_github_app.oauth import VERIFY_URL, GitHubOAuth
from a13n_harness_ui_github_app.registration import APP_PERMISSIONS, GITHUB_APP_REGISTRATION_URL
from a13n_harness_ui_github_app.setup import GitHubSetup

CLIENT_ID = "Iv23liExample"
TOKEN_REPLY = {
    "access_token": "ghu_example",
    "token_type": "bearer",
    "expires_in": 28800,
    "refresh_token": "ghr_example",
    "refresh_token_expires_in": 15897600,
}
DEVICE_REPLY = {
    "device_code": "private-device-code",
    "user_code": "ABCD-EFGH",
    "verification_uri": VERIFY_URL,
    "expires_in": 900,
    "interval": 5,
}


class MemoryContext(Context):
    def __init__(self, *, authorized=False, expired=False):
        self.connector_id = "connector-example"
        self.oauth = None
        credentials = {}
        if authorized:
            credentials = GitHubOAuth.tokens(TOKEN_REPLY).credentials(CLIENT_ID)
            if expired:
                credentials["expires_at"] = "0"
        self.current = ConnectorConfiguration(
            connector_id=self.connector_id,
            kind="github-app",
            group_name="github-app",
            settings={"client_id": CLIENT_ID} if authorized else {},
            credentials=credentials,
        )

    async def configuration(self):
        return self.current.model_copy(deep=True)

    async def require_available(self, capture: Capture | None = None):
        if not self.current.enabled or (capture is not None and capture.configuration_version != self.current.version):
            raise HarnessUiError("Account disabled or changed", code="connector_binding_changed")
        return await self.configuration()

    async def configure(self, candidate, *, expected_version, credentials=None):
        assert expected_version == self.current.version
        assert candidate.credential_version == self.current.credential_version
        self.current = candidate.model_copy(
            update={
                "version": self.current.version + 1,
                "credentials": dict(credentials) if credentials is not None else self.current.credentials,
                "credential_version": self.current.credential_version + (credentials is not None),
            }
        )
        return await self.configuration()

    async def save_credentials(self, *, expected_version, credentials):
        assert expected_version == self.current.credential_version
        self.current = self.current.model_copy(
            update={
                "credential_version": expected_version + 1,
                "credentials": dict(credentials),
            }
        )
        return self.current.credential_version


def private_source(context):
    return McpPrivateValueSource(
        connector_id=context.connector_id, configuration_version=context.current.version, key="token"
    )


def test_installed_connector_is_discoverable():
    entries = tuple(entry_points(group="a13n_harness_ui.connectors", name="github-app"))
    assert len(entries) == 1
    assert isinstance(entries[0].load()(), Definition)
    catalog = Catalog(installed=entries)
    assert catalog.items["github-app"].available
    assert isinstance(catalog.definitions["github-app"], GitHubApp)
    assert "github" in catalog.definitions


@pytest.mark.anyio
async def test_initial_account():
    context = MemoryContext()
    async with GitHubApp().open(context) as controller:
        assert (await controller.status()).state == "unconfigured"
        assert await controller.capture() is None
        flow = await controller.begin_setup("configure")
        step = await flow.read()
        assert step.key == "configure"
        registration = next(action for action in step.actions if action.id == "register")
        assert registration.kind == "open_url"
        assert registration.url == GITHUB_APP_REGISTRATION_URL
        assert "enable Device Flow" in step.description
        assert "expiring user tokens" in step.description
        assert "Tokens refresh automatically" in step.description
        assert not context.current.credentials
        await flow.close()


def test_registration_link_uses_public_defaults():
    link = urlparse(GITHUB_APP_REGISTRATION_URL)
    assert link.scheme == "https"
    assert link.netloc == "github.com"
    assert link.path == "/settings/apps/new"
    assert parse_qs(link.query) == {
        "name": ["a13n Harness UI Connector"],
        "description": ["GitHub App integration for a13n Harness UI"],
        "url": ["https://a13n.dev/"],
        "public": ["true"],
        "webhook_active": ["false"],
        "request_oauth_on_install": ["false"],
        **{key: [value] for key, value in APP_PERMISSIONS.items()},
    }
    assert len(APP_PERMISSIONS) == 34
    assert APP_PERMISSIONS["metadata"] == "read"
    assert APP_PERMISSIONS["administration"] == "write"
    assert APP_PERMISSIONS["workflows"] == "write"
    assert APP_PERMISSIONS["git_ssh_keys"] == "write"
    assert not any(key.startswith("organization_") for key in APP_PERMISSIONS)
    assert "members" not in APP_PERMISSIONS
    assert "custom_properties_for_organizations" not in APP_PERMISSIONS
    readme = Path(__file__).parents[1] / "README.md"
    assert f"({GITHUB_APP_REGISTRATION_URL})" in readme.read_text()


@pytest.mark.anyio
async def test_configured_setup_keeps_connect_as_primary_action():
    async with GitHubApp().open(MemoryContext(authorized=True)) as controller:
        flow = await controller.begin_setup("configure")
        step = await flow.read()
        submissions = [action for action in step.actions if action.kind in {"submit", "confirm"}]
        assert submissions[-1].id == "connect"
        assert submissions[-1].label == "Reconnect GitHub App"
        assert "refreshes your user token automatically" in step.description
        assert any(action.id == "register" for action in step.actions)
        await flow.close()


@pytest.mark.anyio
async def test_device_setup_and_private_capture():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=DEVICE_REPLY if request.url.path.endswith("/code") else TOKEN_REPLY)

    context = MemoryContext()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        flow = GitHubSetup(controller)
        await flow.read()
        step = await flow.act("connect", {"client_id": CLIENT_ID})
        assert step.state == "waiting"
        assert "ABCD-EFGH" in step.description
        assert "private-device-code" not in step.model_dump_json()
        assert not context.current.credentials
        await flow._poll()
        assert (await flow.read()).state == "completed"
        assert "token refresh automatically" in (await flow.read()).description
        assert (await controller.status()).state == "ready"
        assert context.current.credentials["token"] == "Bearer ghu_example"
        assert context.current.settings == {"client_id": CLIENT_ID}
        binding = await controller.capture()
        assert binding is not None
        assert "ghu_example" not in str(binding)
        assert "ghr_example" not in str(binding)
        assert "api.githubcopilot.com/mcp/" in str(binding)
        assert parse_qs(requests[0].content.decode())["scope"] == ["offline_access"]
        assert "client_secret" not in requests[1].content.decode()


@pytest.mark.anyio
@pytest.mark.parametrize("error", ["authorization_pending", "slow_down"])
async def test_pending_and_slow_down(error):
    def handler(request):
        return httpx2.Response(200, json=DEVICE_REPLY if request.url.path.endswith("/code") else {"error": error})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        flow = GitHubSetup(GitHubAppController(MemoryContext(), GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        await flow._poll()
        assert flow.device is not None
        assert flow.device.interval == (10 if error == "slow_down" else 5)
        assert flow.next_poll > monotonic()


@pytest.mark.anyio
async def test_cancel_does_not_store_tokens():
    context = MemoryContext()
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=DEVICE_REPLY))
    ) as client:
        flow = GitHubSetup(GitHubAppController(context, GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        await flow.act("cancel", {})
        await flow._poll()
        assert flow.device is None
        assert not context.current.credentials


@pytest.mark.anyio
async def test_concurrent_refresh_rotates_once():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=TOKEN_REPLY)

    context = MemoryContext(authorized=True, expired=True)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        source = private_source(context)
        async with anyio.create_task_group() as group:
            group.start_soon(controller._private_value, source)
            group.start_soon(controller._private_value, source)
        assert len(requests) == 1
        assert context.current.credential_version == 3
        assert "refresh_pending" not in context.current.credentials
        assert float(context.current.credentials["expires_at"]) > time()
        assert "client_secret" not in requests[0].content.decode()


@pytest.mark.anyio
async def test_failed_refresh_is_fenced_after_restart():
    def handler(request):
        raise httpx2.ReadTimeout("credential must not appear", request=request)

    context = MemoryContext(authorized=True, expired=True)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        with pytest.raises(HarnessUiError, match="request failed"):
            await controller._private_value(private_source(context))
        restarted = GitHubAppController(context, GitHubOAuth(client))
        assert (await restarted.status()).state == "degraded"
        assert await restarted.capture() is None
        with pytest.raises(HarnessUiError, match="Reconnect"):
            await restarted._private_value(private_source(context))


@pytest.mark.anyio
async def test_disconnect_fences_old_capture():
    context = MemoryContext(authorized=True)
    async with httpx2.AsyncClient() as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        source = private_source(context)
        flow = GitHubSetup(controller)
        await flow.act("disconnect", {})
        assert (await flow.read()).state == "completed"
        assert not context.current.credentials
        with pytest.raises(HarnessUiError, match="changed"):
            await controller._private_value(source)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response", [{"error": "device_flow_disabled"}, {**DEVICE_REPLY, "verification_uri": "https://evil.invalid"}]
)
async def test_invalid_authorization_responses(response):
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=response))
    ) as client:
        with pytest.raises(HarnessUiError):
            await GitHubOAuth(client).start(CLIENT_ID)


@pytest.mark.anyio
async def test_setup_does_not_overwrite_concurrent_changes():
    context = MemoryContext()

    def handler(request):
        if request.url.path.endswith("/code"):
            return httpx2.Response(200, json=DEVICE_REPLY)
        context.current = context.current.model_copy(update={"version": 2})
        return httpx2.Response(200, json=TOKEN_REPLY)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        flow = GitHubSetup(GitHubAppController(context, GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        with pytest.raises(HarnessUiError, match="changed"):
            await flow._poll()
        assert not context.current.credentials


@pytest.mark.anyio
async def test_setup_worker_polls_and_completes(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=DEVICE_REPLY if request.url.path.endswith("/code") else TOKEN_REPLY)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        flow = GitHubSetup(GitHubAppController(MemoryContext(), GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        # Make the initial interval elapsed without waiting for GitHub's real polling delay.
        flow.next_poll = 0
        observed = anyio.Event()
        original_poll = flow._poll

        async def poll_once():
            try:
                await original_poll()
            finally:
                observed.set()

        monkeypatch.setattr(flow, "_poll", poll_once)
        async with anyio.create_task_group() as group:
            group.start_soon(flow.run)
            with anyio.fail_after(3):
                await observed.wait()
            assert (await flow.read()).state == "completed"
            await flow.close()
        assert len(requests) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("failure, expected_error", [("access_denied", "declined"), ("expired_token", "expired")])
async def test_setup_worker_reports_terminal_authorization_error(failure, expected_error, monkeypatch):
    def handler(request):
        result = DEVICE_REPLY if request.url.path.endswith("/code") else {"error": failure}
        return httpx2.Response(200, json=result)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        flow = GitHubSetup(GitHubAppController(MemoryContext(), GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        flow.next_poll = 0
        observed = anyio.Event()
        original_poll = flow._poll

        async def poll_once():
            try:
                await original_poll()
            finally:
                observed.set()

        monkeypatch.setattr(flow, "_poll", poll_once)
        async with anyio.create_task_group() as group:
            group.start_soon(flow.run)
            with anyio.fail_after(3):
                await observed.wait()
            assert (await flow.read()).state == "failed"
            assert expected_error in ((await flow.read()).error or "")
            await flow.close()
        assert flow.device is None


@pytest.mark.anyio
async def test_disabled_account_rejects_token_resolution():
    context = MemoryContext(authorized=True)
    context.current = context.current.model_copy(update={"enabled": False})
    async with httpx2.AsyncClient() as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        assert (await controller.status()).state == "disabled"
        with pytest.raises(HarnessUiError):
            await controller._private_value(private_source(context))


@pytest.mark.anyio
async def test_cancellation_during_refresh_retains_durable_fence():
    started = anyio.Event()

    async def handler(request):
        started.set()
        await anyio.sleep_forever()
        return httpx2.Response(200, json=TOKEN_REPLY)

    context = MemoryContext(authorized=True, expired=True)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        async with anyio.create_task_group() as group:
            group.start_soon(controller._private_value, private_source(context))
            await started.wait()
            group.cancel_scope.cancel()
        assert context.current.credentials["refresh_pending"] == "true"
        assert (await controller.status()).state == "degraded"


@pytest.mark.anyio
async def test_close_during_poll_preserves_previous_authorization():
    context = MemoryContext(authorized=True)
    initial = dict(context.current.credentials)
    flow = None

    async def handler(request):
        if request.url.path.endswith("/code"):
            return httpx2.Response(200, json=DEVICE_REPLY)
        assert flow is not None
        await flow.close()
        return httpx2.Response(200, json=TOKEN_REPLY)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        flow = GitHubSetup(GitHubAppController(context, GitHubOAuth(client)))
        await flow.act("connect", {"client_id": CLIENT_ID})
        await flow._poll()
        assert context.current.credentials == initial
        assert context.current.version == 1


@pytest.mark.anyio
@pytest.mark.parametrize("seconds_remaining, expected_refreshes", [(120, 0), (30, 1)])
async def test_token_refresh_threshold(seconds_remaining, expected_refreshes):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=TOKEN_REPLY)

    context = MemoryContext(authorized=True)
    context.current.credentials["expires_at"] = str(time() + seconds_remaining)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        controller = GitHubAppController(context, GitHubOAuth(client))
        assert await controller._private_value(private_source(context)) == "Bearer ghu_example"
        assert len(requests) == expected_refreshes


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error, expected_message",
    [("device_flow_disabled", "Enable Device Flow"), ("incorrect_client_credentials", "Client ID")],
)
async def test_registration_errors_show_specific_recovery(error, expected_message):
    response = {"error": error, "error_description": "untrusted-sensitive-detail"}
    transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=response))
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(HarnessUiError, match=expected_message) as caught:
            await GitHubOAuth(client).start(CLIENT_ID)
        assert "untrusted-sensitive-detail" not in str(caught.value)


def test_revoked_refresh_authorization_has_reconnect_message():
    with pytest.raises(HarnessUiError, match="Reconnect the GitHub App"):
        GitHubOAuth.tokens({"error": "bad_refresh_token"})
