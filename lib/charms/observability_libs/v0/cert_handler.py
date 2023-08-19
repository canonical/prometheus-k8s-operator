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
    peer_relation_name="replicas",
    cert_subject="unit_name",  # Optional
)
```

You can then observe the library's custom event and make use of the key and cert:
```python
self.framework.observe(self.cert_handler.on.cert_changed, self._on_server_cert_changed)

container.push(keypath, self.cert_handler.key)
container.push(certpath, self.cert_handler.cert)
```

This library requires a peer relation to be declared in the requirer's metadata. Peer relation data
is used for "persistent storage" of the private key and certs.
"""
import json
import socket
from typing import List, Optional, Union

try:
    from charms.tls_certificates_interface.v2.tls_certificates import (  # type: ignore
        AllCertificatesInvalidatedEvent,
        CertificateAvailableEvent,
        CertificateExpiringEvent,
        CertificateInvalidatedEvent,
        TLSCertificatesRequiresV2,
        generate_csr,
        generate_private_key,
    )
except ImportError:
    raise ImportError(
        "charms.tls_certificates_interface.v2.tls_certificates is missing; please get it through charmcraft fetch-lib"
    )
import logging

from ops.charm import CharmBase, RelationBrokenEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

logger = logging.getLogger(__name__)


LIBID = "b5cd5cd580f3428fa5f59a8876dcbe6a"
LIBAPI = 0
LIBPATCH = 7


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
        peer_relation_name: str,
        certificates_relation_name: str = "certificates",
        cert_subject: Optional[str] = None,
        extra_sans_dns: Optional[List[str]] = None,
    ):
        """CertHandler is used to wrap TLS Certificates management operations for charms.

        CerHandler manages one single cert.

        Args:
            charm: The owning charm.
            key: A manually-crafted, static, unique identifier used by ops to identify events.
             It shouldn't change between one event to another.
            peer_relation_name: Must match metadata.yaml.
            certificates_relation_name: Must match metadata.yaml.
            cert_subject: Custom subject. Name collisions are under the caller's responsibility.
            extra_sans_dns: DNS names. If none are given, use FQDN.
        """
        super().__init__(charm, key)

        self.charm = charm
        # We need to sanitize the unit name, otherwise route53 complains:
        # "urn:ietf:params:acme:error:malformed" :: Domain name contains an invalid character
        self.cert_subject = charm.unit.name.replace("/", "-") if not cert_subject else cert_subject

        # Use fqdn only if no SANs were given, and drop empty/duplicate SANs
        self.sans_dns = list(set(filter(None, (extra_sans_dns or [socket.getfqdn()]))))

        self.peer_relation_name = peer_relation_name
        self.certificates_relation_name = certificates_relation_name

        self.certificates = TLSCertificatesRequiresV2(self.charm, self.certificates_relation_name)

        self.framework.observe(
            self.charm.on.config_changed,
            self._on_config_changed,
        )
        self.framework.observe(
            self.charm.on.certificates_relation_joined,  # pyright: ignore
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

        # Peer relation events
        self.framework.observe(
            self.charm.on[self.peer_relation_name].relation_created, self._on_peer_relation_created
        )

    @property
    def enabled(self) -> bool:
        """Boolean indicating whether the charm has a tls_certificates relation."""
        # We need to check for units as a temporary workaround because of https://bugs.launchpad.net/juju/+bug/2024583
        # This could in theory not work correctly on scale down to 0 but it is necessary for the moment.
        return (
            len(self.charm.model.relations[self.certificates_relation_name]) > 0
            and len(self.charm.model.get_relation(self.certificates_relation_name).units) > 0  # type: ignore
        )

    @property
    def _peer_relation(self) -> Optional[Relation]:
        """Return the peer relation."""
        return self.charm.model.get_relation(self.peer_relation_name, None)

    def _on_peer_relation_created(self, _):
        """Generate the private key and store it in a peer relation."""
        # We're in "relation-created", so the relation should be there

        # Just in case we already have a private key, do not overwrite it.
        # Not sure how this could happen.
        # TODO figure out how to go about key rotation.
        if not self._private_key:
            private_key = generate_private_key()
            self._private_key = private_key.decode()

        # Generate CSR here, in case peer events fired after tls-certificate relation events
        if not (self.charm.model.get_relation(self.certificates_relation_name)):
            # peer relation event happened to fire before tls-certificates events.
            # Abort, and let the "certificates joined" observer create the CSR.
            return

        self._generate_csr()

    def _on_certificates_relation_joined(self, _) -> None:
        """Generate the CSR and request the certificate creation."""
        if not self._peer_relation:
            # tls-certificates relation event happened to fire before peer events.
            # Abort, and let the "peer joined" relation create the CSR.
            return

        self._generate_csr()

    def _on_config_changed(self, _):
        # FIXME on config changed, the web_external_url may or may not change. But because every
        #  call to `generate_csr` appends a uuid, CSRs cannot be easily compared to one another.
        #  so for now, will be overwriting the CSR (and cert) every config change. This is not
        #  great. We could avoid this problem if:
        #  - we extract the external_url from the existing cert and compare to current; or
        #  - we drop the web_external_url from the list of SANs.
        # Generate a CSR only if the necessary relations are already in place.
        if self._peer_relation and self.charm.model.get_relation(self.certificates_relation_name):
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
        # At this point, assuming "peer joined" and "certificates joined" have already fired
        # (caller must guard) so we must have a private_key entry in relation data at our disposal.
        # Otherwise, traceback -> debug.

        # In case we already have a csr, do not overwrite it by default.
        if overwrite or renew or not self._csr:
            private_key = self._private_key
            assert private_key is not None  # for type checker
            csr = generate_csr(
                private_key=private_key.encode(),
                subject=self.cert_subject,
                sans_dns=self.sans_dns,
            )

            if renew and self._csr:
                self.certificates.request_certificate_renewal(
                    old_certificate_signing_request=self._csr.encode(),
                    new_certificate_signing_request=csr,
                )
            else:
                logger.info("Creating CSR for %s with DNS %s", self.cert_subject, self.sans_dns)
                self.certificates.request_certificate_creation(certificate_signing_request=csr)

            # Note: CSR is being replaced with a new one, so until we get the new cert, we'd have
            # a mismatch between the CSR and the cert.
            # For some reason the csr contains a trailing '\n'. TODO figure out why
            self._csr = csr.decode().strip()

        if clear_cert:
            self._ca_cert = ""
            self._server_cert = ""
            self._chain = []

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Get the certificate from the event and store it in a peer relation.

        Note: assuming "limit: 1" in metadata
        """
        # We need to store the ca cert and server cert somewhere it would persist across upgrades.
        # While we support Juju 2.9, the only option is peer data. When we drop 2.9, then secrets.

        # I think juju guarantees that a peer-created always fires before any regular
        # relation-changed. If that is not the case, we would need more guards and more paths.

        # Process the cert only if it belongs to the unit that requested it (this unit)
        event_csr = (
            event.certificate_signing_request.strip()
            if event.certificate_signing_request
            else None
        )
        if event_csr == self._csr:
            self._ca_cert = event.ca
            self._server_cert = event.certificate
            self._chain = event.chain
            self.on.cert_changed.emit()  # pyright: ignore

    @property
    def key(self):
        """Return the private key."""
        return self._private_key

    @property
    def _private_key(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("private_key", None)
        return None

    @_private_key.setter
    def _private_key(self, value: str):
        # Caller must guard. We want the setter to fail loudly. Failure must have a side effect.
        rel = self._peer_relation
        assert rel is not None  # For type checker
        rel.data[self.charm.unit].update({"private_key": value})

    @property
    def _csr(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("csr", None)
        return None

    @_csr.setter
    def _csr(self, value: str):
        # Caller must guard. We want the setter to fail loudly. Failure must have a side effect.
        rel = self._peer_relation
        assert rel is not None  # For type checker
        rel.data[self.charm.unit].update({"csr": value})

    @property
    def _ca_cert(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("ca", None)
        return None

    @_ca_cert.setter
    def _ca_cert(self, value: str):
        # Caller must guard. We want the setter to fail loudly. Failure must have a side effect.
        rel = self._peer_relation
        assert rel is not None  # For type checker
        rel.data[self.charm.unit].update({"ca": value})

    @property
    def cert(self):
        """Return the server cert."""
        return self._server_cert

    @property
    def ca(self):
        """Return the CA cert."""
        return self._ca_cert

    @property
    def _server_cert(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("certificate", None)
        return None

    @_server_cert.setter
    def _server_cert(self, value: str):
        # Caller must guard. We want the setter to fail loudly. Failure must have a side effect.
        rel = self._peer_relation
        assert rel is not None  # For type checker
        rel.data[self.charm.unit].update({"certificate": value})

    @property
    def _chain(self) -> List[str]:
        if self._peer_relation:
            if chain := self._peer_relation.data[self.charm.unit].get("chain", []):
                return json.loads(chain)
        return []

    @_chain.setter
    def _chain(self, value: List[str]):
        # Caller must guard. We want the setter to fail loudly. Failure must have a side effect.
        rel = self._peer_relation
        assert rel is not None  # For type checker
        rel.data[self.charm.unit].update({"chain": json.dumps(value)})

    @property
    def chain(self) -> List[str]:
        """Return the ca chain."""
        return self._chain

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        """Generate a new CSR and request certificate renewal."""
        if event.certificate == self._server_cert:
            self._generate_csr(renew=True)

    def _certificate_revoked(self, event) -> None:
        """Remove the certificate from the peer relation and generate a new CSR."""
        # Note: assuming "limit: 1" in metadata
        if event.certificate == self._server_cert:
            self._generate_csr(overwrite=True, clear_cert=True)
            self.on.cert_changed.emit()  # pyright: ignore

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        """Deal with certificate revocation and expiration."""
        if event.certificate != self._server_cert:
            return

        # if event.reason in ("revoked", "expired"):
        # Currently, the reason does not matter to us because the action is the same.
        self._generate_csr(overwrite=True, clear_cert=True)
        self.on.cert_changed.emit()  # pyright: ignore

    def _on_all_certificates_invalidated(self, event: AllCertificatesInvalidatedEvent) -> None:
        # Do what you want with this information, probably remove all certificates
        # Note: assuming "limit: 1" in metadata
        self._generate_csr(overwrite=True, clear_cert=True)
        self.on.cert_changed.emit()  # pyright: ignore

    def _on_certificates_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the certificates data when removing the relation."""
        if self._peer_relation:
            private_key = self._private_key
            # This is a workaround for https://bugs.launchpad.net/juju/+bug/2024583
            self._peer_relation.data[self.charm.unit].clear()
            if private_key:
                self._peer_relation.data[self.charm.unit].update({"private_key": private_key})

        self.on.cert_changed.emit()  # pyright: ignore
