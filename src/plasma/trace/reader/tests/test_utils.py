from tracereader.utils import merge_sort

def myrange(n):
    for i in range(n):
        yield i

def test_merge_sort():
    assert list(merge_sort([myrange(3), myrange(3), myrange(3)])) == [0, 0, 0, 1, 1, 1, 2, 2, 2]

    assert list(merge_sort([[{'key': 2}, {'key': 3}, {'key': 4}],
                            [{'key': 1}, {'key': 3}]], key=lambda x: x['key'])) == [{'key': 1}, {'key': 2}, {'key': 3}, {'key': 3}, {'key': 4}]
