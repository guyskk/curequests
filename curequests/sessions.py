from requests.sessions import (
    Session, Request, preferred_clock,
    timedelta, dispatch_hook, extract_cookies_to_jar
)
from requests.sessions import (
    cookielib,
    cookiejar_from_dict,
    merge_cookies,
    RequestsCookieJar,
    get_netrc_auth,
    merge_setting,
    CaseInsensitiveDict,
    merge_hooks)
from .adapters import CuHTTPAdapter
from .models import CuPreparedRequest


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

    def prepare_request(self, request):
        """Constructs a :class:`PreparedRequest <PreparedRequest>` for
        transmission and returns it. The :class:`PreparedRequest` has settings
        merged from the :class:`Request <Request>` instance and those of the
        :class:`Session`.

        :param request: :class:`Request` instance to prepare with this
            session's settings.
        :rtype: requests.PreparedRequest
        """
        cookies = request.cookies or {}

        # Bootstrap CookieJar.
        if not isinstance(cookies, cookielib.CookieJar):
            cookies = cookiejar_from_dict(cookies)

        # Merge with session cookies
        merged_cookies = merge_cookies(
            merge_cookies(RequestsCookieJar(), self.cookies), cookies)

        # Set environment's basic authentication if not explicitly set.
        auth = request.auth
        if self.trust_env and not auth and not self.auth:
            auth = get_netrc_auth(request.url)

        p = CuPreparedRequest()
        p.prepare(
            method=request.method.upper(),
            url=request.url,
            files=request.files,
            data=request.data,
            json=request.json,
            headers=merge_setting(request.headers, self.headers, dict_class=CaseInsensitiveDict),
            params=merge_setting(request.params, self.params),
            auth=merge_setting(auth, self.auth),
            cookies=merged_cookies,
            hooks=merge_hooks(request.hooks, self.hooks),
        )
        return p

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
