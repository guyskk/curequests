from curequests.resource_pool import ResourcePool
from curequests.future import Future

from .utils import run_with_curio


@run_with_curio
async def test_resource_pool_idle():
    pool = ResourcePool(Future, max_items_total=1)
    # get resource A
    ga1 = pool.get('A')
    assert ga1.need_open
    A = ga1.need_open
    assert pool.num_total == 1
    assert pool.num_idle == 0

    # put pack A
    pa1 = pool.put(A)
    assert not pa1.need_close
    assert not pa1.need_notify
    assert pool.num_total == 1
    assert pool.num_idle == 1

    # get A again
    ga2 = pool.get('A')
    assert ga2.idle == A
    assert pool.num_total == 1
    assert pool.num_idle == 0


@run_with_curio
async def test_resource_pool_wait_and_notify_same_key():
    pool = ResourcePool(Future, max_items_total=1)
    # open a resource
    ga1 = pool.get('A')
    assert ga1.need_open
    A = ga1.need_open
    assert pool.num_total == 1
    assert pool.num_idle == 0

    # get A again, need wait
    ga2 = pool.get('A')
    assert not ga2.idle
    assert ga2.need_wait
    assert pool.num_total == 1
    assert pool.num_idle == 0

    # put pack A
    pa1 = pool.put(A)
    assert not pa1.need_close
    assert pa1.need_notify
    fut, result = pa1.need_notify
    await fut.set_result(result)

    ga2 = await ga2.need_wait
    assert ga2.idle == A
    assert pool.num_total == 1
    assert pool.num_idle == 0


@run_with_curio
async def test_resource_pool_wait_and_notify_diff_key():
    pool = ResourcePool(Future, max_items_per_key=2, max_items_total=2)
    # open two resource
    ga1 = pool.get('A')
    assert ga1.need_open
    A = ga1.need_open
    gb1 = pool.get('B')
    assert gb1.need_open
    B = gb1.need_open

    # pool is full
    assert pool.num_busy == 2
    assert pool.num_total == 2
    assert pool.size('A') == 1
    assert pool.size('B') == 1

    # get A again, need wait
    ga2 = pool.get('A')
    assert not ga2.need_open
    assert not ga2.idle
    assert ga2.need_wait

    # put back B, should close B
    pb1 = pool.put(B)
    assert pb1.need_close == B
    assert pb1.need_notify
    fut, result = pb1.need_notify
    await fut.set_result(result)

    # open a new A
    ga2 = await ga2.need_wait
    assert not ga2.idle
    assert not ga2.need_close
    assert ga2.need_open
    assert ga2.need_open.key == 'A'
    assert ga2.need_open != A

    assert pool.num_busy == 2
    assert pool.num_total == 2
    assert pool.size('A') == 2
    assert pool.size('B') == 0


@run_with_curio
async def test_put_when_pool_closed():
    pool = ResourcePool(Future)
    ga = pool.get('A')
    pool.close()
    ret = pool.put(ga.need_open)
    assert ret.need_close


@run_with_curio
async def test_close():
    pool = ResourcePool(Future, max_items_per_key=2, max_items_total=3)
    # make an idle resource
    ga = pool.get('A')
    pool.put(ga.need_open)
    # open two new resource
    pool.get('B')
    pool.get('C')

    assert pool.num_idle == 1
    assert pool.num_total == 3

    need_close, need_wait = pool.close(force=True)
    assert len(need_close) == 3
    assert len(need_wait) == 0
