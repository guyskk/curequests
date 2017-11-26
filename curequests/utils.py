import inspect
import codecs
from collections import namedtuple

from curio.meta import finalize
from requests.adapters import TimeoutSauce


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

TimeoutValue = namedtuple('TimeoutValue', 'connect read')


def normalize_timeout(timeout):
    if isinstance(timeout, tuple):
        try:
            connect, read = timeout
            timeout = TimeoutValue(connect=connect, read=read)
        except ValueError as e:
            # this may raise a string formatting error.
            err = ('Invalid timeout {0}. Pass a (connect, read) '
                   'timeout tuple, or a single float to set '
                   'both timeouts to the same value'.format(timeout))
            raise ValueError(err)
    elif isinstance(timeout, TimeoutSauce):
        raise ValueError('Not support urllib3 Timeout object')
    else:
        timeout = TimeoutValue(connect=timeout, read=timeout)
    return timeout


def select_proxy(scheme, host, port, proxies):
    """Select a proxy for the url, if applicable.

    :param scheme, host, port: The url being for the request
    :param proxies: A dictionary of schemes or schemes and hosts to proxy URLs
    """
    proxies = proxies or {}
    if host is None:
        return proxies.get(scheme, proxies.get('all'))

    proxy_keys = [
        scheme + '://' + host,
        scheme,
        'all://' + host,
        'all',
    ]
    proxy = None
    for proxy_key in proxy_keys:
        if proxy_key in proxies:
            proxy = proxies[proxy_key]
            break

    return proxy


async def ensure_asyncgen(body):
    if not inspect.isasyncgen(body):
        for chunk in body:
            yield chunk
    else:
        async for chunk in body:
            yield chunk
