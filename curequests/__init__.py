# flake8: noqa
"""Concurrent requests by curio

api:
    - request, use curio Session
Session:
    - __init__, mount curio HTTPAdapter
    - send, almost the same as requests, change some calls to async/await style
    - close, async/await style
HTTPAdapter:
    - use httptools, implement use curio
    - send, return curio Response
    - close
Response:
    - iter_content
    - content
    - ...
"""
from requests import *
from .sessions import *
from .models import *
from .api import *
