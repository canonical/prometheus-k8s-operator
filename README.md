# Juju Charm/Operator for Prometheus on Kubernetes

## Description

[Prometheus](https://prometheus.io) is an open source monitoring
system and alterting toolkit. This repository contains a
[Charm](https://discourse.juju.is/t/charm-writing/1260) for deploying
Prometheus in Kubernetes clusters using [Juju](https://jaas.ai/).


## Usage

```
    juju deploy prometheus
```

### Scale Out Usage

...

## Developing

Create and activate a virtualenv,
and install the development requirements,

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

Just run `run_tests`:

    ./run_tests
