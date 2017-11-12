from os.path import isdir, exists
from collections import namedtuple

import yarl
import curio
from curio import ssl
from requests.adapters import BaseAdapter, TimeoutSauce
from requests.adapters import (
    CaseInsensitiveDict, get_encoding_from_headers, extract_cookies_to_jar)
from requests.exceptions import ConnectionError

from .models import CuResponse
from .cuhttp import ResponseParser, RequestSerializer
from .connection_pool import ConnectionPool


DEFAULT_CONNS_PER_NETLOC = 10
DEFAULT_CONNS_TOTAL = 100
CONTENT_CHUNK_SIZE = 16 * 1024

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


class CuHTTPAdapter(BaseAdapter):
    """The built-in HTTP Adapter for urllib3.

    Provides a general-case interface for Requests sessions to contact HTTP and
    HTTPS urls by implementing the Transport Adapter interface. This class will
    usually be created by the :class:`Session <Session>` class under the
    covers.

    :param pool_connections: The number of urllib3 connection pools to cache.
    :param pool_maxsize: The maximum number of connections to save in the pool.
    :param max_retries: The maximum number of retries each connection
        should attempt. Note, this applies only to failed DNS lookups, socket
        connections and connection timeouts, never to requests where data has
        made it to the server. By default, Requests does not retry failed
        connections. If you need granular control over the conditions under
        which we retry a request, import urllib3's ``Retry`` class and pass
        that instead.
    :param pool_block: Whether the connection pool should block for connections.

    Usage::

      >>> import requests
      >>> s = requests.Session()
      >>> a = requests.adapters.HTTPAdapter(max_retries=3)
      >>> s.mount('http://', a)
    """

    def __init__(self, *,
                 max_conns_per_netloc=DEFAULT_CONNS_PER_NETLOC,
                 max_conns_total=DEFAULT_CONNS_TOTAL,
                 ):
        super().__init__()
        self._pool = ConnectionPool(
            max_conns_per_netloc=max_conns_per_netloc,
            max_conns_total=max_conns_total,
        )

    def get_ssl_params(self, url, verify, cert):
        if url.scheme.lower() != 'https' or (not verify and not cert):
            return {'ssl': False}

        ssl_params = {}
        ssl_context = ssl.create_default_context()

        if verify:
            if isinstance(verify, str):
                if not exists(verify):
                    raise FileNotFoundError(
                        f'Could not find a suitable TLS CA certificate bundle, '
                        f'invalid path: {verify}')
                if isdir(verify):
                    ssl_context.load_verify_locations(capath=verify)
                else:
                    ssl_context.load_verify_locations(cafile=verify)
            ssl_params['server_hostname'] = url.raw_host
            ssl_context.verify_mode = ssl.CERT_REQUIRED

        if cert:
            if isinstance(cert, str):
                cert_file = cert
                key_file = None
            else:
                cert_file, key_file = cert
            if cert_file and not exists(cert_file):
                raise FileNotFoundError(
                    f'Could not find the TLS certificate file, '
                    f'invalid path: {cert_file}')
            if key_file and not exists(key_file):
                raise FileNotFoundError(
                    f'Could not find the TLS certificate file, '
                    f'invalid path: {key_file}')
            ssl_context.load_cert_chain(cert_file, key_file)

        ssl_params['ssl'] = ssl_context
        return ssl_params

    async def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        """Sends PreparedRequest object. Returns Response object.

        :param request: The :class:`PreparedRequest <PreparedRequest>` being sent.
        :param stream: (optional) Whether to stream the request content.
        :param timeout: (optional) How long to wait for the server to send
            data before giving up, as a float, or a :ref:`(connect timeout,
            read timeout) <timeouts>` tuple.
        :type timeout: float or tuple or urllib3 Timeout object
        :param verify: (optional) Either a boolean, in which case it controls whether
            we verify the server's TLS certificate, or a string, in which case it
            must be a path to a CA bundle to use
        :param cert: (optional) Any user-provided SSL certificate to be trusted.
        :param proxies: (optional) The proxies dictionary to apply to the request.
        :rtype: requests.Response
        """
        url = yarl.URL(request.url)
        request.headers.setdefault('Host', url.raw_host)

        request_path = url.raw_path
        if url.raw_query_string:
            request_path += '?' + url.raw_query_string
        serializer = RequestSerializer(
            path=request_path,
            method=request.method,
            headers=request.headers,
            body=request.body,
        )

        ssl_params = self.get_ssl_params(url, verify, cert)
        timeout = normalize_timeout(timeout)
        conn = await self._pool.get(
            scheme=url.scheme,
            host=url.raw_host,
            port=url.port,
            timeout=timeout.connect,
            **ssl_params,
        )

        try:
            sock = conn.sock
            try:
                async for bytes_to_send in serializer:
                    await sock.sendall(bytes_to_send)
                raw = await ResponseParser(sock, timeout=timeout.read).parse()
                if not stream:
                    content = []
                    async for chunk in raw.stream(CONTENT_CHUNK_SIZE):
                        content.append(chunk)
                    content = b''.join(content)
                    if raw.keep_alive:
                        await conn.release()
                    else:
                        await conn.close()
            except (curio.socket.error) as err:
                raise ConnectionError(err, request=request)
        except:
            await conn.close()
            raise

        response = self.build_response(request, raw, conn)
        if not stream:
            response._content = content
            response._content_consumed = True
        return response

    def build_response(self, req, resp, conn):
        """Builds a :class:`Response <requests.Response>` object from a urllib3
        response. This should not be called from user code, and is only exposed
        for use when subclassing the
        :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`

        :param req: The :class:`PreparedRequest <PreparedRequest>` used to generate the response.
        :param resp: The urllib3 response object.
        :rtype: requests.Response
        """
        response = CuResponse()

        # Fallback to None if there's no status_code, for whatever reason.
        response.status_code = getattr(resp, 'status', None)

        # Make headers case-insensitive.
        response.headers = CaseInsensitiveDict(getattr(resp, 'headers', {}))

        # Set encoding.
        response.encoding = get_encoding_from_headers(response.headers)
        response.raw = resp
        response.reason = response.raw.reason

        if isinstance(req.url, bytes):
            response.url = req.url.decode('utf-8')
        else:
            response.url = req.url

        # Add new cookies from the server.
        extract_cookies_to_jar(response.cookies, req, resp)

        # Give the Response some context.
        response.request = req
        response.connection = conn

        return response

    async def close(self):
        """Disposes of any internal state.

        Currently, this closes the PoolManager and any active ProxyManager,
        which closes any pooled connections.
        """
        await self._pool.close()
