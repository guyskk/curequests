"""
ConnectionPool
"""
from itertools import chain
import curio
from requests.exceptions import ConnectTimeout


class Connection:

    def __init__(self, resource):
        self._resource = resource
        self.sock = resource.value

    async def close(self):
        await self._resource.close()

    async def release(self):
        await self._resource.release()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            await self.release()
        else:
            await self.close()


class ConnectionPool:
    """Connection Pool"""

    def __init__(self, max_conns_per_netloc=10, max_conns_total=100):
        self._pool = ResourcePool(
            dispose_func=self._close_connection,
            max_items_per_key=max_conns_per_netloc,
            max_items_total=max_conns_total,
        )

    async def _open_connection(self, item, timeout=None, **kwargs):
        if item.value is not None:
            return
        scheme, host, port = item.key
        sock_co = curio.open_connection(
            host=host,
            port=port,
            **kwargs
        )
        if timeout is not None:
            sock_co = curio.timeout_after(timeout, sock_co)
        try:
            sock = await sock_co
        except curio.TaskTimeout as ex:
            raise ConnectTimeout(str(ex)) from None
        item.value = sock

    async def _close_connection(self, item):
        await item.value.close()

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

    async def get(self, scheme, host, port, **kwargs):
        resource = await self._pool.get((scheme, host, port))
        await self._open_connection(resource, **kwargs)
        return Connection(resource)

    async def close(self, force=False):
        await self._pool.close(force=force)


class ResourcePoolClosed(Exception):
    """Resource pool closed"""


class Resource:

    def __init__(self, key, pool):
        self.key = key
        self.pool = pool
        self.value = None

    def __repr__(self):
        return f'<{type(self).__name__} {self.key}>'

    async def release(self):
        await self.pool.put(self)

    async def close(self):
        await self.pool.remove(self)


class ResourcePool:
    """A general resource pool algorithm

    TODO: maybe not coroutine safe and thread safe!
    """

    def __init__(self, dispose_func, max_items_per_key=10, max_items_total=100):
        self._dispose = dispose_func
        self._closed = False
        self.max_items_per_key = max_items_per_key
        self.max_items_total = max_items_total
        self._idle_resources = {}  # key: [item, ...]
        self._busy_resources = {}  # key: [item, ...]
        self._waitings = {}  # key: [promise, ...]
        # the two numbers is for better performance
        self._num_idle = 0
        self._num_total = 0
        self._co_lock = curio.RLock()

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

    async def remove(self, item):
        if self._closed:
            await self._dispose(item)
            return
        self._busy_resources[item.key].remove(item)
        self._num_total -= 1
        await self._dispose(item)
        await self._notify_waitings()

    async def put(self, item):
        if self._closed:
            await self._dispose(item)
            return
        self._busy_resources[item.key].remove(item)
        waitings = self._waitings.get(item.key)
        if waitings:
            self._busy_resources[item.key].append(item)
            # just notify a promise in the fastest way
            promise = waitings.pop(0)
            await promise.set(item)
            return
        self._idle_resources.setdefault(item.key, []).append(item)
        self._num_idle += 1
        await self._notify_waitings()

    async def _notify_waitings(self):
        await self._close_an_idle_resource_if_need()
        async with self._co_lock:
            for key, waitings in self._waitings.items():
                if not waitings:
                    continue
                item = self._open_new_resource_if_permit(key)
                if item is not None:
                    promise = waitings.pop(0)
                    await promise.set(item)
                    break

    async def _close_an_idle_resource_if_need(self):
        if self._num_total < self.max_items_total:
            return
        async with self._co_lock:
            for key, idles in self._idle_resources.items():
                if idles:
                    item = idles.pop(0)
                    self._num_idle -= 1
                    self._num_total -= 1
                    await self._dispose(item)
                    break

    def _open_new_resource_if_permit(self, key):
        if self.size(key) < self.max_items_per_key:
            item = Resource(key, self)
            self._busy_resources.setdefault(key, []).append(item)
            self._num_total += 1
            return item

    async def get(self, key):
        if self._closed:
            raise ResourcePoolClosed('The resource pool was closed')
        idles = self._idle_resources.get(key)
        if idles:
            item = idles.pop()
            self._busy_resources.setdefault(key, []).append(item)
            self._num_idle -= 1
        else:
            await self._close_an_idle_resource_if_need()
            item = self._open_new_resource_if_permit(key)
            if item is None:
                promise = curio.Promise()
                self._waitings.setdefault(key, []).append(promise)
                item = await promise.get()
        return item

    async def close(self, force=False):
        self._closed = True
        for promise in chain.from_iterable(self._waitings.values()):
            promise.clear()
        for item in chain.from_iterable(self._idle_resources.values()):
            await self._dispose(item)
        if force:
            for item in chain.from_iterable(self._busy_resources.values()):
                await self._dispose(item)
        self._busy_resources.clear()
        self._idle_resources.clear()
        self._waitings.clear()
        self._num_idle = 0
        self._num_total = 0


async def main():

    async def dispose_resource(item):
        print('close', item)

    pool = ResourcePool(dispose_resource, max_items_total=1)

    async def task(i, key):
        print('task:', i, key)
        item = await pool.get(key)
        if item.value is None:
            print('open', item)
            item.value = i
        print('task:', i, 'get:', item)
        await curio.sleep(0.1)
        if i % 10 == 0:
            await item.close()
        else:
            await item.release()

    tasks = []
    for i in range(1000):
        t = await curio.spawn(task, i, f'host{i % 10}')
        tasks.append(t)
    for t in tasks:
        await t.join()
    print(pool)

if __name__ == '__main__':
    curio.run(main)
