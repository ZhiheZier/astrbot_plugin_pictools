"""Size-bounded media input with public-address DNS resolution."""

import asyncio
import base64
import binascii
import ipaddress
import socket
from pathlib import Path
from urllib.parse import unquote, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL


class MediaInputError(ValueError):
    pass


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_url(value: str) -> URL:
    try:
        url = URL(value)
        if (
            url.scheme not in {"https", "http"}
            or not url.host
            or url.user is not None
            or url.password is not None
            or url.port not in {80, 443}
        ):
            raise MediaInputError("图片地址必须是公开的 HTTP/HTTPS 地址。")
        try:
            address = ipaddress.ip_address(url.host)
        except ValueError:
            if url.host.lower() == "localhost" or url.host.endswith(".local"):
                raise MediaInputError("不支持内网图片地址。")
        else:
            if not _public_ip(str(address)):
                raise MediaInputError("不支持内网图片地址。")
        return url
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, MediaInputError):
            raise
        raise MediaInputError("图片地址无效。") from exc


class PublicResolver(AbstractResolver):
    def __init__(self):
        self.resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.resolver.resolve(host, port, family)
        if not records or any(not _public_ip(record["host"]) for record in records):
            raise OSError("Image hostname resolved to a non-public address")
        return records

    async def close(self):
        await self.resolver.close()


class MediaReader:
    def __init__(self, max_bytes: int, timeout: float, trusted_roots: tuple[Path, ...]):
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.trusted_roots = tuple(root.resolve() for root in trusted_roots)
        self.session: aiohttp.ClientSession | None = None
        self.resolver: PublicResolver | None = None

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self.resolver is not None:
            await self.resolver.close()
            self.resolver = None

    async def _download(self, source: str) -> bytes:
        if self.session is None or self.session.closed:
            self.resolver = PublicResolver()
            connector = aiohttp.TCPConnector(resolver=self.resolver, limit=4)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
            )
        url = validate_url(source)
        # Bound the entire redirect chain, rather than each hop independently.
        async with asyncio.timeout(self.timeout):
            for _ in range(5):
                async with self.session.get(url, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise MediaInputError("图片地址重定向无效。")
                        url = validate_url(str(url.join(URL(location))))
                        continue
                    if response.status != 200:
                        raise MediaInputError(
                            "图片下载失败，链接可能已过期，请重新发送图片。"
                        )
                    if (
                        response.content_length is not None
                        and response.content_length > self.max_bytes
                    ):
                        raise MediaInputError("图片文件过大，请压缩后重试。")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        if len(data) + len(chunk) > self.max_bytes:
                            raise MediaInputError("图片文件过大，请压缩后重试。")
                        data.extend(chunk)
                    return bytes(data)
        raise MediaInputError("图片地址重定向次数过多。")

    def _read_local(self, source: str) -> bytes:
        if source.startswith("file:"):
            parsed = urlsplit(source)
            if parsed.netloc:
                raise MediaInputError("不支持网络共享文件。")
            source = unquote(parsed.path)
            # File URIs on Windows contain a leading slash before the drive.
            if len(source) > 3 and source[0] == "/" and source[2] == ":":
                source = source[1:]
        if source.startswith(("\\\\", "//")):
            raise MediaInputError("不支持网络共享文件。")
        path = Path(source).resolve()
        if not any(path.is_relative_to(root) for root in self.trusted_roots):
            raise MediaInputError("只能读取 AstrBot 临时媒体目录中的图片。")
        with path.open("rb") as stream:
            if path.stat().st_size > self.max_bytes:
                raise MediaInputError("图片文件过大，请压缩后重试。")
            data = stream.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise MediaInputError("图片文件过大，请压缩后重试。")
        return data

    async def read(self, source: str) -> bytes:
        try:
            if source.startswith(("https://", "http://")):
                data = await self._download(source)
            elif source.startswith("base64://"):
                encoded = source.removeprefix("base64://")
                if len(encoded) > ((self.max_bytes + 2) // 3) * 4:
                    raise MediaInputError("图片文件过大，请压缩后重试。")
                data = base64.b64decode(encoded, validate=True)
                if len(data) > self.max_bytes:
                    raise MediaInputError("图片文件过大，请压缩后重试。")
            else:
                data = await asyncio.to_thread(self._read_local, source)
            if not data:
                raise MediaInputError("收到的图片为空，请重新发送。")
            return data
        except MediaInputError:
            raise
        except TimeoutError as exc:
            raise MediaInputError("图片下载超时，请稍后重试。") from exc
        except (aiohttp.ClientError, OSError, ValueError, binascii.Error) as exc:
            raise MediaInputError("无法读取图片，请重新发送原图后重试。") from exc
