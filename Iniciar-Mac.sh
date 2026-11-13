#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$TASK_ROOT/.venv-mac/bin/python" ]; then
    exec "$TASK_ROOT/.venv-mac/bin/python" "$TASK_ROOT/scripts/run_gui.py" "$@"
fi
echo 'Falta .venv-mac. Sigue las instrucciones de docs/macOS.md.' >&2
exit 1
