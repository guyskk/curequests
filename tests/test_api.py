# -*- coding: utf-8 -*-
from curequests import get, post
from utils import run_with_curio


@run_with_curio
async def test_get():
    r = await get('http://httpbin.org/get')
    assert r.status_code == 200


@run_with_curio
async def test_post():
    data = {'hello': 'world'}
    r = await post('http://httpbin.org/post', json=data)
    assert r.status_code == 200
    assert r.json()['json'] == data


@run_with_curio
async def test_https():
    r = await get('https://httpbin.org/get')
    assert r.status_code == 200


@run_with_curio
async def test_gzip():
    r = await get('https://httpbin.org/gzip')
    assert r.status_code == 200
    assert r.json()


@run_with_curio
async def test_chunked():
    r = await get('http://httpbin.org/stream/1')
    assert r.status_code == 200
    assert r.json()
