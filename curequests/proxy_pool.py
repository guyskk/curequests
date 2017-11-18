from yarl import URL
from requests.auth import _basic_auth_str
from requests.exceptions import ProxyError
from curio.network import _wrap_ssl_client

from .cuhttp import RequestSerializer, ResponseParser
from .connection_pool import ConnectionPool


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


class ProxyPool:

    def __init__(self, max_conns_per_proxy=10, max_conns_total=100):
        self._conn_pool = ConnectionPool(max_conns_per_proxy, max_conns_total)

    async def get(self, scheme, host, port, *, proxy, **kwargs):
        proxy = URL(proxy)
        conn = await self._conn_pool.get(proxy.scheme, proxy.raw_host, proxy.port)
        if not kwargs.get('ssl', False):
            return conn
        headers = {}
        if proxy.raw_user:
            headers['Proxy-Authorization'] = _basic_auth_str(
                proxy.raw_user, proxy.password)
        request = RequestSerializer(f'{host}:{port}', method='CONNECT', headers=headers)
        async for chunk in request:
            await conn.sock.sendall(chunk)
        response = await ResponseParser(conn.sock).parse()
        if response.status != 200:
            raise ProxyError(response)
        kwargs.setdefault('ssl', None)
        kwargs.setdefault('server_hostname', None)
        kwargs.setdefault('alpn_protocols', None)
        conn.sock = await _wrap_ssl_client(conn.sock, **kwargs)
        return conn

    async def close(self):
        await self._conn_pool.close()
