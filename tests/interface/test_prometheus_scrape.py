# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from interface_tester import InterfaceTester


def test_prometheus_scrape_v0_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        interface_name="prometheus_scrape",
    )
    interface_tester.run()
