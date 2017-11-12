from curio.meta import finalize
from requests.models import Response
from requests.exceptions import (
    ChunkedEncodingError, ContentDecodingError,
    ConnectionError, StreamConsumedError)
from requests.models import ITER_CHUNK_SIZE
from .utils import stream_decode_response_unicode, iter_slices
from .cuhttp import DecodeError, ProtocolError, ReadTimeoutError


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
