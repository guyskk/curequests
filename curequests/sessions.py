import logging
from urllib.parse import urlparse, urljoin

from requests.utils import requote_uri
from requests.sessions import (
    Session, Request, preferred_clock,
    timedelta, dispatch_hook, extract_cookies_to_jar
)
from requests.exceptions import TooManyRedirects
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
from .models import MultipartBody, StreamBody

logger = logging.getLogger(__name__)


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

    async def _send(self, request, **kwargs):
        """Send a given PreparedRequest.

        :rtype: requests.Response
        """
        logger.debug(f'Send request: {request}')
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

        hooks = request.hooks

        # Get the appropriate adapter to use
        adapter = self.get_adapter(url=request.url)

        # Start time (approximately) of the request
        start = preferred_clock()

        # Send the request
        r = await adapter.send(request, **kwargs)

        # Total elapsed time of the request (approximately)
        elapsed = preferred_clock() - start
        logger.debug(f'Request {request} elapsed {elapsed:.3f} seconds')
        r.elapsed = timedelta(seconds=elapsed)

        # Response manipulation hooks
        r = dispatch_hook('response', hooks, r, **kwargs)

        extract_cookies_to_jar(self.cookies, request, r.raw)

        return r

    def _get_next_url(self, resp):
        url = resp.headers['location'] or ''

        # Handle redirection without scheme (see: RFC 1808 Section 4)
        if url.startswith('//'):
            scheme = urlparse(resp.url).scheme
            url = f'{scheme}:{url}'

        # The scheme should be lower case...
        parsed = urlparse(url)
        url = parsed.geturl()

        # Facilitate relative 'location' headers, as allowed by RFC 7231.
        # (e.g. '/path/to/resource' instead of 'http://domain.tld/path/to/resource')
        # Compliant with RFC3986, we percent encode the url.
        if not parsed.netloc:
            url = urljoin(resp.url, requote_uri(url))
        else:
            url = requote_uri(url)
        return url

    def _get_next_method(self, resp):
        """When being redirected we may want to change the method of the request
        based on certain specs or browser behavior.
        """
        method = resp.request.method

        # http://tools.ietf.org/html/rfc7231#section-6.4.4
        if resp.status_code == 303 and method != 'HEAD':
            method = 'GET'

        # Do what the browsers do, despite standards...
        # First, turn 302s into GETs.
        if resp.status_code == 302 and method != 'HEAD':
            method = 'GET'

        # Second, if a POST is responded to with a 301, turn it into a GET.
        # This bizarre behaviour is explained in Issue 1704.
        if resp.status_code == 301 and method == 'POST':
            method = 'GET'

        return method

    async def send(self, request, **kwargs):
        """Send a given PreparedRequest.

        :rtype: requests.Response
        """
        allow_redirects = kwargs.pop('allow_redirects', True)
        if not allow_redirects:
            return await self._send(request, **kwargs)

        history = []
        while True:
            resp = await self._send(request, **kwargs)
            resp.history = history[:]
            history.append(resp)
            if not resp.is_redirect:
                return resp

            # Release the connection back into the pool.
            await resp.close()

            if len(history) > self.max_redirects:
                raise TooManyRedirects('Exceeded %s redirects.' % self.max_redirects, response=resp)

            next_request = request.copy()
            next_request.url = self._get_next_url(resp)
            next_request.method = self._get_next_method(resp)
            logger.debug(f'Redirect to: {next_request.method} {next_request.url}')
            headers = next_request.headers

            # https://github.com/requests/requests/issues/1084
            if resp.status_code not in (307, 308):
                # https://github.com/requests/requests/issues/3490
                purged_headers = ('Content-Length', 'Content-Type', 'Transfer-Encoding')
                for header in purged_headers:
                    next_request.headers.pop(header, None)
                next_request.body = None

            # Attempt to rewind consumed file-like object.
            should_rewind = (
                ('Content-Length' in headers or 'Transfer-Encoding' in headers) and
                isinstance(next_request.body, (MultipartBody, StreamBody)))
            if should_rewind:
                logger.debug(f'Rewind request body for redirection: {next_request}')
                next_request.body.rewind()

            try:
                del headers['Cookie']
            except KeyError:
                pass

            # Extract any cookies sent on the response to the cookiejar
            # in the new request. Because we've mutated our copied prepared
            # request, use the old one that we haven't yet touched.
            extract_cookies_to_jar(next_request._cookies, request, resp.raw)
            merge_cookies(next_request._cookies, self.cookies)
            next_request.prepare_cookies(next_request._cookies)

            self.rebuild_auth(next_request, resp)

            # Override the original request.
            request = next_request

    def rebuild_auth(self, prepared_request, response):
        """When being redirected we may want to strip authentication from the
        request to avoid leaking credentials. This method intelligently removes
        and reapplies authentication where possible to avoid credential loss.
        """
        headers = prepared_request.headers
        url = prepared_request.url

        if 'Authorization' in headers:
            # If we get redirected to a new host, we should strip out any
            # authentication headers.
            original_parsed = urlparse(response.request.url)
            redirect_parsed = urlparse(url)

            if (original_parsed.hostname != redirect_parsed.hostname):
                del headers['Authorization']

        # .netrc might have more auth for us on our new host.
        new_auth = get_netrc_auth(url) if self.trust_env else None
        if new_auth is not None:
            prepared_request.prepare_auth(new_auth)

        return

    async def close(self):
        """Closes all adapters and as such the session"""
        logger.debug(f'Close session {self}')
        for v in self.adapters.values():
            await v.close()


def session():
    """
    Returns a :class:`CuSession` for context-management.

    :rtype: CuSession
    """

    return CuSession()
