import os

from tracereader.parser import TraceInfo, TraceHeader
from tracereader.ui import handle_path, run, Trace

test_file = os.path.join(os.path.dirname(__file__), 'PLASMA.20750.160601_085907_871.trace')

def test_handle_path():
    list(handle_path(test_file))

def test_main():
    run([test_file, test_file, test_file], verbose=True)
