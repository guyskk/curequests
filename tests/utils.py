import functools
from newio_kernel import run


def run_with_curio(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        run(f(*args, **kwargs))
    return wrapper
