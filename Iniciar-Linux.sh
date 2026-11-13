#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$TASK_ROOT/.venv-linux/bin/python" ]; then
    exec "$TASK_ROOT/.venv-linux/bin/python" "$TASK_ROOT/scripts/run_gui.py" "$@"
fi
if [ -x "$TASK_ROOT/.venv/bin/python" ]; then
    exec "$TASK_ROOT/.venv/bin/python" "$TASK_ROOT/scripts/run_gui.py" "$@"
fi
exec python3 "$TASK_ROOT/scripts/run_gui.py" "$@"
