import asyncio
import email.utils
import json
import logging
import random
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import aiohttp

LOG = logging.getLogger(__name__)


class FetchError(RuntimeError):
    def __init__(self, status, url, detail=None):
        self.status = status
        self.url = url
        self.detail = (str(detail)[:250] if detail else None)
        super().__init__(f"HTTP {status} from {url}")


class AsyncFetcher:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.semaphore = asyncio.Semaphore(max(1, settings.concurrency))
        self.session = transport
        self.owns_session = transport is None
        self.host_locks = {}
        self.next_request = {}

    async def __aenter__(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=50, connect=12)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": self.settings.user_agent})
        return self

    async def __aexit__(self, *args):
        if self.owns_session and self.session:
            await self.session.close()

    async def _host_wait(self, url):
        host = urlsplit(url).hostname or ""
        lock = self.host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self.next_request.get(host, 0) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            interval = max(3.0, self.settings.host_interval) if host == "export.arxiv.org" else max(0.01, self.settings.host_interval)
            self.next_request[host] = time.monotonic() + interval

    @staticmethod
    def retry_seconds(value):
        if value is None:
            return None
        try:
            return min(180, max(0, float(value)))
        except ValueError:
            try:
                dt = email.utils.parsedate_to_datetime(value)
                return min(180, max(0, (dt - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                return None

    async def request(self, url, *, method="GET", json_body=None, headers=None, attempts=5):
        if urlsplit(url).scheme != "https":
            raise ValueError("External requests must use HTTPS")
        for index in range(attempts):
            await self._host_wait(url)
            try:
                async with self.semaphore:
                    async with self.session.request(method, url, json=json_body, headers=headers, allow_redirects=True) as response:
                        status = response.status
                        if 200 <= status < 300:
                            if "application/json" in response.headers.get("Content-Type", ""):
                                return await response.json(content_type=None)
                            return await response.text(errors="replace")
                        limited_403 = status == 403 and (
                            response.headers.get("X-RateLimit-Remaining") == "0" or
                            response.headers.get("Retry-After") is not None
                        )
                        if status in {401, 403, 404, 410, 451} and not limited_403 or (status not in {408, 413, 425, 429, 500, 502, 503, 504} and not limited_403) or status == 413:
                            detail = None
                            try:
                                error_body = (await response.text(errors="replace"))[:1000]
                                obj = json.loads(error_body)
                                err = obj.get("error", obj) if isinstance(obj, dict) else {}
                                if isinstance(err, dict):
                                    detail = err.get("message") or err.get("code")
                                elif isinstance(err, str):
                                    detail = err
                            except (ValueError, TypeError):
                                pass
                            raise FetchError(status, url, detail)
                        retry_after = self.retry_seconds(response.headers.get("Retry-After"))
                        if limited_403 and retry_after is None and response.headers.get("X-RateLimit-Reset"):
                            try:
                                retry_after = max(0, min(180, float(response.headers["X-RateLimit-Reset"]) - time.time()))
                            except ValueError:
                                pass
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                LOG.warning("transient_network_error url=%s error=%s", url, type(exc).__name__)
                retry_after = None
            if index == attempts - 1:
                raise FetchError(status if 'status' in locals() else "network", url)
            delay = retry_after if retry_after is not None else min(45, 2 ** index + random.uniform(0, 1))
            LOG.warning("retry url=%s attempt=%s sleep=%.1f", url, index + 1, delay)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def get_json(self, url, *, headers=None):
        result = await self.request(url, headers=headers)
        if isinstance(result, str):
            return json.loads(result)
        return result
