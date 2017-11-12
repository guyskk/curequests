# Curio + Requests: Async HTTP for Humans

[![travis-ci](https://api.travis-ci.org/guyskk/curequests.svg?branch=master)](https://travis-ci.org/guyskk/curequests) [![codecov](https://codecov.io/gh/guyskk/curequests/branch/master/graph/badge.svg)](https://codecov.io/gh/guyskk/curequests)
> The same taste as Requests!

## Overview

```python
from curio import run
from curequests import get, post

async def main():
    r = await get('https://httpbin.org/get')
    print(r.json())
    r = await post('https://httpbin.org/post', json={'hello': 'world'})
    print(r.json())

run(main)
```

## Install

Python 3.6+ is required.

```bash
pip install curequests
```

## Features

Follow http://docs.python-requests.org/en/master/#the-user-guide

> Work in progress, Not production ready!

### Quickstart

- [x] Make a Request
- [x] Passing Parameters In URLs
- [x] Response Content
- [x] Binary Response Content
- [x] JSON Response Content
- [x] Custom Headers
- [ ] POST a Multipart-Encoded File
- [x] Response Status Codes
- [x] Response Headers
- [x] Cookies
- [ ] Redirection and History
- [x] Timeouts
- [x] Errors and Exceptions

### Advanced Usage

- [x] Session Objects [CuSession]
- [x] Request and Response Objects [CuResponse]
- [x] Prepared Requests
- [x] SSL Cert Verification
- [x] Client Side Certificates
- [x] CA Certificates
- [x] Body Content Workflow
- [x] Keep-Alive
- [ ] Streaming Uploads
- [ ] Chunk-Encoded Requests
- [ ] POST Multiple Multipart-Encoded Files
- [x] Event Hooks
- [x] Custom Authentication
- [x] Streaming Requests [Async Generator]
- [ ] Proxies
- [x] Compliance
- [x] HTTP Verbs
- [x] Custom Verbs
- [x] Link Headers
- [x] Transport Adapters [CuHTTPAdapter]
- [x] Blocking Or Non-Blocking?
- [x] Header Ordering
- [x] Timeouts
- [x] Authentication

### Similar projects

- https://github.com/littlecodersh/trip
  Async HTTP for Humans, Tornado & Requests In Pair
