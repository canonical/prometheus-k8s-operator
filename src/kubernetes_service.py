# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A simple class used for patching incorrect Kubernetes Service definitions created by Juju."""

from typing import List, Tuple

import kubernetes


class PatchFailed(RuntimeError):
    """Patching the kubernetes service failed."""


class K8sServicePatch:
    """A utility for patching the Kubernetes service set up by Juju.

    Attributes:
            namespace_file (str): path to the k8s namespace file in the charm container
    """

    namespace_file = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

    @staticmethod
    def namespace() -> str:
        """Read the Kubernetes namespace we're deployed in from the mounted service token.

        Returns:
            str: The current Kubernetes namespace
        """
        with open(K8sServicePatch.namespace_file, "r") as f:
            return f.read().strip()

    @staticmethod
    def _k8s_auth():
        """Authenticate with the Kubernetes API using an in-cluster service token.

        Raises:
            PatchFailed: if no permissions to read cluster role
        """
        # Authenticate against the Kubernetes API using a mounted ServiceAccount token
        kubernetes.config.load_incluster_config()
        # Test the service account we've got for sufficient perms
        api = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient())

        try:
            api.list_namespaced_service(namespace=K8sServicePatch.namespace())
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 403:
                raise PatchFailed(
                    "No permission to read cluster role. " "Run `juju trust` on this application."
                ) from e
            else:
                raise e

    @staticmethod
    def _k8s_service(
        app: str, service_ports: List[Tuple[str, int, int]]
    ) -> kubernetes.client.V1Service:
        """Property accessor to return a valid Kubernetes Service representation for Alertmanager.

        Args:
            app: app name
            service_ports: a list of tuples (name, port, target_port) for every service port.

        Returns:
            kubernetes.client.V1Service: A Kubernetes Service with correctly annotated metadata and
            ports.
        """
        ports = [
            kubernetes.client.V1ServicePort(name=port[0], port=port[1], target_port=port[2])
            for port in service_ports
        ]

        ns = K8sServicePatch.namespace()
        return kubernetes.client.V1Service(
            api_version="v1",
            metadata=kubernetes.client.V1ObjectMeta(
                namespace=ns,
                name=app,
                labels={"app.kubernetes.io/name": app},
            ),
            spec=kubernetes.client.V1ServiceSpec(
                ports=ports,
                selector={"app.kubernetes.io/name": app},
            ),
        )

    @staticmethod
    def set_ports(app: str, service_ports: List[Tuple[str, int, int]]):
        """Patch the Kubernetes service created by Juju to map the correct port.

        Currently, Juju uses port 65535 for all endpoints. This can be observed via:

            kubectl describe services -n <model_name> | grep Port -C 2

        At runtime, pebble watches which ports are bound and we need to patch the gap for pebble
        not telling Juju to fix the K8S Service definition.

        Typical usage example from within charm code (e.g. on_install):

            service_ports = [("my-app-api", 9093, 9093), ("my-app-ha", 9094, 9094)]
            K8sServicePatch.set_ports(self.app.name, service_ports)

        Args:
            app: app name
            service_ports: a list of tuples (name, port, target_port) for every service port.

        Raises:
            PatchFailed: if patching fails.
        """
        # First ensure we're authenticated with the Kubernetes API
        K8sServicePatch._k8s_auth()

        ns = K8sServicePatch.namespace()
        # Set up a Kubernetes client
        api = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient())
        try:
            # Delete the existing service so we can redefine with correct ports
            # I don't think you can issue a patch that *replaces* the existing ports,
            # only append
            api.delete_namespaced_service(name=app, namespace=ns)
            # Recreate the service with the correct ports for the application
            api.create_namespaced_service(
                namespace=ns, body=K8sServicePatch._k8s_service(app, service_ports)
            )
        except kubernetes.client.exceptions.ApiException as e:
            raise PatchFailed("Failed to patch k8s service: {}".format(e))
