# Architecture decision log

## 2022-09-13 Use stored state for keeping track of config hash

In the context of preventing unnecessary reloads
([#352](https://github.com/canonical/prometheus-k8s-operator/pull/352)), facing the concerns
outlined in the table below, we decided for using stored state for keeping track of the config
hash.

Note that the charm's storage backend is the charm (`use_juju_for_storage` is not set), so files
will be written if the pod churns (which is good, probably unlike if the storage backend was the
controller).


|                | StoredState            | Pull                                                         |
|----------------|------------------------|--------------------------------------------------------------|
| Multiple files | Easy to calculate hash | Need to pull (and sort?) all data (config, certs AND alerts) |
| Tinkering      | Manual changes persist | Manual changes disappear every _configure                    |
| Robustness     | Only push              | Pull (multiple files) then push                              |
