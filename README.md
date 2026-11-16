# a13n-harness-ui-github-app

GitHub App Connector for a13n Harness UI, distributed as an independent Python package.

## Features

- GitHub App user authorization through Device Flow, with a copyable code and GitHub authorization link in AHUI setup.
- Expiring user access tokens and rotating refresh tokens in AHUI private account storage.
- GitHub's official Remote MCP tools through AHUI's native Connector and CodeAct integration.
- Explicit connection testing, reconnect and local disconnect.

Operations use the authorized user's identity and GitHub App attribution. GitHub controls the exact badge and attribution presentation. Repository access is the intersection of the user's access, the App permissions and the App installation's selected repositories.

## Register your GitHub App

Use **Create GitHub App** in the Connector setup to open a prefilled registration page. It sets the homepage to [a13n](https://a13n.dev/), selects broad repository and user-account permissions and allows installation on other accounts. The registration belongs to the GitHub account you choose.

[Create a prefilled GitHub App](https://github.com/settings/apps/new?name=a13n+Harness+UI+Connector&description=GitHub+App+integration+for+a13n+Harness+UI&url=https%3A%2F%2Fa13n.dev%2F&public=true&webhook_active=false&request_oauth_on_install=false&actions=write&administration=write&artifact_metadata=write&attestations=write&checks=write&code_quality=write&codespaces=write&contents=write&dependabot_secrets=write&deployments=write&discussions=write&environments=write&issues=write&merge_queues=write&metadata=read&packages=write&pages=write&pull_requests=write&repository_custom_properties=write&repository_hooks=write&repository_projects=admin&secret_scanning_alerts=write&secrets=write&security_events=write&statuses=write&vulnerability_alerts=write&workflows=write&email_addresses=write&followers=write&git_ssh_keys=write&gpg_keys=write&interaction_limits=write&profile=write&starring=write)

Review the prefilled values before creating the App. **Manually enable Device Flow** on the GitHub registration page and keep **Expire user authorization tokens** enabled. GitHub's documented registration URL parameters cover the remaining prefilled values. Choose an available App name if the suggested name is taken.

| Field | Value |
| --- | --- |
| GitHub App name | `a13n Harness UI Connector`, or an available name of your choice |
| Homepage URL | `https://a13n.dev/` |
| Callback URL | Leave empty for Device Flow |
| Expire user authorization tokens | Enable |
| Request user authorization during installation | Leave unchecked for this setup flow |
| Enable Device Flow | Enable |
| Setup URL | Leave empty |
| Webhook Active | Leave unchecked for this version |
| Where can this GitHub App be installed? | Choose **Only on this account** for your own account, or **Any account** to support other accounts and organizations |

The prefill requests 34 repository and user-account GitHub App permissions, using each permission's highest supported level. This includes repository administration, Actions and workflows, checks, deployments, releases and contents, issues, PRs, discussions, projects, security alerts, secrets, packages, Pages, Codespaces and user-account permissions. Metadata uses read-only access. Contents covers repository file access. The complete set lives in `registration.py` and follows GitHub's public `app-permissions` schema reviewed on 2026-11-16.

Review the selected permissions in GitHub before registering. Effective access follows the App installation, user authorization and organization policy. Approve updated installation permissions after changing an existing App's permissions.

After registration, copy the **Client ID** from the App settings page. The Client ID is a public identifier, usually beginning with `Iv`. The implemented device authorization and refresh flow uses this single registration value. Client Secret, App ID and PEM private keys belong to other GitHub App authentication flows.

Install the App using **Install App**, and select the repositories to expose. Installation and user authorization are separate steps. Organization installations follow that organization's approval policies.

### First-time checklist

- Create the GitHub App with an available name and review its prefilled permissions.
- Enable **Device Flow** and keep **Expire user authorization tokens** enabled in GitHub.
- Install the App on the target account and select the repositories to expose.
- Copy its **Client ID** into AHUI, enter the device code on GitHub and approve user authorization.

The registered App can be reused for later logins. Each authorized user completes their own device authorization. Operations are attributed to that user with the App's identity, subject to GitHub's presentation.

### Connect from AHUI

1. Install this package into the AHUI Python environment and restart AHUI.
2. Open **Settings → Connections → Connectors → Add connection → GitHub App**.
3. Name the account and open setup.
4. Enter the GitHub App **Client ID** and choose **Connect GitHub App**.
5. Copy the displayed code, choose **Open GitHub**, enter the code and authorize your App.
6. After setup completes, send a new message so the next Run captures the connection.
7. Use **Test connection** in the account setup to check GitHub MCP access explicitly.

AHUI stores access and refresh tokens in its private database under Host filesystem protection. The authorization code is displayed only in the human setup flow. Public declarations and Run captures contain private credential references. Local disconnect clears saved authorization and advances the account configuration version. GitHub's **Settings → Applications → Authorized GitHub Apps** manages upstream authorization revocation.

## Automatic renewal and reconnect

Renewal is automatic after the initial device authorization. GitHub's default access token lifetime is eight hours, and refresh tokens last about six months. Each successful refresh rotates both tokens and saves their new expiry times. The plugin requests `offline_access` during device authorization to obtain expiring user tokens and a refresh token.

When a new MCP connection needs authorization, AHUI refreshes a token that has expired or has 60 seconds or less remaining. An idle account refreshes on its next connection. The configured **Test connection** action follows the same path. Concurrent refreshes serialize per account.

| Situation | User action |
| --- | --- |
| Routine access token expiry with valid refresh authorization | Continue using the connection; AHUI renews it automatically |
| Refresh token expiry or revoked authorization | Choose **Reconnect GitHub App** and authorize a new device code |
| Interrupted or uncertain refresh | Choose **Reconnect GitHub App** to recover authorization |
| App permissions expanded | Approve the installation's permission update in GitHub |
| Repository missing from the installation | Add it to the App installation's selected repositories |
| Existing MCP Run spans the access token lifetime | Start a fresh Run to open a connection with a current token |

## Manual verification

After installing the package, restart the AHUI process that uses that Python environment. This checkout can run its own installed AHUI through `uv run --locked a13n-harness-ui webui`.

1. Open **Settings → Connections → Connectors**, add **GitHub App** and open **Create GitHub App**. Confirm the a13n homepage and repository/account permissions on GitHub.
2. Complete the first-time checklist above, then finish device authorization. Expect the Connector to become ready.
3. Reopen setup and choose **Test connection**. Expect a successful GitHub MCP connection test.
4. Send a fresh chat message asking the agent to identify the connected GitHub user and read an Issue or PR in an installed repository. Confirm the returned account and repository.
5. Ask the agent to post a short test comment on an Issue or PR you choose. Inspect the author and GitHub App attribution on GitHub.
6. Restart AHUI and repeat the connection test to check saved authorization. After the access token expires, repeat the test to exercise automatic renewal. Mocked tests cover the refresh path during development.

For a failed test, record the failing step and the displayed error. Share the Connector's public status and error text when reporting the result. Keep token values in the private account store.

## Development

Requires Python 3.13+ and uv.

```sh
uv sync --locked
make check
make build
```

Tests exercise the installed entry point and OAuth requests using local HTTP fixtures. Live account authorization, upstream permissions and GitHub's rendered attribution need account-level verification.

## Load into AHUI

Requires Python 3.13+ and AHUI `>=0.37.6,<0.38`. Install the package into the same Python environment as AHUI, then restart the AHUI process. GitHub installation builds the package directly from its repository. PyPI publication is optional.

### AHUI managed by uv tool

Stop AHUI, then install it with the Connector as an additional dependency. For an upgrade from an older AHUI release, back up its configuration and data root first. Replace `OWNER` with the repository owner and `TAG_OR_COMMIT` with a published tag or commit SHA.

```sh
uv tool install --force --python 3.13 \
  --with "git+https://github.com/OWNER/a13n-harness-ui-github-app.git@TAG_OR_COMMIT" \
  "a13n-harness-ui>=0.37.6,<0.38"
```

This selects a compatible AHUI version and records the Connector as a dependency of the tool environment. Include any additional dependencies from your existing installation as further `--with` arguments. Restart AHUI with your usual configuration and data root, then open **Settings → Connections → Connectors**.

For local development, use an editable checkout.

```sh
uv tool install --force --python 3.13 \
  --with-editable /path/to/a13n-harness-ui-github-app \
  "a13n-harness-ui>=0.37.6,<0.38"
```

### AHUI in a uv project

Run this from the project that already depends on AHUI.

```sh
uv add "git+https://github.com/OWNER/a13n-harness-ui-github-app.git@TAG_OR_COMMIT"
```

For local development, add an editable checkout instead.

```sh
uv add --editable /path/to/a13n-harness-ui-github-app
```

### AHUI in an existing virtual environment

Use the Python executable from the environment that runs AHUI.

```sh
uv pip install --python /path/to/ahui-environment/bin/python \
  "git+https://github.com/OWNER/a13n-harness-ui-github-app.git@TAG_OR_COMMIT"
```

The registered Connector key is `github-app`.

## Runtime behavior

The plugin uses AHUI account configuration versions and credential compare-and-swap writes. Concurrent refreshes within the account controller serialize. A durable pending marker is written before submitting a rotating refresh token. Interrupted or uncertain refreshes require a fresh device authorization to recover. Closing setup cancels pending local authorization work and preserves previously saved credentials.

Access tokens refresh when an MCP connection resolves its private Authorization header, within 60 seconds of expiry. AHUI holds a native MCP client for one logical Run. An already-open client retains its original header, so a Run spanning the token lifetime may need a new message and fresh Run after expiry. GitHub defaults to an eight-hour user access token lifetime.

The current integration targets GitHub.com and tool execution. GitHub Enterprise endpoints and automatic event collection are future extensions.

## Architecture and references

AHUI owns account persistence, private credential storage, setup presentation and Run capture. This package owns GitHub App device authorization, refresh and its concrete service recipe. The fixed GitHub Remote MCP endpoint is `https://api.githubcopilot.com/mcp/`.

- [AHUI Connector contract](https://github.com/converge-ai-labs/agent-foundation/blob/main/spec/a13n-harness-ui/13-connectors.md)
- [AHUI Connector example](https://github.com/converge-ai-labs/agent-foundation/tree/main/examples/harness-ui-connectors)
- [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)
- [Generating a user access token with Device Flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app#using-the-device-flow-to-generate-a-user-access-token)
- [Refreshing user access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)
- [GitHub App user attribution](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user)
