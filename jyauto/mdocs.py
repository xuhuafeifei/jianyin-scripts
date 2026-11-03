"""Minimal mdocs HTTP client (same API the official CLI uses)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_TOKEN_ENV = "MDOCS_TOKEN"
DEFAULT_SERVER = "http://127.0.0.1:4000"


class MdocsError(RuntimeError):
    pass


class Mdocs:
    def __init__(self, server: Optional[str] = None, token: Optional[str] = None):
        self.server = (server or os.environ.get("MDOCS_SERVER") or DEFAULT_SERVER).rstrip("/")
        if not self.server.startswith("http"):
            self.server = ("http://" + self.server) if ":" in self.server else f"http://{self.server}:4000"
        self.token = token or os.environ.get(DEFAULT_TOKEN_ENV) or ""
        if not self.token:
            raise MdocsError(
                "缺少 mdocs CLI Token：设置环境变量 MDOCS_TOKEN，或在 mdocs 设置页创建后传入 --token")

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self.server}/api{path}"
        data = None
        headers = {"x-cli-token": self.token}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(detail).get("error") or {}
                raise MdocsError(f"[{err.get('code')}] {err.get('message')}") from None
            except json.JSONDecodeError:
                raise MdocsError(f"HTTP {e.code}: {detail[:200]}") from None
        except urllib.error.URLError as e:
            raise MdocsError(f"无法连接 mdocs 服务 {self.server}: {e.reason}") from None
        if isinstance(payload, dict) and payload.get("ok") is False:
            err = payload.get("error") or {}
            raise MdocsError(f"[{err.get('code')}] {err.get('message')}")
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    # --------------------------------------------------------------- queries
    def domains(self) -> list[dict]:
        return self._request("GET", "/domains") or []

    def documents(self, domain_id: Optional[str] = None) -> list[dict]:
        qs = f"?domainId={urllib.parse.quote(domain_id)}" if domain_id else ""
        return self._request("GET", f"/documents{qs}") or []

    def get(self, document_id: str, text: bool = True) -> dict:
        suffix = "?format=text" if text else ""
        return self._request("GET", f"/documents/{urllib.parse.quote(document_id)}{suffix}")

    def search(self, query: str, domain_id: Optional[str] = None, top_n: int = 10) -> list[dict]:
        body = {"query": query, "topN": top_n}
        if domain_id:
            body["domainId"] = domain_id
        return self._request("POST", "/documents/search", body) or []

    # --------------------------------------------------------------- helpers
    def latest(self, domain_id: Optional[str] = None,
               file_types: tuple[str, ...] = ("md", "markdown", "html")) -> dict:
        docs = [d for d in self.documents(domain_id)
                if d.get("fileType") in file_types]
        if not docs:
            raise MdocsError("该工作空间没有可用的文章")
        return max(docs, key=lambda d: d.get("updatedAt") or "")

    def latest_by_domain(self) -> list[tuple[str, dict]]:
        out = []
        for dom in self.domains():
            if not dom.get("docCount"):
                continue
            try:
                doc = self.latest(dom["domainId"])
            except MdocsError:
                continue
            out.append((dom["domainName"], doc))
        out.sort(key=lambda pair: pair[1].get("updatedAt") or "", reverse=True)
        return out
