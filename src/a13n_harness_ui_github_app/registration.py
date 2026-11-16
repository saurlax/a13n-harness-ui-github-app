"""Shared public GitHub App registration defaults with repository and user-account permissions."""

from urllib.parse import urlencode

# GitHub app-permissions schema, reviewed 2026-11-16. Metadata remains read-only.
APP_PERMISSIONS = {
    "actions": "write",
    "administration": "write",
    "artifact_metadata": "write",
    "attestations": "write",
    "checks": "write",
    "code_quality": "write",
    "codespaces": "write",
    "contents": "write",
    "dependabot_secrets": "write",
    "deployments": "write",
    "discussions": "write",
    "environments": "write",
    "issues": "write",
    "merge_queues": "write",
    "metadata": "read",
    "packages": "write",
    "pages": "write",
    "pull_requests": "write",
    "repository_custom_properties": "write",
    "repository_hooks": "write",
    "repository_projects": "admin",
    "secret_scanning_alerts": "write",
    "secrets": "write",
    "security_events": "write",
    "statuses": "write",
    "vulnerability_alerts": "write",
    "workflows": "write",
    "email_addresses": "write",
    "followers": "write",
    "git_ssh_keys": "write",
    "gpg_keys": "write",
    "interaction_limits": "write",
    "profile": "write",
    "starring": "write",
}

GITHUB_APP_REGISTRATION_URL = "https://github.com/settings/apps/new?" + urlencode(
    {
        "name": "a13n Harness UI Connector",
        "description": "GitHub App integration for a13n Harness UI",
        "url": "https://a13n.dev/",
        "public": "true",
        "webhook_active": "false",
        "request_oauth_on_install": "false",
        **APP_PERMISSIONS,
    }
)
