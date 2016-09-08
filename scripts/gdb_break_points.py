#!/usr/bin/python

import sys

bps = {}

for l in sys.stdin:
    name, pos = l.strip().split(':')[:2]
    pos = int(pos)
    cmd = 'GDB'.join(l.strip().split('GDB')[1:]).strip()
    cmds = bps.pop((name, pos-1), [])
    cmds.append(cmd)
    bps[(name, pos)] = cmds

print '''
set $_exitcode = -999
set breakpoint pending on

'''

for (name, pos), cmds in bps.iteritems():
    print '''
break {}:{}
commands
    {}
end'''.format(name, pos+1, '\n    '.join(cmds))

print '''
run

if $_exitcode != -999
  quit
end
'''
