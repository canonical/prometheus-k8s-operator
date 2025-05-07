# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


"""Library for the tls-certificates relation.

This library contains the Requires and Provides classes for handling the tls-certificates
interface.

Pre-requisites:
  - Juju >= 3.0

## Getting Started
From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.tls_certificates_interface.v3.tls_certificates
```

Add the following libraries to the charm's `requirements.txt` file:
- jsonschema
- cryptography >= 42.0.0

Add the following section to the charm's `charmcraft.yaml` file:
```yaml
parts:
  charm:
    build-packages:
      - libffi-dev
      - libssl-dev
      - rustc
      - cargo
```

### Provider charm
The provider charm is the charm providing certificates to another charm that requires them. In
this example, the provider charm is storing its private key using a peer relation interface called
`replicas`.

Example:
```python
from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateCreationRequestEvent,
    CertificateRevocationRequestEvent,
    TLSCertificatesProvidesV3,
    generate_private_key,
)
from ops.charm import CharmBase, InstallEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus


def generate_ca(private_key: bytes, subject: str) -> str:
    return "whatever ca content"


def generate_certificate(ca: str, private_key: str, csr: str) -> str:
    return "Whatever certificate"


class ExampleProviderCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.certificates = TLSCertificatesProvidesV3(self, "certificates")
        self.framework.observe(
            self.certificates.on.certificate_request,
            self._on_certificate_request
        )
        self.framework.observe(
            self.certificates.on.certificate_revocation_request,
            self._on_certificate_revocation_request
        )
        self.framework.observe(self.on.install, self._on_install)

    def _on_install(self, event: InstallEvent) -> None:
        private_key_password = b"banana"
        private_key = generate_private_key(password=private_key_password)
        ca_certificate = generate_ca(private_key=private_key, subject="whatever")
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        replicas_relation.data[self.app].update(
            {
                "private_key_password": "banana",
                "private_key": private_key,
                "ca_certificate": ca_certificate,
            }
        )
        self.unit.status = ActiveStatus()

    def _on_certificate_request(self, event: CertificateCreationRequestEvent) -> None:
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        ca_certificate = replicas_relation.data[self.app].get("ca_certificate")
        private_key = replicas_relation.data[self.app].get("private_key")
        certificate = generate_certificate(
            ca=ca_certificate,
            private_key=private_key,
            csr=event.certificate_signing_request,
        )

        self.certificates.set_relation_certificate(
            certificate=certificate,
            certificate_signing_request=event.certificate_signing_request,
            ca=ca_certificate,
            chain=[ca_certificate, certificate],
            relation_id=event.relation_id,
            recommended_expiry_notification_time=720,
        )

    def _on_certificate_revocation_request(self, event: CertificateRevocationRequestEvent) -> None:
        # Do what you want to do with this information
        pass


if __name__ == "__main__":
    main(ExampleProviderCharm)
```

### Requirer charm
The requirer charm is the charm requiring certificates from another charm that provides them. In
this example, the requirer charm is storing its certificates using a peer relation interface called
`replicas`.

Example:
```python
from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    CertificateRevokedEvent,
    TLSCertificatesRequiresV3,
    generate_csr,
    generate_private_key,
)
from ops.charm import CharmBase, RelationCreatedEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from typing import Union


class ExampleRequirerCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.cert_subject = "whatever"
        self.certificates = TLSCertificatesRequiresV3(self, "certificates")
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on.certificates_relation_created, self._on_certificates_relation_created
        )
        self.framework.observe(
            self.certificates.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self.certificates.on.certificate_expiring, self._on_certificate_expiring
        )
        self.framework.observe(
            self.certificates.on.certificate_invalidated, self._on_certificate_invalidated
        )
        self.framework.observe(
            self.certificates.on.all_certificates_invalidated,
            self._on_all_certificates_invalidated
        )

    def _on_install(self, event) -> None:
        private_key_password = b"banana"
        private_key = generate_private_key(password=private_key_password)
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        replicas_relation.data[self.app].update(
            {"private_key_password": "banana", "private_key": private_key.decode()}
        )

    def _on_certificates_relation_created(self, event: RelationCreatedEvent) -> None:
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        private_key_password = replicas_relation.data[self.app].get("private_key_password")
        private_key = replicas_relation.data[self.app].get("private_key")
        csr = generate_csr(
            private_key=private_key.encode(),
            private_key_password=private_key_password.encode(),
            subject=self.cert_subject,
        )
        replicas_relation.data[self.app].update({"csr": csr.decode()})
        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        replicas_relation.data[self.app].update({"certificate": event.certificate})
        replicas_relation.data[self.app].update({"ca": event.ca})
        replicas_relation.data[self.app].update({"chain": event.chain})
        self.unit.status = ActiveStatus()

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        old_csr = replicas_relation.data[self.app].get("csr")
        private_key_password = replicas_relation.data[self.app].get("private_key_password")
        private_key = replicas_relation.data[self.app].get("private_key")
        new_csr = generate_csr(
            private_key=private_key.encode(),
            private_key_password=private_key_password.encode(),
            subject=self.cert_subject,
        )
        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=old_csr,
            new_certificate_signing_request=new_csr,
        )
        replicas_relation.data[self.app].update({"csr": new_csr.decode()})

    def _certificate_revoked(self) -> None:
        old_csr = replicas_relation.data[self.app].get("csr")
        private_key_password = replicas_relation.data[self.app].get("private_key_password")
        private_key = replicas_relation.data[self.app].get("private_key")
        new_csr = generate_csr(
            private_key=private_key.encode(),
            private_key_password=private_key_password.encode(),
            subject=self.cert_subject,
        )
        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=old_csr,
            new_certificate_signing_request=new_csr,
        )
        replicas_relation.data[self.app].update({"csr": new_csr.decode()})
        replicas_relation.data[self.app].pop("certificate")
        replicas_relation.data[self.app].pop("ca")
        replicas_relation.data[self.app].pop("chain")
        self.unit.status = WaitingStatus("Waiting for new certificate")

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        replicas_relation = self.model.get_relation("replicas")
        if not replicas_relation:
            self.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return
        if event.reason == "revoked":
            self._certificate_revoked()
        if event.reason == "expired":
            self._on_certificate_expiring(event)

    def _on_all_certificates_invalidated(self, event: AllCertificatesInvalidatedEvent) -> None:
        # Do what you want with this information, probably remove all certificates.
        pass


if __name__ == "__main__":
    main(ExampleRequirerCharm)
```

You can relate both charms by running:

```bash
juju relate <tls-certificates provider charm> <tls-certificates requirer charm>
```

"""  # noqa: D405, D410, D411, D214, D416

import copy
import ipaddress
import json
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, Union

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtensionOID
from jsonschema import exceptions, validate
from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationBrokenEvent,
    RelationChangedEvent,
    SecretExpiredEvent,
)
from ops.framework import EventBase, EventSource, Handle, Object
from ops.jujuversion import JujuVersion
from ops.model import (
    Application,
    ModelError,
    Relation,
    RelationDataContent,
    Secret,
    SecretNotFoundError,
    Unit,
)

# The unique Charmhub library identifier, never change it
LIBID = "afd8c2bccf834997afce12c2706d2ede"

# Increment this major API version when introducing breaking changes
LIBAPI = 3

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 25

PYDEPS = ["cryptography", "jsonschema"]

REQUIRER_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "$id": "https://canonical.github.io/charm-relation-interfaces/interfaces/tls_certificates/v1/schemas/requirer.json",
    "type": "object",
    "title": "`tls_certificates` requirer root schema",
    "description": "The `tls_certificates` root schema comprises the entire requirer databag for this interface.",  # noqa: E501
    "examples": [
        {
            "certificate_signing_requests": [
                {
                    "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----\\nMIICWjCCAUICAQAwFTETMBEGA1UEAwwKYmFuYW5hLmNvbTCCASIwDQYJKoZIhvcN\\nAQEBBQADggEPADCCAQoCggEBANWlx9wE6cW7Jkb4DZZDOZoEjk1eDBMJ+8R4pyKp\\nFBeHMl1SQSDt6rAWsrfL3KOGiIHqrRY0B5H6c51L8LDuVrJG0bPmyQ6rsBo3gVke\\nDSivfSLtGvHtp8lwYnIunF8r858uYmblAR0tdXQNmnQvm+6GERvURQ6sxpgZ7iLC\\npPKDoPt+4GKWL10FWf0i82FgxWC2KqRZUtNbgKETQuARLig7etBmCnh20zmynorA\\ncY7vrpTPAaeQpGLNqqYvKV9W6yWVY08V+nqARrFrjk3vSioZSu8ZJUdZ4d9++SGl\\nbH7A6e77YDkX9i/dQ3Pa/iDtWO3tXS2MvgoxX1iSWlGNOHcCAwEAAaAAMA0GCSqG\\nSIb3DQEBCwUAA4IBAQCW1fKcHessy/ZhnIwAtSLznZeZNH8LTVOzkhVd4HA7EJW+\\nKVLBx8DnN7L3V2/uPJfHiOg4Rx7fi7LkJPegl3SCqJZ0N5bQS/KvDTCyLG+9E8Y+\\n7wqCmWiXaH1devimXZvazilu4IC2dSks2D8DPWHgsOdVks9bme8J3KjdNMQudegc\\newWZZ1Dtbd+Rn7cpKU3jURMwm4fRwGxbJ7iT5fkLlPBlyM/yFEik4SmQxFYrZCQg\\n0f3v4kBefTh5yclPy5tEH+8G0LMsbbo3dJ5mPKpAShi0QEKDLd7eR1R/712lYTK4\\ndi4XaEfqERgy68O4rvb4PGlJeRGS7AmL7Ss8wfAq\\n-----END CERTIFICATE REQUEST-----\\n"  # noqa: E501
                },
                {
                    "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----\\nMIICWjCCAUICAQAwFTETMBEGA1UEAwwKYmFuYW5hLmNvbTCCASIwDQYJKoZIhvcN\\nAQEBBQADggEPADCCAQoCggEBAMk3raaX803cHvzlBF9LC7KORT46z4VjyU5PIaMb\\nQLIDgYKFYI0n5hf2Ra4FAHvOvEmW7bjNlHORFEmvnpcU5kPMNUyKFMTaC8LGmN8z\\nUBH3aK+0+FRvY4afn9tgj5435WqOG9QdoDJ0TJkjJbJI9M70UOgL711oU7ql6HxU\\n4d2ydFK9xAHrBwziNHgNZ72L95s4gLTXf0fAHYf15mDA9U5yc+YDubCKgTXzVySQ\\nUx73VCJLfC/XkZIh559IrnRv5G9fu6BMLEuBwAz6QAO4+/XidbKWN4r2XSq5qX4n\\n6EPQQWP8/nd4myq1kbg6Q8w68L/0YdfjCmbyf2TuoWeImdUCAwEAAaAAMA0GCSqG\\nSIb3DQEBCwUAA4IBAQBIdwraBvpYo/rl5MH1+1Um6HRg4gOdQPY5WcJy9B9tgzJz\\nittRSlRGTnhyIo6fHgq9KHrmUthNe8mMTDailKFeaqkVNVvk7l0d1/B90Kz6OfmD\\nxN0qjW53oP7y3QB5FFBM8DjqjmUnz5UePKoX4AKkDyrKWxMwGX5RoET8c/y0y9jp\\nvSq3Wh5UpaZdWbe1oVY8CqMVUEVQL2DPjtopxXFz2qACwsXkQZxWmjvZnRiP8nP8\\nbdFaEuh9Q6rZ2QdZDEtrU4AodPU3NaukFr5KlTUQt3w/cl+5//zils6G5zUWJ2pN\\ng7+t9PTvXHRkH+LnwaVnmsBFU2e05qADQbfIn7JA\\n-----END CERTIFICATE REQUEST-----\\n"  # noqa: E501
                },
            ]
        }
    ],
    "properties": {
        "certificate_signing_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "certificate_signing_request": {"type": "string"},
                    "ca": {"type": "boolean"},
                },
                "required": ["certificate_signing_request"],
            },
        }
    },
    "required": ["certificate_signing_requests"],
    "additionalProperties": True,
}

PROVIDER_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "$id": "https://canonical.github.io/charm-relation-interfaces/interfaces/tls_certificates/v1/schemas/provider.json",
    "type": "object",
    "title": "`tls_certificates` provider root schema",
    "description": "The `tls_certificates` root schema comprises the entire provider databag for this interface.",  # noqa: E501
    "examples": [
        {
            "certificates": [
                {
                    "ca": "-----BEGIN CERTIFICATE-----\\nMIIDJTCCAg2gAwIBAgIUMsSK+4FGCjW6sL/EXMSxColmKw8wDQYJKoZIhvcNAQEL\\nBQAwIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdoYXRldmVyMB4XDTIyMDcyOTIx\\nMTgyN1oXDTIzMDcyOTIxMTgyN1owIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdo\\nYXRldmVyMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA55N9DkgFWbJ/\\naqcdQhso7n1kFvt6j/fL1tJBvRubkiFMQJnZFtekfalN6FfRtA3jq+nx8o49e+7t\\nLCKT0xQ+wufXfOnxv6/if6HMhHTiCNPOCeztUgQ2+dfNwRhYYgB1P93wkUVjwudK\\n13qHTTZ6NtEF6EzOqhOCe6zxq6wrr422+ZqCvcggeQ5tW9xSd/8O1vNID/0MTKpy\\nET3drDtBfHmiUEIBR3T3tcy6QsIe4Rz/2sDinAcM3j7sG8uY6drh8jY3PWar9til\\nv2l4qDYSU8Qm5856AB1FVZRLRJkLxZYZNgreShAIYgEd0mcyI2EO/UvKxsIcxsXc\\nd45GhGpKkwIDAQABo1cwVTAfBgNVHQ4EGAQWBBRXBrXKh3p/aFdQjUcT/UcvICBL\\nODAhBgNVHSMEGjAYgBYEFFcGtcqHen9oV1CNRxP9Ry8gIEs4MA8GA1UdEwEB/wQF\\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAGmCEvcoFUrT9e133SHkgF/ZAgzeIziO\\nBjfAdU4fvAVTVfzaPm0yBnGqzcHyacCzbZjKQpaKVgc5e6IaqAQtf6cZJSCiJGhS\\nJYeosWrj3dahLOUAMrXRr8G/Ybcacoqc+osKaRa2p71cC3V6u2VvcHRV7HDFGJU7\\noijbdB+WhqET6Txe67rxZCJG9Ez3EOejBJBl2PJPpy7m1Ml4RR+E8YHNzB0lcBzc\\nEoiJKlDfKSO14E2CPDonnUoWBJWjEvJys3tbvKzsRj2fnLilytPFU0gH3cEjCopi\\nzFoWRdaRuNHYCqlBmso1JFDl8h4fMmglxGNKnKRar0WeGyxb4xXBGpI=\\n-----END CERTIFICATE-----\\n",  # noqa: E501
                    "chain": [
                        "-----BEGIN CERTIFICATE-----\\nMIIDJTCCAg2gAwIBAgIUMsSK+4FGCjW6sL/EXMSxColmKw8wDQYJKoZIhvcNAQEL\\nBQAwIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdoYXRldmVyMB4XDTIyMDcyOTIx\\nMTgyN1oXDTIzMDcyOTIxMTgyN1owIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdo\\nYXRldmVyMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA55N9DkgFWbJ/\\naqcdQhso7n1kFvt6j/fL1tJBvRubkiFMQJnZFtekfalN6FfRtA3jq+nx8o49e+7t\\nLCKT0xQ+wufXfOnxv6/if6HMhHTiCNPOCeztUgQ2+dfNwRhYYgB1P93wkUVjwudK\\n13qHTTZ6NtEF6EzOqhOCe6zxq6wrr422+ZqCvcggeQ5tW9xSd/8O1vNID/0MTKpy\\nET3drDtBfHmiUEIBR3T3tcy6QsIe4Rz/2sDinAcM3j7sG8uY6drh8jY3PWar9til\\nv2l4qDYSU8Qm5856AB1FVZRLRJkLxZYZNgreShAIYgEd0mcyI2EO/UvKxsIcxsXc\\nd45GhGpKkwIDAQABo1cwVTAfBgNVHQ4EGAQWBBRXBrXKh3p/aFdQjUcT/UcvICBL\\nODAhBgNVHSMEGjAYgBYEFFcGtcqHen9oV1CNRxP9Ry8gIEs4MA8GA1UdEwEB/wQF\\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAGmCEvcoFUrT9e133SHkgF/ZAgzeIziO\\nBjfAdU4fvAVTVfzaPm0yBnGqzcHyacCzbZjKQpaKVgc5e6IaqAQtf6cZJSCiJGhS\\nJYeosWrj3dahLOUAMrXRr8G/Ybcacoqc+osKaRa2p71cC3V6u2VvcHRV7HDFGJU7\\noijbdB+WhqET6Txe67rxZCJG9Ez3EOejBJBl2PJPpy7m1Ml4RR+E8YHNzB0lcBzc\\nEoiJKlDfKSO14E2CPDonnUoWBJWjEvJys3tbvKzsRj2fnLilytPFU0gH3cEjCopi\\nzFoWRdaRuNHYCqlBmso1JFDl8h4fMmglxGNKnKRar0WeGyxb4xXBGpI=\\n-----END CERTIFICATE-----\\n"  # noqa: E501, W505
                    ],
                    "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----\nMIICWjCCAUICAQAwFTETMBEGA1UEAwwKYmFuYW5hLmNvbTCCASIwDQYJKoZIhvcN\nAQEBBQADggEPADCCAQoCggEBANWlx9wE6cW7Jkb4DZZDOZoEjk1eDBMJ+8R4pyKp\nFBeHMl1SQSDt6rAWsrfL3KOGiIHqrRY0B5H6c51L8LDuVrJG0bPmyQ6rsBo3gVke\nDSivfSLtGvHtp8lwYnIunF8r858uYmblAR0tdXQNmnQvm+6GERvURQ6sxpgZ7iLC\npPKDoPt+4GKWL10FWf0i82FgxWC2KqRZUtNbgKETQuARLig7etBmCnh20zmynorA\ncY7vrpTPAaeQpGLNqqYvKV9W6yWVY08V+nqARrFrjk3vSioZSu8ZJUdZ4d9++SGl\nbH7A6e77YDkX9i/dQ3Pa/iDtWO3tXS2MvgoxX1iSWlGNOHcCAwEAAaAAMA0GCSqG\nSIb3DQEBCwUAA4IBAQCW1fKcHessy/ZhnIwAtSLznZeZNH8LTVOzkhVd4HA7EJW+\nKVLBx8DnN7L3V2/uPJfHiOg4Rx7fi7LkJPegl3SCqJZ0N5bQS/KvDTCyLG+9E8Y+\n7wqCmWiXaH1devimXZvazilu4IC2dSks2D8DPWHgsOdVks9bme8J3KjdNMQudegc\newWZZ1Dtbd+Rn7cpKU3jURMwm4fRwGxbJ7iT5fkLlPBlyM/yFEik4SmQxFYrZCQg\n0f3v4kBefTh5yclPy5tEH+8G0LMsbbo3dJ5mPKpAShi0QEKDLd7eR1R/712lYTK4\ndi4XaEfqERgy68O4rvb4PGlJeRGS7AmL7Ss8wfAq\n-----END CERTIFICATE REQUEST-----\n",  # noqa: E501
                    "certificate": "-----BEGIN CERTIFICATE-----\nMIICvDCCAaQCFFPAOD7utDTsgFrm0vS4We18OcnKMA0GCSqGSIb3DQEBCwUAMCAx\nCzAJBgNVBAYTAlVTMREwDwYDVQQDDAh3aGF0ZXZlcjAeFw0yMjA3MjkyMTE5Mzha\nFw0yMzA3MjkyMTE5MzhaMBUxEzARBgNVBAMMCmJhbmFuYS5jb20wggEiMA0GCSqG\nSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDVpcfcBOnFuyZG+A2WQzmaBI5NXgwTCfvE\neKciqRQXhzJdUkEg7eqwFrK3y9yjhoiB6q0WNAeR+nOdS/Cw7layRtGz5skOq7Aa\nN4FZHg0or30i7Rrx7afJcGJyLpxfK/OfLmJm5QEdLXV0DZp0L5vuhhEb1EUOrMaY\nGe4iwqTyg6D7fuBili9dBVn9IvNhYMVgtiqkWVLTW4ChE0LgES4oO3rQZgp4dtM5\nsp6KwHGO766UzwGnkKRizaqmLylfVusllWNPFfp6gEaxa45N70oqGUrvGSVHWeHf\nfvkhpWx+wOnu+2A5F/Yv3UNz2v4g7Vjt7V0tjL4KMV9YklpRjTh3AgMBAAEwDQYJ\nKoZIhvcNAQELBQADggEBAChjRzuba8zjQ7NYBVas89Oy7u++MlS8xWxh++yiUsV6\nWMk3ZemsPtXc1YmXorIQohtxLxzUPm2JhyzFzU/sOLmJQ1E/l+gtZHyRCwsb20fX\nmphuJsMVd7qv/GwEk9PBsk2uDqg4/Wix0Rx5lf95juJP7CPXQJl5FQauf3+LSz0y\nwF/j+4GqvrwsWr9hKOLmPdkyKkR6bHKtzzsxL9PM8GnElk2OpaPMMnzbL/vt2IAt\nxK01ZzPxCQCzVwHo5IJO5NR/fIyFbEPhxzG17QsRDOBR9fl9cOIvDeSO04vyZ+nz\n+kA2c3fNrZFAtpIlOOmFh8Q12rVL4sAjI5mVWnNEgvI=\n-----END CERTIFICATE-----\n",  # noqa: E501
                }
            ]
        },
        {
            "certificates": [
                {
                    "ca": "-----BEGIN CERTIFICATE-----\\nMIIDJTCCAg2gAwIBAgIUMsSK+4FGCjW6sL/EXMSxColmKw8wDQYJKoZIhvcNAQEL\\nBQAwIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdoYXRldmVyMB4XDTIyMDcyOTIx\\nMTgyN1oXDTIzMDcyOTIxMTgyN1owIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdo\\nYXRldmVyMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA55N9DkgFWbJ/\\naqcdQhso7n1kFvt6j/fL1tJBvRubkiFMQJnZFtekfalN6FfRtA3jq+nx8o49e+7t\\nLCKT0xQ+wufXfOnxv6/if6HMhHTiCNPOCeztUgQ2+dfNwRhYYgB1P93wkUVjwudK\\n13qHTTZ6NtEF6EzOqhOCe6zxq6wrr422+ZqCvcggeQ5tW9xSd/8O1vNID/0MTKpy\\nET3drDtBfHmiUEIBR3T3tcy6QsIe4Rz/2sDinAcM3j7sG8uY6drh8jY3PWar9til\\nv2l4qDYSU8Qm5856AB1FVZRLRJkLxZYZNgreShAIYgEd0mcyI2EO/UvKxsIcxsXc\\nd45GhGpKkwIDAQABo1cwVTAfBgNVHQ4EGAQWBBRXBrXKh3p/aFdQjUcT/UcvICBL\\nODAhBgNVHSMEGjAYgBYEFFcGtcqHen9oV1CNRxP9Ry8gIEs4MA8GA1UdEwEB/wQF\\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAGmCEvcoFUrT9e133SHkgF/ZAgzeIziO\\nBjfAdU4fvAVTVfzaPm0yBnGqzcHyacCzbZjKQpaKVgc5e6IaqAQtf6cZJSCiJGhS\\nJYeosWrj3dahLOUAMrXRr8G/Ybcacoqc+osKaRa2p71cC3V6u2VvcHRV7HDFGJU7\\noijbdB+WhqET6Txe67rxZCJG9Ez3EOejBJBl2PJPpy7m1Ml4RR+E8YHNzB0lcBzc\\nEoiJKlDfKSO14E2CPDonnUoWBJWjEvJys3tbvKzsRj2fnLilytPFU0gH3cEjCopi\\nzFoWRdaRuNHYCqlBmso1JFDl8h4fMmglxGNKnKRar0WeGyxb4xXBGpI=\\n-----END CERTIFICATE-----\\n",  # noqa: E501
                    "chain": [
                        "-----BEGIN CERTIFICATE-----\\nMIIDJTCCAg2gAwIBAgIUMsSK+4FGCjW6sL/EXMSxColmKw8wDQYJKoZIhvcNAQEL\\nBQAwIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdoYXRldmVyMB4XDTIyMDcyOTIx\\nMTgyN1oXDTIzMDcyOTIxMTgyN1owIDELMAkGA1UEBhMCVVMxETAPBgNVBAMMCHdo\\nYXRldmVyMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA55N9DkgFWbJ/\\naqcdQhso7n1kFvt6j/fL1tJBvRubkiFMQJnZFtekfalN6FfRtA3jq+nx8o49e+7t\\nLCKT0xQ+wufXfOnxv6/if6HMhHTiCNPOCeztUgQ2+dfNwRhYYgB1P93wkUVjwudK\\n13qHTTZ6NtEF6EzOqhOCe6zxq6wrr422+ZqCvcggeQ5tW9xSd/8O1vNID/0MTKpy\\nET3drDtBfHmiUEIBR3T3tcy6QsIe4Rz/2sDinAcM3j7sG8uY6drh8jY3PWar9til\\nv2l4qDYSU8Qm5856AB1FVZRLRJkLxZYZNgreShAIYgEd0mcyI2EO/UvKxsIcxsXc\\nd45GhGpKkwIDAQABo1cwVTAfBgNVHQ4EGAQWBBRXBrXKh3p/aFdQjUcT/UcvICBL\\nODAhBgNVHSMEGjAYgBYEFFcGtcqHen9oV1CNRxP9Ry8gIEs4MA8GA1UdEwEB/wQF\\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAGmCEvcoFUrT9e133SHkgF/ZAgzeIziO\\nBjfAdU4fvAVTVfzaPm0yBnGqzcHyacCzbZjKQpaKVgc5e6IaqAQtf6cZJSCiJGhS\\nJYeosWrj3dahLOUAMrXRr8G/Ybcacoqc+osKaRa2p71cC3V6u2VvcHRV7HDFGJU7\\noijbdB+WhqET6Txe67rxZCJG9Ez3EOejBJBl2PJPpy7m1Ml4RR+E8YHNzB0lcBzc\\nEoiJKlDfKSO14E2CPDonnUoWBJWjEvJys3tbvKzsRj2fnLilytPFU0gH3cEjCopi\\nzFoWRdaRuNHYCqlBmso1JFDl8h4fMmglxGNKnKRar0WeGyxb4xXBGpI=\\n-----END CERTIFICATE-----\\n"  # noqa: E501, W505
                    ],
                    "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----\nMIICWjCCAUICAQAwFTETMBEGA1UEAwwKYmFuYW5hLmNvbTCCASIwDQYJKoZIhvcN\nAQEBBQADggEPADCCAQoCggEBANWlx9wE6cW7Jkb4DZZDOZoEjk1eDBMJ+8R4pyKp\nFBeHMl1SQSDt6rAWsrfL3KOGiIHqrRY0B5H6c51L8LDuVrJG0bPmyQ6rsBo3gVke\nDSivfSLtGvHtp8lwYnIunF8r858uYmblAR0tdXQNmnQvm+6GERvURQ6sxpgZ7iLC\npPKDoPt+4GKWL10FWf0i82FgxWC2KqRZUtNbgKETQuARLig7etBmCnh20zmynorA\ncY7vrpTPAaeQpGLNqqYvKV9W6yWVY08V+nqARrFrjk3vSioZSu8ZJUdZ4d9++SGl\nbH7A6e77YDkX9i/dQ3Pa/iDtWO3tXS2MvgoxX1iSWlGNOHcCAwEAAaAAMA0GCSqG\nSIb3DQEBCwUAA4IBAQCW1fKcHessy/ZhnIwAtSLznZeZNH8LTVOzkhVd4HA7EJW+\nKVLBx8DnN7L3V2/uPJfHiOg4Rx7fi7LkJPegl3SCqJZ0N5bQS/KvDTCyLG+9E8Y+\n7wqCmWiXaH1devimXZvazilu4IC2dSks2D8DPWHgsOdVks9bme8J3KjdNMQudegc\newWZZ1Dtbd+Rn7cpKU3jURMwm4fRwGxbJ7iT5fkLlPBlyM/yFEik4SmQxFYrZCQg\n0f3v4kBefTh5yclPy5tEH+8G0LMsbbo3dJ5mPKpAShi0QEKDLd7eR1R/712lYTK4\ndi4XaEfqERgy68O4rvb4PGlJeRGS7AmL7Ss8wfAq\n-----END CERTIFICATE REQUEST-----\n",  # noqa: E501
                    "certificate": "-----BEGIN CERTIFICATE-----\nMIICvDCCAaQCFFPAOD7utDTsgFrm0vS4We18OcnKMA0GCSqGSIb3DQEBCwUAMCAx\nCzAJBgNVBAYTAlVTMREwDwYDVQQDDAh3aGF0ZXZlcjAeFw0yMjA3MjkyMTE5Mzha\nFw0yMzA3MjkyMTE5MzhaMBUxEzARBgNVBAMMCmJhbmFuYS5jb20wggEiMA0GCSqG\nSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDVpcfcBOnFuyZG+A2WQzmaBI5NXgwTCfvE\neKciqRQXhzJdUkEg7eqwFrK3y9yjhoiB6q0WNAeR+nOdS/Cw7layRtGz5skOq7Aa\nN4FZHg0or30i7Rrx7afJcGJyLpxfK/OfLmJm5QEdLXV0DZp0L5vuhhEb1EUOrMaY\nGe4iwqTyg6D7fuBili9dBVn9IvNhYMVgtiqkWVLTW4ChE0LgES4oO3rQZgp4dtM5\nsp6KwHGO766UzwGnkKRizaqmLylfVusllWNPFfp6gEaxa45N70oqGUrvGSVHWeHf\nfvkhpWx+wOnu+2A5F/Yv3UNz2v4g7Vjt7V0tjL4KMV9YklpRjTh3AgMBAAEwDQYJ\nKoZIhvcNAQELBQADggEBAChjRzuba8zjQ7NYBVas89Oy7u++MlS8xWxh++yiUsV6\nWMk3ZemsPtXc1YmXorIQohtxLxzUPm2JhyzFzU/sOLmJQ1E/l+gtZHyRCwsb20fX\nmphuJsMVd7qv/GwEk9PBsk2uDqg4/Wix0Rx5lf95juJP7CPXQJl5FQauf3+LSz0y\nwF/j+4GqvrwsWr9hKOLmPdkyKkR6bHKtzzsxL9PM8GnElk2OpaPMMnzbL/vt2IAt\nxK01ZzPxCQCzVwHo5IJO5NR/fIyFbEPhxzG17QsRDOBR9fl9cOIvDeSO04vyZ+nz\n+kA2c3fNrZFAtpIlOOmFh8Q12rVL4sAjI5mVWnNEgvI=\n-----END CERTIFICATE-----\n",  # noqa: E501
                    "revoked": True,
                }
            ]
        },
    ],
    "properties": {
        "certificates": {
            "$id": "#/properties/certificates",
            "type": "array",
            "items": {
                "$id": "#/properties/certificates/items",
                "type": "object",
                "required": ["certificate_signing_request", "certificate", "ca", "chain"],
                "properties": {
                    "certificate_signing_request": {
                        "$id": "#/properties/certificates/items/certificate_signing_request",
                        "type": "string",
                    },
                    "certificate": {
                        "$id": "#/properties/certificates/items/certificate",
                        "type": "string",
                    },
                    "ca": {"$id": "#/properties/certificates/items/ca", "type": "string"},
                    "chain": {
                        "$id": "#/properties/certificates/items/chain",
                        "type": "array",
                        "items": {
                            "type": "string",
                            "$id": "#/properties/certificates/items/chain/items",
                        },
                    },
                    "revoked": {
                        "$id": "#/properties/certificates/items/revoked",
                        "type": "boolean",
                    },
                },
                "additionalProperties": True,
            },
        }
    },
    "required": ["certificates"],
    "additionalProperties": True,
}


logger = logging.getLogger(__name__)


@dataclass
class RequirerCSR:
    """This class represents a certificate signing request from an interface Requirer."""

    relation_id: int
    application_name: str
    unit_name: str
    csr: str
    is_ca: bool


@dataclass
class ProviderCertificate:
    """This class represents a certificate from an interface Provider."""

    relation_id: int
    application_name: str
    csr: str
    certificate: str
    ca: str
    chain: List[str]
    revoked: bool
    expiry_time: datetime
    expiry_notification_time: Optional[datetime] = None

    def chain_as_pem(self) -> str:
        """Return full certificate chain as a PEM string."""
        return "\n\n".join(reversed(self.chain))

    def to_json(self) -> str:
        """Return the object as a JSON string.

        Returns:
            str: JSON representation of the object
        """
        return json.dumps(
            {
                "relation_id": self.relation_id,
                "application_name": self.application_name,
                "csr": self.csr,
                "certificate": self.certificate,
                "ca": self.ca,
                "chain": self.chain,
                "revoked": self.revoked,
                "expiry_time": self.expiry_time.isoformat(),
                "expiry_notification_time": self.expiry_notification_time.isoformat()
                if self.expiry_notification_time
                else None,
            }
        )


class CertificateAvailableEvent(EventBase):
    """Charm Event triggered when a TLS certificate is available."""

    def __init__(
        self,
        handle: Handle,
        certificate: str,
        certificate_signing_request: str,
        ca: str,
        chain: List[str],
    ):
        super().__init__(handle)
        self.certificate = certificate
        self.certificate_signing_request = certificate_signing_request
        self.ca = ca
        self.chain = chain

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "certificate": self.certificate,
            "certificate_signing_request": self.certificate_signing_request,
            "ca": self.ca,
            "chain": self.chain,
        }

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.certificate = snapshot["certificate"]
        self.certificate_signing_request = snapshot["certificate_signing_request"]
        self.ca = snapshot["ca"]
        self.chain = snapshot["chain"]

    def chain_as_pem(self) -> str:
        """Return full certificate chain as a PEM string."""
        return "\n\n".join(reversed(self.chain))


class CertificateExpiringEvent(EventBase):
    """Charm Event triggered when a TLS certificate is almost expired."""

    def __init__(self, handle: Handle, certificate: str, expiry: str):
        """CertificateExpiringEvent.

        Args:
            handle (Handle): Juju framework handle
            certificate (str): TLS Certificate
            expiry (str): Datetime string representing the time at which the certificate
                won't be valid anymore.
        """
        super().__init__(handle)
        self.certificate = certificate
        self.expiry = expiry

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {"certificate": self.certificate, "expiry": self.expiry}

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.certificate = snapshot["certificate"]
        self.expiry = snapshot["expiry"]


class CertificateInvalidatedEvent(EventBase):
    """Charm Event triggered when a TLS certificate is invalidated."""

    def __init__(
        self,
        handle: Handle,
        reason: Literal["expired", "revoked"],
        certificate: str,
        certificate_signing_request: str,
        ca: str,
        chain: List[str],
    ):
        super().__init__(handle)
        self.reason = reason
        self.certificate_signing_request = certificate_signing_request
        self.certificate = certificate
        self.ca = ca
        self.chain = chain

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "reason": self.reason,
            "certificate_signing_request": self.certificate_signing_request,
            "certificate": self.certificate,
            "ca": self.ca,
            "chain": self.chain,
        }

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.reason = snapshot["reason"]
        self.certificate_signing_request = snapshot["certificate_signing_request"]
        self.certificate = snapshot["certificate"]
        self.ca = snapshot["ca"]
        self.chain = snapshot["chain"]


class AllCertificatesInvalidatedEvent(EventBase):
    """Charm Event triggered when all TLS certificates are invalidated."""

    def __init__(self, handle: Handle):
        super().__init__(handle)

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {}

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        pass


class CertificateCreationRequestEvent(EventBase):
    """Charm Event triggered when a TLS certificate is required."""

    def __init__(
        self,
        handle: Handle,
        certificate_signing_request: str,
        relation_id: int,
        is_ca: bool = False,
    ):
        super().__init__(handle)
        self.certificate_signing_request = certificate_signing_request
        self.relation_id = relation_id
        self.is_ca = is_ca

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "certificate_signing_request": self.certificate_signing_request,
            "relation_id": self.relation_id,
            "is_ca": self.is_ca,
        }

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.certificate_signing_request = snapshot["certificate_signing_request"]
        self.relation_id = snapshot["relation_id"]
        self.is_ca = snapshot["is_ca"]


class CertificateRevocationRequestEvent(EventBase):
    """Charm Event triggered when a TLS certificate needs to be revoked."""

    def __init__(
        self,
        handle: Handle,
        certificate: str,
        certificate_signing_request: str,
        ca: str,
        chain: str,
    ):
        super().__init__(handle)
        self.certificate = certificate
        self.certificate_signing_request = certificate_signing_request
        self.ca = ca
        self.chain = chain

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "certificate": self.certificate,
            "certificate_signing_request": self.certificate_signing_request,
            "ca": self.ca,
            "chain": self.chain,
        }

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.certificate = snapshot["certificate"]
        self.certificate_signing_request = snapshot["certificate_signing_request"]
        self.ca = snapshot["ca"]
        self.chain = snapshot["chain"]


def _load_relation_data(relation_data_content: RelationDataContent) -> dict:
    """Load relation data from the relation data bag.

    Json loads all data.

    Args:
        relation_data_content: Relation data from the databag

    Returns:
        dict: Relation data in dict format.
    """
    certificate_data = {}
    try:
        for key in relation_data_content:
            try:
                certificate_data[key] = json.loads(relation_data_content[key])
            except (json.decoder.JSONDecodeError, TypeError):
                certificate_data[key] = relation_data_content[key]
    except ModelError:
        pass
    return certificate_data


def _get_closest_future_time(
    expiry_notification_time: datetime, expiry_time: datetime
) -> datetime:
    """Return expiry_notification_time if not in the past, otherwise return expiry_time.

    Args:
        expiry_notification_time (datetime): Notification time of impending expiration
        expiry_time (datetime): Expiration time

    Returns:
        datetime: expiry_notification_time if not in the past, expiry_time otherwise
    """
    return (
        expiry_notification_time
        if datetime.now(timezone.utc) < expiry_notification_time
        else expiry_time
    )


def calculate_expiry_notification_time(
    validity_start_time: datetime,
    expiry_time: datetime,
    provider_recommended_notification_time: Optional[int],
    requirer_recommended_notification_time: Optional[int],
) -> datetime:
    """Calculate a reasonable time to notify the user about the certificate expiry.

    It takes into account the time recommended by the provider and by the requirer.
    Time recommended by the provider is preferred,
    then time recommended by the requirer,
    then dynamically calculated time.

    Args:
        validity_start_time: Certificate validity time
        expiry_time: Certificate expiry time
        provider_recommended_notification_time:
            Time in hours prior to expiry to notify the user.
            Recommended by the provider.
        requirer_recommended_notification_time:
            Time in hours prior to expiry to notify the user.
            Recommended by the requirer.

    Returns:
        datetime: Time to notify the user about the certificate expiry.
    """
    if provider_recommended_notification_time is not None:
        provider_recommended_notification_time = abs(provider_recommended_notification_time)
        provider_recommendation_time_delta = expiry_time - timedelta(
            hours=provider_recommended_notification_time
        )
        if validity_start_time < provider_recommendation_time_delta:
            return provider_recommendation_time_delta

    if requirer_recommended_notification_time is not None:
        requirer_recommended_notification_time = abs(requirer_recommended_notification_time)
        requirer_recommendation_time_delta = expiry_time - timedelta(
            hours=requirer_recommended_notification_time
        )
        if validity_start_time < requirer_recommendation_time_delta:
            return requirer_recommendation_time_delta
    calculated_hours = (expiry_time - validity_start_time).total_seconds() / (3600 * 3)
    return expiry_time - timedelta(hours=calculated_hours)


def generate_ca(
    private_key: bytes,
    subject: str,
    private_key_password: Optional[bytes] = None,
    validity: int = 365,
    country: str = "US",
) -> bytes:
    """Generate a CA Certificate.

    Args:
        private_key (bytes): Private key
        subject (str): Common Name that can be an IP or a Full Qualified Domain Name (FQDN).
        private_key_password (bytes): Private key password
        validity (int): Certificate validity time (in days)
        country (str): Certificate Issuing country

    Returns:
        bytes: CA Certificate.
    """
    private_key_object = serialization.load_pem_private_key(
        private_key, password=private_key_password
    )
    subject_name = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(x509.NameOID.COMMON_NAME, subject),
        ]
    )
    subject_identifier_object = x509.SubjectKeyIdentifier.from_public_key(
        private_key_object.public_key()  # type: ignore[arg-type]
    )
    subject_identifier = key_identifier = subject_identifier_object.public_bytes()
    key_usage = x509.KeyUsage(
        digital_signature=True,
        key_encipherment=True,
        key_cert_sign=True,
        key_agreement=False,
        content_commitment=False,
        data_encipherment=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(private_key_object.public_key())  # type: ignore[arg-type]
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=validity))
        .add_extension(x509.SubjectKeyIdentifier(digest=subject_identifier), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier(
                key_identifier=key_identifier,
                authority_cert_issuer=None,
                authority_cert_serial_number=None,
            ),
            critical=False,
        )
        .add_extension(key_usage, critical=True)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(private_key_object, hashes.SHA256())  # type: ignore[arg-type]
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def get_certificate_extensions(
    authority_key_identifier: bytes,
    csr: x509.CertificateSigningRequest,
    alt_names: Optional[List[str]],
    is_ca: bool,
) -> List[x509.Extension]:
    """Generate a list of certificate extensions from a CSR and other known information.

    Args:
        authority_key_identifier (bytes): Authority key identifier
        csr (x509.CertificateSigningRequest): CSR
        alt_names (list): List of alt names to put on cert - prefer putting SANs in CSR
        is_ca (bool): Whether the certificate is a CA certificate

    Returns:
        List[x509.Extension]: List of extensions
    """
    cert_extensions_list: List[x509.Extension] = [
        x509.Extension(
            oid=ExtensionOID.AUTHORITY_KEY_IDENTIFIER,
            value=x509.AuthorityKeyIdentifier(
                key_identifier=authority_key_identifier,
                authority_cert_issuer=None,
                authority_cert_serial_number=None,
            ),
            critical=False,
        ),
        x509.Extension(
            oid=ExtensionOID.SUBJECT_KEY_IDENTIFIER,
            value=x509.SubjectKeyIdentifier.from_public_key(csr.public_key()),
            critical=False,
        ),
        x509.Extension(
            oid=ExtensionOID.BASIC_CONSTRAINTS,
            critical=True,
            value=x509.BasicConstraints(ca=is_ca, path_length=None),
        ),
    ]

    sans: List[x509.GeneralName] = []
    san_alt_names = [x509.DNSName(name) for name in alt_names] if alt_names else []
    sans.extend(san_alt_names)
    try:
        loaded_san_ext = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans.extend(
            [x509.DNSName(name) for name in loaded_san_ext.value.get_values_for_type(x509.DNSName)]
        )
        sans.extend(
            [x509.IPAddress(ip) for ip in loaded_san_ext.value.get_values_for_type(x509.IPAddress)]
        )
        sans.extend(
            [
                x509.RegisteredID(oid)
                for oid in loaded_san_ext.value.get_values_for_type(x509.RegisteredID)
            ]
        )
    except x509.ExtensionNotFound:
        pass

    if sans:
        cert_extensions_list.append(
            x509.Extension(
                oid=ExtensionOID.SUBJECT_ALTERNATIVE_NAME,
                critical=False,
                value=x509.SubjectAlternativeName(sans),
            )
        )

    if is_ca:
        cert_extensions_list.append(
            x509.Extension(
                ExtensionOID.KEY_USAGE,
                critical=True,
                value=x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
            )
        )

    existing_oids = {ext.oid for ext in cert_extensions_list}
    for extension in csr.extensions:
        if extension.oid == ExtensionOID.SUBJECT_ALTERNATIVE_NAME:
            continue
        if extension.oid in existing_oids:
            logger.warning("Extension %s is managed by the TLS provider, ignoring.", extension.oid)
            continue
        cert_extensions_list.append(extension)

    return cert_extensions_list


def generate_certificate(
    csr: bytes,
    ca: bytes,
    ca_key: bytes,
    ca_key_password: Optional[bytes] = None,
    validity: int = 365,
    alt_names: Optional[List[str]] = None,
    is_ca: bool = False,
) -> bytes:
    """Generate a TLS certificate based on a CSR.

    Args:
        csr (bytes): CSR
        ca (bytes): CA Certificate
        ca_key (bytes): CA private key
        ca_key_password: CA private key password
        validity (int): Certificate validity (in days)
        alt_names (list): List of alt names to put on cert - prefer putting SANs in CSR
        is_ca (bool): Whether the certificate is a CA certificate

    Returns:
        bytes: Certificate
    """
    csr_object = x509.load_pem_x509_csr(csr)
    subject = csr_object.subject
    ca_pem = x509.load_pem_x509_certificate(ca)
    issuer = ca_pem.issuer
    private_key = serialization.load_pem_private_key(ca_key, password=ca_key_password)

    certificate_builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(csr_object.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=validity))
    )
    extensions = get_certificate_extensions(
        authority_key_identifier=ca_pem.extensions.get_extension_for_class(
            x509.SubjectKeyIdentifier
        ).value.key_identifier,
        csr=csr_object,
        alt_names=alt_names,
        is_ca=is_ca,
    )
    for extension in extensions:
        try:
            certificate_builder = certificate_builder.add_extension(
                extval=extension.value,
                critical=extension.critical,
            )
        except ValueError as e:
            logger.warning("Failed to add extension %s: %s", extension.oid, e)

    cert = certificate_builder.sign(private_key, hashes.SHA256())  # type: ignore[arg-type]
    return cert.public_bytes(serialization.Encoding.PEM)


def generate_private_key(
    password: Optional[bytes] = None,
    key_size: int = 2048,
    public_exponent: int = 65537,
) -> bytes:
    """Generate a private key.

    Args:
        password (bytes): Password for decrypting the private key
        key_size (int): Key size in bytes
        public_exponent: Public exponent.

    Returns:
        bytes: Private Key
    """
    private_key = rsa.generate_private_key(
        public_exponent=public_exponent,
        key_size=key_size,
    )
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=(
            serialization.BestAvailableEncryption(password)
            if password
            else serialization.NoEncryption()
        ),
    )
    return key_bytes


def generate_csr(  # noqa: C901
    private_key: bytes,
    subject: str,
    add_unique_id_to_subject_name: bool = True,
    organization: Optional[str] = None,
    email_address: Optional[str] = None,
    country_name: Optional[str] = None,
    state_or_province_name: Optional[str] = None,
    locality_name: Optional[str] = None,
    private_key_password: Optional[bytes] = None,
    sans: Optional[List[str]] = None,
    sans_oid: Optional[List[str]] = None,
    sans_ip: Optional[List[str]] = None,
    sans_dns: Optional[List[str]] = None,
    additional_critical_extensions: Optional[List] = None,
) -> bytes:
    """Generate a CSR using private key and subject.

    Args:
        private_key (bytes): Private key
        subject (str): CSR Common Name that can be an IP or a Full Qualified Domain Name (FQDN).
        add_unique_id_to_subject_name (bool): Whether a unique ID must be added to the CSR's
            subject name. Always leave to "True" when the CSR is used to request certificates
            using the tls-certificates relation.
        organization (str): Name of organization.
        email_address (str): Email address.
        country_name (str): Country Name.
        state_or_province_name (str): State or Province Name.
        locality_name (str): Locality Name.
        private_key_password (bytes): Private key password
        sans (list): Use sans_dns - this will be deprecated in a future release
            List of DNS subject alternative names (keeping it for now for backward compatibility)
        sans_oid (list): List of registered ID SANs
        sans_dns (list): List of DNS subject alternative names (similar to the arg: sans)
        sans_ip (list): List of IP subject alternative names
        additional_critical_extensions (list): List of critical additional extension objects.
            Object must be a x509 ExtensionType.

    Returns:
        bytes: CSR
    """
    signing_key = serialization.load_pem_private_key(private_key, password=private_key_password)
    subject_name = [x509.NameAttribute(x509.NameOID.COMMON_NAME, subject)]
    if add_unique_id_to_subject_name:
        unique_identifier = uuid.uuid4()
        subject_name.append(
            x509.NameAttribute(x509.NameOID.X500_UNIQUE_IDENTIFIER, str(unique_identifier))
        )
    if organization:
        subject_name.append(x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, organization))
    if email_address:
        subject_name.append(x509.NameAttribute(x509.NameOID.EMAIL_ADDRESS, email_address))
    if country_name:
        subject_name.append(x509.NameAttribute(x509.NameOID.COUNTRY_NAME, country_name))
    if state_or_province_name:
        subject_name.append(
            x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, state_or_province_name)
        )
    if locality_name:
        subject_name.append(x509.NameAttribute(x509.NameOID.LOCALITY_NAME, locality_name))
    csr = x509.CertificateSigningRequestBuilder(subject_name=x509.Name(subject_name))

    _sans: List[x509.GeneralName] = []
    if sans_oid:
        _sans.extend([x509.RegisteredID(x509.ObjectIdentifier(san)) for san in sans_oid])
    if sans_ip:
        _sans.extend([x509.IPAddress(ipaddress.ip_address(san)) for san in sans_ip])
    if sans:
        _sans.extend([x509.DNSName(san) for san in sans])
    if sans_dns:
        _sans.extend([x509.DNSName(san) for san in sans_dns])
    if _sans:
        csr = csr.add_extension(x509.SubjectAlternativeName(set(_sans)), critical=False)

    if additional_critical_extensions:
        for extension in additional_critical_extensions:
            csr = csr.add_extension(extension, critical=True)

    signed_certificate = csr.sign(signing_key, hashes.SHA256())  # type: ignore[arg-type]
    return signed_certificate.public_bytes(serialization.Encoding.PEM)


def get_sha256_hex(data: str) -> str:
    """Calculate the hash of the provided data and return the hexadecimal representation."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(data.encode())
    return digest.finalize().hex()


def csr_matches_certificate(csr: str, cert: str) -> bool:
    """Check if a CSR matches a certificate.

    Args:
        csr (str): Certificate Signing Request as a string
        cert (str): Certificate as a string
    Returns:
        bool: True/False depending on whether the CSR matches the certificate.
    """
    csr_object = x509.load_pem_x509_csr(csr.encode("utf-8"))
    cert_object = x509.load_pem_x509_certificate(cert.encode("utf-8"))

    if csr_object.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ) != cert_object.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ):
        return False
    return True


def _relation_data_is_valid(
    relation: Relation, app_or_unit: Union[Application, Unit], json_schema: dict
) -> bool:
    """Check whether relation data is valid based on json schema.

    Args:
        relation (Relation): Relation object
        app_or_unit (Union[Application, Unit]): Application or unit object
        json_schema (dict): Json schema

    Returns:
        bool: Whether relation data is valid.
    """
    relation_data = _load_relation_data(relation.data[app_or_unit])
    try:
        validate(instance=relation_data, schema=json_schema)
        return True
    except exceptions.ValidationError:
        return False


class CertificatesProviderCharmEvents(CharmEvents):
    """List of events that the TLS Certificates provider charm can leverage."""

    certificate_creation_request = EventSource(CertificateCreationRequestEvent)
    certificate_revocation_request = EventSource(CertificateRevocationRequestEvent)


class CertificatesRequirerCharmEvents(CharmEvents):
    """List of events that the TLS Certificates requirer charm can leverage."""

    certificate_available = EventSource(CertificateAvailableEvent)
    certificate_expiring = EventSource(CertificateExpiringEvent)
    certificate_invalidated = EventSource(CertificateInvalidatedEvent)
    all_certificates_invalidated = EventSource(AllCertificatesInvalidatedEvent)


class TLSCertificatesProvidesV3(Object):
    """TLS certificates provider class to be instantiated by TLS certificates providers."""

    on = CertificatesProviderCharmEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: CharmBase, relationship_name: str):
        super().__init__(charm, relationship_name)
        self.framework.observe(
            charm.on[relationship_name].relation_changed, self._on_relation_changed
        )
        self.charm = charm
        self.relationship_name = relationship_name

    def _load_app_relation_data(self, relation: Relation) -> dict:
        """Load relation data from the application relation data bag.

        Json loads all data.

        Args:
            relation: Relation data from the application databag

        Returns:
            dict: Relation data in dict format.
        """
        # If unit is not leader, it does not try to reach relation data.
        if not self.model.unit.is_leader():
            return {}
        return _load_relation_data(relation.data[self.charm.app])

    def _add_certificate(
        self,
        relation_id: int,
        certificate: str,
        certificate_signing_request: str,
        ca: str,
        chain: List[str],
        recommended_expiry_notification_time: Optional[int] = None,
    ) -> None:
        """Add certificate to relation data.

        Args:
            relation_id (int): Relation id
            certificate (str): Certificate
            certificate_signing_request (str): Certificate Signing Request
            ca (str): CA Certificate
            chain (list): CA Chain
            recommended_expiry_notification_time (int):
                Time in hours before the certificate expires to notify the user.

        Returns:
            None
        """
        relation = self.model.get_relation(
            relation_name=self.relationship_name, relation_id=relation_id
        )
        if not relation:
            raise RuntimeError(
                f"Relation {self.relationship_name} does not exist - "
                f"The certificate request can't be completed"
            )
        new_certificate = {
            "certificate": certificate,
            "certificate_signing_request": certificate_signing_request,
            "ca": ca,
            "chain": chain,
            "recommended_expiry_notification_time": recommended_expiry_notification_time,
        }
        provider_relation_data = self._load_app_relation_data(relation)
        provider_certificates = provider_relation_data.get("certificates", [])
        certificates = copy.deepcopy(provider_certificates)
        if new_certificate in certificates:
            logger.info("Certificate already in relation data - Doing nothing")
            return
        certificates.append(new_certificate)
        relation.data[self.model.app]["certificates"] = json.dumps(certificates)

    def _remove_certificate(
        self,
        relation_id: int,
        certificate: Optional[str] = None,
        certificate_signing_request: Optional[str] = None,
    ) -> None:
        """Remove certificate from a given relation based on user provided certificate or csr.

        Args:
            relation_id (int): Relation id
            certificate (str): Certificate (optional)
            certificate_signing_request: Certificate signing request (optional)

        Returns:
            None
        """
        relation = self.model.get_relation(
            relation_name=self.relationship_name,
            relation_id=relation_id,
        )
        if not relation:
            raise RuntimeError(
                f"Relation {self.relationship_name} with relation id {relation_id} does not exist"
            )
        provider_relation_data = self._load_app_relation_data(relation)
        provider_certificates = provider_relation_data.get("certificates", [])
        certificates = copy.deepcopy(provider_certificates)
        for certificate_dict in certificates:
            if certificate and certificate_dict["certificate"] == certificate:
                certificates.remove(certificate_dict)
            if (
                certificate_signing_request
                and certificate_dict["certificate_signing_request"] == certificate_signing_request
            ):
                certificates.remove(certificate_dict)
        relation.data[self.model.app]["certificates"] = json.dumps(certificates)

    def revoke_all_certificates(self) -> None:
        """Revoke all certificates of this provider.

        This method is meant to be used when the Root CA has changed.
        """
        for relation in self.model.relations[self.relationship_name]:
            provider_relation_data = self._load_app_relation_data(relation)
            provider_certificates = copy.deepcopy(provider_relation_data.get("certificates", []))
            for certificate in provider_certificates:
                certificate["revoked"] = True
            relation.data[self.model.app]["certificates"] = json.dumps(provider_certificates)

    def set_relation_certificate(
        self,
        certificate: str,
        certificate_signing_request: str,
        ca: str,
        chain: List[str],
        relation_id: int,
        recommended_expiry_notification_time: Optional[int] = None,
    ) -> None:
        """Add certificates to relation data.

        Args:
            certificate (str): Certificate
            certificate_signing_request (str): Certificate signing request
            ca (str): CA Certificate
            chain (list): CA Chain
            relation_id (int): Juju relation ID
            recommended_expiry_notification_time (int):
                Recommended time in hours before the certificate expires to notify the user.

        Returns:
            None
        """
        if not self.model.unit.is_leader():
            return
        certificates_relation = self.model.get_relation(
            relation_name=self.relationship_name, relation_id=relation_id
        )
        if not certificates_relation:
            raise RuntimeError(f"Relation {self.relationship_name} does not exist")
        self._remove_certificate(
            certificate_signing_request=certificate_signing_request.strip(),
            relation_id=relation_id,
        )
        self._add_certificate(
            relation_id=relation_id,
            certificate=certificate.strip(),
            certificate_signing_request=certificate_signing_request.strip(),
            ca=ca.strip(),
            chain=[cert.strip() for cert in chain],
            recommended_expiry_notification_time=recommended_expiry_notification_time,
        )

    def remove_certificate(self, certificate: str) -> None:
        """Remove a given certificate from relation data.

        Args:
            certificate (str): TLS Certificate

        Returns:
            None
        """
        certificates_relation = self.model.relations[self.relationship_name]
        if not certificates_relation:
            raise RuntimeError(f"Relation {self.relationship_name} does not exist")
        for certificate_relation in certificates_relation:
            self._remove_certificate(certificate=certificate, relation_id=certificate_relation.id)

    def get_issued_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return a List of issued (non revoked) certificates.

        Returns:
            List: List of ProviderCertificate objects
        """
        provider_certificates = self.get_provider_certificates(relation_id=relation_id)
        return [certificate for certificate in provider_certificates if not certificate.revoked]

    def get_provider_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return a List of issued certificates.

        Returns:
            List: List of ProviderCertificate objects
        """
        certificates: List[ProviderCertificate] = []
        relations = (
            [
                relation
                for relation in self.model.relations[self.relationship_name]
                if relation.id == relation_id
            ]
            if relation_id is not None
            else self.model.relations.get(self.relationship_name, [])
        )
        for relation in relations:
            if not relation.app:
                logger.warning("Relation %s does not have an application", relation.id)
                continue
            provider_relation_data = self._load_app_relation_data(relation)
            provider_certificates = provider_relation_data.get("certificates", [])
            for certificate in provider_certificates:
                try:
                    certificate_object = x509.load_pem_x509_certificate(
                        data=certificate["certificate"].encode()
                    )
                except ValueError as e:
                    logger.error("Could not load certificate - Skipping: %s", e)
                    continue
                provider_certificate = ProviderCertificate(
                    relation_id=relation.id,
                    application_name=relation.app.name,
                    csr=certificate["certificate_signing_request"],
                    certificate=certificate["certificate"],
                    ca=certificate["ca"],
                    chain=certificate["chain"],
                    revoked=certificate.get("revoked", False),
                    expiry_time=certificate_object.not_valid_after_utc,
                    expiry_notification_time=certificate.get(
                        "recommended_expiry_notification_time"
                    ),
                )
                certificates.append(provider_certificate)
        return certificates

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle relation changed event.

        Looks at the relation data and either emits:
        - certificate request event: If the unit relation data contains a CSR for which
            a certificate does not exist in the provider relation data.
        - certificate revocation event: If the provider relation data contains a CSR for which
            a csr does not exist in the requirer relation data.

        Args:
            event: Juju event

        Returns:
            None
        """
        if event.unit is None:
            logger.error("Relation_changed event does not have a unit.")
            return
        if not self.model.unit.is_leader():
            return
        if not _relation_data_is_valid(event.relation, event.unit, REQUIRER_JSON_SCHEMA):
            logger.debug("Relation data did not pass JSON Schema validation")
            return
        provider_certificates = self.get_provider_certificates(relation_id=event.relation.id)
        requirer_csrs = self.get_requirer_csrs(relation_id=event.relation.id)
        provider_csrs = [
            certificate_creation_request.csr
            for certificate_creation_request in provider_certificates
        ]
        for certificate_request in requirer_csrs:
            if certificate_request.csr not in provider_csrs:
                self.on.certificate_creation_request.emit(
                    certificate_signing_request=certificate_request.csr,
                    relation_id=certificate_request.relation_id,
                    is_ca=certificate_request.is_ca,
                )
        self._revoke_certificates_for_which_no_csr_exists(relation_id=event.relation.id)

    def _revoke_certificates_for_which_no_csr_exists(self, relation_id: int) -> None:
        """Revoke certificates for which no unit has a CSR.

        Goes through all generated certificates and compare against the list of CSRs for all units.

        Returns:
            None
        """
        provider_certificates = self.get_unsolicited_certificates(relation_id=relation_id)
        for provider_certificate in provider_certificates:
            self.on.certificate_revocation_request.emit(
                certificate=provider_certificate.certificate,
                certificate_signing_request=provider_certificate.csr,
                ca=provider_certificate.ca,
                chain=provider_certificate.chain,
            )
            self.remove_certificate(certificate=provider_certificate.certificate)

    def get_unsolicited_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return provider certificates for which no certificate requests exists.

        Those certificates should be revoked.
        """
        unsolicited_certificates: List[ProviderCertificate] = []
        provider_certificates = self.get_provider_certificates(relation_id=relation_id)
        requirer_csrs = self.get_requirer_csrs(relation_id=relation_id)
        list_of_csrs = [csr.csr for csr in requirer_csrs]
        for certificate in provider_certificates:
            if certificate.csr not in list_of_csrs:
                unsolicited_certificates.append(certificate)
        return unsolicited_certificates

    def get_outstanding_certificate_requests(
        self, relation_id: Optional[int] = None
    ) -> List[RequirerCSR]:
        """Return CSR's for which no certificate has been issued.

        Args:
            relation_id (int): Relation id

        Returns:
            list: List of RequirerCSR objects.
        """
        requirer_csrs = self.get_requirer_csrs(relation_id=relation_id)
        outstanding_csrs: List[RequirerCSR] = []
        for relation_csr in requirer_csrs:
            if not self.certificate_issued_for_csr(
                app_name=relation_csr.application_name,
                csr=relation_csr.csr,
                relation_id=relation_id,
            ):
                outstanding_csrs.append(relation_csr)
        return outstanding_csrs

    def get_requirer_csrs(self, relation_id: Optional[int] = None) -> List[RequirerCSR]:
        """Return a list of requirers' CSRs.

        It returns CSRs from all relations if relation_id is not specified.
        CSRs are returned per relation id, application name and unit name.

        Returns:
            list: List[RequirerCSR]
        """
        relation_csrs: List[RequirerCSR] = []
        relations = (
            [
                relation
                for relation in self.model.relations[self.relationship_name]
                if relation.id == relation_id
            ]
            if relation_id is not None
            else self.model.relations.get(self.relationship_name, [])
        )

        for relation in relations:
            for unit in relation.units:
                requirer_relation_data = _load_relation_data(relation.data[unit])
                unit_csrs_list = requirer_relation_data.get("certificate_signing_requests", [])
                for unit_csr in unit_csrs_list:
                    csr = unit_csr.get("certificate_signing_request")
                    if not csr:
                        logger.warning("No CSR found in relation data - Skipping")
                        continue
                    ca = unit_csr.get("ca", False)
                    if not relation.app:
                        logger.warning("No remote app in relation - Skipping")
                        continue
                    relation_csr = RequirerCSR(
                        relation_id=relation.id,
                        application_name=relation.app.name,
                        unit_name=unit.name,
                        csr=csr,
                        is_ca=ca,
                    )
                    relation_csrs.append(relation_csr)
        return relation_csrs

    def certificate_issued_for_csr(
        self, app_name: str, csr: str, relation_id: Optional[int]
    ) -> bool:
        """Check whether a certificate has been issued for a given CSR.

        Args:
            app_name (str): Application name that the CSR belongs to.
            csr (str): Certificate Signing Request.
            relation_id (Optional[int]): Relation ID

        Returns:
            bool: True/False depending on whether a certificate has been issued for the given CSR.
        """
        issued_certificates_per_csr = self.get_issued_certificates(relation_id=relation_id)
        for issued_certificate in issued_certificates_per_csr:
            if issued_certificate.csr == csr and issued_certificate.application_name == app_name:
                return csr_matches_certificate(csr, issued_certificate.certificate)
        return False


class TLSCertificatesRequiresV3(Object):
    """TLS certificates requirer class to be instantiated by TLS certificates requirers."""

    on = CertificatesRequirerCharmEvents()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: CharmBase,
        relationship_name: str,
        expiry_notification_time: Optional[int] = None,
    ):
        """Generate/use private key and observes relation changed event.

        Args:
            charm: Charm object
            relationship_name: Juju relation name
            expiry_notification_time (int): Number of hours prior to certificate expiry.
                Used to trigger the CertificateExpiring event.
                This value is used as a recommendation only,
                The actual value is calculated taking into account the provider's recommendation.
        """
        super().__init__(charm, relationship_name)
        if not JujuVersion.from_environ().has_secrets:
            logger.warning("This version of the TLS library requires Juju secrets (Juju >= 3.0)")
        self.relationship_name = relationship_name
        self.charm = charm
        self.expiry_notification_time = expiry_notification_time
        self.framework.observe(
            charm.on[relationship_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[relationship_name].relation_broken, self._on_relation_broken
        )
        self.framework.observe(charm.on.secret_expired, self._on_secret_expired)

    def get_requirer_csrs(self) -> List[RequirerCSR]:
        """Return list of requirer's CSRs from relation unit data.

        Returns:
            list: List of RequirerCSR objects.
        """
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            return []
        requirer_csrs = []
        requirer_relation_data = _load_relation_data(relation.data[self.model.unit])
        requirer_csrs_dict = requirer_relation_data.get("certificate_signing_requests", [])
        for requirer_csr_dict in requirer_csrs_dict:
            csr = requirer_csr_dict.get("certificate_signing_request")
            if not csr:
                logger.warning("No CSR found in relation data - Skipping")
                continue
            ca = requirer_csr_dict.get("ca", False)
            relation_csr = RequirerCSR(
                relation_id=relation.id,
                application_name=self.model.app.name,
                unit_name=self.model.unit.name,
                csr=csr,
                is_ca=ca,
            )
            requirer_csrs.append(relation_csr)
        return requirer_csrs

    def get_provider_certificates(self) -> List[ProviderCertificate]:
        """Return list of certificates from the provider's relation data."""
        provider_certificates: List[ProviderCertificate] = []
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            logger.debug("No relation: %s", self.relationship_name)
            return []
        if not relation.app:
            logger.debug("No remote app in relation: %s", self.relationship_name)
            return []
        provider_relation_data = _load_relation_data(relation.data[relation.app])
        provider_certificate_dicts = provider_relation_data.get("certificates", [])
        for provider_certificate_dict in provider_certificate_dicts:
            certificate = provider_certificate_dict.get("certificate")
            if not certificate:
                logger.warning("No certificate found in relation data - Skipping")
                continue
            try:
                certificate_object = x509.load_pem_x509_certificate(data=certificate.encode())
            except ValueError as e:
                logger.error("Could not load certificate - Skipping: %s", e)
                continue
            ca = provider_certificate_dict.get("ca")
            chain = provider_certificate_dict.get("chain", [])
            csr = provider_certificate_dict.get("certificate_signing_request")
            recommended_expiry_notification_time = provider_certificate_dict.get(
                "recommended_expiry_notification_time"
            )
            expiry_time = certificate_object.not_valid_after_utc
            validity_start_time = certificate_object.not_valid_before_utc
            expiry_notification_time = calculate_expiry_notification_time(
                validity_start_time=validity_start_time,
                expiry_time=expiry_time,
                provider_recommended_notification_time=recommended_expiry_notification_time,
                requirer_recommended_notification_time=self.expiry_notification_time,
            )
            if not csr:
                logger.warning("No CSR found in relation data - Skipping")
                continue
            revoked = provider_certificate_dict.get("revoked", False)
            provider_certificate = ProviderCertificate(
                relation_id=relation.id,
                application_name=relation.app.name,
                csr=csr,
                certificate=certificate,
                ca=ca,
                chain=chain,
                revoked=revoked,
                expiry_time=expiry_time,
                expiry_notification_time=expiry_notification_time,
            )
            provider_certificates.append(provider_certificate)
        return provider_certificates

    def _add_requirer_csr_to_relation_data(self, csr: str, is_ca: bool) -> None:
        """Add CSR to relation data.

        Args:
            csr (str): Certificate Signing Request
            is_ca (bool): Whether the certificate is a CA certificate

        Returns:
            None
        """
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            raise RuntimeError(
                f"Relation {self.relationship_name} does not exist - "
                f"The certificate request can't be completed"
            )
        for requirer_csr in self.get_requirer_csrs():
            if requirer_csr.csr == csr and requirer_csr.is_ca == is_ca:
                logger.info("CSR already in relation data - Doing nothing")
                return
        new_csr_dict = {
            "certificate_signing_request": csr,
            "ca": is_ca,
        }
        requirer_relation_data = _load_relation_data(relation.data[self.model.unit])
        existing_relation_data = requirer_relation_data.get("certificate_signing_requests", [])
        new_relation_data = copy.deepcopy(existing_relation_data)
        new_relation_data.append(new_csr_dict)
        relation.data[self.model.unit]["certificate_signing_requests"] = json.dumps(
            new_relation_data
        )

    def _remove_requirer_csr_from_relation_data(self, csr: str) -> None:
        """Remove CSR from relation data.

        Args:
            csr (str): Certificate signing request

        Returns:
            None
        """
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            raise RuntimeError(
                f"Relation {self.relationship_name} does not exist - "
                f"The certificate request can't be completed"
            )
        if not self.get_requirer_csrs():
            logger.info("No CSRs in relation data - Doing nothing")
            return
        requirer_relation_data = _load_relation_data(relation.data[self.model.unit])
        existing_relation_data = requirer_relation_data.get("certificate_signing_requests", [])
        new_relation_data = copy.deepcopy(existing_relation_data)
        for requirer_csr in new_relation_data:
            if requirer_csr["certificate_signing_request"] == csr:
                new_relation_data.remove(requirer_csr)
        relation.data[self.model.unit]["certificate_signing_requests"] = json.dumps(
            new_relation_data
        )

    def request_certificate_creation(
        self, certificate_signing_request: bytes, is_ca: bool = False
    ) -> None:
        """Request TLS certificate to provider charm.

        Args:
            certificate_signing_request (bytes): Certificate Signing Request
            is_ca (bool): Whether the certificate is a CA certificate

        Returns:
            None
        """
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            raise RuntimeError(
                f"Relation {self.relationship_name} does not exist - "
                f"The certificate request can't be completed"
            )
        self._add_requirer_csr_to_relation_data(
            certificate_signing_request.decode().strip(), is_ca=is_ca
        )
        logger.info("Certificate request sent to provider")

    def request_certificate_revocation(self, certificate_signing_request: bytes) -> None:
        """Remove CSR from relation data.

        The provider of this relation is then expected to remove certificates associated to this
        CSR from the relation data as well and emit a request_certificate_revocation event for the
        provider charm to interpret.

        Args:
            certificate_signing_request (bytes): Certificate Signing Request

        Returns:
            None
        """
        self._remove_requirer_csr_from_relation_data(certificate_signing_request.decode().strip())
        logger.info("Certificate revocation sent to provider")

    def request_certificate_renewal(
        self, old_certificate_signing_request: bytes, new_certificate_signing_request: bytes
    ) -> None:
        """Renew certificate.

        Removes old CSR from relation data and adds new one.

        Args:
            old_certificate_signing_request: Old CSR
            new_certificate_signing_request: New CSR

        Returns:
            None
        """
        try:
            self.request_certificate_revocation(
                certificate_signing_request=old_certificate_signing_request
            )
        except RuntimeError:
            logger.warning("Certificate revocation failed.")
        self.request_certificate_creation(
            certificate_signing_request=new_certificate_signing_request
        )
        logger.info("Certificate renewal request completed.")

    def get_assigned_certificates(self) -> List[ProviderCertificate]:
        """Get a list of certificates that were assigned to this unit.

        Returns:
            List: List[ProviderCertificate]
        """
        assigned_certificates = []
        for requirer_csr in self.get_certificate_signing_requests(fulfilled_only=True):
            if cert := self._find_certificate_in_relation_data(requirer_csr.csr):
                assigned_certificates.append(cert)
        return assigned_certificates

    def get_expiring_certificates(self) -> List[ProviderCertificate]:
        """Get a list of certificates that were assigned to this unit that are expiring or expired.

        Returns:
            List: List[ProviderCertificate]
        """
        expiring_certificates: List[ProviderCertificate] = []
        for requirer_csr in self.get_certificate_signing_requests(fulfilled_only=True):
            if cert := self._find_certificate_in_relation_data(requirer_csr.csr):
                if not cert.expiry_time or not cert.expiry_notification_time:
                    continue
                if datetime.now(timezone.utc) > cert.expiry_notification_time:
                    expiring_certificates.append(cert)
        return expiring_certificates

    def get_certificate_signing_requests(
        self,
        fulfilled_only: bool = False,
        unfulfilled_only: bool = False,
    ) -> List[RequirerCSR]:
        """Get the list of CSR's that were sent to the provider.

        You can choose to get only the CSR's that have a certificate assigned or only the CSR's
        that don't.

        Args:
            fulfilled_only (bool): This option will discard CSRs that don't have certificates yet.
            unfulfilled_only (bool): This option will discard CSRs that have certificates signed.

        Returns:
            List of RequirerCSR objects.
        """
        csrs = []
        for requirer_csr in self.get_requirer_csrs():
            cert = self._find_certificate_in_relation_data(requirer_csr.csr)
            if (unfulfilled_only and cert) or (fulfilled_only and not cert):
                continue
            csrs.append(requirer_csr)

        return csrs

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle relation changed event.

        Goes through all providers certificates that match a requested CSR.

        If the provider certificate is revoked, emit a CertificateInvalidateEvent,
        otherwise emit a CertificateAvailableEvent.

        Remove the secret for revoked certificate, or add a secret with the correct expiry
        time for new certificates.

        Args:
            event: Juju event

        Returns:
            None
        """
        if not event.app:
            logger.warning("No remote app in relation - Skipping")
            return
        if not _relation_data_is_valid(event.relation, event.app, PROVIDER_JSON_SCHEMA):
            logger.debug("Relation data did not pass JSON Schema validation")
            return
        provider_certificates = self.get_provider_certificates()
        requirer_csrs = [
            certificate_creation_request.csr
            for certificate_creation_request in self.get_requirer_csrs()
        ]
        for certificate in provider_certificates:
            if certificate.csr in requirer_csrs:
                csr_in_sha256_hex = get_sha256_hex(certificate.csr)
                if certificate.revoked:
                    with suppress(SecretNotFoundError):
                        logger.debug(
                            "Removing secret with label %s",
                            f"{LIBID}-{csr_in_sha256_hex}",
                        )
                        secret = self.model.get_secret(label=f"{LIBID}-{csr_in_sha256_hex}")
                        secret.remove_all_revisions()
                    self.on.certificate_invalidated.emit(
                        reason="revoked",
                        certificate=certificate.certificate,
                        certificate_signing_request=certificate.csr,
                        ca=certificate.ca,
                        chain=certificate.chain,
                    )
                else:
                    try:
                        secret = self.model.get_secret(label=f"{LIBID}-{csr_in_sha256_hex}")
                        logger.debug(
                            "Setting secret with label %s", f"{LIBID}-{csr_in_sha256_hex}"
                        )
                        # Juju < 3.6 will create a new revision even if the content is the same
                        if (
                            secret.get_content(refresh=True).get("certificate", "")
                            == certificate.certificate
                        ):
                            logger.debug(
                                "Secret %s with correct certificate already exists",
                                f"{LIBID}-{csr_in_sha256_hex}",
                            )
                            continue
                        secret.set_content(
                            {"certificate": certificate.certificate, "csr": certificate.csr}
                        )
                        secret.set_info(
                            expire=self._get_next_secret_expiry_time(certificate),
                        )
                    except SecretNotFoundError:
                        logger.debug(
                            "Creating new secret with label %s", f"{LIBID}-{csr_in_sha256_hex}"
                        )
                        secret = self.charm.unit.add_secret(
                            {"certificate": certificate.certificate, "csr": certificate.csr},
                            label=f"{LIBID}-{csr_in_sha256_hex}",
                            expire=self._get_next_secret_expiry_time(certificate),
                        )
                    self.on.certificate_available.emit(
                        certificate_signing_request=certificate.csr,
                        certificate=certificate.certificate,
                        ca=certificate.ca,
                        chain=certificate.chain,
                    )

    def _get_next_secret_expiry_time(self, certificate: ProviderCertificate) -> Optional[datetime]:
        """Return the expiry time or expiry notification time.

        Extracts the expiry time from the provided certificate, calculates the
        expiry notification time and return the closest of the two, that is in
        the future.

        Args:
            certificate: ProviderCertificate object

        Returns:
            Optional[datetime]: None if the certificate expiry time cannot be read,
                                next expiry time otherwise.
        """
        if not certificate.expiry_time or not certificate.expiry_notification_time:
            return None
        return _get_closest_future_time(
            certificate.expiry_notification_time,
            certificate.expiry_time,
        )

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle Relation Broken Event.

        Emitting `all_certificates_invalidated` from `relation-broken` rather
        than `relation-departed` since certs are stored in app data.

        Args:
            event: Juju event

        Returns:
            None
        """
        self.on.all_certificates_invalidated.emit()

    def _on_secret_expired(self, event: SecretExpiredEvent) -> None:
        """Handle Secret Expired Event.

        Loads the certificate from the secret, and will emit 1 of 2
        events.

        If the certificate is not yet expired, emits CertificateExpiringEvent
        and updates the expiry time of the secret to the exact expiry time on
        the certificate.

        If the certificate is expired, emits CertificateInvalidedEvent and
        deletes the secret.

        Args:
            event (SecretExpiredEvent): Juju event
        """
        csr = self._get_csr_from_secret(event.secret)
        if not csr:
            logger.error("Failed to get CSR from secret %s", event.secret.label)
            return
        provider_certificate = self._find_certificate_in_relation_data(csr)
        if not provider_certificate:
            # A secret expired but we did not find matching certificate. Cleaning up
            logger.warning(
                "Failed to find matching certificate for csr, cleaning up secret %s",
                event.secret.label,
            )
            event.secret.remove_all_revisions()
            return

        if not provider_certificate.expiry_time:
            # A secret expired but matching certificate is invalid. Cleaning up
            logger.warning(
                "Certificate matching csr is invalid, cleaning up secret %s",
                event.secret.label,
            )
            event.secret.remove_all_revisions()
            return

        if datetime.now(timezone.utc) < provider_certificate.expiry_time:
            logger.warning("Certificate almost expired")
            self.on.certificate_expiring.emit(
                certificate=provider_certificate.certificate,
                expiry=provider_certificate.expiry_time.isoformat(),
            )
            event.secret.set_info(
                expire=provider_certificate.expiry_time,
            )
        else:
            logger.warning("Certificate is expired")
            self.on.certificate_invalidated.emit(
                reason="expired",
                certificate=provider_certificate.certificate,
                certificate_signing_request=provider_certificate.csr,
                ca=provider_certificate.ca,
                chain=provider_certificate.chain,
            )
            self.request_certificate_revocation(provider_certificate.certificate.encode())
            event.secret.remove_all_revisions()

    def _find_certificate_in_relation_data(self, csr: str) -> Optional[ProviderCertificate]:
        """Return the certificate that match the given CSR."""
        for provider_certificate in self.get_provider_certificates():
            if provider_certificate.csr != csr:
                continue
            return provider_certificate
        return None

    def _get_csr_from_secret(self, secret: Secret) -> Union[str, None]:
        """Extract the CSR from the secret label or content.

        This function is a workaround to maintain backwards compatibility
        and fix the issue reported in
        https://github.com/canonical/tls-certificates-interface/issues/228
        """
        try:
            content = secret.get_content(refresh=True)
        except SecretNotFoundError:
            return None
        if not (csr := content.get("csr", None)):
            # In versions <14 of the Lib we were storing the CSR in the label of the secret
            # The CSR now is stored int the content of the secret, which was a breaking change
            # Here we get the CSR if the secret was created by an app using libpatch 14 or lower
            if secret.label and secret.label.startswith(f"{LIBID}-"):
                csr = secret.label[len(f"{LIBID}-") :]
        return csr
