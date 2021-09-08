# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest.mock import patch

import kubernetes

from kubernetes_service import K8sServicePatch, PatchFailed


class TestK8sServicePatch(unittest.TestCase):
    def setUp(self) -> None:
        self.service_ports = [
            ("svc1", 1234, 12340),
            ("svc2", 1235, 12350),
        ]

    @patch("charm.K8sServicePatch.namespace", lambda: "lma")
    def test_k8s_service(self):
        app_name = "some-app"
        service = K8sServicePatch._k8s_service(app_name, self.service_ports)

        self.assertEqual(service.metadata.name, app_name)
        self.assertEqual(service.metadata.namespace, "lma")
        self.assertEqual(service.metadata.labels, {"app.kubernetes.io/name": app_name})
        self.assertEqual(
            service.spec.ports,
            [
                kubernetes.client.V1ServicePort(
                    name="svc1",
                    port=1234,
                    target_port=12340,
                ),
                kubernetes.client.V1ServicePort(
                    name="svc2",
                    port=1235,
                    target_port=12350,
                ),
            ],
        )

    @patch("kubernetes_service.K8sServicePatch.namespace")
    @patch("kubernetes_service.K8sServicePatch._k8s_auth")
    @patch("kubernetes_service.kubernetes.client.CoreV1Api.delete_namespaced_service")
    @patch("kubernetes_service.kubernetes.client.CoreV1Api.create_namespaced_service")
    def test_patch_k8s_service(self, create, delete, auth, ns):
        ns.return_value = "lma"
        name = "some-app"
        create.return_value = delete.return_value = auth.return_value = True
        K8sServicePatch.set_ports(name, self.service_ports)
        delete.assert_called_with(name=name, namespace=K8sServicePatch.namespace())
        create.assert_called_with(
            namespace=K8sServicePatch.namespace(),
            body=K8sServicePatch._k8s_service(name, self.service_ports),
        )

        # Now test when we don't get authed
        auth.side_effect = PatchFailed("Dummy exception")
        self.assertRaises(PatchFailed, K8sServicePatch.set_ports, name, self.service_ports)
        # Ensure these mock calls haven't increased from the last run
        delete.assert_called_with(name=name, namespace=K8sServicePatch.namespace())
        create.assert_called_with(
            namespace=K8sServicePatch.namespace(),
            body=K8sServicePatch._k8s_service(name, self.service_ports),
        )

    @patch("kubernetes_service.kubernetes.client.CoreV1Api.list_namespaced_service")
    @patch("kubernetes_service.K8sServicePatch.namespace")
    @patch("kubernetes_service.kubernetes.config.load_incluster_config")
    def test_k8s_auth(self, load_config, ns, list_svc):
        ns.return_value = "lma"
        load_config.return_value = True

        K8sServicePatch._k8s_auth()
        list_svc.assert_called_with(namespace=K8sServicePatch.namespace())

        # Now test what happens when listing a svc throws an exception
        list_svc.side_effect = kubernetes.client.exceptions.ApiException(status=403)
        self.assertRaises(PatchFailed, K8sServicePatch._k8s_auth)
