#!/bin/bash

tmp=$(mktemp)
git grep -n --full-name --untracked "// GDB" | python scripts/gdb_break_points.py > $tmp

echo "Running: gdb -x $tmp $@"
gdb -x $tmp $@
