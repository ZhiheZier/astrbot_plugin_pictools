# ruff: noqa: I001
# Bootstrap the test package before importing the plugin's relative modules.
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests import PACKAGE  # noqa: F401
from pictools_under_test.core.media_io import (
    MediaInputError,
    MediaReader,
    PublicResolver,
    validate_url,
)


class Response:
    def __init__(self, chunks=(), status=200, headers=None, length=None):
        self.chunks = chunks
        self.status = status
        self.headers = headers or {}
        self.content_length = length
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class Session:
    closed = False

    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(str(url))
        return next(self.responses)

    async def close(self):
        self.closed = True


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_and_content_length_limits(self):
        for response in [
            Response(length=5),
            Response(chunks=[b"tes", b"t!"]),
            Response(status=403),
        ]:
            reader = MediaReader(4, 5, ())
            reader.session = Session([response])
            with self.assertRaises(MediaInputError):
                await reader.read("https://example.com/image")
            await reader.close()

    async def test_redirects_are_validated_and_relative_urls_work(self):
        reader = MediaReader(4, 5, ())
        reader.session = Session(
            [Response(status=302, headers={"Location": "http://127.0.0.1/secret"})]
        )
        with self.assertRaises(MediaInputError):
            await reader.read("https://example.com/image")
        self.assertEqual(len(reader.session.urls), 1)
        await reader.close()
        reader.session = Session(
            [
                Response(status=302, headers={"Location": "/new?token=abc%2B123"}),
                Response(chunks=[b"test"]),
            ]
        )
        self.assertEqual(await reader.read("https://example.com/image"), b"test")
        self.assertEqual(
            reader.session.urls[-1], "https://example.com/new?token=abc%2B123"
        )
        await reader.close()

    async def test_base64_limit_and_malformed_input(self):
        reader = MediaReader(4, 5, ())
        self.assertEqual(
            await reader.read("base64://" + base64.b64encode(b"test").decode()), b"test"
        )
        for value in ["base64://dGVzdCE=", "base64://???", "base64://"]:
            with self.subTest(value=value), self.assertRaises(MediaInputError):
                await reader.read(value)
        await reader.close()

    async def test_local_files_restricted_to_media_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            media.mkdir()
            source = media / "sample image.png"
            source.write_bytes(b"test")
            outside = root / "secret.txt"
            outside.write_bytes(b"secret")
            reader = MediaReader(4, 5, (media,))
            self.assertEqual(await reader.read(str(source)), b"test")
            self.assertEqual(await reader.read(source.as_uri()), b"test")
            for path in [outside, media / ".." / "secret.txt"]:
                with self.assertRaises(MediaInputError):
                    await reader.read(str(path))
            source.write_bytes(b"oversized")
            with self.assertRaises(MediaInputError):
                await reader.read(str(source))

    def test_public_url_validation(self):
        self.assertEqual(
            str(validate_url("https://q1.qlogo.cn/g?b=qq&nk=123&s=640")),
            "https://q1.qlogo.cn/g?b=qq&nk=123&s=640",
        )
        for url in [
            "http://127.0.0.1/a",
            "http://10.0.0.1/a",
            "http://169.254.169.254/",
            "http://[::1]/a",
            "http://[::ffff:127.0.0.1]/a",
            "http://localhost/a",
            "http://example.com:6185/",
            "https://user:pass@example.com/",
            "file:///etc/passwd",
            "https://192.168.1.1/",
            "http://224.0.0.1/",
        ]:
            with self.subTest(url=url), self.assertRaises(MediaInputError):
                validate_url(url)

    async def test_dns_private_and_mixed_records_rejected(self):
        resolver = PublicResolver()
        try:
            for records in [
                [],
                [{"host": "127.0.0.1"}],
                [{"host": "1.1.1.1"}, {"host": "10.0.0.1"}],
            ]:
                with patch.object(
                    resolver.resolver, "resolve", AsyncMock(return_value=records)
                ):
                    with self.assertRaises(OSError):
                        await resolver.resolve("example.com")
        finally:
            await resolver.close()


if __name__ == "__main__":
    unittest.main()
