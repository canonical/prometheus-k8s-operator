# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""## Overview.

This document explains how to use the `CertHandler` class to
create and manage TLS certificates through the `tls_certificates` interface.

The goal of the CertHandler is to provide a wrapper to the `tls_certificates`
library functions to make the charm integration smoother.

## Library Usage

This library should be used to create a `CertHandler` object, as per the
following example:

```python
self.cert_handler = CertHandler(
    charm=self,
    key="my-app-cert-manager",
    cert_subject="unit_name",  # Optional
)
```

You can then observe the library's custom event and make use of the key and cert:
```python
self.framework.observe(self.cert_handler.on.cert_changed, self._on_server_cert_changed)

container.push(keypath, self.cert_handler.private_key)
container.push(certpath, self.cert_handler.servert_cert)
```

Since this library uses [Juju Secrets](https://juju.is/docs/juju/secret) it requires Juju >= 3.0.3.
"""
import ipaddress
import socket
from itertools import filterfalse
from typing import List, Optional, Union

try:
    from charms.tls_certificates_interface.v3.tls_certificates import (  # type: ignore
        AllCertificatesInvalidatedEvent,
        CertificateAvailableEvent,
        CertificateExpiringEvent,
        CertificateInvalidatedEvent,
        TLSCertificatesRequiresV3,
        generate_csr,
        generate_private_key,
    )
except ImportError as e:
    raise ImportError(
        "failed to import charms.tls_certificates_interface.v2.tls_certificates; "
        "Either the library itself is missing (please get it through charmcraft fetch-lib) "
        "or one of its dependencies is unmet."
    ) from e

import logging

from ops.charm import CharmBase, RelationBrokenEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.jujuversion import JujuVersion
from ops.model import SecretNotFoundError

logger = logging.getLogger(__name__)


LIBID = "b5cd5cd580f3428fa5f59a8876dcbe6a"
LIBAPI = 1
LIBPATCH = 5


def is_ip_address(value: str) -> bool:
    """Return True if the input value is a valid IPv4 address; False otherwise."""
    try:
        ipaddress.IPv4Address(value)
        return True
    except ipaddress.AddressValueError:
        return False


class CertChanged(EventBase):
    """Event raised when a cert is changed (becomes available or revoked)."""


class CertHandlerEvents(ObjectEvents):
    """Events for CertHandler."""

    cert_changed = EventSource(CertChanged)


class CertHandler(Object):
    """A wrapper for the requirer side of the TLS Certificates charm library."""

    on = CertHandlerEvents()  # pyright: ignore

    def __init__(
        self,
        charm: CharmBase,
        *,
        key: str,
        certificates_relation_name: str = "certificates",
        cert_subject: Optional[str] = None,
        sans: Optional[List[str]] = None,
    ):
        """CertHandler is used to wrap TLS Certificates management operations for charms.

        CerHandler manages one single cert.

        Args:
            charm: The owning charm.
            key: A manually-crafted, static, unique identifier used by ops to identify events.
             It shouldn't change between one event to another.
            certificates_relation_name: Must match metadata.yaml.
            cert_subject: Custom subject. Name collisions are under the caller's responsibility.
            sans: DNS names. If none are given, use FQDN.
        """
        super().__init__(charm, key)
        self._check_juju_supports_secrets()

        self.charm = charm
        # We need to sanitize the unit name, otherwise route53 complains:
        # "urn:ietf:params:acme:error:malformed" :: Domain name contains an invalid character
        self.cert_subject = charm.unit.name.replace("/", "-") if not cert_subject else cert_subject

        # Use fqdn only if no SANs were given, and drop empty/duplicate SANs
        sans = list(set(filter(None, (sans or [socket.getfqdn()]))))
        self.sans_ip = list(filter(is_ip_address, sans))
        self.sans_dns = list(filterfalse(is_ip_address, sans))

        self.certificates_relation_name = certificates_relation_name
        self.certificates = TLSCertificatesRequiresV3(self.charm, self.certificates_relation_name)

        self.framework.observe(
            self.charm.on.config_changed,
            self._on_config_changed,
        )
        self.framework.observe(
            self.charm.on[self.certificates_relation_name].relation_joined,  # pyright: ignore
            self._on_certificates_relation_joined,
        )
        self.framework.observe(
            self.certificates.on.certificate_available,  # pyright: ignore
            self._on_certificate_available,
        )
        self.framework.observe(
            self.certificates.on.certificate_expiring,  # pyright: ignore
            self._on_certificate_expiring,
        )
        self.framework.observe(
            self.certificates.on.certificate_invalidated,  # pyright: ignore
            self._on_certificate_invalidated,
        )
        self.framework.observe(
            self.certificates.on.all_certificates_invalidated,  # pyright: ignore
            self._on_all_certificates_invalidated,
        )
        self.framework.observe(
            self.charm.on[self.certificates_relation_name].relation_broken,  # pyright: ignore
            self._on_certificates_relation_broken,
        )

    @property
    def enabled(self) -> bool:
        """Boolean indicating whether the charm has a tls_certificates relation."""
        # We need to check for units as a temporary workaround because of https://bugs.launchpad.net/juju/+bug/2024583
        # This could in theory not work correctly on scale down to 0 but it is necessary for the moment.

        if not self.charm.model.get_relation(self.certificates_relation_name):
            return False

        if not self.charm.model.get_relation(
            self.certificates_relation_name
        ).units:  # pyright: ignore
            return False

        if not self.charm.model.get_relation(
            self.certificates_relation_name
        ).app:  # pyright: ignore
            return False

        if not self.charm.model.get_relation(
            self.certificates_relation_name
        ).data:  # pyright: ignore
            return False

        return True

    def _on_certificates_relation_joined(self, _) -> None:
        self._generate_privkey()
        self._generate_csr()

    def _generate_privkey(self):
        # Generate priv key unless done already
        # TODO figure out how to go about key rotation.

        if not (relation := self.charm.model.get_relation(self.certificates_relation_name)):
            return

        if not self.private_key:
            private_key = generate_private_key()
            secret = self.charm.unit.add_secret({"private-key": private_key.decode()})
            secret.grant(relation)
            relation.data[self.charm.unit]["private-key-secret-id"] = secret.id  # pyright: ignore

    def _on_config_changed(self, _):
        relation = self.charm.model.get_relation(self.certificates_relation_name)

        if not relation:
            return

        self._generate_privkey()
        self._generate_csr(renew=True)

    def _generate_csr(
        self, overwrite: bool = False, renew: bool = False, clear_cert: bool = False
    ):
        """Request a CSR "creation" if renew is False, otherwise request a renewal.

        Without overwrite=True, the CSR would be created only once, even if calling the method
        multiple times. This is useful needed because the order of peer-created and
        certificates-joined is not predictable.

        This method intentionally does not emit any events, leave it for caller's responsibility.
        """
        # if we are in a relation-broken hook, we might not have a relation to publish the csr to.
        if not self.charm.model.get_relation(self.certificates_relation_name):
            logger.warning(
                f"No {self.certificates_relation_name!r} relation found. " f"Cannot generate csr."
            )
            return

        # In case we already have a csr, do not overwrite it by default.
        if overwrite or renew or not self._csr:
            private_key = self.private_key
            if private_key is None:
                # FIXME: raise this in a less nested scope by
                #  generating privkey and csr in the same method.
                raise RuntimeError(
                    "private key unset. call _generate_privkey() before you call this method."
                )
            csr = generate_csr(
                private_key=private_key.encode(),
                subject=self.cert_subject,
                sans_dns=self.sans_dns,
                sans_ip=self.sans_ip,
            )

            if renew and self._csr:
                self.certificates.request_certificate_renewal(
                    old_certificate_signing_request=self._csr.encode(),
                    new_certificate_signing_request=csr,
                )
            else:
                logger.info(
                    "Creating CSR for %s with DNS %s and IPs %s",
                    self.cert_subject,
                    self.sans_dns,
                    self.sans_ip,
                )
                self.certificates.request_certificate_creation(certificate_signing_request=csr)

            # Note: CSR is being replaced with a new one, so until we get the new cert, we'd have
            # a mismatch between the CSR and the cert.
            # For some reason the csr contains a trailing '\n'. TODO figure out why
            self._csr = csr.decode().strip()

        if clear_cert:
            try:
                secret = self.model.get_secret(label="ca-certificate-chain")
                secret.remove_all_revisions()
            except SecretNotFoundError:
                logger.debug("Secret with label: 'ca-certificate-chain' not found")

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Get the certificate from the event and store it in a peer relation.

        Note: assuming "limit: 1" in metadata
        """
        event_csr = (
            event.certificate_signing_request.strip()
            if event.certificate_signing_request
            else None
        )
        if event_csr == self._csr:
            content = {
                "ca-cert": event.ca,
                "server-cert": event.certificate,
                "chain": event.chain_as_pem(),
                "csr": event_csr,
            }
            try:
                secret = self.model.get_secret(label="ca-certificate-chain")
            except SecretNotFoundError:
                if not (
                    relation := self.charm.model.get_relation(self.certificates_relation_name)
                ):
                    logger.error("Relation %s not found", self.certificates_relation_name)
                    return

                secret = self.charm.unit.add_secret(content, label="ca-certificate-chain")
                secret.grant(relation)
                relation.data[self.charm.unit]["secret-id"] = secret.id  # pyright: ignore
                self.on.cert_changed.emit()  # pyright: ignore

    def _retrieve_secret_id(self, secret_id_name: str) -> Optional[str]:
        if not (relation := self.charm.model.get_relation(self.certificates_relation_name)):
            return None

        if not (secret_id := relation.data[self.charm.unit].get(secret_id_name)):
            return None

        return secret_id

    def _retrieve_from_secret(self, value: str, secret_id_name: str) -> Optional[str]:
        if not (secret_id := self._retrieve_secret_id(secret_id_name)):
            return None

        if not (secret := self.model.get_secret(id=secret_id)):
            return None

        content = secret.get_content()
        return content.get(value)

    @property
    def private_key(self) -> Optional[str]:
        """Private key."""
        return self._retrieve_from_secret("private-key", "private-key-secret-id")

    @property
    def private_key_secret_id(self) -> Optional[str]:
        """ID of the Juju Secret for the Private key."""
        return self._retrieve_secret_id("private-key-secret-id")

    @property
    def _csr(self) -> Optional[str]:
        return self._retrieve_from_secret("csr", "csr-secret-id")

    @_csr.setter
    def _csr(self, value: str):
        if not (relation := self.charm.model.get_relation(self.certificates_relation_name)):
            return

        if not (secret_id := relation.data[self.charm.unit].get("csr-secret-id", None)):
            secret = self.charm.unit.add_secret({"csr": value})
            secret.grant(relation)
            relation.data[self.charm.unit]["csr-secret-id"] = secret.id  # pyright: ignore
            return

        secret = self.model.get_secret(id=secret_id)
        secret.set_content({"csr": value})

    @property
    def ca_cert(self) -> Optional[str]:
        """CA Certificate."""
        return self._retrieve_from_secret("ca-cert", "secret-id")

    @property
    def ca_server_cert_secret_id(self) -> Optional[str]:
        """CA server cert secret id."""
        return self._retrieve_secret_id("secret-id")

    @property
    def server_cert(self) -> Optional[str]:
        """Server Certificate."""
        return self._retrieve_from_secret("server-cert", "secret-id")

    @property
    def _chain(self) -> Optional[str]:
        return self._retrieve_from_secret("chain", "secret-id")

    @property
    def chain(self) -> Optional[str]:
        """Return the ca chain."""
        return self._chain

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        """Generate a new CSR and request certificate renewal."""
        if event.certificate == self.server_cert:
            self._generate_csr(renew=True)

    def _certificate_revoked(self, event) -> None:
        """Remove the certificate and generate a new CSR."""
        # Note: assuming "limit: 1" in metadata
        if event.certificate == self.server_cert:
            self._generate_csr(overwrite=True, clear_cert=True)
            self.on.cert_changed.emit()  # pyright: ignore

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        """Deal with certificate revocation and expiration."""
        if event.certificate != self.server_cert:
            return

        # if event.reason in ("revoked", "expired"):
        # Currently, the reason does not matter to us because the action is the same.
        self._generate_csr(overwrite=True, clear_cert=True)
        self.on.cert_changed.emit()  # pyright: ignore

    def _on_all_certificates_invalidated(self, _: AllCertificatesInvalidatedEvent) -> None:
        # Do what you want with this information, probably remove all certificates
        # Note: assuming "limit: 1" in metadata
        self._generate_csr(overwrite=True, clear_cert=True)
        self.on.cert_changed.emit()  # pyright: ignore

    def _on_certificates_relation_broken(self, _: RelationBrokenEvent) -> None:
        """Clear the certificates data when removing the relation."""
        try:
            secret = self.model.get_secret(label="csr-secret-id")
            secret.remove_all_revisions()
        except SecretNotFoundError:
            logger.debug("Secret 'csr-scret-id' not found")
        self.on.cert_changed.emit()  # pyright: ignore

    def _check_juju_supports_secrets(self) -> None:
        version = JujuVersion.from_environ()

        if not JujuVersion(version=str(version)).has_secrets:
            msg = f"Juju version {version} does not supports Secrets. Juju >= 3.0.3 is needed"
            logger.error(msg)
            raise RuntimeError(msg)
