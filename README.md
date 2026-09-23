# jupyter-positron-verifier

> [!CAUTION]
> This package is no longer needed to run Positron Server on JupyterHub. It is **not** recommended to use this package.
> Rather, follow the instructions given by `jupyter-positron-server`: https://posit-dev.github.io/jupyter-positron-server/

A JupyterHub managed service that mints short-lived, cryptographically signed Positron Server license tokens for per-session use.

## What it does

When Positron Server runs inside a JupyterHub environment, it needs a per-session license token to operate. This service sits between JupyterHub and Positron Server and handles that handoff:

1. **Authenticates the caller** — verifies the caller's JupyterHub API token against the Hub's `/authorizations/token` endpoint using the service's own token.
2. **Checks entitlement** — calls a local `license-manager` binary to verify the host's Positron Server license is active. The result is cached for 5 minutes.
3. **Mints a license** — signs a JSON payload (connection token + timestamp) with an RSA private key 
4. **Prevents reuse** — tracks issued connection tokens so each one gets exactly one license.

The single HTTP endpoint is `POST {SERVICE_PREFIX}/mint`.

## Running

```bash
pip install jupyter-positron-verifier
positron-verifier
```

In practice, this is used under the hood by Positron. You should not need to interact with this package.
