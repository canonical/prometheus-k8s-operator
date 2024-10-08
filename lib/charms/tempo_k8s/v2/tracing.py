#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This charm library has been transferred to the HA version of this charm.

The new owner is the `tempo-coordinator-k8s` charm:
- [github](https://github.com/canonical/tempo-coordinator-k8s/)
- [charmhub](https://charmhub.io/tempo-coordinator-k8s/)

The new library (with its major version reset to 0) can be found at

https://charmhub.io/tempo-coordinator-k8s/libraries/tracing

to install it:

> charmcraft fetch-lib charms.tempo_coordinator_k8s.v0.tracing

The API is unchanged, so you can search and replace the path to swap the old lib with the new one.
"""

LIBID = "12977e9aa0b34367903d8afeb8c3d85d"
LIBAPI = 2
LIBPATCH = 11

raise DeprecationWarning(
    "this charm lib is deprecated; please use charms.tempo_coordinator_k8s.v0.tracing instead. "
    "see https://charmhub.io/tempo-coordinator-k8s/libraries/tracing"
)
