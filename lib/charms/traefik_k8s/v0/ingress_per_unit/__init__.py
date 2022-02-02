# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Interface Library for ingress_per_unit

This library wraps relation endpoints using the `ingress_per_unit` interface
and provides a Python API for both requesting and providing per-unit
ingress.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`. **Note
that you also need to add the `sborl` dependency to your charm's `requirements.txt`.**

```shell
cd some-charm
charmcraft fetch-lib charms.traefik-k8s.v0.ingress_per_unit
echo "sborl" >> requirements.txt
```

Then, to initialise the library:

```python
# ...
from charms.traefik-k8s.v0.ingress_per_unit import IngressUnitRequirer

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress_per_unit = IngressPerUnitRequirer(self, port=80)
    self.framework.observe(self.ingress_per_unit.on.ready, self._handle_ingress_per_unit)
    # ...

    def _handle_ingress_per_unit(self, event):
        log.info("This unit's ingress URL: %s", self.ingress_per_unit.url)
```
"""

# The unique Charmhub library identifier, never change it
LIBID = ""  # can't register a library until the charm is in the store 9_9

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

from . import testing

# flake8: noqa: E401,E402
from .provides import IngressPerUnitProvider
from .requires import IngressPerUnitRequirer
