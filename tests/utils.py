import functools
import curio


def run_with_curio(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            curio.run(f(*args, **kwargs))
        except curio.TaskError as ex:
            raise ex.__cause__ from None
    return wrapper
