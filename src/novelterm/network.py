"""HTTP requests with a minimum delay per host, retries and clear error messages."""

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from enum import Enum, auto
from urllib.parse import urlparse

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) novelterm/0.1"
REQUEST_TIMEOUT_SECONDS = 30
MINIMUM_SECONDS_BETWEEN_REQUESTS = 1.0
"""Minimum time between two requests to the same host."""
MAXIMUM_ATTEMPTS = 3
FIRST_RETRY_DELAY_SECONDS = 2.0
MAXIMUM_RETRY_AFTER_SECONDS = 60.0
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
RATE_LIMITED_SCHEMES = frozenset({"http", "https"})


class RequestMethod(Enum):
    GET = "get"
    POST = "post"
    """Sends an empty body. For site endpoints that return a page part, such as a chapter list."""


class FetchFailure(Enum):
    BLOCKED = auto()
    """HTTP 401 or 403: the site refuses the request, often because of bot protection."""
    NOT_FOUND = auto()
    """HTTP 404 or 410."""
    RATE_LIMITED = auto()
    """HTTP 429 on every attempt."""
    SERVER_ERROR = auto()
    """Another HTTP error status."""
    NETWORK = auto()
    """No HTTP answer: no connection, DNS error, timeout."""


class FetchError(Exception):
    def __init__(self, url: str, failure: FetchFailure, detail: str) -> None:
        super().__init__(f"{url}: {detail}")
        self.url = url
        self.failure = failure
        self.detail = detail

    def explanation(self) -> str:
        match self.failure:
            case FetchFailure.BLOCKED:
                return (
                    f"The site refused the request ({self.detail}). It may block programs like novelterm, "
                    "or the page may need a login. novelterm does not try to get around this."
                )
            case FetchFailure.NOT_FOUND:
                return f"The page does not exist ({self.detail}). The site may have moved it, or the source file may be out of date."
            case FetchFailure.RATE_LIMITED:
                return f"The site asks novelterm to slow down ({self.detail}). Wait a few minutes and try again."
            case FetchFailure.SERVER_ERROR:
                return f"The site returned an error ({self.detail}). Try again later."
            case FetchFailure.NETWORK:
                return f"No connection to the site ({self.detail}). Check your internet connection."


@dataclass(frozen=True)
class Response:
    content: bytes
    charset: str | None


class HostPacer:
    """Waits so that requests to one host are at least a minimum time apart."""

    def __init__(self, minimum_seconds: float) -> None:
        self.minimum_seconds = minimum_seconds
        self.last_request_time: dict[str, float] = {}

    def wait_for(self, host: str) -> None:
        previous = self.last_request_time.get(host)
        if previous is not None:
            remaining = self.minimum_seconds - (time.monotonic() - previous)
            if remaining > 0:
                time.sleep(remaining)
        self.last_request_time[host] = time.monotonic()


PACER = HostPacer(MINIMUM_SECONDS_BETWEEN_REQUESTS)


def failure_for_status(status: int) -> FetchFailure:
    match status:
        case 401 | 403:
            return FetchFailure.BLOCKED
        case 404 | 410:
            return FetchFailure.NOT_FOUND
        case 429:
            return FetchFailure.RATE_LIMITED
        case _:
            return FetchFailure.SERVER_ERROR


def retry_delay(attempt: int, headers: Message | None) -> float:
    """Seconds to wait before the next attempt. Uses Retry-After when the site sends a number."""
    retry_after = headers.get("Retry-After") if headers else None
    match retry_after:
        case str() if retry_after.strip().isdigit():
            return min(float(retry_after.strip()), MAXIMUM_RETRY_AFTER_SECONDS)
        case _:
            return FIRST_RETRY_DELAY_SECONDS * 2 ** (attempt - 1)


def fetch(url: str, method: RequestMethod = RequestMethod.GET) -> Response:
    """Download one URL. Raises FetchError with the reason when it fails."""
    parsed = urlparse(url)
    match method:
        case RequestMethod.GET:
            body = None
        case RequestMethod.POST:
            body = b""
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT}, method=method.value.upper())
    for attempt in range(1, MAXIMUM_ATTEMPTS + 1):
        if parsed.scheme in RATE_LIMITED_SCHEMES:
            PACER.wait_for(parsed.hostname or "")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return Response(content=response.read(), charset=response.headers.get_content_charset())
        except urllib.error.HTTPError as error:
            failure = failure_for_status(error.code)
            if error.code not in RETRY_STATUS_CODES or attempt == MAXIMUM_ATTEMPTS:
                raise FetchError(url, failure, f"HTTP {error.code} {error.reason}") from error
            time.sleep(retry_delay(attempt, error.headers))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == MAXIMUM_ATTEMPTS:
                reason = error.reason if isinstance(error, urllib.error.URLError) else error
                raise FetchError(url, FetchFailure.NETWORK, str(reason)) from error
            time.sleep(retry_delay(attempt, None))
    raise AssertionError("unreachable: the last attempt returns or raises")
