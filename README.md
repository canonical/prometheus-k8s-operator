# Prometheus Operator

## Description

The Prometheus Operator provides a cluster monitoring solution using
[Prometheus](https://prometheus.io), which is an open source
monitoring system and alerting toolkit.

This repository contains a [Juju](https://jaas.ai/) Charm for
deploying the monitoring component of Prometheus in a Kubernetes
cluster. The alerting component of prometheus is offered through a
separate Charm.

## Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands

    sudo snap install microk8s --classic
    microk8s.enable dns storage registry dashboard
    sudo snap install juju --classic
    juju bootstrap microk8s microk8s
    juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath

## Build

Install the charmcraft tool

    sudo snap install charmcraft

Build the charm in this git repository

    charmcraft build

## Usage

Create a Juju model for your monitoring operators

    juju add-model lma

Deploy Prometheus using its default configuration.

    juju deploy ./prometheus.charm

View the Prometheus dashboard

1. Use `juju status` to determine IP of the Prometheus unit
2. Navigate to `http://<IP-Address>:9090` using your browser

If required, remove the deployed monitoring model completely

    juju destroy-model -y lma --no-wait --force --destroy-storage

## Relations

Currently supported relations are

- [Grafana](https://github.com/canonical/grafana-operator)
- [Alertmanager](https://github.com/canonical/alertmanager-operator)

## Developing

Use your existing Python 3 development environment or create and
activate a Python 3 virtualenv

    virtualenv -p python3 venv
    source venv/bin/activate

Install the development requirements

    pip install -r requirements-dev.txt

## Testing

Just run `run_tests`:

    ./run_tests
