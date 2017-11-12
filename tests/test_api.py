import json
from curio.meta import finalize
from curequests import get, post
from utils import run_with_curio


@run_with_curio
async def test_get(httpbin_both):
    r = await get(httpbin_both + '/get')
    assert r.status_code == 200


@run_with_curio
async def test_post(httpbin_both):
    data = {'hello': 'world'}
    r = await post(httpbin_both + '/post', json=data)
    assert r.status_code == 200
    assert r.json()['json'] == data


@run_with_curio
async def test_gzip(httpbin_both):
    r = await get(httpbin_both + '/gzip')
    assert r.status_code == 200
    assert r.json()


@run_with_curio
async def test_chunked(httpbin_both):
    r = await get(httpbin_both + '/stream/1', stream=True)
    assert r.status_code == 200
    body = []
    async with finalize(r.iter_content()) as gen:
        async for chunk in gen:
            body.append(chunk)
    body = b''.join(body).decode('utf-8')
    assert json.loads(body)
