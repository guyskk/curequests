# Curio + Requests: Async HTTP for Humans

[![PyPI](https://img.shields.io/pypi/pyversions/curequests.svg)](https://pypi.python.org/pypi/curequests)
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
- [x] POST a Multipart-Encoded File
- [x] Response Status Codes
- [x] Response Headers
- [x] Cookies
- [x] Redirection and History
- [x] Timeouts
- [x] Errors and Exceptions

### Advanced Usage

- [x] Session Objects [CuSession]
- [x] Request and Response Objects [CuResponse]
- [x] Prepared Requests [CuRequest, CuPreparedRequest]
- [x] SSL Cert Verification
- [x] Client Side Certificates
- [x] CA Certificates
- [x] Body Content Workflow
- [x] Keep-Alive
- [x] Streaming Uploads
- [x] Chunk-Encoded Requests [Generator / Async Generator]
- [x] POST Multiple Multipart-Encoded Files
- [x] Event Hooks
- [x] Custom Authentication
- [x] Streaming Requests [Async Generator]
- [x] Proxies [HTTP&HTTPS, not support SOCKS currently]
- [x] Compliance
- [x] HTTP Verbs
- [x] Custom Verbs
- [x] Link Headers
- [x] Transport Adapters [CuHTTPAdapter]
- [x] Blocking Or Non-Blocking?
- [x] Header Ordering
- [x] Timeouts
- [x] Authentication

### How to Contribute

1. Check for open issues or open a fresh issue to start a discussion around a feature idea or a bug. There is a *Contributor Friendly* tag for issues that should be ideal for people who are not very familiar with the codebase yet.
2. Fork the repository on GitHub to start making your changes to the **master** branch (or branch off of it).
3. Write a test which shows that the bug was fixed or that the feature works as expected.
4. Send a pull request and bug the maintainer until it gets merged and published. :) Make sure to add yourself to *AUTHORS.md*.

### Similar projects

- https://github.com/littlecodersh/trip
  Async HTTP for Humans, Tornado & Requests In Pair
- https://github.com/theelous3/asks
  Async requests-like httplib for python
