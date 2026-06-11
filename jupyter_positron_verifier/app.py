"""
FastAPI application for the Positron Hub minting service.
"""

import logging
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from .entitlement import EntitlementChecker
from .signing import Signer
from .store import TokenStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (overridable in tests via dependency_overrides)
# ---------------------------------------------------------------------------

_signer: Signer | None = None
_entitlement: EntitlementChecker | None = None
_store: TokenStore = TokenStore()


def get_signer() -> Signer:
    global _signer
    if _signer is None:
        _signer = Signer.from_env()
    return _signer


def get_entitlement() -> EntitlementChecker:
    global _entitlement
    if _entitlement is None:
        _entitlement = EntitlementChecker.from_env()
    return _entitlement


def get_store() -> TokenStore:
    return _store


# ---------------------------------------------------------------------------
# Hub token verification (module-level so tests can override it)
# ---------------------------------------------------------------------------

_hub_api_url = os.environ.get("JUPYTERHUB_API_URL", "http://hub:8081/hub/api").rstrip("/")
# The service's own API token, set by JupyterHub when it launches this managed service.
_service_token = os.environ.get("JUPYTERHUB_API_TOKEN", "")


async def verify_hub_token(request: Request) -> str:
    """Verify the caller's token using the Hub /authorizations/token endpoint.

    Accepts both JupyterHub-style ``Authorization: token X`` and OAuth-style
    ``Authorization: Bearer X`` so that jupyter-positron-server can use its
    native JUPYTERHUB_API_TOKEN without scheme conversion.

    The service authenticates with its own token; the Hub tells us whether the
    caller's token is valid and which user it belongs to.
    """
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() not in ("bearer", "token") or not parts[1]:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    caller_token = parts[1]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_hub_api_url}/authorizations/token/{caller_token}",
                headers={"Authorization": f"token {_service_token}"},
                timeout=5,
            )
        except httpx.RequestError as e:
            logger.error(f"Hub token validation request failed: {e}")
            raise HTTPException(status_code=503, detail="Hub unreachable")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid JupyterHub API token")
    return resp.json().get("name", "")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MintRequest(BaseModel):
    connection_token: str


class MintResponse(BaseModel):
    license: str


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    service_prefix: str | None = None,
    signer: Signer | None = None,
    entitlement: EntitlementChecker | None = None,
    store: TokenStore | None = None,
) -> FastAPI:
    """
    Create and return the FastAPI application.

    service_prefix defaults to JUPYTERHUB_SERVICE_PREFIX (trailing slash stripped).
    Pass signer/entitlement/store overrides for testing.
    """
    if service_prefix is None:
        service_prefix = os.environ.get(
            "JUPYTERHUB_SERVICE_PREFIX", "/services/positron-license/"
        ).rstrip("/")

    application = FastAPI(
        title="Positron License Verifier",
        description="Mints short-lived Positron Server license tokens for JupyterHub sessions.",
    )

    if signer is not None:
        application.dependency_overrides[get_signer] = lambda: signer
    if entitlement is not None:
        application.dependency_overrides[get_entitlement] = lambda: entitlement
    if store is not None:
        application.dependency_overrides[get_store] = lambda: store

    @application.post(f"{service_prefix}/mint", response_model=MintResponse)
    async def mint(
        request: MintRequest,
        _caller: str = Depends(verify_hub_token),
        signer_dep: Signer = Depends(get_signer),
        entitlement_dep: EntitlementChecker = Depends(get_entitlement),
        store_dep: TokenStore = Depends(get_store),
    ) -> MintResponse:
        """Mint a short-lived signed Positron license for the given connection token."""
        if not await entitlement_dep.is_valid():
            raise HTTPException(status_code=403, detail="Positron Server license not valid")

        connection_token = request.connection_token.strip()
        if not connection_token:
            raise HTTPException(status_code=422, detail="connection_token must not be empty")

        try:
            await store_dep.record(connection_token)
        except ValueError:
            raise HTTPException(
                status_code=409,
                detail="A license for this connection token was already issued",
            )

        license_json = signer_dep.mint(connection_token)
        logger.info(f"Issued license for token (first 8): {connection_token[:8]}...")
        return MintResponse(license=license_json)

    return application


app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8099"))
    uvicorn.run(
        "jupyter_positron_verifier.app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
