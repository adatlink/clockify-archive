from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class APIResponse:
    data: Any
    headers: dict[str, str]
    status: int


class ClockifyAPIError(RuntimeError):
    def __init__(self, status: int, message: str, url: str, body: str = "") -> None:
        super().__init__(f"Clockify API error {status}: {message} ({url})")
        self.status = status
        self.url = url
        self.body = body


class ClockifyClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.clockify.me/api/v1",
        *,
        timeout: float = 60.0,
        retries: int = 4,
        user_agent: str = "clockify-archive/0.1.1",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        if params:
            clean: list[tuple[str, Any]] = []
            for key, value in params.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    clean.extend((key, x) for x in value)
                else:
                    clean.append((key, value))
            query = urllib.parse.urlencode(clean, doseq=True)
            if query:
                url += ("&" if "?" in url else "?") + query
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> APIResponse:
        url = self._url(path, params)
        headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        payload = None
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    text = raw.decode("utf-8") if raw else ""
                    data = json.loads(text) if text else None
                    return APIResponse(data, {k: v for k, v in resp.headers.items()}, resp.status)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else min(2 ** attempt, 15)
                    except ValueError:
                        delay = min(2 ** attempt, 15)
                    time.sleep(delay)
                    last_error = exc
                    continue
                message = exc.reason or "HTTP error"
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        message = parsed.get("message") or parsed.get("error") or message
                except json.JSONDecodeError:
                    pass
                raise ClockifyAPIError(exc.code, str(message), url, body) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                raise RuntimeError(f"Network error calling Clockify: {exc}") from exc
        raise RuntimeError(f"Clockify request failed: {last_error}")

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> APIResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None) -> APIResponse:
        return self.request("POST", path, params=params, json_body=json_body)

    @staticmethod
    def _extract(data: Any, extractor: str | Callable[[Any], Iterable[Any]] | None) -> list[Any]:
        if extractor is None:
            if isinstance(data, list):
                return data
            return []
        if callable(extractor):
            return list(extractor(data))
        cur = data
        for part in extractor.split("."):
            if not isinstance(cur, dict):
                return []
            cur = cur.get(part)
        return cur if isinstance(cur, list) else []

    def paginate(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extractor: str | Callable[[Any], Iterable[Any]] | None = None,
        page_param: str = "page",
        page_size_param: str = "page-size",
        page_size: int = 200,
        start_page: int = 1,
        json_body: Any | None = None,
        max_pages: int = 100000,
    ) -> tuple[list[Any], list[Any]]:
        items: list[Any] = []
        pages: list[Any] = []
        page = start_page
        for _ in range(max_pages):
            q = dict(params or {})
            q[page_param] = page
            q[page_size_param] = page_size
            resp = self.request(method, path, params=q, json_body=json_body)
            pages.append(resp.data)
            batch = self._extract(resp.data, extractor)
            items.extend(batch)

            last_page = str(resp.headers.get("Last-Page", "")).lower()
            if last_page == "true":
                break
            if not batch or len(batch) < page_size:
                break
            page += 1
        return items, pages

    def download(self, path: str, destination: Path) -> tuple[Path, dict[str, str]]:
        url = self._url(path)
        headers = {"X-Api-Key": self.api_key, "User-Agent": self.user_agent}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
                response_headers = {k: v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ClockifyAPIError(exc.code, str(exc.reason), url, body) from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = destination.suffix
        if not suffix:
            content_type = response_headers.get("Content-Type", "").split(";", 1)[0].strip()
            guessed = mimetypes.guess_extension(content_type) if content_type else None
            if guessed:
                destination = destination.with_suffix(guessed)
        destination.write_bytes(data)
        return destination, response_headers
