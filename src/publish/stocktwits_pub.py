"""Phase 2 publisher: posts text + chart PNG to Stocktwits' CORE messages/create.

urllib on purpose (see src/stocktwits.py): Stocktwits' Cloudflare blocks the
`requests` library's TLS fingerprint (403) but passes urllib. Multipart is
assembled by hand because urllib has no multipart helper.
"""
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import config
from src.publish.base import Publisher, PostResult
from src.publish.record import write_post_artifacts
from src.source.base import Candidate

# The multipart file field for the chart image. Unconfirmed against current
# Stocktwits docs (offline); the first live post validates it. One line to fix.
CHART_FIELD = "chart"
_BOUNDARY = "----stocktwits52wkPosterBoundary7MA4YWxkTrZu0gW"


class PublishError(Exception):
    """A post did not succeed (HTTP error, CF block, error status, bad body).

    run.py catches this and leaves the ticker 'pending' (lost, never duplicated).
    """


def _encode_multipart(fields: dict[str, str],
                      file_field: str, filename: str, file_bytes: bytes,
                      content_type: str, boundary: str) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append((f'Content-Disposition: form-data; name="{file_field}"; '
                  f'filename="{filename}"\r\n').encode())
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


class StocktwitsPublisher(Publisher):
    def __init__(self, access_token: str, out_dir, today: date, *,
                 user_agent: str = config.STOCKTWITS_USER_AGENT,
                 url: str = config.STOCKTWITS_CREATE_URL,
                 urlopen=urllib.request.urlopen, timeout: int = 15):
        self.access_token = access_token
        self.out_dir = Path(out_dir)
        self.today = today
        self.user_agent = user_agent
        self.url = url
        self._urlopen = urlopen
        self.timeout = timeout

    def post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult:
        body = _encode_multipart(
            {"access_token": self.access_token, "body": text},
            CHART_FIELD, "chart.png", image_png, "image/png", _BOUNDARY)
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"User-Agent": self.user_agent,
                     "Content-Type":
                         f"multipart/form-data; boundary={_BOUNDARY}"})
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as e:  # HTTPError <: URLError
            raise PublishError(f"{candidate.ticker}: transport error: {e}") from e

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise PublishError(
                f"{candidate.ticker}: unparseable response: {raw[:200]!r}") from e
        status = (data.get("response") or {}).get("status")
        if status != 200:
            raise PublishError(
                f"{candidate.ticker}: stocktwits status {status}: {raw[:200]!r}")
        message_id = (data.get("message") or {}).get("id")
        if message_id is None:
            raise PublishError(
                f"{candidate.ticker}: no message id in response: {raw[:200]!r}")

        # Only after a confirmed post: write the auditable record.
        write_post_artifacts(self.out_dir, self.today, candidate.ticker,
                             text, image_png)
        return PostResult(post_id=str(message_id), dry_run=False)
