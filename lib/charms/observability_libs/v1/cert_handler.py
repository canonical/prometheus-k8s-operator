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
container.push(certpath, self.cert_handler.server_cert)
```

Since this library uses [Juju Secrets](https://juju.is/docs/juju/secret) it requires Juju >= 3.0.3.
"""
import abc
import hashlib
import ipaddress
import json
import socket
from itertools import filterfalse
from typing import Dict, List, Optional, Union

try:
    from charms.tls_certificates_interface.v3.tls_certificates import (  # type: ignore
        AllCertificatesInvalidatedEvent,
        CertificateAvailableEvent,
        CertificateExpiringEvent,
        CertificateInvalidatedEvent,
        ProviderCertificate,
        TLSCertificatesRequiresV3,
        generate_csr,
        generate_private_key,
    )
except ImportError as e:
    raise ImportError(
        "failed to import charms.tls_certificates_interface.v3.tls_certificates; "
        "Either the library itself is missing (please get it through charmcraft fetch-lib) "
        "or one of its dependencies is unmet."
    ) from e

import logging

from ops.charm import CharmBase
from ops.framework import BoundEvent, EventBase, EventSource, Object, ObjectEvents, StoredState
from ops.jujuversion import JujuVersion
from ops.model import Relation, Secret, SecretNotFoundError

logger = logging.getLogger(__name__)

LIBID = "b5cd5cd580f3428fa5f59a8876dcbe6a"
LIBAPI = 1
LIBPATCH = 14

VAULT_SECRET_LABEL = "cert-handler-private-vault"


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


class _VaultBackend(abc.ABC):
    """Base class for a single secret manager.

    Assumptions:
    - A single secret (label) is managed by a single instance.
    - Secret is per-unit (not per-app, i.e. may differ from unit to unit).
    """

    def store(self, contents: Dict[str, str], clear: bool = False): ...

    def get_value(self, key: str) -> Optional[str]: ...

    def retrieve(self) -> Dict[str, str]: ...

    def clear(self): ...


class _RelationVaultBackend(_VaultBackend):
    """Relation backend for Vault.

    Use it to store data in a relation databag.
    Assumes that a single relation exists and its data is readable.
    If not, it will raise RuntimeErrors as soon as you try to read/write.
    It will store the data, in plaintext (json-dumped) nested under a configurable
    key in the **unit databag** of this relation.

    Typically, you'll use this with peer relations.

    Note: it is assumed that this object has exclusive access to the data, even though in practice it does not.
      Modifying relation data yourself would go unnoticed and disrupt consistency.
    """

    _NEST_UNDER = "lib.charms.observability_libs.v1.cert_handler::vault"
    # This key needs to be relation-unique. If someone ever creates multiple Vault(_RelationVaultBackend)
    # instances backed by the same (peer) relation, they'll need to set different _NEST_UNDERs
    # for each _RelationVaultBackend instance or they'll be fighting over it.

    def __init__(self, charm: CharmBase, relation_name: str):
        self.charm = charm
        self.relation_name = relation_name

    def _check_ready(self):
        relation = self.charm.model.get_relation(self.relation_name)
        if not relation or not relation.data:
            # if something goes wrong here, the peer-backed vault is not ready to operate
            # it can be because you are trying to use it too soon, i.e. before the (peer)
            # relation has been created (or has joined).
            raise RuntimeError("Relation backend not ready.")

    @property
    def _relation(self) -> Optional[Relation]:
        self._check_ready()
        return self.charm.model.get_relation(self.relation_name)

    @property
    def _databag(self):
        self._check_ready()
        # _check_ready verifies that there is a relation
        return self._relation.data[self.charm.unit]  # type: ignore

    def _read(self) -> Dict[str, str]:
        value = self._databag.get(self._NEST_UNDER)
        if value:
            return json.loads(value)
        return {}

    def _write(self, value: Dict[str, str]):
        if not all(isinstance(x, str) for x in value.values()):
            # the caller has to take care of encoding
            raise TypeError("You can only store strings in Vault.")

        self._databag[self._NEST_UNDER] = json.dumps(value)

    def store(self, contents: Dict[str, str], clear: bool = False):
        """Create a new revision by updating the previous one with ``contents``."""
        current = self._read()

        if clear:
            current.clear()

        current.update(contents)
        self._write(current)

    def get_value(self, key: str) -> Optional[str]:
        """Like retrieve, but single-value."""
        return self._read().get(key)

    def retrieve(self):
        """Return the full vault content."""
        return self._read()

    def clear(self):
        del self._databag[self._NEST_UNDER]


class _SecretVaultBackend(_VaultBackend):
    """Relation backend for Vault.

    Use it to store data in a Juju secret.
    Assumes that Juju supports secrets.
    If not, it will raise some exception as soon as you try to read/write.

    Note: it is assumed that this object has exclusive access to the data, even though in practice it does not.
      Modifying secret's data yourself would go unnoticed and disrupt consistency.
    """

    _uninitialized_key = "uninitialized-secret-key"

    def __init__(self, charm: CharmBase, secret_label: str):
        self.charm = charm
        self.secret_label = secret_label  # needs to be charm-unique.

    @property
    def _secret(self) -> Secret:
        try:
            # we are owners, so we don't need to grant it to ourselves
            return self.charm.model.get_secret(label=self.secret_label)
        except SecretNotFoundError:
            # we need to set SOME contents when we're creating the secret, so we do it.
            return self.charm.unit.add_secret(
                {self._uninitialized_key: "42"}, label=self.secret_label
            )

    def store(self, contents: Dict[str, str], clear: bool = False):
        """Create a new revision by updating the previous one with ``contents``."""
        secret = self._secret
        current = secret.get_content(refresh=True)

        if clear:
            current.clear()
        elif current.get(self._uninitialized_key):
            # is this the first revision? clean up the mock contents we created instants ago.
            del current[self._uninitialized_key]

        current.update(contents)
        secret.set_content(current)

    def get_value(self, key: str) -> Optional[str]:
        """Like retrieve, but single-value."""
        return self._secret.get_content(refresh=True).get(key)

    def retrieve(self):
        """Return the full vault content."""
        return self._secret.get_content(refresh=True)

    def clear(self):
        self._secret.remove_all_revisions()


class Vault:
    """Simple application secret wrapper for local usage."""

    def __init__(self, backend: _VaultBackend):
        self._backend = backend

    def store(self, contents: Dict[str, str], clear: bool = False):
        """Store these contents in the vault overriding whatever is there."""
        self._backend.store(contents, clear=clear)

    def get_value(self, key: str):
        """Like retrieve, but single-value."""
        return self._backend.get_value(key)

    def retrieve(self) -> Dict[str, str]:
        """Return the full vault content."""
        return self._backend.retrieve()

    def clear(self):
        """Clear the vault."""
        try:
            self._backend.clear()
        except SecretNotFoundError:
            # guard against: https://github.com/canonical/observability-libs/issues/95
            # this is fine, it might mean an earlier hook had already called .clear()
            # not sure what exactly the root cause is, might be a juju bug
            logger.debug("Could not clear vault: secret is gone already.")


class CertHandler(Object):
    """A wrapper for the requirer side of the TLS Certificates charm library."""

    on = CertHandlerEvents()  # pyright: ignore
    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        *,
        key: str,
        certificates_relation_name: str = "certificates",
        peer_relation_name: str = "peers",
        cert_subject: Optional[str] = None,
        sans: Optional[List[str]] = None,
        refresh_events: Optional[List[BoundEvent]] = None,
    ):
        """CertHandler is used to wrap TLS Certificates management operations for charms.

        CerHandler manages one single cert.

        Args:
            charm: The owning charm.
            key: A manually-crafted, static, unique identifier used by ops to identify events.
             It shouldn't change between one event to another.
            certificates_relation_name: Name of the certificates relation over which we obtain TLS certificates.
                Must match metadata.yaml.
            peer_relation_name: Name of a peer relation used to store our secrets.
                Only used on older Juju versions where secrets are not supported.
                Must match metadata.yaml.
            cert_subject: Custom subject. Name collisions are under the caller's responsibility.
            sans: DNS names. If none are given, use FQDN.
            refresh_events: [DEPRECATED].
        """
        super().__init__(charm, key)
        # use StoredState to store the hash of the CSR
        # to potentially trigger a CSR renewal
        self._stored.set_default(
            csr_hash=None,
        )
        self.charm = charm

        # We need to sanitize the unit name, otherwise route53 complains:
        # "urn:ietf:params:acme:error:malformed" :: Domain name contains an invalid character
        self.cert_subject = charm.unit.name.replace("/", "-") if not cert_subject else cert_subject

        # Use fqdn only if no SANs were given, and drop empty/duplicate SANs
        sans = list(set(filter(None, (sans or [socket.getfqdn()]))))
        # sort SANS lists to avoid unnecessary csr renewals during reconciliation
        self.sans_ip = sorted(filter(is_ip_address, sans))
        self.sans_dns = sorted(filterfalse(is_ip_address, sans))

        if self._check_juju_supports_secrets():
            vault_backend = _SecretVaultBackend(charm, secret_label=VAULT_SECRET_LABEL)

            # TODO: gracefully handle situations where the
            #  secret is gone because the admin has removed it manually
            # self.framework.observe(self.charm.on.secret_remove, self._rotate_csr)

        else:
            vault_backend = _RelationVaultBackend(charm, relation_name=peer_relation_name)
        self.vault = Vault(vault_backend)

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
            self.charm.on.upgrade_charm,  # pyright: ignore
            self._on_upgrade_charm,
        )

        if refresh_events:
            logger.warn(
                "DEPRECATION WARNING. `refresh_events` is now deprecated. CertHandler will automatically refresh the CSR when necessary."
            )

        self._reconcile()

    def _reconcile(self):
        """Run all logic that is independent of what event we're processing."""
        self._refresh_csr_if_needed()

    def _on_upgrade_charm(self, _):
        has_privkey = self.vault.get_value("private-key")

        self._migrate_vault()

        # If we already have a csr, but the pre-migration vault has no privkey stored,
        # the csr must have been signed with a privkey that is now outdated and utterly lost.
        # So we throw away the csr and generate a new one (and a new privkey along with it).
        if not has_privkey and self._csr:
            logger.debug("CSR and privkey out of sync after charm upgrade. Renewing CSR.")
            # this will call `self.private_key` which will generate a new privkey.
            self._generate_csr(renew=True)

    def _refresh_csr_if_needed(self):
        """Refresh the current CSR with a new one if there are any SANs changes."""
        if self._stored.csr_hash is not None and self._stored.csr_hash != self._csr_hash:
            self._generate_csr(renew=True)

    def _migrate_vault(self):
        peer_backend = _RelationVaultBackend(self.charm, relation_name="peers")

        if self._check_juju_supports_secrets():
            # we are on recent juju
            if self.vault.retrieve():
                # we already were on recent juju: nothing to migrate
                logger.debug(
                    "Private key is already stored as a juju secret. Skipping private key migration."
                )
                return

            # we used to be on old juju: our secret stuff is in peer data
            if contents := peer_backend.retrieve():
                logger.debug(
                    "Private key found in relation data. "
                    "Migrating private key to a juju secret."
                )
                # move over to secret-backed storage
                self.vault.store(contents)

                # clear the peer storage
                peer_backend.clear()
                return

        # if we are downgrading, i.e. from juju with secrets to juju without,
        # we have lost all that was in the secrets backend.

    @property
    def enabled(self) -> bool:
        """Boolean indicating whether the charm has a tls_certificates relation.

        See also the `available` property.
        """
        # We need to check for units as a temporary workaround because of https://bugs.launchpad.net/juju/+bug/2024583
        # This could in theory not work correctly on scale down to 0 but it is necessary for the moment.

        if not self.relation:
            return False

        if not self.relation.units:  # pyright: ignore
            return False

        if not self.relation.app:  # pyright: ignore
            return False

        if not self.relation.data:  # pyright: ignore
            return False

        return True

    @property
    def _csr_hash(self) -> str:
        """A hash of the config that constructs the CSR.

        Only include here the config options that, should they change, should trigger a renewal of
        the CSR.
        """

        def _stable_hash(data):
            return hashlib.sha256(str(data).encode()).hexdigest()

        return _stable_hash(
            (
                tuple(self.sans_dns),
                tuple(self.sans_ip),
            )
        )

    @property
    def available(self) -> bool:
        """Return True if all certs are available in relation data; False otherwise."""
        return (
            self.enabled
            and self.server_cert is not None
            and self.private_key is not None
            and self.ca_cert is not None
        )

    def _on_certificates_relation_joined(self, _) -> None:
        # this will only generate a csr if we don't have one already
        self._generate_csr()

    def _on_config_changed(self, _):
        # this will only generate a csr if we don't have one already
        self._generate_csr()

    @property
    def relation(self):
        """The "certificates" relation."""
        return self.charm.model.get_relation(self.certificates_relation_name)

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
        if not self.relation:
            logger.warning(
                f"No {self.certificates_relation_name!r} relation found. " f"Cannot generate csr."
            )
            return

        # In case we already have a csr, do not overwrite it by default.
        if overwrite or renew or not self._csr:
            private_key = self.private_key
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

            self._stored.csr_hash = self._csr_hash

        if clear_cert:
            self.vault.clear()

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Emit cert-changed."""
        self.on.cert_changed.emit()  # pyright: ignore

    @property
    def private_key(self) -> str:
        """Private key.

        BEWARE: if the vault misbehaves, the backing secret is removed, the peer relation dies
        or whatever, we might be calling generate_private_key() again and cause a desync
        with the CSR because it's going to be signed with an outdated key we have no way of retrieving.
        The caller needs to ensure that if the vault backend gets reset, then so does the csr.

        TODO: we could consider adding a way to verify if the csr was signed by our privkey,
            and do that on collect_unit_status as a consistency check
        """
        private_key = self.vault.get_value("private-key")
        if private_key is None:
            private_key = generate_private_key().decode()
            self.vault.store({"private-key": private_key})
        return private_key

    @property
    def _csr(self) -> Optional[str]:
        csrs = self.certificates.get_requirer_csrs()
        if not csrs:
            return None

        # in principle we only ever need one cert.
        # we might want to complicate this a bit once we get into cert rotations: during the rotation, we may need to
        # keep the old one around for a little while. If there's multiple certs, at the moment we're
        # ignoring all but the last one.
        if len(csrs) > 1:
            logger.warning(
                f"Multiple CSRs found in {self.certificates_relation_name!r} relation. "
                "cert_handler is not ready to expect it."
            )

        return csrs[-1].csr

    def get_cert(self) -> Optional[ProviderCertificate]:
        """Get the certificate from relation data."""
        all_certs = self.certificates.get_provider_certificates()
        # search for the cert matching our csr.
        matching_cert = [c for c in all_certs if c.csr == self._csr]
        return matching_cert[0] if matching_cert else None

    @property
    def ca_cert(self) -> Optional[str]:
        """CA Certificate."""
        cert = self.get_cert()
        return cert.ca if cert else None

    @property
    def server_cert(self) -> Optional[str]:
        """Server Certificate."""
        cert = self.get_cert()
        return cert.certificate if cert else None

    @property
    def chain(self) -> Optional[str]:
        """Return the entire chain bundled as a single PEM string. This includes, if available, the certificate, intermediate CAs, and the root CA.

        If the server certificate is not set in the chain by the provider, we'll add it
        to the top of the chain so that it could be used by a server.
        """
        cert = self.get_cert()
        if not cert:
            return None
        chain = cert.chain_as_pem()
        if cert.certificate not in chain:
            # add server cert to chain
            chain = cert.certificate + "\n\n" + chain
        return chain

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        """Generate a new CSR and request certificate renewal."""
        if event.certificate == self.server_cert:
            self._generate_csr(renew=True)
            # FIXME why are we not emitting cert_changed here?

    def _certificate_revoked(self, event) -> None:
        """Remove the certificate and generate a new CSR."""
        # Note: assuming "limit: 1" in metadata
        if event.certificate == self.server_cert:
            self._generate_csr(overwrite=True, clear_cert=True)
            self.on.cert_changed.emit()  # pyright: ignore

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        """Deal with certificate revocation and expiration."""
        if event.certificate == self.server_cert:
            # if event.reason in ("revoked", "expired"):
            # Currently, the reason does not matter to us because the action is the same.
            self._generate_csr(overwrite=True, clear_cert=True)
            self.on.cert_changed.emit()  # pyright: ignore

    def _on_all_certificates_invalidated(self, _: AllCertificatesInvalidatedEvent) -> None:
        """Clear all secrets data when removing the relation."""
        # Note: assuming "limit: 1" in metadata
        # The "certificates_relation_broken" event is converted to "all invalidated" custom
        # event by the tls-certificates library. Per convention, we let the lib manage the
        # relation and we do not observe "certificates_relation_broken" directly.
        self.vault.clear()
        # We do not generate a CSR here because the relation is gone.
        self.on.cert_changed.emit()  # pyright: ignore

    def _check_juju_supports_secrets(self) -> bool:
        version = JujuVersion.from_environ()
        if not JujuVersion(version=str(version)).has_secrets:
            msg = f"Juju version {version} does not supports Secrets. Juju >= 3.0.3 is needed"
            logger.debug(msg)
            return False
        return True
