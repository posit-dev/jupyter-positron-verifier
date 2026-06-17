# jupyter-positron-verifier

A JupyterHub managed service that mints short-lived, cryptographically signed Positron Server license tokens for per-session use.

## What it does

When Positron Server runs inside a JupyterHub environment, it needs a per-session license token to operate. This service sits between JupyterHub and Positron Server and handles that handoff:

1. **Authenticates the caller** — verifies the caller's JupyterHub API token against the Hub's `/authorizations/token` endpoint using the service's own token.
2. **Checks entitlement** — calls a local `license-manager` binary to verify the host's Positron Server license is active. The result is cached for 5 minutes.
3. **Mints a license** — signs a JSON payload (connection token + timestamp) with an RSA private key 
4. **Prevents reuse** — tracks issued connection tokens so each one gets exactly one license.

The single HTTP endpoint is `POST {SERVICE_PREFIX}/mint`.

## Configuration

All configuration is via environment variables. JupyterHub sets the `JUPYTERHUB_*` variables automatically for managed services.

| Variable | Description |
|---|---|
| `JUPYTERHUB_API_URL` | Hub API base URL (default: `http://hub:8081/hub/api`) |
| `JUPYTERHUB_API_TOKEN` | This service's own Hub token (set automatically by JupyterHub) |
| `JUPYTERHUB_SERVICE_PREFIX` | URL prefix for this service (default: `/services/positron-license/`) |
| `POSITRON_MINTING_KEY` | PEM-encoded RSA private key (literal string) |
| `POSITRON_MINTING_KEY_FILE` | Path to a PEM-encoded RSA private key file (used if `POSITRON_MINTING_KEY` is unset) |
| `POSITRON_LICENSE_MANAGER_PATH` | Path to the `license-manager` binary for entitlement checks |
| `PORT` | Port to listen on (default: `8099`) |

## Running

```bash
pip install jupyter-positron-verifier
positron-verifier
```

In practice, this is used under the hood by Positron. You should not need to interact with this package.
