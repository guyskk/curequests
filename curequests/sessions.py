from requests.sessions import (Session, Request, preferred_clock,
                               timedelta, dispatch_hook, extract_cookies_to_jar)
from .adapters import CuHTTPAdapter


class CuSession(Session):

    def __init__(self):
        super().__init__()
        self.mount('https://', CuHTTPAdapter())
        self.mount('http://', CuHTTPAdapter())

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

    async def send(self, request, **kwargs):
        """Send a given PreparedRequest.

        :rtype: requests.Response
        """
        # Set defaults that the hooks can utilize to ensure they always have
        # the correct parameters to reproduce the previous request.
        kwargs.setdefault('stream', self.stream)
        kwargs.setdefault('verify', self.verify)
        kwargs.setdefault('cert', self.cert)
        kwargs.setdefault('proxies', self.proxies)

        # It's possible that users might accidentally send a Request object.
        # Guard against that specific failure case.
        if isinstance(request, Request):
            raise ValueError('You can only send PreparedRequests.')

        kwargs.pop('allow_redirects', True)
        hooks = request.hooks

        # Get the appropriate adapter to use
        adapter = self.get_adapter(url=request.url)

        # Start time (approximately) of the request
        start = preferred_clock()

        # Send the request
        r = await adapter.send(request, **kwargs)

        # Total elapsed time of the request (approximately)
        elapsed = preferred_clock() - start
        r.elapsed = timedelta(seconds=elapsed)

        # Response manipulation hooks
        r = dispatch_hook('response', hooks, r, **kwargs)

        extract_cookies_to_jar(self.cookies, request, r.raw)

        return r

    async def close(self):
        """Closes all adapters and as such the session"""
        for v in self.adapters.values():
            await v.close()


def session():
    """
    Returns a :class:`CuSession` for context-management.

    :rtype: CuSession
    """

    return CuSession()
