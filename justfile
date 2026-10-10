default:
    @just --list

# Validate openapi.yaml as an OpenAPI document
validate:
    uvx openapi-spec-validator openapi.yaml

# Validate a running add-on against the protocol
[positional-arguments]
conformance url *args:
    uv run conformance/run.py "$@"

# Check the conformance runner against the fake add-on
selftest:
    bash conformance/selftest.sh

# All offline checks
test: validate selftest
