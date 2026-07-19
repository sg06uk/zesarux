#!/usr/bin/env bash
# run-sieve.sh -- compatibility shim. The demos now run via run-demo.sh; this
# keeps the old command working:  ./run-sieve.sh [--headless]  ==  run-demo.sh sieve
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-demo.sh" sieve "$@"
