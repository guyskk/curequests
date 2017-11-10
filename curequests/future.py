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

    async def __await__(self):
        await self._event.wait()

        if self._exception is not None:
            raise self._exception

        return self._result
