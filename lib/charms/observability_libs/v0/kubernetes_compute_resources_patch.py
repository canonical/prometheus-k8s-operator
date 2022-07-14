# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""# KubernetesComputeResourcesPatch Library.

This library is designed to enable developers to more simply patch the Kubernetes compute resource
limits and requests created by Juju during the deployment of a sidecar charm.

When initialised, this library binds a handler to the parent charm's `config-changed` event, which
applies the patch to the cluster. This should ensure that the resource limits are correct
throughout the charm's life. Additional optional user-provided events for re-applying the patch are
supported but discouraged.

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
    KubernetesComputeResourcesPatch
)

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.resources_patch = KubernetesComputeResourcesPatch(
        self,
        "container-name",
        limits={"cpu": "1", "mem": "2Gi"},
        requests={"cpu": "1", "mem": "2Gi"}
    )
    # ...
```

Additionally, you may wish to use mocks in your charm's unit testing to ensure that the library
does not try to make any API calls, or open any files during testing that are unlikely to be
present, and could break your tests. The easiest way to do this is during your test `setUp`:

```python
# ...

@patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _is_patched=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)
@patch("lightkube.core.client.GenericSyncClient")
def setUp(self, *unused):
    self.harness = Harness(SomeCharm)
    # ...
```
"""

import logging
from types import MethodType
from typing import Dict, List, Optional, TypedDict, Union

from lightkube import ApiError, Client
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
from lightkube.utils.quantity import equals_canonically
from ops.charm import CharmBase
from ops.framework import BoundEvent, EventBase, EventSource, Object, ObjectEvents

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "2a6066f701444e8db44ba2f6af28da90"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


class ResourceSpecDict(TypedDict, total=False):
    """A dict representing a K8s resource limit.

    See:
    - https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
    - https://gtsystem.github.io/lightkube-models/1.23/models/core_v1/#resourcerequirements
    """

    cpu: Optional[str]
    memory: Optional[str]


def sanitize_resource_spec_dict(dct: Optional[ResourceSpecDict]) -> Optional[ResourceSpecDict]:
    """Make sure only recognized keys are present, and drop all keys whose value is empty."""
    if not dct:
        return dct

    d = dct.copy()
    if any(k not in ResourceSpecDict.__annotations__.keys() for k in d.keys()):
        raise ValueError(
            "Invalid resource limits dict: must have keys {}".format(
                ", ".join(ResourceSpecDict.__annotations__.keys())
            )
        )
    for k, v in dct.items():
        if v == "" or v is None:
            # Remove key, otherwise it will be serialized as 0 and pod won't be scheduled.
            del d[k]  # type: ignore

    # fractional byte value "858993459200m" (0.8Gi) is invalid, must be an integer
    # FIXME: round up memory two whole bytes
    return d


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


class KubernetesComputeResourcesPatch(Object):
    """A utility for patching the Kubernetes compute resources set up by Juju."""

    on = K8sResourcePatchEvents()

    def __init__(
        self,
        charm: CharmBase,
        container_name: str,
        *,
        limits: Optional[ResourceSpecDict],
        requests: Optional[ResourceSpecDict],
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ):
        """Constructor for KubernetesComputeResourcesPatch.

        References:
            - https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/

        Args:
            charm: the charm that is instantiating the library.
            container_name: the container for which to apply the resource limits.
            limits: a dictionary for `limits` resources.
            requests: a dictionary for `requests` resources.
            refresh_event: an optional bound event or list of bound events which
                will be observed to re-apply the patch.
        """
        super().__init__(charm, "kubernetes-compute-resource-patch")
        self._charm = charm
        self._container_name = container_name
        self.resource_reqs = ResourceRequirements(
            limits=sanitize_resource_spec_dict(limits),  # type: ignore[arg-type]
            requests=sanitize_resource_spec_dict(requests),  # type: ignore[arg-type]
        )
        self.patched_delta = self._patched_delta(
            namespace=self._namespace,
            app_name=self._app,
            container_name=self._container_name,
            resource_reqs=self.resource_reqs,
        )

        # Make mypy type checking happy that self._patch is a method
        assert isinstance(self._patch, MethodType)
        # Ensure this patch is applied during the 'config-changed' event, which is emitted every
        # startup and every upgrade. The config-changed event is a good time to apply this kind of
        # patch because it is always emitted after storage-attached, leadership and peer-created,
        # all of which only fire after install. Patching the statefulset prematurely could result
        # in those events firing without a workload.
        self.framework.observe(charm.on.config_changed, self._patch)

        if not refresh_event:
            refresh_event = []
        elif not isinstance(refresh_event, list):
            refresh_event = [refresh_event]
        for ev in refresh_event:
            self.framework.observe(ev, self._patch)

    @classmethod
    def _patched_delta(
        cls,
        namespace: str,
        app_name: str,
        container_name: str,
        resource_reqs: ResourceRequirements,
    ) -> StatefulSet:
        client = Client()
        statefulset = client.get(StatefulSet, name=app_name, namespace=namespace)

        return StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[attr-defined]
                serviceName=statefulset.spec.serviceName,  # type: ignore[attr-defined]
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[Container(name=container_name, resources=resource_reqs)]
                    )
                ),
            )
        )

    def _patch(self, _) -> None:
        """Patch the Kubernetes resources created by Juju to limit cpu or mem."""
        # Need to ignore invalid input, otherwise the statefulset gives "FailedCreate" and the
        # charm would be stuck in unknown/lost.
        try:
            client = Client()
            if self._is_patched(client):
                return

            client.patch(
                StatefulSet,
                self._app,
                self.patched_delta,
                namespace=self._namespace,
                patch_type=PatchType.APPLY,
                field_manager=self.__class__.__name__,
            )

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
                self.resource_reqs,
            )

    def is_ready(self):
        """Reports if the resource patch has been applied and is in effect.

        Returns:
            bool: A boolean indicating if the service patch has been applied and is in effect.
        """
        client = Client()
        pod = client.get(Pod, name=self._pod, namespace=self._namespace)
        podspec = self._get_container(self._container_name, pod.spec.containers)  # type: ignore[attr-defined]

        try:
            ready = equals_canonically(self.resource_reqs, podspec.resources)
            patched = self._is_patched(client)
        except (ValueError, ApiError) as e:
            msg = f"Failed to apply resource limit patch: {e}"
            logger.error(msg)
            self.on.patch_failed.emit(message=msg)
            return False

        return patched and ready

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

    def _is_patched(self, client: Client) -> bool:
        """Reports if the resource patch has been applied to the StatefulSet.

        Returns:
            bool: A boolean indicating if the service patch has been applied.
        """
        statefulset = client.get(StatefulSet, name=self._app, namespace=self._namespace)
        podspec_tpl = self._get_container(
            self._container_name,
            statefulset.spec.template.spec.containers,  # type: ignore[attr-defined]
        )

        return equals_canonically(podspec_tpl.resources, self.resource_reqs)

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
