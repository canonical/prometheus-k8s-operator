# Release Process

## Overview

At any given time there are three versions of the Prometheus charm
available

1. Stable - This is a well tested production ready version of the
   Charm.
2. Candidate - This is a feature ready next version of the stable
   release, currently in beta testing.
3. Edge - This is the bleeding edge developer version of the charm.

Guidelines on the creation of these versions are as follows.

1. Stable releases are done in consultation with product owner and
   engineering manager as and when the release candidate has been well
   tested and deemed ready for production.

2. Candidate releases are done when charm reaches a state of feature
   completion with respect to the next planned milestone.

3. Edge versions are released at the developers discretion. This
   process is automated in response to merge into master branch of
   Canonical GitHub repository. Note that merging to master will be
   blocked if any unit or integration fails.
