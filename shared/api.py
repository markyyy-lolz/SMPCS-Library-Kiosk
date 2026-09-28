from __future__ import annotations
import requests
from typing import Any

class ApiError(RuntimeError):
    pass

class SupabaseAPI:
    def __init__(self, url: str, key: str, timeout: int = 12):
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        self.timeout = timeout
        if not self.url or not self.key:
            raise ApiError("Supabase URL and API key are required.")
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs):
        try:
            r = self.session.request(
                method, f"{self.url}{path}", timeout=self.timeout, **kwargs
            )
        except requests.RequestException as e:
            raise ApiError(f"Network error: {e}") from e

        if not r.ok:
            detail = r.text[:1000]
            try:
                obj = r.json()
                detail = obj.get("message") or obj.get("hint") or obj.get("details") or obj.get("error") or detail
            except Exception:
                pass
            raise ApiError(f"Supabase error {r.status_code}: {detail}")
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:
            return r.text

    def rpc(self, name: str, params: dict | None = None):
        return self._request("POST", f"/rest/v1/rpc/{name}", json=params or {})

    def select(self, table: str, query: str = "", params: dict | None = None):
        return self._request("GET", f"/rest/v1/{table}{query}", params=params or {})

    def insert(self, table: str, payload: Any, prefer="return=representation"):
        return self._request(
            "POST", f"/rest/v1/{table}",
            headers={"Prefer": prefer}, json=payload
        )

    def update(self, table: str, query: str, payload: dict, prefer="return=representation"):
        return self._request(
            "PATCH", f"/rest/v1/{table}{query}",
            headers={"Prefer": prefer}, json=payload
        )

    def delete(self, table: str, query: str):
        return self._request("DELETE", f"/rest/v1/{table}{query}")

    def health(self) -> bool:
        self.select("library_settings", "?select=key&limit=1")
        return True
