from tracereader.utils import merge_sort

def myrange(n):
    for i in range(n):
        yield i

def test_merge_sort():
    assert list(merge_sort([myrange(3), myrange(3), myrange(3)])) == [0, 0, 0, 1, 1, 1, 2, 2, 2]
