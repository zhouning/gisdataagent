#!/bin/sh
set -eu

if [ "${1:-}" = "--smoke" ]; then
    run_dir="${LISFLOOD_SMOKE_RUN_DIR:-/tmp/lisflood-smoke}"
    rm -rf "$run_dir"
    mkdir -p "$run_dir"
    cp /opt/lisflood/validation/lisflood_synthetic.* "$run_dir/"
    cd "$run_dir"
    /opt/lisflood/bin/lisflood -v lisflood_synthetic.par
    test -s lisflood_synthetic.mass
    test -s lisflood_synthetic.max
    printf '%s\n' "LISFLOOD-FP smoke completed: $run_dir"
    exit 0
fi

exec /opt/lisflood/bin/lisflood "$@"
