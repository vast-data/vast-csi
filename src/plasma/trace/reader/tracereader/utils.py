import bisect

def merge_sort(iters, key):
    heads_and_iters = []
    for i in iters:
        try:
            head_and_iter = (next(i), i)
        except StopIteration:
            pass
        else:
            bisect.insort(heads_and_iters, head_and_iter)

    while heads_and_iters:
        try:
            value, i = heads_and_iters.pop(0)
        except IndexError:
            break
        yield value
        try:
            value = next(i)
        except StopIteration:
            pass
        else:
            bisect.insort(heads_and_iters, (value, i))
