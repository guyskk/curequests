import functools
import curio


def run_with_curio(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return curio.run(f(*args, **kwargs))
    return wrapper
