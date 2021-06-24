# Release Process

## Overview

At any given time there are three revisions of the Prometheus charm [available on CharmHub.io](https://charmhub.io/prometheus-k8s), for each of the following channels:

1. `latest/stable` is a well tested production ready version of the Charm.
2. `latest/candidate` is a feature ready next version of the stable release, currently in testing.
3. `latest/edge` is the bleeding edge developer version of the charm. While we really try not to, it may break and introduce regressions.

Currently, the Prometheus charm does not make use of the `latest/beta` channel.
For more information about CharmHub channels, refer to the [Juju charm store](https://discourse.charmhub.io/t/the-juju-charm-store) documentation.

## When to create which revisions

* **Stable revisions** are done in consultation with product manager and engineering manager when the `candidate` revision has been well tested and is deemed ready for production.
* **Candidate revisions** are done when the charm reaches a state of feature completion with respect to the next planned `stable` release.
* **Edge revisions** are released at the developers discretion, potentially every time something is merged into `main` and the unit tests pass.

## How to publish revisions

Refer to the [Publish your operator in Charmhub](https://discourse.charmhub.io/t/publish-your-operator-in-charmhub) documentation.
After a `latest/stable` release, it is expected that the version of the charm is the same as the one in `latest/candidate`, and those two channels will diverge again when we are ramping up through `latest/candidate` releases for a new `latest/stable` release.

## A note on granularity of revisions

We believe in shipping often and with confidence.
It is perfectly acceptable to have a new `latest/stable` release containing just one bug fix or a small new feature with respect to the last one.
