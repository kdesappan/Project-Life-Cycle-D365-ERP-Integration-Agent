"""D365 F&O OData HTTP client with Azure AD client-credentials authentication."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

try:
    import msal
    _MSAL_AVAILABLE = True
except ImportError:
    _MSAL_AVAILABLE = False


class D365Client:
    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        data_area_id: str = "2020",
    ) -> None:
        # base_url is the full host, e.g. https://myenv.operations.dynamics.com
        self.base_url = base_url.rstrip("/") + "/data"
        self._resource_host = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.data_area_id = data_area_id
        self._token: str | None = None
        self._token_expires: datetime | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _acquire_token(self) -> str:
        if not _MSAL_AVAILABLE:
            return "demo-token"
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        scope = [f"{self._resource_host}/.default"]
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=scope)
        if "access_token" not in result:
            raise RuntimeError(f"D365 auth failed: {result.get('error_description', result)}")
        return result["access_token"]  # type: ignore[return-value]

    def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._token_expires and now < self._token_expires:
            return self._token
        self._token = self._acquire_token()
        self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=55)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def preflight_auth(self) -> tuple[bool, str]:
        """Try to acquire a token and return (ok, message) — does not make any OData call."""
        try:
            self._get_token()
            return True, "Token acquired successfully"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def get(self, path: str) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.get(url, headers=self._headers(), params={"cross-company": "true"})
            try:
                resp_body = resp.json() if resp.content else {}
            except Exception:  # noqa: BLE001
                resp_body = {"raw": resp.text}
            return resp.status_code, resp_body
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": str(exc), "url": url}

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(url, headers=self._headers(), json=body, params={"cross-company": "true"})
            try:
                resp_body = resp.json()
            except Exception:  # noqa: BLE001
                resp_body = {"raw": resp.text}
            return resp.status_code, resp_body
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": str(exc), "url": url}

    def patch(self, path: str, body: dict) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.patch(url, headers=self._headers(), json=body, params={"cross-company": "true"})
            try:
                resp_body = resp.json() if resp.content else {}
            except Exception:  # noqa: BLE001
                resp_body = {"raw": resp.text}
            return resp.status_code, resp_body
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": str(exc), "url": url}

    # ------------------------------------------------------------------
    # Metadata preflight
    # ------------------------------------------------------------------

    def test_connection(self) -> tuple[bool, str]:
        try:
            status, _ = self.get("/$metadata")
            if status < 400:
                return True, f"Connected to {self._resource_host} (HTTP {status})"
            return False, f"Metadata endpoint returned HTTP {status}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


def build_client_from_env() -> D365Client:
    base_url = os.getenv("D365_BASE_URL") or f"https://{os.getenv('D365_ENVIRONMENT', 'demo-env')}.operations.dynamics.com"
    return D365Client(
        base_url=base_url,
        tenant_id=os.getenv("D365_TENANT_ID", ""),
        client_id=os.getenv("D365_CLIENT_ID", ""),
        client_secret=os.getenv("D365_CLIENT_SECRET", ""),
        data_area_id=os.getenv("D365_DATA_AREA_ID", os.getenv("D365_COMPANY", "2020")),
    )
