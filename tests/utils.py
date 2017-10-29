# -*- coding: utf-8 -*-

import functools
import contextlib
import os
import curio


@contextlib.contextmanager
def override_environ(**kwargs):
    save_env = dict(os.environ)
    for key, value in kwargs.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(save_env)


def run_with_curio(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return curio.run(f(*args, **kwargs))
    return wrapper
