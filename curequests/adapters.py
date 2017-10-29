import curio
import yarl
from collections import namedtuple
from requests.adapters import BaseAdapter, TimeoutSauce
from requests.adapters import (
    CaseInsensitiveDict, get_encoding_from_headers, extract_cookies_to_jar)
from requests.exceptions import ConnectionError
from requests import ConnectTimeout

from .models import CuResponse
from .cuhttp import ResponseParser, RequestSerializer

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connections = []

    async def open_connection(self, request, timeout=None):
        url = yarl.URL(request.url)
        request.headers.setdefault('Host', url.raw_host)
        if url.scheme == 'https':
            ssl = True
            server_hostname = url.raw_host
        else:
            ssl = False
            server_hostname = None
        open_connection = curio.open_connection(
            host=url.raw_host,
            port=url.port,
            ssl=ssl,
            server_hostname=server_hostname,
        )
        if timeout:
            open_connection = curio.timeout_after(timeout, open_connection)
        try:
            conn = await open_connection
        except curio.TaskTimeout as ex:
            raise ConnectTimeout(str(ex)) from None
        self._connections.append(conn)
        return conn

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
        request_path = url.raw_path
        if url.raw_query_string:
            request_path += '?' + url.raw_query_string
        serializer = RequestSerializer(
            path=request_path,
            method=request.method,
            headers=request.headers,
            body=request.body,
        )

        timeout = normalize_timeout(timeout)
        conn = await self.open_connection(request, timeout=timeout.connect)

        try:
            async for bytes_to_send in serializer:
                await conn.sendall(bytes_to_send)
            raw = await ResponseParser(conn, timeout=timeout.read).parse()
            response = self.build_response(request, raw)
            if not stream:
                content = []
                async for trunk in raw.stream():
                    content.append(trunk)
                content = b''.join(content)
                response._content = content
                response._content_consumed = True
        except (curio.socket.error) as err:
            raise ConnectionError(err, request=request)
        return response

    def build_response(self, req, resp):
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
        response.connection = self

        return response

    async def close(self):
        """Disposes of any internal state.

        Currently, this closes the PoolManager and any active ProxyManager,
        which closes any pooled connections.
        """
        for conn in self._connections:
            await conn.close()
