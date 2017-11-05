"""
PoolManager
ConnectionPool
ConnectionProxy
conn: open -> busy -> idle
                \-> close
"""
from itertools import chain
import curio


class ConnectionPool:
    """Connection Pool"""

    def __init__(self,
                 max_conns_per_netloc=10,
                 max_conns_total=100,
                 timeout=None,
                 **connection_params,
                 ):
        self._timeout = timeout
        self._connection_params = connection_params
        self._pool = ResourcePool(self, max_items_per_key=max_conns_per_netloc,
                                  max_items_total=max_conns_total)

    async def open_resource(self, item):
        host, port = item.key
        sock_co = curio.open_connection(
            host=host,
            port=port,
            **self._connection_params,
        )
        if self._timeout is not None:
            sock_co = curio.timeout_after(self._timeout, sock_co)
        item.sock = await sock_co

    async def close_resource(self, item):
        await item.sock.close()

    @property
    def num_idle(self):
        return self._pool.num_idle

    @property
    def num_busy(self):
        return self._pool.num_busy

    @property
    def num_total(self):
        return self._pool.num_total

    def __repr__(self):
        return f'<{type(self).__name__} idle:{self.num_idle} total:{self.num_total}>'

    async def put(self, conn):
        await self._pool.put(conn)

    async def get(self, host, port):
        return await self._pool.get((host, port))


class Resource:

    def __init__(self, key):
        self.key = key

    def __repr__(self):
        return f'<{type(self).__name__} {self.key}>'


class ResourcePool:
    """A general resource pool algorithm"""

    def __init__(self, manager, max_items_per_key=10, max_items_total=100):
        self.manager = manager
        self.max_items_per_key = max_items_per_key
        self.max_items_total = max_items_total
        self._idle_resources = {}  # key: [item, ...]
        self._busy_resources = {}  # key: [item, ...]
        self._waitings = {}  # key: [promise, ...]
        # the two numbers is for better performance
        self._num_idle = 0
        self._num_total = 0
        # keep coroutine safe
        self._lock = curio.RLock()

    @property
    def num_idle(self):
        return self._num_idle

    @property
    def num_busy(self):
        return self._num_total - self._num_idle

    @property
    def num_total(self):
        return self._num_total

    def size(self, key):
        r = [self._idle_resources, self._busy_resources]
        return sum(len(x.get(key, [])) for x in r)

    def __repr__(self):
        return f'<{type(self).__name__} idle:{self.num_idle} total:{self.num_total}>'

    async def put(self, item, close=False):
        async with self._lock:
            self._busy_resources[item.key].remove(item)
            if close:
                self._num_total -= 1
                await self.manager.close_resource(item)
            else:
                waitings = self._waitings.get(item.key)
                if waitings:
                    self._busy_resources[item.key].append(item)
                    # just notify a promise in the fastest way
                    promise = waitings.pop(0)
                    await promise.set(item)
                    return
                self._idle_resources.setdefault(item.key, []).append(item)
                self._num_idle += 1
            # notify waitings
            await self._close_an_idle_resource_if_need()
            for key, waitings in self._waitings.items():
                if not waitings:
                    continue
                item = await self._open_new_resource_if_permit(key)
                if item is not None:
                    promise = waitings.pop(0)
                    await promise.set(item)
                    break

    async def _close_an_idle_resource_if_need(self):
        if self._num_total < self.max_items_total:
            return
        for key, idles in self._idle_resources.items():
            if idles:
                item = idles.pop(0)
                self._num_idle -= 1
                self._num_total -= 1
                await self.manager.close_resource(item)
                break

    async def _open_new_resource_if_permit(self, key):
        if self.size(key) < self.max_items_per_key:
            item = Resource(key)
            self._busy_resources.setdefault(key, []).append(item)
            self._num_total += 1
            await self.manager.open_resource(item)
            return item

    async def get(self, key):
        async with self._lock:
            idles = self._idle_resources.get(key)
            if idles:
                item = idles.pop()
                self._busy_resources.setdefault(key, []).append(item)
                self._num_idle -= 1
            else:
                await self._close_an_idle_resource_if_need()
                item = await self._open_new_resource_if_permit(key)
                if item is None:
                    promise = curio.Promise()
                    self._waitings.setdefault(key, []).append(promise)
                    item = await promise.get()
            return item

    async def clear(self):
        async with self._lock:
            for item in chain.from_iterable(self._idle_resources.values()):
                await self.manager.close_resource(item)
            for item in chain.from_iterable(self._busy_resources.values()):
                await self.manager.close_resource(item)
            for promise in chain.from_iterable(self._waitings.values()):
                promise.clear()
            self._busy_resources.clear()
            self._idle_resources.clear()
            self._waitings.clear()
            self._num_idle = 0
            self._num_total = 0


async def main():

    class Manager:

        async def open_resource(self, item):
            print('open', item)

        async def close_resource(self, item):
            print('close', item)

    pool = ResourcePool(Manager())

    async def task(i, key):
        print('task:', i, key)
        item = await pool.get(key)
        print('task:', i, 'get:', item)
        await curio.sleep(0.1)
        await pool.put(item, close=i % 10 == 0)

    tasks = []
    for i in range(30):
        t = await curio.spawn(task, i, f'host{i % 10}')
        tasks.append(t)
    for t in tasks:
        await t.join()
    print(pool)

if __name__ == '__main__':
    curio.run(main)
