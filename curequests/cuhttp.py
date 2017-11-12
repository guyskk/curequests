import zlib
from collections import namedtuple
import httptools
from curio import timeout_after, TaskTimeout
from curio.io import StreamBase
from requests.structures import CaseInsensitiveDict
from requests import ReadTimeout as ReadTimeoutError
from urllib3.response import GzipDecoder as GzipDecoderBase
from urllib3.response import DeflateDecoder as DeflateDecoderBase
from urllib3.exceptions import DecodeError


class ProtocolError(httptools.HttpParserError):
    """ProtocolError"""


class _Decoder:

    def decompress(self, *args, **kwargs):
        try:
            return super().decompress(*args, **kwargs)
        except zlib.error as ex:
            msg = 'failed to decode response with {}'.format(
                type(self).__name__)
            raise DecodeError(msg) from ex


class GzipDecoder(_Decoder, GzipDecoderBase):
    """GzipDecoder"""


class DeflateDecoder(_Decoder, DeflateDecoderBase):
    """DeflateDecoder"""


Response = namedtuple('Response', [
    'status',
    'reason',
    'version',
    'keep_alive',
    'headers',
    'stream',
])

MAX_BUFFER_SIZE = 64 * 1024
DEFAULT_BUFFER_SIZE = 4 * 1024


class ResponseStream(StreamBase):
    """Response stream as file object"""

    def __init__(self, sock, gen, buffer_size_setter):
        super().__init__(sock)
        self._gen = gen
        self._set_buffer_size = buffer_size_setter

    async def _read(self, maxbytes=-1):
        maxbytes = maxbytes if maxbytes > 0 else MAX_BUFFER_SIZE
        self._set_buffer_size(maxbytes)
        try:
            return await self._gen.__anext__()
        except StopAsyncIteration:
            return b''


class ResponseParser:
    """
    Attrs:
        version
        status
        reason
        keep_alive

        headers
        body_stream

        started
        headers_completed
        completed
    """

    def __init__(self, sock, *, buffer_size=DEFAULT_BUFFER_SIZE, timeout=None):
        self._sock = sock
        self._parser = httptools.HttpResponseParser(self)

        # options
        self.buffer_size = buffer_size
        self.timeout = timeout

        # primary attrs
        self.version = None
        self.status = None
        self.reason = b''
        self.headers = []

        # temp attrs
        self.current_buffer_size = self.buffer_size
        self.header_name = b''
        self.body_chunks = []

        # state
        self.started = False
        self.headers_completed = False
        self.completed = False

    # ========= httptools callbacks ========
    def on_message_begin(self):
        self.started = True

    def on_status(self, status: bytes):
        self.reason += status

    def on_header(self, name: bytes, value: bytes or None):
        self.header_name += name
        if value is not None:
            self.headers.append((self.header_name.decode(), value.decode()))
            self.header_name = b''

    def on_headers_complete(self):
        self.version = self._parser.get_http_version()
        self.status = self._parser.get_status_code()
        self.reason = self.reason.decode()
        self.keep_alive = self._parser.should_keep_alive()
        self.headers = CaseInsensitiveDict(self.headers)
        self.headers_completed = True

    def on_body(self, body: bytes):
        # Implement Note: a `feed_data` can cause multi `on_body` when data
        # is large, eg: len(data) > 8192, so we should store `body` in a list
        self.body_chunks.append(body)

    def on_message_complete(self):
        self.completed = True
    # ========= end httptools callbacks ========

    async def recv(self):
        if not self.timeout or self.timeout <= 0:
            return await self._sock.recv(self.current_buffer_size)
        else:
            try:
                return await timeout_after(
                    self.timeout,
                    self._sock.recv(self.current_buffer_size)
                )
            except TaskTimeout as ex:
                raise ReadTimeoutError(str(ex)) from None

    def _set_current_buffer_size(self, buffer_size):
        self.current_buffer_size = buffer_size

    def _get_decoder(self):
        mode = self.headers.get('Content-Encoding', '').lower()
        if mode == 'gzip':
            return GzipDecoder()
        elif mode == 'deflate':
            return DeflateDecoder()
        return None

    async def parse(self):
        while not self.headers_completed:
            data = await self.recv()
            self._parser.feed_data(data)
            if not data:
                break
        if not self.headers_completed:
            raise ProtocolError('incomplete response headers')
        body_stream = self.body_stream()
        decoder = self._get_decoder()
        if decoder:
            body_stream = _decompress(body_stream, decoder)

        def stream(chunk_size=DEFAULT_BUFFER_SIZE):
            self._set_current_buffer_size(chunk_size)
            return body_stream

        environ = dict(
            version=self.version,
            status=self.status,
            reason=self.reason,
            keep_alive=self.keep_alive,
            headers=self.headers,
            stream=stream,
        )
        return Response(**environ)

    async def body_stream(self):
        while self.body_chunks:
            yield self.body_chunks.pop(0)
        while not self.completed:
            data = await self.recv()
            # feed data even when data is empty, so parser will completed
            self._parser.feed_data(data)
            while self.body_chunks:
                yield self.body_chunks.pop(0)
            if not data:
                break
        if not self.completed:
            raise ProtocolError('incomplete response body')


class RequestSerializer:
    def __init__(self, path, method='GET', *, version='HTTP/1.1', headers=None,
                 body=b'', body_stream=None):
        self.path = path
        self.method = method
        self.version = version
        if headers is None:
            self.headers = {}
        else:
            self.headers = headers
        self.body = body if body is not None else b''
        self.body_stream = body_stream

    def _format_headers(self):
        headers = [f'{self.method} {self.path} {self.version}']
        for k, v in self.headers.items():
            headers.append(f'{k}: {v}')
        return '\r\n'.join(headers).encode() + b'\r\n\r\n'

    async def __aiter__(self):
        if self.body_stream is None:
            # one-off request
            if self.method in {'POST', 'PUT', 'PATCH'}:
                self.headers['Content-Length'] = len(self.body)
            yield self._format_headers()
            yield self.body
        else:
            # stream request
            if 'Content-Length' not in self.headers:
                raise ValueError('Content-Length not set')
            yield self._format_headers()
            async for chunk in self.body_stream:
                yield chunk


async def _decompress(body_stream, decoder):
    async for chunk in body_stream:
        yield decoder.decompress(chunk)
    buf = decoder.decompress(b'')
    yield buf + decoder.flush()
