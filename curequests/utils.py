import codecs
from curio.meta import finalize


async def stream_decode_response_unicode(iterator, r):
    """Stream decodes a iterator."""

    async with finalize(iterator) as iterator:
        if r.encoding is None:
            async for item in iterator:
                yield item
            return

        decoder = codecs.getincrementaldecoder(r.encoding)(errors='replace')
        async for chunk in iterator:
            rv = decoder.decode(chunk)
            if rv:
                yield rv
        rv = decoder.decode(b'', final=True)
        if rv:
            yield rv


async def iter_slices(string, slice_length):
    """Iterate over slices of a string."""
    pos = 0
    if slice_length is None or slice_length <= 0:
        slice_length = len(string)
    while pos < len(string):
        yield string[pos:pos + slice_length]
        pos += slice_length
