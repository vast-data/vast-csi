import os

from tracereader.parser import TraceInfo, TraceHeader
from tracereader.ui import handle_path, run, Trace

test_file = os.path.join(os.path.dirname(__file__), 'PLASMA.20750.160601_085907_871.trace')

def test_handle_path():
    traces = [Trace(info=TraceInfo(format='Silo started. Affinity set to: %d.',
                                   file='build/src/plasma/execution/p_silo.c',
                                   func='silo_main',
                                   line=114),
                    header=TraceHeader(time=1464785947870537000,
                                       job_id=0,
                                       info_index=0,
                                       severity=2),
                    params=[-1],
                    component='PLASMA',
                    tid='20750'),
              Trace(info=TraceInfo(format='Starting module: %s.',
                                   file='build/src/plasma/execution/p_silo.c',
                                   func='silo_start_in_fiber', line=90),
                    header=TraceHeader(time=1464785947871350580,
                                       job_id=2, info_index=2, severity=2),
                    params=['MODULE_P'], component='PLASMA', tid='20750'),
              Trace(info=TraceInfo(format='Starting module: %s.',
                                   file='build/src/plasma/execution/p_silo.c',
                                   func='silo_start_in_fiber',
                                   line=90),
                    header=TraceHeader(time=1464785947871351433,
                                       job_id=2,
                                       info_index=2,
                                       severity=2),
                    params=['MODULE_I'],
                    component='PLASMA',
                    tid='20750'),
              Trace(info=TraceInfo(format='Silo finished.',
                                   file='build/src/plasma/execution/p_silo.c',
                                   func='silo_main',
                                   line=122),
                    header=TraceHeader(time=1464785947871497021,
                                       job_id=0,
                                       info_index=1,
                                       severity=2),
                    params=[],
                    component='PLASMA',
                    tid='20750')]
    assert list(handle_path(test_file)) == traces

def test_run():
    run([test_file, test_file, test_file])
