import bisect

def merge_sort(iters, key=lambda x: x):
    """
    Gets a sequence of sorted iterators and returns a generator that unifies them to a single sorted stream.
    In order to sort on something other than the value itself (for example, one of its attributes), a key function can be passed.
    """
    heads_and_iters = []
    # in order to run bisect on the values we place them in tuple
    # a tuple compares elements lexicographically. when two values are the same
    # the iterators would be compared and result in a TypeError, for that reason
    # we use a tie breaker that would be different for every iterator.
    tie_breaker = 0
    for i in iters:
        if not hasattr(i, 'next'):
            i = iter(i)
        try:
            tie_breaker += 1
            head_and_iter = (next(i), tie_breaker, i)
        except StopIteration:
            pass
        else:
            bisect.insort(heads_and_iters, head_and_iter)

    while heads_and_iters:
        try:
            value, tie_breaker, i = heads_and_iters.pop(0)
        except IndexError:
            break
        yield value
        try:
            value = next(i)
        except StopIteration:
            pass
        else:
            bisect.insort(heads_and_iters, (value, tie_breaker, i))
