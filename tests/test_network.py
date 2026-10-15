import io
import unittest
import urllib.error
from email.message import Message
from unittest import mock

from novelterm import network
from novelterm.network import FetchError, FetchFailure, HostPacer, fetch


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *arguments: object) -> None:
        self.close()


def http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.org/", status, "reason", headers, None)


@mock.patch("novelterm.network.time.sleep")
@mock.patch.object(network, "PACER", HostPacer(0))
class FetchTests(unittest.TestCase):
    def test_success(self, sleep: mock.Mock) -> None:
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"page")):
            response = fetch("https://example.org/")
        self.assertEqual((response.content, response.charset), (b"page", "utf-8"))
        sleep.assert_not_called()

    def test_forbidden_is_not_retried(self, sleep: mock.Mock) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=http_error(403)) as urlopen:
            with self.assertRaises(FetchError) as context:
                fetch("https://example.org/")
        self.assertEqual(context.exception.failure, FetchFailure.BLOCKED)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("refused", context.exception.explanation())

    def test_rate_limit_uses_retry_after_then_succeeds(self, sleep: mock.Mock) -> None:
        answers = [http_error(429, retry_after="7"), FakeResponse(b"page")]
        with mock.patch("urllib.request.urlopen", side_effect=answers):
            self.assertEqual(fetch("https://example.org/").content, b"page")
        sleep.assert_called_once_with(7.0)

    def test_server_errors_stop_after_three_attempts(self, sleep: mock.Mock) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(503)] * 3) as urlopen:
            with self.assertRaises(FetchError) as context:
                fetch("https://example.org/")
        self.assertEqual(context.exception.failure, FetchFailure.SERVER_ERROR)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0])

    def test_network_error(self, sleep: mock.Mock) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(FetchError) as context:
                fetch("https://example.org/")
        self.assertEqual(context.exception.failure, FetchFailure.NETWORK)


class HostPacerTests(unittest.TestCase):
    def test_waits_only_for_the_same_host(self) -> None:
        pacer = HostPacer(1.0)
        with mock.patch("novelterm.network.time.monotonic", side_effect=[100.0, 100.2, 101.2, 101.3]):
            with mock.patch("novelterm.network.time.sleep") as sleep:
                pacer.wait_for("example.org")
                pacer.wait_for("example.org")
                pacer.wait_for("other.org")
        self.assertEqual(len(sleep.call_args_list), 1)
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)


if __name__ == "__main__":
    unittest.main()
