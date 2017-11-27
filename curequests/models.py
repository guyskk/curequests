import mimetypes
from uuid import uuid4
from os.path import basename
from urllib.parse import quote

from curio.meta import finalize
from curio.file import AsyncFile
from requests.models import Request, Response, PreparedRequest
from requests.utils import super_len, to_key_val_list
from requests.exceptions import (
    ChunkedEncodingError, ContentDecodingError,
    ConnectionError, StreamConsumedError)
from requests.models import ITER_CHUNK_SIZE

from .utils import stream_decode_response_unicode, iter_slices
from .cuhttp import DecodeError, ProtocolError, ReadTimeoutError


EOL = '\r\n'
bEOL = b'\r\n'


class CuResponse(Response):
    """The :class:`CuResponse <CuResponse>` object, which contains a
    server's response to an async HTTP request.
    """

    def __enter__(self):
        raise AttributeError(
            f'{type(self).__name__} not support synchronous context '
            'manager, use asynchronous context manager instead.')

    def __exit__(self, *args):
        raise AttributeError(
            f'{type(self).__name__} not support synchronous context '
            'manager, use asynchronous context manager instead.')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __iter__(self):
        raise AttributeError(
            f'{type(self).__name__} not support synchronous iter, '
            'use asynchronous iter instead.')

    def __aiter__(self):
        """Allows you to use a response as an iterator."""
        return self.iter_content(128)

    def iter_content(self, chunk_size=1, decode_unicode=False):
        """Iterates over the response data.  When stream=True is set on the
        request, this avoids reading the content at once into memory for
        large responses.  The chunk size is the number of bytes it should
        read into memory.  This is not necessarily the length of each item
        returned as decoding can take place.

        chunk_size must be of type int or None. A value of None will
        function differently depending on the value of `stream`.
        stream=True will read data as it arrives in whatever size the
        chunks are received. If stream=False, data is returned as
        a single chunk.

        If decode_unicode is True, content will be decoded using the best
        available encoding based on the response.
        """
        if self._content_consumed and isinstance(self._content, bool):
            raise StreamConsumedError()
        elif chunk_size is not None and not isinstance(chunk_size, int):
            raise TypeError('chunk_size must be an int, it is instead a %s.' % type(chunk_size))

        async def generate():
            async with self:
                async with finalize(self.raw.stream(chunk_size)) as gen:
                    try:
                        async for trunk in gen:
                            yield trunk
                    except ProtocolError as e:
                        raise ChunkedEncodingError(e)
                    except DecodeError as e:
                        raise ContentDecodingError(e)
                    except ReadTimeoutError as e:
                        raise ConnectionError(e)
                    self._content_consumed = True

        if self._content_consumed:
            # simulate reading small chunks of the content
            chunks = iter_slices(self._content, chunk_size)
        else:
            chunks = generate()

        if decode_unicode:
            chunks = stream_decode_response_unicode(chunks, self)

        return chunks

    async def iter_lines(self, chunk_size=ITER_CHUNK_SIZE, decode_unicode=None, delimiter=None):
        """Iterates over the response data, one line at a time.  When
        stream=True is set on the request, this avoids reading the
        content at once into memory for large responses.

        .. note:: This method is not reentrant safe.
        """

        pending = None

        gen = self.iter_content(chunk_size=chunk_size, decode_unicode=decode_unicode)

        async with finalize(gen) as gen:
            async for chunk in gen:

                if pending is not None:
                    chunk = pending + chunk

                if delimiter:
                    lines = chunk.split(delimiter)
                else:
                    lines = chunk.splitlines()

                if lines and lines[-1] and chunk and lines[-1][-1] == chunk[-1]:
                    pending = lines.pop()
                else:
                    pending = None

                for line in lines:
                    yield line

        if pending is not None:
            yield pending

    @property
    def content(self):
        """Content of the response, in bytes."""

        if self._content is False:
            # Read the contents.
            if self._content_consumed:
                raise RuntimeError(
                    'The content for this response was already consumed')

            if self.status_code == 0 or self.raw is None:
                self._content = None
            else:
                raise RuntimeError(
                    'The content for this response was not readed')

        self._content_consumed = True
        # don't need to release the connection; that's been handled by urllib3
        # since we exhausted the data.
        return self._content

    async def close(self):
        if self._content_consumed:
            if self.raw.keep_alive:
                await self.connection.release()
            else:
                await self.connection.close()
        else:
            await self.connection.close()


def encode_headers(headers):
    ret = []
    for k, v in headers.items():
        ret.append('{}: {}'.format(k, v))
    return EOL.join(ret).encode('ascii')


class Field:

    __slots__ = (
        'name', 'filename', 'content', 'file', 'headers', 'content_length',
        'encoded_headers', '_should_close_file',
    )

    def __init__(self, name, *, filename=None, headers=None, content_type=None,
                 file=None, filepath=None, content=None, encoding='utf-8'):
        self.name = quote(name, safe='')
        self.headers = headers or {}
        self.content_length = None
        self._should_close_file = False

        if content is not None:
            if isinstance(content, str):
                content = content.encode(encoding)
        self.content = content

        if filepath is not None:
            file = open(filepath, 'rb')
            self._should_close_file = True
        if file is not None:
            if not isinstance(file, AsyncFile):
                file = AsyncFile(file)
        self.file = file

        if content is None and file is None:
            raise ValueError('Field data must be provided.')
        if content is not None and file is not None:
            raise ValueError("Can't provide both content and file.")

        if content is not None:
            self.content_length = len(content)
        else:
            with file.blocking() as f:
                self.content_length = super_len(f)

        if filename is None:
            if filepath is None and file is not None:
                filepath = getattr(file, 'name')
            if filepath is not None:
                filename = basename(filepath)
        if filename is not None:
            filename = quote(filename, safe='')
        self.filename = filename

        if content_type is None and filename is not None:
            content_type = mimetypes.guess_type(filename)[0]
        if content_type is not None:
            self.headers['Content-Type'] = content_type

        disposition = ['form-data', f'name="{self.name}"']
        if self.filename is not None:
            disposition.append(f'filename="{self.filename}"')
        self.headers['Content-Disposition'] = '; '.join(disposition)

        self.encoded_headers = encode_headers(self.headers)

    def __len__(self):
        return self.content_length

    async def close(self):
        if self._should_close_file:
            await self.file.close()


class MultipartBody:

    def __init__(self, fields, boundary=None):
        self.fields = fields
        if not boundary:
            boundary = uuid4().hex
        self.boundary = boundary
        self.encoded_boundary = boundary.encode('ascii')
        self.content_type = 'multipart/form-data; boundary={}'.format(boundary)
        self.content_length = self._compute_content_length()
        self._gen = self._generator()

    def _compute_content_length(self):
        eol_len = len(bEOL)
        boundary_len = len(self.encoded_boundary)
        length = 0
        for field in self.fields:
            length += 2 + boundary_len + eol_len
            length += len(field.encoded_headers) + eol_len
            length += eol_len
            length += field.content_length + eol_len
        length += 2 + boundary_len + 2 + eol_len
        return length

    def __len__(self):
        return self.content_length

    async def __aiter__(self):
        async for chunk in self._gen:
            yield chunk

    async def _generator(self):
        chunk_size = 16 * 1024
        sep = b'--' + self.encoded_boundary + bEOL
        for field in self.fields:
            yield sep + field.encoded_headers + bEOL + bEOL
            if field.content is not None:
                yield field.content
            else:
                while True:
                    chunk = await field.file.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            yield bEOL
        yield b'--' + self.encoded_boundary + b'--' + bEOL


class CuPreparedRequest(PreparedRequest):

    def prepare_body(self, data, files, json=None):
        """Prepares the given HTTP body data."""
        if not files:
            return super().prepare_body(data, files, json)

        fields = []
        for key, value in to_key_val_list(data or {}):
            fields.append(Field(key, content=value))
        for (k, v) in to_key_val_list(files or {}):
            # support for explicit filename
            ft = None
            fh = None
            if isinstance(v, (tuple, list)):
                if len(v) == 2:
                    fn, fp = v
                elif len(v) == 3:
                    fn, fp, ft = v
                else:
                    fn, fp, ft, fh = v
            else:
                fn = None
                fp = v

            if isinstance(fp, (str, bytes, bytearray)):
                content = fp
                fp = None
            else:
                content = None

            fields.append(Field(
                k, filename=fn, file=fp, content=content,
                content_type=ft, headers=fh))

        self.body = MultipartBody(fields)
        self.headers.setdefault('Content-Type', self.body.content_type)
        self.prepare_content_length(self.body)


class CuRequest(Request):
    def prepare(self):
        """Constructs a :class:`PreparedRequest <PreparedRequest>` for transmission and returns it."""
        p = CuPreparedRequest()
        p.prepare(
            method=self.method,
            url=self.url,
            headers=self.headers,
            files=self.files,
            data=self.data,
            json=self.json,
            params=self.params,
            auth=self.auth,
            cookies=self.cookies,
            hooks=self.hooks,
        )
        return p
