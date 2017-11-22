"""ConnectionPool

Usage:

    pool = ConnectionPool()
    conn = await pool.get('http', 'httpbin.org', 80)
    async with conn:
        ...
        # connection will close if exception raised
        # else connection will release to pool
"""
from base64 import b64encode
from yarl import URL
from curio.io import WantRead, WantWrite
from requests.exceptions import ProxyError

from .resource_pool import ResourcePool, ResourcePoolClosedError
from .future import Future
from .cuhttp import RequestSerializer, ResponseParser
from .network import open_connection, ssl_wrap_socket


def _basic_auth_str(username, password):
    """Returns a Basic Auth string."""
    auth = ('%s:%s' % (username, password)).encode('utf-8')
    return 'Basic ' + b64encode(auth).decode('utf-8').strip()


class ConnectionPoolClosedError(ResourcePoolClosedError):
    """Connection pool closed"""


async def _close_connection_if_need(resource):
    if resource is not None:
        conn = resource.connection
        conn._closed = True
        await conn.sock.close()


class Connection:
    """Connection

    Attrs:
        scheme (str): scheme
        host (str): host
        port (int): port
        sock (curio.Socket): socket
        proxy (yarl.URL): proxy url
        closed (bool): connection closed or not
        released (bool): connection released or not
    """

    def __init__(self, resource_pool, resource, sock, proxy=None):
        self._resource_pool = resource_pool
        self._resource = resource
        resource.connection = self  # bind resource & connection
        self.scheme, self.host, self.port = resource.key
        self.sock = sock
        self.proxy = proxy
        self._closed = False
        self._released = False

    @property
    def closed(self):
        return self._closed

    @property
    def released(self):
        return self._released

    def _is_peer_closed(self):
        """check if socket in close-wait state"""
        # the socket is non-blocking mode, read 1 bytes will return EOF
        # which means peer closed, or raise exception means alive
        try:
            r = self.sock._socket_recv(1)  # FIXME: I use a private method, bad!
        except WantRead:
            return False
        except WantWrite:
            return False
        assert r == b'', "is_peer_closed shouldn't be called at this time!"
        return True

    async def _close_or_release(self, close=False):
        if self._closed or self._released:
            return
        pool_ret = self._resource_pool.put(self._resource, close=close)
        self._released = True
        await _close_connection_if_need(pool_ret.need_close)
        if pool_ret.need_notify is not None:
            fut, result = pool_ret.need_notify
            await fut.set_result(result)

    async def close(self):
        """Close the connection"""
        await self._close_or_release(close=True)

    async def release(self):
        """Release the connection to connection pool"""
        await self._close_or_release(close=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            await self.release()
        else:
            await self.close()

    def __repr__(self):
        scheme, host, port = self.scheme, self.host, self.port
        if self.proxy:
            proxy = self.proxy
            if proxy.password:
                proxy = proxy.with_password('***')
            proxy = ' proxy={}'.format(proxy)
        else:
            proxy = ''
        status = 'busy'
        if self.released:
            status = 'idle'
        if self.closed:
            status = 'closed'
        return f'<{type(self).__name__} {scheme}://{host}:{port}{proxy} [{status}]>'


class ConnectionPool:
    """Connection Pool

    Attrs:
        max_conns_per_netloc (int): max connections per netloc
        max_conns_total (int): max connections in total
    """

    def __init__(self, max_conns_per_netloc=10, max_conns_total=100):
        self.max_conns_per_netloc = max_conns_per_netloc
        self.max_conns_total = max_conns_total
        self._pool = ResourcePool(
            future_class=Future,
            max_items_per_key=max_conns_per_netloc,
            max_items_total=max_conns_total,
        )

    async def _open_connection(self, resource, proxy=None, timeout=None, **ssl_params):
        scheme, host, port = resource.key
        if not proxy:
            sock = await open_connection(
                host=host,
                port=port,
                timeout=timeout,
                **ssl_params
            )
            return Connection(self._pool, resource, sock)
        proxy = URL(proxy)
        sock = await open_connection(
            host=proxy.raw_host,
            port=proxy.port,
            timeout=timeout,
        )
        conn = Connection(self._pool, resource, sock, proxy)
        return await self._setup_proxy(conn, proxy, **ssl_params)

    async def _setup_proxy(self, conn, proxy, **ssl_params):
        if not ssl_params.get('ssl_context'):
            return conn
        headers = {}
        if proxy.raw_user:
            auth = _basic_auth_str(proxy.raw_user, proxy.password)
            headers['Proxy-Authorization'] = auth
        path = f'{conn.host}:{conn.port}'
        request = RequestSerializer(path, method='CONNECT', headers=headers)
        async for chunk in request:
            await conn.sock.sendall(chunk)
        response = await ResponseParser(conn.sock).parse()
        if response.status != 200:
            raise ProxyError(response)
        conn.sock = await ssl_wrap_socket(conn.sock, **ssl_params)
        return conn

    @property
    def num_idle(self):
        """Number of idle connections"""
        return self._pool.num_idle

    @property
    def num_busy(self):
        """Number of busy connections"""
        return self._pool.num_busy

    @property
    def num_total(self):
        """Number of total connections"""
        return self._pool.num_total

    def __repr__(self):
        return f'<{type(self).__name__} idle:{self.num_idle} total:{self.num_total}>'

    async def get(self, scheme, host, port, **kwargs):
        """Get a connection

        Params:
            scheme (str): connection scheme
            host (str): connection host
            port (int): connection port
            timeout (int): connection timeout in seconds
            **kwargs: see curio.open_connection
        """
        while True:
            conn = await self._get(scheme, host, port, **kwargs)
            if conn._is_peer_closed():
                await conn.close()
            else:
                return conn

    async def _get(self, scheme, host, port, **kwargs):
        try:
            pool_ret = self._pool.get((scheme, host, port))
        except ResourcePoolClosedError as ex:
            raise ConnectionPoolClosedError('Connection pool closed') from ex
        await _close_connection_if_need(pool_ret.need_close)
        if pool_ret.need_wait is not None:
            pool_ret = await pool_ret.need_wait

        if pool_ret.need_open is not None:
            conn = await self._open_connection(pool_ret.need_open, **kwargs)
        else:
            conn = pool_ret.idle.connection
            conn._released = False
        return conn

    async def close(self, force=False):
        """Close the connection pool

        Params:
            force (bool): close busy connections or not
        """
        need_close, need_wait = self._pool.close(force=force)
        ex = ConnectionPoolClosedError('Connection pool closed')
        for resource in need_close:
            await _close_connection_if_need(resource)
        for fut in need_wait:
            await fut.set_exception(ex)
