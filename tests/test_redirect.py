import pytest
from curequests import session
from requests.exceptions import TooManyRedirects
from utils import run_with_curio


@run_with_curio
async def test_redirect(httpbin_both):
    s = session()
    s.max_redirects = 3
    r = await s.get(httpbin_both + '/redirect/3')
    assert len(r.history) == 3
    with pytest.raises(TooManyRedirects) as exc_info:
        r = await s.get(httpbin_both + '/redirect/4')
    assert len(exc_info.value.response.history) == 3
