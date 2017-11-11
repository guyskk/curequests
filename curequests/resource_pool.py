from itertools import chain
from threading import RLock
from namedlist import namedlist


class ResourcePoolClosedError(Exception):
    """Resource pool closed"""


class Resource:
    def __init__(self, key):
        self.key = key

    def __repr__(self):
        return f'<{type(self).__name__} {self.key}>'


ResourcePoolResult = namedlist(
    'ResourcePoolResult',
    [
        'idle',  # idle resource
        'need_open',  # resource need open
        'need_close',  # resource need close
        'need_notify',  # (future, ResourcePoolResult)
        'need_wait',  # future need wait
    ],
    default=None)


class ResourcePool:
    """A general resource pool algorithm, it's thread safe

    Params:
        future_class: a future class
        max_items_per_key (int): max items pre key
        max_items_total (int): max items total

    Note: All resource's open/close/await operations are caller's business
    """

    def __init__(self, future_class, max_items_per_key=10, max_items_total=100):
        self._closed = False
        self.future_class = future_class
        self.max_items_per_key = max_items_per_key
        self.max_items_total = max_items_total
        self._idle_resources = {}  # key: [item, ...]
        self._busy_resources = {}  # key: [item, ...]
        self._waitings = {}  # key: [promise, ...]
        # the two numbers is for better performance
        self._num_idle = 0
        self._num_total = 0
        # keep thread safe
        self._lock = RLock()

    @property
    def num_idle(self):
        """Number of idle resources"""
        return self._num_idle

    @property
    def num_busy(self):
        """Number of busy resources"""
        return self._num_total - self._num_idle

    @property
    def num_total(self):
        """Number of total resources"""
        return self._num_total

    def size(self, key):
        """Number of resources with the given key"""
        r = [self._idle_resources, self._busy_resources]
        return sum(len(x.get(key, [])) for x in r)

    def __repr__(self):
        return f'<{type(self).__name__} idle:{self.num_idle} total:{self.num_total}>'

    def put(self, *args, **kwargs):
        """Put back a resource

        Params:
            item (Resource): the resource to put back
            close (bool): close the resource or not
        Returns:
            ResourcePoolResult
        """
        with self._lock:
            return self._put(*args, **kwargs)

    def _put(self, item, close=False):
        ret = ResourcePoolResult()
        if self._closed:
            ret.need_close = item
            return ret

        self._busy_resources[item.key].remove(item)
        if not close:
            waitings = self._waitings.get(item.key)
            if waitings:
                self._busy_resources[item.key].append(item)
                # just notify a future in the fastest way
                ret.need_notify = (waitings.pop(0), ResourcePoolResult(idle=item))
                return ret
            self._idle_resources.setdefault(item.key, []).append(item)
            self._num_idle += 1
        else:
            ret.need_close = item
            self._num_total -= 1

        for key, waitings in self._waitings.items():
            if not waitings:
                continue
            need_close, need_open = self._open_new_resource_if_permit(key)
            if need_open:
                ret.need_notify = (waitings.pop(0), ResourcePoolResult(need_open=need_open))
                assert not (need_close and ret.need_close), \
                    "should't close two resource at once, it's a bug!"
                ret.need_close = need_close
                break

        return ret

    def _close_an_idle_resource(self):
        for key, idles in self._idle_resources.items():
            if idles:
                self._num_idle -= 1
                self._num_total -= 1
                return idles.pop(0)

    def _open_new_resource(self, key):
        need_open = Resource(key)
        self._busy_resources.setdefault(key, []).append(need_open)
        self._num_total += 1
        return need_open

    def _open_new_resource_if_permit(self, key):
        can_open_key = self.size(key) < self.max_items_per_key
        can_open_total = self._num_total < self.max_items_total
        can_close = self._num_idle > 0
        if can_open_key and can_open_total:
            # open new resource
            need_open = self._open_new_resource(key)
            return None, need_open
        elif can_open_key and not can_open_total and can_close:
            # close an idle resource then open new resource
            need_close = self._close_an_idle_resource()
            assert need_close and self._num_total < self.max_items_total, \
                "pool still full after close an idle resource, it's a bug!"
            need_open = self._open_new_resource(key)
            return need_close, need_open
        else:
            return None, None

    def get(self, *args, **kwargs):
        """Get a resource

        Params:
            key (hashable): resource key
        Returns:
            ResourcePoolResult
        """
        with self._lock:
            return self._get(*args, **kwargs)

    def _get(self, key):
        if self._closed:
            raise ResourcePoolClosedError('The resource pool was closed')
        ret = ResourcePoolResult()
        idles = self._idle_resources.get(key)
        if idles:
            item = idles.pop()
            self._busy_resources.setdefault(key, []).append(item)
            self._num_idle -= 1
            ret.idle = item
        else:
            need_close, need_open = self._open_new_resource_if_permit(key)
            if need_open is None:
                fut = self.future_class()
                self._waitings.setdefault(key, []).append(fut)
                ret.need_wait = fut
            else:
                ret.need_close = need_close
                ret.need_open = need_open
        return ret

    def close(self, *args, **kwargs):
        """Close resource pool

        Params:
            force (bool): close busy resources or not
        Returns:
            tuple(need_close, need_wait):
                 need_close: list of resources need close
                 need_wait: list of futures need wait
        """
        with self._lock:
            return self._close(*args, **kwargs)

    def _close(self, force=False):
        need_close = []
        need_wait = []
        self._closed = True

        for fut in chain.from_iterable(self._waitings.values()):
            need_wait.append(fut)
        self._waitings.clear()

        for item in chain.from_iterable(self._idle_resources.values()):
            need_close.append(item)
        self._idle_resources.clear()
        self._num_idle = 0

        if force:
            for item in chain.from_iterable(self._busy_resources.values()):
                need_close.append(item)
            self._busy_resources.clear()

        self._num_total = 0
        return need_close, need_wait
