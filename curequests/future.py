from curio import Event


class Future:

    def __init__(self):
        self._event = Event()
        self._result = None
        self._exception = None

    async def set_result(self, result):
        self._result = result
        await self._event.set()

    async def set_exception(self, exception):
        self._exception = exception
        await self._event.set()

    async def _get_result(self):
        await self._event.wait()

        if self._exception is not None:
            raise self._exception

        return self._result

    def __await__(self):
        """Future is awaitable

        PS: I don't know how to implement __await__, but I know coroutine
            implemented it, so just forward the call!
        """
        return self._get_result().__await__()
