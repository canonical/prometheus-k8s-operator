# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""# KubernetesComputeResourcesPatch Library.

This library is designed to enable developers to more simply patch the Kubernetes compute resource
limits and requests created by Juju during the deployment of a charm.

When initialised, this library binds a handler to the parent charm's `config-changed` event.
The config-changed event is used because it is guaranteed to fire on startup, on upgrade and on
pod churn. Additionally, resource limits may be set by charm config options, which would also be
caught out-of-the-box by this handler. The handler applies the patch to the app's StatefulSet.
This should ensure that the resource limits are correct throughout the charm's life. Additional
optional user-provided events for re-applying the patch are supported but discouraged.

The constructor takes a reference to the parent charm, a 'limits' and a 'requests' dictionaries
that together define the resource requirements. For information regarding the `lightkube`
`ResourceRequirements` model, please visit the `lightkube`
[docs](https://gtsystem.github.io/lightkube-models/1.23/models/core_v1/#resourcerequirements).


## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`. **Note
that you also need to add `lightkube` and `lightkube-models` to your charm's `requirements.txt`.**

```shell
cd some-charm
charmcraft fetch-lib charms.observability_libs.v0.kubernetes_compute_resources_patch
cat << EOF >> requirements.txt
lightkube
lightkube-models
EOF
```

Then, to initialise the library:

```python
# ...
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    KubernetesComputeResourcesPatch,
    ResourceRequirements,
)

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.resources_patch = KubernetesComputeResourcesPatch(
        self,
        "container-name",
        resource_reqs_func=lambda: ResourceRequirements(
            limits={"cpu": "2"}, requests={"cpu": "1"}
        ),
    )
    self.framework.observe(self.resources_patch.on.patch_failed, self._on_resource_patch_failed)

  def _on_resource_patch_failed(self, event):
    self.unit.status = BlockedStatus(event.message)
    # ...
```

Or, if, for example, the resource specs are coming from config options:

```python
class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.resources_patch = KubernetesComputeResourcesPatch(
        self,
        "container-name",
        resource_reqs_func=self._resource_spec_from_config,
    )

  def _resource_spec_from_config(self) -> ResourceRequirements:
    spec = {"cpu": self.model.config.get("cpu"), "memory": self.model.config.get("memory")}
    return ResourceRequirements(limits=spec, requests=spec)
```

If you wish to pull the state of the resources patch operation and set the charm unit status based on that patch result,
you can achieve that using `get_status()` function.
```python
class SomeCharm(CharmBase):
    def __init__(self, *args):
        #...
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
    #...
    def _on_collect_unit_status(self, event: CollectStatusEvent):
        event.add_status(self.resources_patch.get_status())
```

Additionally, you may wish to use mocks in your charm's unit testing to ensure that the library
does not try to make any API calls, or open any files during testing that are unlikely to be
present, and could break your tests. The easiest way to do this is during your test `setUp`:

```python
# ...
from ops import ActiveStatus

@patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _is_patched=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
    get_status=lambda _: ActiveStatus(),
)
@patch("lightkube.core.client.GenericSyncClient")
def setUp(self, *unused):
    self.harness = Harness(SomeCharm)
    # ...
```

References:
- https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- https://gtsystem.github.io/lightkube-models/1.23/models/core_v1/#resourcerequirements
"""

import decimal
import logging
from decimal import Decimal
from math import ceil, floor
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import tenacity
from lightkube import ApiError, Client  # pyright: ignore
from lightkube.core import exceptions
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    PodSpec,
    PodTemplateSpec,
    ResourceRequirements,
)
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType
from lightkube.utils.quantity import equals_canonically, parse_quantity
from ops import ActiveStatus, BlockedStatus, WaitingStatus
from ops.charm import CharmBase
from ops.framework import BoundEvent, EventBase, EventSource, Object, ObjectEvents
from ops.model import StatusBase

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "2a6066f701444e8db44ba2f6af28da90"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 8


_Decimal = Union[Decimal, float, str, int]  # types that are potentially convertible to Decimal


def adjust_resource_requirements(
    limits: Optional[Dict[Any, Any]],
    requests: Optional[Dict[Any, Any]],
    adhere_to_requests: bool = True,
) -> ResourceRequirements:
    """Adjust resource limits so that `limits` and `requests` are consistent with each other.

    Args:
        limits: the "limits" portion of the resource spec.
        requests: the "requests" portion of the resource spec.
        adhere_to_requests: a flag indicating which portion should be adjusted when "limits" is
         lower than "requests":
         - if True, "limits" will be adjusted to max(limits, requests).
         - if False, "requests" will be adjusted to min(limits, requests).

    Returns:
        An adjusted (limits, requests) 2-tuple.

    >>> adjust_resource_requirements({}, {})
    ResourceRequirements(claims=None, limits={}, requests={})
    >>> adjust_resource_requirements({"cpu": "1"}, {})
    ResourceRequirements(claims=None, limits={'cpu': '1'}, requests={'cpu': '1'})
    >>> adjust_resource_requirements({"cpu": "1"}, {"cpu": "2"}, True)
    ResourceRequirements(claims=None, limits={'cpu': '2'}, requests={'cpu': '2'})
    >>> adjust_resource_requirements({"cpu": "1"}, {"cpu": "2"}, False)
    ResourceRequirements(claims=None, limits={'cpu': '1'}, requests={'cpu': '1'})
    >>> adjust_resource_requirements({"cpu": "1"}, {"memory": "1G"}, True)
    ResourceRequirements(claims=None, limits={'cpu': '1'}, requests={'memory': '1G', 'cpu': '1'})
    >>> adjust_resource_requirements({"cpu": "1"}, {"memory": "1G"}, False)
    ResourceRequirements(claims=None, limits={'cpu': '1'}, requests={'memory': '1G', 'cpu': '1'})
    >>> adjust_resource_requirements({"cpu": "1", "memory": "1"}, {"memory": "2"}, True)
    ResourceRequirements(\
claims=None, limits={'cpu': '1', 'memory': '2'}, requests={'memory': '2', 'cpu': '1'})
    >>> adjust_resource_requirements({"cpu": "1", "memory": "1"}, {"memory": "1G"}, False)
    ResourceRequirements(\
claims=None, limits={'cpu': '1', 'memory': '1'}, requests={'memory': '1', 'cpu': '1'})
    >>> adjust_resource_requirements({"custom-resource": "1"}, {"custom-resource": "2"}, False)
    Traceback (most recent call last):
      ...
    ValueError: Invalid limits spec: {'custom-resource': '1'}
    """
    if not is_valid_spec(limits):
        raise ValueError("Invalid limits spec: {}".format(limits))
    if not is_valid_spec(requests):
        raise ValueError("Invalid default requests spec: {}".format(requests))

    limits = sanitize_resource_spec_dict(limits) or {}
    requests = sanitize_resource_spec_dict(requests) or {}

    # Make sure we do not modify in-place
    limits, requests = limits.copy(), requests.copy()

    # Need to copy key-val pairs from "limits" to "requests", if they are not present in
    # "requests". This replicates K8s behavior:
    # https://kubernetes.io/docs/concepts/configuration/manage-resources-containers
    requests.update({k: limits[k] for k in limits if k not in requests})

    if adhere_to_requests:
        # Keep limits fixed when `limits` is too low
        adjusted, fixed = limits, requests
        func = max
    else:
        # Pull down requests when limit is too low
        fixed, adjusted = limits, requests
        func = min

    # adjusted = {}
    for k in adjusted:
        if k not in fixed:
            # The resource constraint is present in the "adjusted" dict but not in the "fixed"
            # dict. Keep the "adjusted" value as is
            continue

        adjusted_value = func(parse_quantity(fixed[k]), parse_quantity(adjusted[k]))  # type: ignore[type-var]
        adjusted[k] = (
            str(adjusted_value.quantize(decimal.Decimal("0.001"), rounding=decimal.ROUND_UP))  # type: ignore[union-attr]
            .rstrip("0")
            .rstrip(".")
        )

    return (
        ResourceRequirements(limits=adjusted, requests=fixed)
        if adhere_to_requests
        else ResourceRequirements(limits=fixed, requests=adjusted)
    )


def is_valid_spec(spec: Optional[dict], debug=False) -> bool:  # noqa: C901
    """Check if the spec dict is valid.

    TODO: generally, the keys can be anything, not just cpu and memory. Perhaps user could pass
     list of custom allowed keys in addition to the K8s ones?
    """
    if spec is None:
        return True
    if not isinstance(spec, dict):
        if debug:
            logger.error("Invalid resource spec type '%s': must be either None or dict.", spec)
        return False

    for k, v in spec.items():
        valid_keys = ["cpu", "memory"]  # K8s permits custom keys, but we limit here to what we use
        if k not in valid_keys:
            if debug:
                logger.error("Invalid key in resource spec: %s; valid keys: %s.", k, valid_keys)
            return False
        try:
            assert isinstance(v, (str, type(None)))  # for type checker
            pv = parse_quantity(v)
        except ValueError:
            if debug:
                logger.error("Invalid resource spec entry: {%s: %s}.", k, v)
            return False

        if pv and pv < 0:
            if debug:
                logger.error("Invalid resource spec entry: {%s: %s}; must be non-negative.", k, v)
            return False

    return True


def sanitize_resource_spec_dict(spec: Optional[dict]) -> Optional[dict]:
    """Fix spec values without altering semantics.

    The purpose of this helper function is to correct known issues.
    This function is not intended for fixing user mistakes such as incorrect keys present; that is
    left for the `is_valid_spec` function.
    """
    if not spec:
        return spec

    d = spec.copy()

    for k, v in spec.items():
        if not v:
            # Need to ignore empty values input, otherwise the StatefulSet will have "0" as the
            # setpoint, the pod will not be scheduled and the charm would be stuck in unknown/lost.
            # This slightly changes the spec semantics compared to lightkube/k8s: a setpoint of
            # `None` would be interpreted here as "no limit".
            del d[k]

    # Round up memory to whole bytes. This is need to avoid K8s errors such as:
    # fractional byte value "858993459200m" (0.8Gi) is invalid, must be an integer
    memory = d.get("memory")
    if memory:
        as_decimal = parse_quantity(memory)
        if as_decimal and as_decimal.remainder_near(floor(as_decimal)):
            d["memory"] = str(ceil(as_decimal))
    return d


def _retry_on_condition(exception):
    """Retry if the exception is an ApiError with a status code != 403.

    Returns: a boolean value to indicate whether to retry or not.
    """
    if isinstance(exception, ApiError) and str(exception.status.code) != "403":
        return True
    if isinstance(exception, exceptions.ConfigError) or isinstance(exception, ValueError):
        return True
    return False


class K8sResourcePatchFailedEvent(EventBase):
    """Emitted when patching fails."""

    def __init__(self, handle, message=None):
        super().__init__(handle)
        self.message = message

    def snapshot(self) -> Dict:
        """Save grafana source information."""
        return {"message": self.message}

    def restore(self, snapshot):
        """Restore grafana source information."""
        self.message = snapshot["message"]


class K8sResourcePatchEvents(ObjectEvents):
    """Events raised by :class:`K8sResourcePatchEvents`."""

    patch_failed = EventSource(K8sResourcePatchFailedEvent)


class ContainerNotFoundError(ValueError):
    """Raised when a given container does not exist in the list of containers."""


class ResourcePatcher:
    """Helper class for patching a container's resource limits in a given StatefulSet."""

    def __init__(self, namespace: str, statefulset_name: str, container_name: str):
        self.namespace = namespace
        self.statefulset_name = statefulset_name
        self.container_name = container_name
        self.client = Client()  # pyright: ignore

    def _patched_delta(self, resource_reqs: ResourceRequirements) -> StatefulSet:
        statefulset = self.client.get(
            StatefulSet, name=self.statefulset_name, namespace=self.namespace
        )

        return StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[attr-defined]
                serviceName=statefulset.spec.serviceName,  # type: ignore[attr-defined]
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[Container(name=self.container_name, resources=resource_reqs)]
                    )
                ),
            )
        )

    @classmethod
    def _get_container(cls, container_name: str, containers: List[Container]) -> Container:
        """Find our container from the container list, assuming list is unique by name.

        Typically, *.spec.containers[0] is the charm container, and [1] is the (only) workload.

        Raises:
            ContainerNotFoundError, if the user-provided container name does not exist in the list.

        Returns:
            An instance of :class:`Container` whose name matches the given name.
        """
        try:
            return next(iter(filter(lambda ctr: ctr.name == container_name, containers)))
        except StopIteration:
            raise ContainerNotFoundError(f"Container '{container_name}' not found")

    def is_patched(self, resource_reqs: ResourceRequirements) -> bool:
        """Reports if the resource patch has been applied to the StatefulSet.

        Returns:
            bool: A boolean indicating if the service patch has been applied.
        """
        return equals_canonically(self.get_templated(), resource_reqs)  # pyright: ignore

    def get_templated(self) -> Optional[ResourceRequirements]:
        """Returns the resource limits specified in the StatefulSet template."""
        statefulset = self.client.get(
            StatefulSet, name=self.statefulset_name, namespace=self.namespace
        )
        podspec_tpl = self._get_container(
            self.container_name,
            statefulset.spec.template.spec.containers,  # type: ignore[attr-defined]
        )
        return podspec_tpl.resources

    def get_actual(self, pod_name: str) -> Optional[ResourceRequirements]:
        """Return the resource limits that are in effect for the container in the given pod."""
        pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        podspec = self._get_container(
            self.container_name, pod.spec.containers  # type: ignore[attr-defined]
        )
        return podspec.resources

    def is_failed(
        self, resource_reqs_func: Callable[[], ResourceRequirements]
    ) -> Tuple[bool, str]:
        """Returns a tuple indicating whether a patch operation has failed along with a failure message.

        Implementation is based on dry running the patch operation to catch if there would be failures (e.g: Wrong spec and Auth errors).
        """
        try:
            resource_reqs = resource_reqs_func()
            limits = resource_reqs.limits
            requests = resource_reqs.requests
        except ValueError as e:
            msg = f"Failed obtaining resource limit spec: {e}"
            logger.error(msg)
            return True, msg

        # Dry run does not catch negative values for resource requests and limits.
        if not is_valid_spec(limits) or not is_valid_spec(requests):
            msg = f"Invalid resource requirements specs: {limits}, {requests}"
            logger.error(msg)
            return True, msg

        resource_reqs = ResourceRequirements(
            limits=sanitize_resource_spec_dict(limits),  # type: ignore[arg-type]
            requests=sanitize_resource_spec_dict(requests),  # type: ignore[arg-type]
        )

        try:
            self.apply(resource_reqs, dry_run=True)
        except ApiError as e:
            if e.status.code == 403:
                msg = f"Kubernetes resources patch failed: `juju trust` this application. {e}"
            else:
                msg = f"Kubernetes resources patch failed: {e}"
            return True, msg
        except ValueError as e:
            msg = f"Kubernetes resources patch failed: {e}"
            return True, msg

        return False, ""

    def is_in_progress(self) -> bool:
        """Returns a boolean to indicate whether a patch operation is in progress.

        Implementation follows a similar approach to `kubectl rollout status statefulset` to track the progress of a rollout.
        Reference: https://github.com/kubernetes/kubectl/blob/kubernetes-1.31.0/pkg/polymorphichelpers/rollout_status.go
        """
        try:
            sts = self.client.get(
                StatefulSet, name=self.statefulset_name, namespace=self.namespace
            )
        except (ValueError, ApiError) as e:
            # Assumption: if there was a persistent issue, it'd have been caught in `is_failed`
            # Wait until next run to try again.
            logger.error(f"Failed to fetch statefulset from K8s api: {e}")
            return False

        if sts.status is None or sts.spec is None:
            logger.debug("status/spec are not yet available")
            return False
        if sts.status.observedGeneration == 0 or (
            sts.metadata
            and sts.status.observedGeneration
            and sts.metadata.generation
            and sts.metadata.generation > sts.status.observedGeneration
        ):
            logger.debug("waiting for statefulset spec update to be observed...")
            return True
        if (
            sts.spec.replicas is not None
            and sts.status.readyReplicas is not None
            and sts.status.readyReplicas < sts.spec.replicas
        ):
            logger.debug(
                f"Waiting for {sts.spec.replicas-sts.status.readyReplicas} pods to be ready..."
            )
            return True

        if (
            sts.spec.updateStrategy
            and sts.spec.updateStrategy.type == "rollingUpdate"
            and sts.spec.updateStrategy.rollingUpdate is not None
        ):
            if (
                sts.spec.replicas is not None
                and sts.spec.updateStrategy.rollingUpdate.partition is not None
            ):
                if sts.status.updatedReplicas and sts.status.updatedReplicas < (
                    sts.spec.replicas - sts.spec.updateStrategy.rollingUpdate.partition
                ):
                    logger.debug(
                        f"Waiting for partitioned roll out to finish: {sts.status.updatedReplicas} out of {sts.spec.replicas - sts.spec.updateStrategy.rollingUpdate.partition} new pods have been updated..."
                    )
                    return True
            logger.debug(
                f"partitioned roll out complete: {sts.status.updatedReplicas} new pods have been updated..."
            )
            return False

        if sts.status.updateRevision != sts.status.currentRevision:
            logger.debug(
                f"waiting for statefulset rolling update to complete {sts.status.updatedReplicas} pods at revision {sts.status.updateRevision}..."
            )
            return True

        logger.debug(
            f"statefulset rolling update complete pods at revision {sts.status.currentRevision}"
        )
        return False

    def is_ready(self, pod_name, resource_reqs: ResourceRequirements):
        """Reports if the resource patch has been applied and is in effect.

        Returns:
            bool: A boolean indicating if the service patch has been applied and is in effect.
        """
        return self.is_patched(resource_reqs) and equals_canonically(  # pyright: ignore
            resource_reqs, self.get_actual(pod_name)  # pyright: ignore
        )

    def apply(self, resource_reqs: ResourceRequirements, dry_run=False) -> None:
        """Patch the Kubernetes resources created by Juju to limit cpu or mem."""
        # Need to ignore invalid input, otherwise the StatefulSet gives "FailedCreate" and the
        # charm would be stuck in unknown/lost.
        if not dry_run and self.is_patched(resource_reqs):
            logger.debug(f"Resource requests are already patched: {resource_reqs}")
            return

        self.client.patch(
            StatefulSet,
            self.statefulset_name,
            self._patched_delta(resource_reqs),
            namespace=self.namespace,
            patch_type=PatchType.APPLY,
            field_manager=self.__class__.__name__,
            dry_run=dry_run,
        )


class KubernetesComputeResourcesPatch(Object):
    """A utility for patching the Kubernetes compute resources set up by Juju."""

    on = K8sResourcePatchEvents()  # pyright: ignore
    PATCH_RETRY_STOP = tenacity.stop_after_delay(20)
    PATCH_RETRY_WAIT = tenacity.wait_fixed(5)
    PATCH_RETRY_IF = tenacity.retry_if_exception(_retry_on_condition)

    def __init__(
        self,
        charm: CharmBase,
        container_name: str,
        *,
        resource_reqs_func: Callable[[], ResourceRequirements],
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ):
        """Constructor for KubernetesComputeResourcesPatch.

        References:
            - https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/

        Args:
            charm: the charm that is instantiating the library.
            container_name: the container for which to apply the resource limits.
            resource_reqs_func: a callable returning a `ResourceRequirements`; if raises, should
              only raise ValueError.
            refresh_event: an optional bound event or list of bound events which
                will be observed to re-apply the patch.
        """
        super().__init__(charm, "{}_{}".format(self.__class__.__name__, container_name))
        self._charm = charm
        self._container_name = container_name
        self.resource_reqs_func = resource_reqs_func
        self.patcher = ResourcePatcher(self._namespace, self._app, container_name)

        # Ensure this patch is applied during the 'config-changed' event, which is emitted every
        # startup and every upgrade. The config-changed event is a good time to apply this kind of
        # patch because it is always emitted after storage-attached, leadership and peer-created,
        # all of which only fire after install. Patching the statefulset prematurely could result
        # in those events firing without a workload.
        self.framework.observe(charm.on.config_changed, self._on_config_changed)

        if not refresh_event:
            refresh_event = []
        elif not isinstance(refresh_event, list):
            refresh_event = [refresh_event]
        for ev in refresh_event:
            self.framework.observe(ev, self._on_config_changed)

    def _on_config_changed(self, _):
        self._patch()

    def _patch(self) -> None:
        """Patch the Kubernetes resources created by Juju to limit cpu or mem.

        This method will keep on retrying to patch the kubernetes resource for a default duration of 20 seconds
        if the patching failure is due to a recoverable error (e.g: Network Latency).
        """
        try:
            resource_reqs = self.resource_reqs_func()
            limits = resource_reqs.limits
            requests = resource_reqs.requests
        except ValueError as e:
            msg = f"Failed obtaining resource limit spec: {e}"
            logger.error(msg)
            self.on.patch_failed.emit(message=msg)
            return

        for spec in (limits, requests):
            if not is_valid_spec(spec):
                msg = f"Invalid resource limit spec: {spec}"
                logger.error(msg)
                self.on.patch_failed.emit(message=msg)
                return

        resource_reqs = ResourceRequirements(
            limits=sanitize_resource_spec_dict(limits),  # type: ignore[arg-type]
            requests=sanitize_resource_spec_dict(requests),  # type: ignore[arg-type]
        )

        try:
            for attempt in tenacity.Retrying(
                retry=self.PATCH_RETRY_IF,
                stop=self.PATCH_RETRY_STOP,
                wait=self.PATCH_RETRY_WAIT,
                # if you don't succeed raise the last caught exception when you're done
                reraise=True,
            ):
                with attempt:
                    logger.debug(
                        f"attempt #{attempt.retry_state.attempt_number} to patch resource limits"
                    )
                    self.patcher.apply(resource_reqs)

        except exceptions.ConfigError as e:
            msg = f"Error creating k8s client: {e}"
            logger.error(msg)
            self.on.patch_failed.emit(message=msg)
            return

        except ApiError as e:
            if e.status.code == 403:
                msg = f"Kubernetes resources patch failed: `juju trust` this application. {e}"

            else:
                msg = f"Kubernetes resources patch failed: {e}"

            logger.error(msg)
            self.on.patch_failed.emit(message=msg)

        except ValueError as e:
            msg = f"Kubernetes resources patch failed: {e}"
            logger.error(msg)
            self.on.patch_failed.emit(message=msg)

        else:
            logger.info(
                "Kubernetes resources for app '%s', container '%s' patched successfully: %s",
                self._app,
                self._container_name,
                resource_reqs,
            )

    def is_ready(self) -> bool:
        """Reports if the resource patch has been applied and is in effect.

        Returns:
            bool: A boolean indicating if the service patch has been applied and is in effect.
        """
        try:
            resource_reqs = self.resource_reqs_func()
            limits = resource_reqs.limits
            requests = resource_reqs.requests
        except ValueError as e:
            msg = f"Failed obtaining resource limit spec: {e}"
            logger.error(msg)
            return False

        if not is_valid_spec(limits) or not is_valid_spec(requests):
            logger.error("Invalid resource requirements specs: %s, %s", limits, requests)
            return False

        resource_reqs = ResourceRequirements(
            limits=sanitize_resource_spec_dict(limits),  # type: ignore[arg-type]
            requests=sanitize_resource_spec_dict(requests),  # type: ignore[arg-type]
        )

        try:
            return self.patcher.is_ready(self._pod, resource_reqs)
        except (ValueError, ApiError) as e:
            msg = f"Failed to apply resource limit patch: {e}"
            logger.error(msg)
            self.on.patch_failed.emit(message=msg)
            return False

    def get_status(self) -> StatusBase:
        """Return the status of patching the resource limits in a `StatusBase` format.

        Returns:
            StatusBase: There is a 1:1 mapping between the state of the patching operation and a `StatusBase` value that the charm can be set to.
        Possible values are:
            - ActiveStatus: The patch was applied successfully.
            - BlockedStatus: The patch failed and requires a human intervention.
            - WaitingStatus: The patch is still in progress.

        Example:
            - ActiveStatus("Patch applied successfully")
            - BlockedStatus("Failed due to missing permissions")
            - WaitingStatus("Patch is in progress")
        """
        failed, msg = self.patcher.is_failed(self.resource_reqs_func)
        if failed:
            return BlockedStatus(msg)
        if self.patcher.is_in_progress():
            return WaitingStatus("waiting for resources patch to apply")
        # patch successful or nothing has been patched yet
        return ActiveStatus()

    @property
    def _app(self) -> str:
        """Name of the current Juju application.

        Returns:
            str: A string containing the name of the current Juju application.
        """
        return self._charm.app.name

    @property
    def _pod(self) -> str:
        """Name of the unit's pod.

        Returns:
            str: A string containing the name of the current unit's pod.
        """
        return "-".join(self._charm.unit.name.rsplit("/", 1))

    @property
    def _namespace(self) -> str:
        """The Kubernetes namespace we're running in.

        If a charm is deployed into the controller model (which certainly could happen as we move
        to representing the controller as a charm) then self._charm.model.name !== k8s namespace.
        Instead, the model name is controller in Juju and controller-<controller-name> for the
        namespace in K8s.

        Returns:
            str: A string containing the name of the current Kubernetes namespace.
        """
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
            return f.read().strip()
