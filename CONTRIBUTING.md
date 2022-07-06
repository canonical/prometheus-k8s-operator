# Contributing / Hacking

## Intended use case

The charm in this repository is a fork of the 
[prometheus-k8s-operator](https://github.com/canonical/prometheus-k8s-operator). In addition 
to the bare Prometheus, this charm includes prometheus-configurer container providing an HTTP API 
for managing alerting rules. API documentation is available in
[github](https://github.com/facebookarchive/prometheus-configmanager/blob/main/prometheus/docs/swagger-v1.yml).

## Code contributions
If you want to propose a new feature, a bug fix or a documentation improvement:
- Create a new branch from main.
- Commit and push your changes to this branch.
- Validate that all Github actions pass.
- Create a pull request in 
[github](https://github.com/canonical/charmed-magma-prometheus-operator/pulls).
- Your pull request will be reviewed by one of the repository maintainers.

## Continuous Integration
On each code push and pull request made in Github, a series of validations are triggered through
Github actions:
- Linting validation
- Static analysis
- Unit tests
- Integration tests

All of them must pass for a change to be reviewed.
