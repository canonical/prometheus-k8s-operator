# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Legacy Charmhub-hosted lib, deprecated in favour of ``charmlibs.interfaces.tls_certificates``.

WARNING: This library is deprecated.
It will not receive feature updates or bugfixes.
``charmlibs.interfaces.tls_certificates`` 1.0 is a bug-for-bug compatible migration of this library.

To migrate:
1. Add 'charmlibs-interfaces-tls-certificates~=1.0' to your charm's dependencies,
   and remove this Charmhub-hosted library from your charm.
2. You can also remove any dependencies added to your charm only because of this library.
3. Replace `from charms.tls_certificates_interface.v4 import tls_certificates`
   with `from charmlibs.interfaces import tls_certificates`.

Read more:
- https://documentation.ubuntu.com/charmlibs
- https://pypi.org/project/charmlibs-interfaces-tls-certificates

---

Charm library for managing TLS certificates (V4).

This library contains the Requires and Provides classes for handling the tls-certificates
interface.

Pre-requisites:
  - Juju >= 3.0
  - cryptography >= 43.0.0
  - pydantic >= 1.0

Learn more on how-to use the TLS Certificates interface library by reading the documentation:
- https://charmhub.io/tls-certificates-interface/

"""  # noqa: D214, D405, D411, D416

import copy
import ipaddress
import json
import logging
import uuid
import warnings
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import (
    Collection,
    Dict,
    FrozenSet,
    List,
    MutableMapping,
    Optional,
    Set,
    Tuple,
    Union,
)

import pydantic
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import CertificateIssuerPrivateKeyTypes
from cryptography.x509.oid import ExtensionOID, NameOID
from ops import BoundEvent, CharmBase, CharmEvents, Secret, SecretExpiredEvent, SecretRemoveEvent
from ops.framework import EventBase, EventSource, Handle, Object
from ops.jujuversion import JujuVersion
from ops.model import Application, ModelError, Relation, SecretNotFoundError, Unit

# The unique Charmhub library identifier, never change it
LIBID = "afd8c2bccf834997afce12c2706d2ede"

# Increment this major API version when introducing breaking changes
LIBAPI = 4

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 27

PYDEPS = [
    "cryptography>=43.0.0",
    "pydantic",
]
IS_PYDANTIC_V1 = int(pydantic.version.VERSION.split(".")[0]) < 2

logger = logging.getLogger(__name__)

NESTED_JSON_KEY = "owasp_event"


@dataclass
class _OWASPLogEvent:
    """OWASP-compliant log event."""

    datetime: str
    event: str
    level: str
    description: str
    type: str = "security"
    labels: Dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_dict(self) -> Dict:
        log_event = dict(asdict(self), **self.labels)
        log_event.pop("labels", None)
        return {k: v for k, v in log_event.items() if v is not None}


class _OWASPLogger:
    """OWASP-compliant logger for security events."""

    def __init__(self, application: Optional[str] = None):
        self.application = application
        self._logger = logging.getLogger(__name__)

    def log_event(self, event: str, level: int, description: str, **labels: str):
        if self.application and "application" not in labels:
            labels["application"] = self.application
        log = _OWASPLogEvent(
            datetime=datetime.now(timezone.utc).astimezone().isoformat(),
            event=event,
            level=logging.getLevelName(level),
            description=description,
            labels=labels,
        )
        self._logger.log(level, log.to_json(), extra={NESTED_JSON_KEY: log.to_dict()})


class TLSCertificatesError(Exception):
    """Base class for custom errors raised by this library."""


class DataValidationError(TLSCertificatesError):
    """Raised when data validation fails."""


class _DatabagModel(pydantic.BaseModel):
    """Base databag model.

    Supports both pydantic v1 and v2.
    """

    if IS_PYDANTIC_V1:

        class Config:
            """Pydantic config."""

            # ignore any extra fields in the databag
            extra = "ignore"
            """Ignore any extra fields in the databag."""
            allow_population_by_field_name = True
            """Allow instantiating this class by field name (instead of forcing alias)."""

        _NEST_UNDER = None

    model_config = pydantic.ConfigDict(
        # tolerate additional keys in databag
        extra="ignore",
        # Allow instantiating this class by field name (instead of forcing alias).
        populate_by_name=True,
        # Custom config key: whether to nest the whole datastructure (as json)
        # under a field or spread it out at the toplevel.
        _NEST_UNDER=None,
    )  # type: ignore
    """Pydantic config."""

    @classmethod
    def load(cls, databag: MutableMapping):
        """Load this model from a Juju databag."""
        if IS_PYDANTIC_V1:
            return cls._load_v1(databag)
        nest_under = cls.model_config.get("_NEST_UNDER")
        if nest_under:
            return cls.model_validate(json.loads(databag[nest_under]))

        try:
            data = {
                k: json.loads(v)
                for k, v in databag.items()
                # Don't attempt to parse model-external values
                if k in {(f.alias or n) for n, f in cls.model_fields.items()}
            }
        except json.JSONDecodeError as e:
            msg = f"invalid databag contents: expecting json. {databag}"
            logger.error(msg)
            raise DataValidationError(msg) from e

        try:
            return cls.model_validate_json(json.dumps(data))
        except pydantic.ValidationError as e:
            msg = f"failed to validate databag: {databag}"
            logger.debug(msg, exc_info=True)
            raise DataValidationError(msg) from e

    @classmethod
    def _load_v1(cls, databag: MutableMapping):
        """Load implementation for pydantic v1."""
        if cls._NEST_UNDER:
            return cls.parse_obj(json.loads(databag[cls._NEST_UNDER]))

        try:
            data = {
                k: json.loads(v)
                for k, v in databag.items()
                # Don't attempt to parse model-external values
                if k in {f.alias for f in cls.__fields__.values()}
            }
        except json.JSONDecodeError as e:
            msg = f"invalid databag contents: expecting json. {databag}"
            logger.error(msg)
            raise DataValidationError(msg) from e

        try:
            return cls.parse_raw(json.dumps(data))  # type: ignore
        except pydantic.ValidationError as e:
            msg = f"failed to validate databag: {databag}"
            logger.debug(msg, exc_info=True)
            raise DataValidationError(msg) from e

    def dump(self, databag: Optional[MutableMapping] = None, clear: bool = True):
        """Write the contents of this model to Juju databag.

        Args:
            databag: The databag to write to.
            clear: Whether to clear the databag before writing.

        Returns:
            MutableMapping: The databag.
        """
        if IS_PYDANTIC_V1:
            return self._dump_v1(databag, clear)
        if clear and databag:
            databag.clear()

        if databag is None:
            databag = {}
        nest_under = self.model_config.get("_NEST_UNDER")
        if nest_under:
            databag[nest_under] = self.model_dump_json(
                by_alias=True,
                # skip keys whose values are default
                exclude_defaults=True,
            )
            return databag

        dct = self.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        databag.update({k: json.dumps(v) for k, v in dct.items()})
        return databag

    def _dump_v1(self, databag: Optional[MutableMapping] = None, clear: bool = True):
        """Dump implementation for pydantic v1."""
        if clear and databag:
            databag.clear()

        if databag is None:
            databag = {}

        if self._NEST_UNDER:
            databag[self._NEST_UNDER] = self.json(by_alias=True, exclude_defaults=True)
            return databag

        dct = json.loads(self.json(by_alias=True, exclude_defaults=True))
        databag.update({k: json.dumps(v) for k, v in dct.items()})

        return databag


class _Certificate(pydantic.BaseModel):
    """Certificate model."""

    ca: str
    certificate_signing_request: str
    certificate: str
    chain: Optional[List[str]] = None
    revoked: Optional[bool] = None

    def to_provider_certificate(self, relation_id: int) -> "ProviderCertificate":
        """Convert to a ProviderCertificate."""
        return ProviderCertificate(
            relation_id=relation_id,
            certificate=Certificate.from_string(self.certificate),
            certificate_signing_request=CertificateSigningRequest.from_string(
                self.certificate_signing_request
            ),
            ca=Certificate.from_string(self.ca),
            chain=[Certificate.from_string(certificate) for certificate in self.chain]
            if self.chain
            else [],
            revoked=self.revoked,
        )


class _CertificateSigningRequest(pydantic.BaseModel):
    """Certificate signing request model."""

    certificate_signing_request: str
    ca: Optional[bool]


class _ProviderApplicationData(_DatabagModel):
    """Provider application data model."""

    certificates: List[_Certificate] = []


class _RequirerData(_DatabagModel):
    """Requirer data model.

    The same model is used for the unit and application data.
    """

    certificate_signing_requests: List[_CertificateSigningRequest] = []


class Mode(Enum):
    """Enum representing the mode of the certificate request.

    UNIT (default): Request a certificate for the unit.
        Each unit will manage its private key,
        certificate signing request and certificate.
    APP: Request a certificate for the application.
        Only the leader unit will manage the private key, certificate signing request
        and certificate.
    """

    UNIT = 1
    APP = 2


class PrivateKey:
    """This class represents a private key."""

    def __init__(
        self, raw: Optional[str] = None, x509_object: Optional[rsa.RSAPrivateKey] = None
    ) -> None:
        """Initialize the PrivateKey object.

        If both raw and x509_object are provided, x509_object takes precedence.
        """
        if x509_object:
            self._private_key = x509_object
        elif raw:
            self._private_key = serialization.load_pem_private_key(
                raw.encode(),
                password=None,
            )
        else:
            raise ValueError("Either raw private key string or x509_object must be provided")

    @property
    def raw(self) -> str:
        """Return the PEM-formatted string representation of the private key."""
        return str(self)

    def __str__(self):
        """Return the private key as a string in PEM format."""
        return (
            self._private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            .decode()
            .strip()
        )

    def __hash__(self):
        """Return the hash of the private key."""
        return hash(self.raw)

    @classmethod
    def from_string(cls, private_key: str) -> "PrivateKey":
        """Create a PrivateKey object from a private key."""
        return cls(raw=private_key)

    def is_valid(self) -> bool:
        """Validate that the private key is PEM-formatted, RSA, and at least 2048 bits."""
        try:
            if not isinstance(self._private_key, rsa.RSAPrivateKey):
                logger.warning("Private key is not an RSA key")
                return False

            if self._private_key.key_size < 2048:
                logger.warning("RSA key size is less than 2048 bits")
                return False

            return True
        except ValueError:
            logger.warning("Invalid private key format")
            return False

    @classmethod
    def generate(cls, key_size: int = 2048, public_exponent: int = 65537) -> "PrivateKey":
        """Generate a new RSA private key.

        Args:
            key_size: The size of the key in bits.
            public_exponent: The public exponent of the key.

        Returns:
            PrivateKey: The generated private key.
        """
        private_key = rsa.generate_private_key(
            public_exponent=public_exponent,
            key_size=key_size,
        )
        _OWASPLogger().log_event(
            event="private_key_generated",
            level=logging.INFO,
            description="Private key generated",
            key_size=str(key_size),
        )
        return PrivateKey(x509_object=private_key)

    def __eq__(self, other: object) -> bool:
        """Check if two PrivateKey objects are equal."""
        if not isinstance(other, PrivateKey):
            return NotImplemented
        return self.raw == other.raw


class Certificate:
    """This class represents a certificate."""

    _cert: x509.Certificate

    def __init__(
        self,
        raw: Optional[str] = None,  # Must remain first argument for backwards compatibility
        # Old Interface fields (ignored)
        common_name: Optional[str] = None,
        expiry_time: Optional[datetime] = None,
        validity_start_time: Optional[datetime] = None,
        is_ca: Optional[bool] = None,
        sans_dns: Optional[Set[str]] = None,
        sans_ip: Optional[Set[str]] = None,
        sans_oid: Optional[Set[str]] = None,
        email_address: Optional[str] = None,
        organization: Optional[str] = None,
        organizational_unit: Optional[str] = None,
        country_name: Optional[str] = None,
        state_or_province_name: Optional[str] = None,
        locality_name: Optional[str] = None,
        # End Old Interface fields
        x509_object: Optional[x509.Certificate] = None,
    ) -> None:
        """Initialize the Certificate object.

        This initializer must maintain the old interface while also allowing
        instantiation from an existing x509_object. It ignores all fields
        other than raw and x509_object, preferring x509_object.
        """
        if x509_object:
            self._cert = x509_object
        elif raw:
            self._cert = x509.load_pem_x509_certificate(data=raw.encode())
        else:
            raise ValueError("Either raw certificate string or x509_object must be provided")

    @property
    def raw(self) -> str:
        """Return the PEM-formatted string representation of the certificate."""
        return str(self)

    @property
    def common_name(self) -> str:
        """Return the common name of the certificate."""
        # We maintain compatibility with the old interface by returning
        # an empty string if no common name is set.
        common_name = self._cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return str(common_name[0].value) if common_name else ""

    @property
    def expiry_time(self) -> datetime:
        """Return the expiry time of the certificate."""
        return self._cert.not_valid_after_utc

    @property
    def validity_start_time(self) -> datetime:
        """Return the validity start time of the certificate."""
        return self._cert.not_valid_before_utc

    @property
    def is_ca(self) -> bool:
        """Return whether the certificate is a CA certificate."""
        try:
            return self._cert.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            ).value.ca  # type: ignore[reportAttributeAccessIssue]
        except x509.ExtensionNotFound:
            return False

    @property
    def sans_dns(self) -> Optional[Set[str]]:
        """Return the DNS Subject Alternative Names of the certificate."""
        with suppress(x509.ExtensionNotFound):
            sans = self._cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san) for san in sans.get_values_for_type(x509.DNSName)}
        return None

    @property
    def sans_ip(self) -> Optional[Set[str]]:
        """Return the IP Subject Alternative Names of the certificate."""
        with suppress(x509.ExtensionNotFound):
            sans = self._cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san) for san in sans.get_values_for_type(x509.IPAddress)}
        return None

    @property
    def sans_oid(self) -> Optional[Set[str]]:
        """Return the OID Subject Alternative Names of the certificate."""
        with suppress(x509.ExtensionNotFound):
            sans = self._cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san.dotted_string) for san in sans.get_values_for_type(x509.RegisteredID)}
        return None

    @property
    def email_address(self) -> Optional[str]:
        """Return the email address of the certificate."""
        email_address = self._cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
        return str(email_address[0].value) if email_address else None

    @property
    def organization(self) -> Optional[str]:
        """Return the organization name of the certificate."""
        organization = self._cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        return str(organization[0].value) if organization else None

    @property
    def organizational_unit(self) -> Optional[str]:
        """Return the organizational unit name of the certificate."""
        organizational_unit = self._cert.subject.get_attributes_for_oid(
            NameOID.ORGANIZATIONAL_UNIT_NAME
        )
        return str(organizational_unit[0].value) if organizational_unit else None

    @property
    def country_name(self) -> Optional[str]:
        """Return the country name of the certificate."""
        country_name = self._cert.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        return str(country_name[0].value) if country_name else None

    @property
    def state_or_province_name(self) -> Optional[str]:
        """Return the state or province name of the certificate."""
        state_or_province_name = self._cert.subject.get_attributes_for_oid(
            NameOID.STATE_OR_PROVINCE_NAME
        )
        return str(state_or_province_name[0].value) if state_or_province_name else None

    @property
    def locality_name(self) -> Optional[str]:
        """Return the locality name of the certificate."""
        locality_name = self._cert.subject.get_attributes_for_oid(NameOID.LOCALITY_NAME)
        return str(locality_name[0].value) if locality_name else None

    def __str__(self) -> str:
        """Return the certificate as a string."""
        return self._cert.public_bytes(serialization.Encoding.PEM).decode().strip()

    def __eq__(self, other: object) -> bool:
        """Check if two Certificate objects are equal."""
        if not isinstance(other, Certificate):
            return NotImplemented
        return self.raw == other.raw

    @classmethod
    def from_string(cls, certificate: str) -> "Certificate":
        """Create a Certificate object from a certificate."""
        try:
            certificate_object = x509.load_pem_x509_certificate(data=certificate.encode())
        except ValueError as e:
            logger.error("Could not load certificate: %s", e)
            raise TLSCertificatesError("Could not load certificate")

        return cls(x509_object=certificate_object)

    def matches_private_key(self, private_key: PrivateKey) -> bool:
        """Check if this certificate matches a given private key.

        Args:
            private_key (PrivateKey): The private key to validate against.

        Returns:
            bool: True if the certificate matches the private key, False otherwise.
        """
        try:
            cert_public_key = self._cert.public_key()
            key_public_key = private_key._private_key.public_key()

            if not isinstance(cert_public_key, rsa.RSAPublicKey):
                logger.warning("Certificate does not use RSA public key")
                return False

            if not isinstance(key_public_key, rsa.RSAPublicKey):
                logger.warning("Private key is not an RSA key")
                return False

            return cert_public_key.public_numbers() == key_public_key.public_numbers()
        except Exception as e:
            logger.warning("Failed to validate certificate and private key match: %s", e)
            return False

    @classmethod
    def generate(
        cls,
        csr: "CertificateSigningRequest",
        ca: "Certificate",
        ca_private_key: "PrivateKey",
        validity: timedelta,
        is_ca: bool = False,
    ) -> "Certificate":
        """Generate a certificate from a CSR signed by the given CA and CA private key.

        Args:
            csr: The certificate signing request.
            ca: The CA certificate.
            ca_private_key: The CA private key.
            validity: The validity period of the certificate.
            is_ca: Whether the generated certificate is a CA certificate.

        Returns:
            Certificate: The generated certificate.
        """
        # Ideally, this would be the constructor, but we can't add new
        # required parameters to the constructor without breaking backwards
        # compatibility.
        private_key = serialization.load_pem_private_key(
            str(ca_private_key).encode(), password=None
        )
        assert isinstance(private_key, CertificateIssuerPrivateKeyTypes)

        # Create a certificate builder
        cert_builder = x509.CertificateBuilder(
            subject_name=csr._csr.subject,
            # issuer_name=ca._cert.subject,  # TODO: Validate this is correct, the old code used `issuer`
            issuer_name=ca._cert.issuer,
            public_key=csr._csr.public_key(),
            serial_number=x509.random_serial_number(),
            not_valid_before=datetime.now(timezone.utc),
            not_valid_after=datetime.now(timezone.utc) + validity,
        )
        extensions = _generate_certificate_request_extensions(
            authority_key_identifier=ca._cert.extensions.get_extension_for_class(
                x509.SubjectKeyIdentifier
            ).value.key_identifier,
            csr=csr._csr,
            is_ca=is_ca,
        )
        for extension in extensions:
            try:
                cert_builder = cert_builder.add_extension(extension.value, extension.critical)
            except ValueError as e:
                logger.error("Could not add extension to certificate: %s", e)
                raise TLSCertificatesError("Could not add extension to certificate") from e

        # Sign the certificate with the CA's private key
        cert = cert_builder.sign(private_key=private_key, algorithm=hashes.SHA256())
        _OWASPLogger().log_event(
            event="certificate_generated",
            level=logging.INFO,
            description="Certificate generated from CSR",
            common_name=csr.common_name,
            is_ca=str(is_ca),
            validity_days=str(validity.days),
        )

        return cls(x509_object=cert)

    @classmethod
    def generate_self_signed_ca(
        cls,
        attributes: "CertificateRequestAttributes",
        private_key: PrivateKey,
        validity: timedelta,
    ) -> "Certificate":
        """Generate a self-signed CA certificate.

        Args:
            attributes: The certificate request attributes.
            private_key: The private key to sign the CA certificate.
            validity: The validity period of the CA certificate.

        Returns:
            Certificate: The generated CA certificate.
        """
        assert isinstance(private_key._private_key, rsa.RSAPrivateKey)

        public_key = private_key._private_key.public_key()

        builder = x509.CertificateBuilder(
            public_key=public_key,
            serial_number=x509.random_serial_number(),
            not_valid_before=datetime.now(timezone.utc),
            not_valid_after=datetime.now(timezone.utc) + validity,
        )

        if subject_name := _extract_subject_name_attributes(attributes):
            builder = builder.subject_name(subject_name).issuer_name(subject_name)

        builder = (
            builder.add_extension(
                x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    key_cert_sign=True,
                    key_agreement=False,
                    content_commitment=False,
                    data_encipherment=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
        )

        if san_extension := _san_extension(
            email_address=attributes.email_address,
            sans_dns=attributes.sans_dns,
            sans_ip=attributes.sans_ip,
            sans_oid=attributes.sans_oid,
        ):
            builder = builder.add_extension(san_extension, critical=False)

        cert = cls(x509_object=builder.sign(private_key._private_key, algorithm=hashes.SHA256()))

        _OWASPLogger().log_event(
            event="ca_certificate_generated",
            level=logging.INFO,
            description="CA certificate generated",
            common_name=cert.common_name,
            validity_days=str(validity.days),
        )

        return cert

    def __hash__(self):
        """Return the hash of the private key."""
        return hash(self.raw)


class CertificateSigningRequest:
    """A representation of the certificate signing request."""

    _csr: x509.CertificateSigningRequest

    def __init__(
        self,
        raw: Optional[str] = None,  # Must remain first argument for backwards compatibility
        # Old Interface fields (ignored)
        common_name: Optional[str] = None,
        sans_dns: Optional[Set[str]] = None,
        sans_ip: Optional[Set[str]] = None,
        sans_oid: Optional[Set[str]] = None,
        email_address: Optional[str] = None,
        organization: Optional[str] = None,
        organizational_unit: Optional[str] = None,
        country_name: Optional[str] = None,
        state_or_province_name: Optional[str] = None,
        locality_name: Optional[str] = None,
        has_unique_identifier: Optional[bool] = None,
        # End Old Interface fields
        x509_object: Optional[x509.CertificateSigningRequest] = None,
    ):
        """Initialize the CertificateSigningRequest object.

        This initializer must maintain the old interface while also allowing
        instantiation from an existing x509_object. It ignores all fields
        other than raw and x509_object, preferring x509_object.
        """
        if x509_object:
            self._csr = x509_object
            return
        elif raw:
            try:
                self._csr = x509.load_pem_x509_csr(raw.encode())
            except ValueError as e:
                logger.error("Could not load CSR: %s", e)
                raise TLSCertificatesError("Could not load CSR")
            return
        raise ValueError("Either raw CSR string or x509_object must be provided")

    @property
    def common_name(self) -> str:
        """Return the common name of the CSR."""
        common_name = self._csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return str(common_name[0].value) if common_name else ""

    @property
    def sans_dns(self) -> Set[str]:
        """Return the DNS Subject Alternative Names of the CSR."""
        with suppress(x509.ExtensionNotFound):
            sans = self._csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san) for san in sans.get_values_for_type(x509.DNSName)}
        return set()

    @property
    def sans_ip(self) -> Set[str]:
        """Return the IP Subject Alternative Names of the CSR."""
        with suppress(x509.ExtensionNotFound):
            sans = self._csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san) for san in sans.get_values_for_type(x509.IPAddress)}
        return set()

    @property
    def sans_oid(self) -> Set[str]:
        """Return the OID Subject Alternative Names of the CSR."""
        with suppress(x509.ExtensionNotFound):
            sans = self._csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return {str(san.dotted_string) for san in sans.get_values_for_type(x509.RegisteredID)}
        return set()

    @property
    def email_address(self) -> Optional[str]:
        """Return the email address of the CSR."""
        email_address = self._csr.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
        return str(email_address[0].value) if email_address else None

    @property
    def organization(self) -> Optional[str]:
        """Return the organization name of the CSR."""
        organization = self._csr.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        return str(organization[0].value) if organization else None

    @property
    def organizational_unit(self) -> Optional[str]:
        """Return the organizational unit name of the CSR."""
        organizational_unit = self._csr.subject.get_attributes_for_oid(
            NameOID.ORGANIZATIONAL_UNIT_NAME
        )
        return str(organizational_unit[0].value) if organizational_unit else None

    @property
    def country_name(self) -> Optional[str]:
        """Return the country name of the CSR."""
        country_name = self._csr.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        return str(country_name[0].value) if country_name else None

    @property
    def state_or_province_name(self) -> Optional[str]:
        """Return the state or province name of the CSR."""
        state_or_province_name = self._csr.subject.get_attributes_for_oid(
            NameOID.STATE_OR_PROVINCE_NAME
        )
        return str(state_or_province_name[0].value) if state_or_province_name else None

    @property
    def locality_name(self) -> Optional[str]:
        """Return the locality name of the CSR."""
        locality_name = self._csr.subject.get_attributes_for_oid(NameOID.LOCALITY_NAME)
        return str(locality_name[0].value) if locality_name else None

    @property
    def has_unique_identifier(self) -> bool:
        """Return whether the CSR has a unique identifier."""
        unique_identifier = self._csr.subject.get_attributes_for_oid(
            NameOID.X500_UNIQUE_IDENTIFIER
        )
        return bool(unique_identifier)

    @property
    def raw(self) -> str:
        """Return the PEM-formatted string representation of the CSR."""
        return self.__str__()

    def __str__(self) -> str:
        """Return the CSR as a string."""
        return self._csr.public_bytes(serialization.Encoding.PEM).decode().strip()

    @property
    def additional_critical_extensions(self) -> List[x509.ExtensionType]:
        """Return additional critical extensions present on the CSR (excluding SAN)."""
        extensions: List[x509.ExtensionType] = []
        for extension in self._csr.extensions:
            if extension.critical and extension.oid != ExtensionOID.SUBJECT_ALTERNATIVE_NAME:
                extensions.append(extension.value)
        return extensions

    @classmethod
    def from_string(cls, csr: str) -> "CertificateSigningRequest":
        """Create a CertificateSigningRequest object from a CSR."""
        return cls(raw=csr)

    @classmethod
    def from_csr(cls, csr: x509.CertificateSigningRequest) -> "CertificateSigningRequest":
        """Create a CertificateSigningRequest object from a CSR."""
        return cls(x509_object=csr)

    def __eq__(self, other: object) -> bool:
        """Check if two CertificateSigningRequest objects are equal."""
        if not isinstance(other, CertificateSigningRequest):
            return NotImplemented
        return self.raw == other.raw

    def __hash__(self):
        """Return the hash of the private key."""
        return hash(self.raw)

    def matches_certificate(self, certificate: Certificate) -> bool:
        """Check if this CSR matches a given certificate.

        Args:
            certificate (Certificate): The certificate to validate against.

        Returns:
            bool: True if the CSR matches the certificate, False otherwise.
        """
        return self._csr.public_key() == certificate._cert.public_key()

    def matches_private_key(self, key: PrivateKey) -> bool:
        """Check if a CSR matches a private key.

        This function only works with RSA keys.

        Args:
            key (PrivateKey): Private key
        Returns:
            bool: True/False depending on whether the CSR matches the private key.
        """
        try:
            key_object_public_key = key._private_key.public_key()
            csr_object_public_key = self._csr.public_key()
            if not isinstance(key_object_public_key, rsa.RSAPublicKey):
                logger.warning("Key is not an RSA key")
                return False
            if not isinstance(csr_object_public_key, rsa.RSAPublicKey):
                logger.warning("CSR is not an RSA key")
                return False
            if (
                csr_object_public_key.public_numbers().n
                != key_object_public_key.public_numbers().n
            ):
                logger.warning("Public key numbers between CSR and key do not match")
                return False
        except ValueError:
            logger.warning("Could not load certificate or CSR.")
            return False
        return True

    def get_sha256_hex(self) -> str:
        """Calculate the hash of the provided data and return the hexadecimal representation."""
        digest = hashes.Hash(hashes.SHA256())
        digest.update(self.raw.encode())
        return digest.finalize().hex()

    def sign(
        self, ca: Certificate, ca_private_key: PrivateKey, validity: timedelta, is_ca: bool = False
    ) -> Certificate:
        """Sign this CSR with the given CA and CA private key.

        Args:
            ca: The CA certificate.
            ca_private_key: The CA private key.
            validity: The validity period of the certificate.
            is_ca: Whether the generated certificate is a CA certificate.

        Returns:
            Certificate: The signed certificate.
        """
        return Certificate.generate(
            csr=self,
            ca=ca,
            ca_private_key=ca_private_key,
            validity=validity,
            is_ca=is_ca,
        )

    @classmethod
    def generate(
        cls,
        attributes: "CertificateRequestAttributes",
        private_key: PrivateKey,
    ) -> "CertificateSigningRequest":
        """Generate a CSR using the supplied attributes and private key.

        Args:
            attributes (CertificateRequestAttributes): Certificate request attributes
            private_key (PrivateKey): Private key
        Returns:
            CertificateSigningRequest: CSR
        """
        signing_key = private_key._private_key
        assert isinstance(signing_key, CertificateIssuerPrivateKeyTypes)

        csr_builder = x509.CertificateSigningRequestBuilder()
        if subject_name := _extract_subject_name_attributes(attributes):
            csr_builder = csr_builder.subject_name(subject_name)

        _sans: List[x509.GeneralName] = []
        if attributes.sans_oid:
            _sans.extend(
                [x509.RegisteredID(x509.ObjectIdentifier(san)) for san in attributes.sans_oid]
            )
        if attributes.sans_ip:
            _sans.extend([x509.IPAddress(ipaddress.ip_address(san)) for san in attributes.sans_ip])
        if attributes.sans_dns:
            _sans.extend([x509.DNSName(san) for san in attributes.sans_dns])
        if _sans:
            csr_builder = csr_builder.add_extension(
                x509.SubjectAlternativeName(set(_sans)), critical=False
            )
        if attributes.additional_critical_extensions:
            for extension in attributes.additional_critical_extensions:
                csr_builder = csr_builder.add_extension(extension, critical=True)
        signed_certificate_request = csr_builder.sign(signing_key, hashes.SHA256())
        return cls(x509_object=signed_certificate_request)


class CertificateRequestAttributes:
    """A representation of the certificate request attributes."""

    def __init__(
        self,
        common_name: Optional[str] = None,
        sans_dns: Optional[Collection[str]] = None,
        sans_ip: Optional[Collection[str]] = None,
        sans_oid: Optional[Collection[str]] = None,
        email_address: Optional[str] = None,
        organization: Optional[str] = None,
        organizational_unit: Optional[str] = None,
        country_name: Optional[str] = None,
        state_or_province_name: Optional[str] = None,
        locality_name: Optional[str] = None,
        is_ca: bool = False,
        add_unique_id_to_subject_name: bool = True,
        additional_critical_extensions: Optional[Collection[x509.ExtensionType]] = None,
    ):
        if not common_name and not sans_dns and not sans_ip and not sans_oid:
            raise ValueError(
                "At least one of common_name, sans_dns, sans_ip, or sans_oid must be provided"
            )
        self._common_name = common_name
        self._sans_dns = set(sans_dns) if sans_dns else None
        self._sans_ip = set(sans_ip) if sans_ip else None
        self._sans_oid = set(sans_oid) if sans_oid else None
        self._email_address = email_address
        self._organization = organization
        self._organizational_unit = organizational_unit
        self._country_name = country_name
        self._state_or_province_name = state_or_province_name
        self._locality_name = locality_name
        self._is_ca = is_ca
        self._add_unique_id_to_subject_name = add_unique_id_to_subject_name
        self._additional_critical_extensions = list(additional_critical_extensions or [])

    @property
    def common_name(self) -> str:
        """Return the common name."""
        # For legacy interface compatibility, return empty string if not set
        return self._common_name if self._common_name else ""

    @property
    def sans_dns(self) -> Optional[Set[str]]:
        """Return the DNS Subject Alternative Names."""
        return self._sans_dns

    @property
    def sans_ip(self) -> Optional[Set[str]]:
        """Return the IP Subject Alternative Names."""
        return self._sans_ip

    @property
    def sans_oid(self) -> Optional[Set[str]]:
        """Return the OID Subject Alternative Names."""
        return self._sans_oid

    @property
    def email_address(self) -> Optional[str]:
        """Return the email address."""
        return self._email_address

    @property
    def organization(self) -> Optional[str]:
        """Return the organization name."""
        return self._organization

    @property
    def organizational_unit(self) -> Optional[str]:
        """Return the organizational unit name."""
        return self._organizational_unit

    @property
    def country_name(self) -> Optional[str]:
        """Return the country name."""
        return self._country_name

    @property
    def state_or_province_name(self) -> Optional[str]:
        """Return the state or province name."""
        return self._state_or_province_name

    @property
    def locality_name(self) -> Optional[str]:
        """Return the locality name."""
        return self._locality_name

    @property
    def is_ca(self) -> bool:
        """Return whether the certificate is a CA certificate."""
        return self._is_ca

    @property
    def add_unique_id_to_subject_name(self) -> bool:
        """Return whether to add a unique identifier to the subject name."""
        return self._add_unique_id_to_subject_name

    @property
    def additional_critical_extensions(self) -> List[x509.ExtensionType]:
        """Return additional critical extensions to be added to the CSR."""
        return self._additional_critical_extensions

    @classmethod
    def from_csr(
        cls, csr: CertificateSigningRequest, is_ca: bool
    ) -> "CertificateRequestAttributes":
        """Create CertificateRequestAttributes from a CertificateSigningRequest.

        Args:
            csr: The CSR to extract attributes from.
            is_ca: Whether a CA certificate is being requested.

        Returns:
            CertificateRequestAttributes: The extracted attributes.
        """
        return cls(
            common_name=csr.common_name,
            sans_dns=csr.sans_dns,
            sans_ip=csr.sans_ip,
            sans_oid=csr.sans_oid,
            email_address=csr.email_address,
            organization=csr.organization,
            organizational_unit=csr.organizational_unit,
            country_name=csr.country_name,
            state_or_province_name=csr.state_or_province_name,
            locality_name=csr.locality_name,
            is_ca=is_ca,
            add_unique_id_to_subject_name=csr.has_unique_identifier,
            additional_critical_extensions=csr.additional_critical_extensions,
        )

    def __eq__(self, other: object) -> bool:
        """Check if two CertificateRequestAttributes objects are equal."""
        if not isinstance(other, CertificateRequestAttributes):
            return NotImplemented
        return (
            self.common_name == other.common_name
            and self.sans_dns == other.sans_dns
            and self.sans_ip == other.sans_ip
            and self.sans_oid == other.sans_oid
            and self.email_address == other.email_address
            and self.organization == other.organization
            and self.organizational_unit == other.organizational_unit
            and self.country_name == other.country_name
            and self.state_or_province_name == other.state_or_province_name
            and self.locality_name == other.locality_name
            and self.is_ca == other.is_ca
            and self.add_unique_id_to_subject_name == other.add_unique_id_to_subject_name
            and self.additional_critical_extensions == other.additional_critical_extensions
        )

    def is_valid(self) -> bool:
        """Validate the attributes of the certificate request.

        Returns:
            bool: True if the attributes are valid, False otherwise.
        """
        if not self.common_name and not self.sans_dns and not self.sans_ip and not self.sans_oid:
            logger.warning(
                "At least one of common_name, sans_dns, sans_ip, or sans_oid must be provided"
            )
            return False
        return True

    def generate_csr(
        self,
        private_key: PrivateKey,
    ) -> CertificateSigningRequest:
        """Generate a CSR using the current attributes and a private key.

        Args:
            private_key (PrivateKey): Private key to sign the CSR.

        Returns:
            CertificateSigningRequest: The generated CSR.
        """
        return CertificateSigningRequest.generate(self, private_key)


@dataclass(frozen=True)
class ProviderCertificate:
    """This class represents a certificate provided by the TLS provider."""

    relation_id: int
    certificate: Certificate
    certificate_signing_request: CertificateSigningRequest
    ca: Certificate
    chain: List[Certificate]
    revoked: Optional[bool] = None

    def to_json(self) -> str:
        """Return the object as a JSON string.

        Returns:
            str: JSON representation of the object
        """
        return json.dumps(
            {
                "csr": str(self.certificate_signing_request),
                "certificate": str(self.certificate),
                "ca": str(self.ca),
                "chain": [str(cert) for cert in self.chain],
                "revoked": self.revoked,
            }
        )


@dataclass(frozen=True)
class RequirerCertificateRequest:
    """This class represents a certificate signing request requested by a specific TLS requirer."""

    relation_id: int
    certificate_signing_request: CertificateSigningRequest
    is_ca: bool


class CertificateAvailableEvent(EventBase):
    """Charm Event triggered when a TLS certificate is available."""

    def __init__(
        self,
        handle: Handle,
        certificate: Certificate,
        certificate_signing_request: CertificateSigningRequest,
        ca: Certificate,
        chain: List[Certificate],
    ):
        super().__init__(handle)
        self.certificate = certificate
        self.certificate_signing_request = certificate_signing_request
        self.ca = ca
        self.chain = chain

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "certificate": str(self.certificate),
            "certificate_signing_request": str(self.certificate_signing_request),
            "ca": str(self.ca),
            "chain": json.dumps([str(certificate) for certificate in self.chain]),
        }

    def restore(self, snapshot: dict):
        """Restore snapshot."""
        self.certificate = Certificate.from_string(snapshot["certificate"])
        self.certificate_signing_request = CertificateSigningRequest.from_string(
            snapshot["certificate_signing_request"]
        )
        self.ca = Certificate.from_string(snapshot["ca"])
        chain_strs = json.loads(snapshot["chain"])
        self.chain = [Certificate.from_string(chain_str) for chain_str in chain_strs]

    def chain_as_pem(self) -> str:
        """Return full certificate chain as a PEM string."""
        return "\n\n".join([str(cert) for cert in self.chain])


def generate_private_key(
    key_size: int = 2048,
    public_exponent: int = 65537,
) -> PrivateKey:
    """Generate a private key with the RSA algorithm.

    Args:
        key_size (int): Key size in bits, must be at least 2048 bits
        public_exponent: Public exponent.

    Returns:
        PrivateKey: Private Key
    """
    warnings.warn(
        "generate_private_key() is deprecated. Use PrivateKey.generate() instead.",
        DeprecationWarning,
    )
    return PrivateKey.generate(key_size=key_size, public_exponent=public_exponent)


def calculate_relative_datetime(target_time: datetime, fraction: float) -> datetime:
    """Calculate a datetime that is a given percentage from now to a target time.

    Args:
        target_time (datetime): The future datetime to interpolate towards.
        fraction (float): Fraction of the interval from now to target_time (0.0-1.0).
            1.0 means return target_time,
            0.9 means return the time after 90% of the interval has passed,
            and 0.0 means return now.
    """
    if fraction <= 0.0 or fraction > 1.0:
        raise ValueError("Invalid fraction. Must be between 0.0 and 1.0")
    now = datetime.now(timezone.utc)
    time_until_target = target_time - now
    return now + time_until_target * fraction


def chain_has_valid_order(chain: List[str]) -> bool:
    """Check if the chain has a valid order.

    Validates that each certificate in the chain is properly signed by the next certificate.
    The chain should be ordered from leaf to root, where each certificate is signed by
    the next one in the chain.

    Args:
        chain (List[str]): List of certificates in PEM format, ordered from leaf to root

    Returns:
        bool: True if the chain has a valid order, False otherwise.
    """
    if len(chain) < 2:
        return True

    try:
        for i in range(len(chain) - 1):
            cert = x509.load_pem_x509_certificate(chain[i].encode())
            issuer = x509.load_pem_x509_certificate(chain[i + 1].encode())
            cert.verify_directly_issued_by(issuer)
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


def generate_csr(  # noqa: C901
    private_key: PrivateKey,
    common_name: str,
    sans_dns: Optional[FrozenSet[str]] = frozenset(),
    sans_ip: Optional[FrozenSet[str]] = frozenset(),
    sans_oid: Optional[FrozenSet[str]] = frozenset(),
    organization: Optional[str] = None,
    organizational_unit: Optional[str] = None,
    email_address: Optional[str] = None,
    country_name: Optional[str] = None,
    locality_name: Optional[str] = None,
    state_or_province_name: Optional[str] = None,
    add_unique_id_to_subject_name: bool = True,
) -> CertificateSigningRequest:
    """Generate a CSR using private key and subject.

    Args:
        private_key (PrivateKey): Private key
        common_name (str): Common name
        sans_dns (FrozenSet[str]): DNS Subject Alternative Names
        sans_ip (FrozenSet[str]): IP Subject Alternative Names
        sans_oid (FrozenSet[str]): OID Subject Alternative Names
        organization (Optional[str]): Organization name
        organizational_unit (Optional[str]): Organizational unit name
        email_address (Optional[str]): Email address
        country_name (Optional[str]): Country name
        state_or_province_name (Optional[str]): State or province name
        locality_name (Optional[str]): Locality name
        add_unique_id_to_subject_name (bool): Whether a unique ID must be added to the CSR's
            subject name. Always leave to "True" when the CSR is used to request certificates
            using the tls-certificates relation.

    Returns:
        CertificateSigningRequest: CSR
    """
    warnings.warn(
        "generate_csr() is deprecated. Use CertificateRequestAttributes.generate_csr() or CertificateSigningRequest.generate() instead.",
        DeprecationWarning,
    )
    return CertificateRequestAttributes(
        common_name=common_name,
        sans_dns=sans_dns,
        sans_ip=sans_ip,
        sans_oid=sans_oid,
        organization=organization,
        organizational_unit=organizational_unit,
        email_address=email_address,
        country_name=country_name,
        state_or_province_name=state_or_province_name,
        locality_name=locality_name,
        add_unique_id_to_subject_name=add_unique_id_to_subject_name,
    ).generate_csr(private_key=private_key)


def generate_ca(
    private_key: PrivateKey,
    validity: timedelta,
    common_name: str,
    sans_dns: Optional[FrozenSet[str]] = frozenset(),
    sans_ip: Optional[FrozenSet[str]] = frozenset(),
    sans_oid: Optional[FrozenSet[str]] = frozenset(),
    organization: Optional[str] = None,
    organizational_unit: Optional[str] = None,
    email_address: Optional[str] = None,
    country_name: Optional[str] = None,
    state_or_province_name: Optional[str] = None,
    locality_name: Optional[str] = None,
) -> Certificate:
    """Generate a self signed CA Certificate.

    Args:
        private_key: Private key
        validity: Certificate validity time
        common_name: Common Name that can be an IP or a Full Qualified Domain Name (FQDN).
        sans_dns: DNS Subject Alternative Names
        sans_ip: IP Subject Alternative Names
        sans_oid: OID Subject Alternative Names
        organization: Organization name
        organizational_unit: Organizational unit name
        email_address: Email address
        country_name: Certificate Issuing country
        state_or_province_name: Certificate Issuing state or province
        locality_name: Certificate Issuing locality

    Returns:
        CA Certificate.
    """
    warnings.warn(
        "generate_ca() is deprecated. Use Certificate.generate_self_signed_ca() instead.",
        DeprecationWarning,
    )
    attributes = CertificateRequestAttributes(
        common_name=common_name,
        sans_dns=sans_dns,
        sans_ip=sans_ip,
        sans_oid=sans_oid,
        organization=organization,
        organizational_unit=organizational_unit,
        email_address=email_address,
        country_name=country_name,
        state_or_province_name=state_or_province_name,
        locality_name=locality_name,
        is_ca=True,
    )
    return Certificate.generate_self_signed_ca(attributes, private_key, validity)


def _san_extension(
    email_address: Optional[str] = None,
    sans_dns: Optional[Collection[str]] = frozenset(),
    sans_ip: Optional[Collection[str]] = frozenset(),
    sans_oid: Optional[Collection[str]] = frozenset(),
) -> Optional[x509.SubjectAlternativeName]:
    sans: List[x509.GeneralName] = []
    if email_address:
        # If an e-mail address was provided, it should always be in the SAN
        sans.append(x509.RFC822Name(email_address))
    if sans_dns:
        sans.extend([x509.DNSName(san) for san in sans_dns])
    if sans_ip:
        sans.extend([x509.IPAddress(ipaddress.ip_address(san)) for san in sans_ip])
    if sans_oid:
        sans.extend([x509.RegisteredID(x509.ObjectIdentifier(san)) for san in sans_oid])
    if not sans:
        return None
    return x509.SubjectAlternativeName(sans)


def generate_certificate(
    csr: CertificateSigningRequest,
    ca: Certificate,
    ca_private_key: PrivateKey,
    validity: timedelta,
    is_ca: bool = False,
) -> Certificate:
    """Generate a TLS certificate based on a CSR.

    Args:
        csr (CertificateSigningRequest): CSR
        ca (Certificate): CA Certificate
        ca_private_key (PrivateKey): CA private key
        validity (timedelta): Certificate validity time
        is_ca (bool): Whether the certificate is a CA certificate

    Returns:
        Certificate: Certificate
    """
    warnings.warn(
        "generate_certificate() is deprecated. Use Certificate.generate() instead.",
        DeprecationWarning,
    )
    return Certificate.generate(
        csr=csr,
        ca=ca,
        ca_private_key=ca_private_key,
        validity=validity,
        is_ca=is_ca,
    )


def _extract_subject_name_attributes(
    attributes: CertificateRequestAttributes,
) -> Optional[x509.Name]:
    subject_name_attributes = []
    if attributes.common_name:
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.COMMON_NAME, attributes.common_name)
        )
    if attributes.add_unique_id_to_subject_name:
        unique_identifier = uuid.uuid4()
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.X500_UNIQUE_IDENTIFIER, str(unique_identifier))
        )
    if attributes.organization:
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, attributes.organization)
        )
    if attributes.organizational_unit:
        subject_name_attributes.append(
            x509.NameAttribute(
                x509.NameOID.ORGANIZATIONAL_UNIT_NAME,
                attributes.organizational_unit,
            )
        )
    if attributes.email_address:
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.EMAIL_ADDRESS, attributes.email_address)
        )
    if attributes.country_name:
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, attributes.country_name)
        )
    if attributes.state_or_province_name:
        subject_name_attributes.append(
            x509.NameAttribute(
                x509.NameOID.STATE_OR_PROVINCE_NAME,
                attributes.state_or_province_name,
            )
        )
    if attributes.locality_name:
        subject_name_attributes.append(
            x509.NameAttribute(x509.NameOID.LOCALITY_NAME, attributes.locality_name)
        )

    if subject_name_attributes:
        return x509.Name(subject_name_attributes)

    return None


def _generate_certificate_request_extensions(
    authority_key_identifier: bytes,
    csr: x509.CertificateSigningRequest,
    is_ca: bool,
) -> List[x509.Extension]:
    """Generate a list of certificate extensions from a CSR and other known information.

    Args:
        authority_key_identifier (bytes): Authority key identifier
        csr (x509.CertificateSigningRequest): CSR
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
    if sans := _generate_subject_alternative_name_extension(csr):
        cert_extensions_list.append(sans)

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


def _generate_subject_alternative_name_extension(
    csr: x509.CertificateSigningRequest,
) -> Optional[x509.Extension]:
    sans: List[x509.GeneralName] = []
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
        sans.extend(
            [
                x509.RFC822Name(name)
                for name in loaded_san_ext.value.get_values_for_type(x509.RFC822Name)
            ]
        )
    except x509.ExtensionNotFound:
        pass
    # If email is present in the CSR Subject, make sure it is also in the SANS
    # to conform to RFC 5280.
    email = csr.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
    if email:
        email_rfc822 = x509.RFC822Name(str(email[0].value))
        if email_rfc822 not in sans:
            sans.append(email_rfc822)

    return (
        x509.Extension(
            oid=ExtensionOID.SUBJECT_ALTERNATIVE_NAME,
            critical=False,
            value=x509.SubjectAlternativeName(sans),
        )
        if sans
        else None
    )


class CertificatesRequirerCharmEvents(CharmEvents):
    """List of events that the TLS Certificates requirer charm can leverage."""

    certificate_available = EventSource(CertificateAvailableEvent)


class TLSCertificatesRequiresV4(Object):
    """A class to manage the TLS certificates interface for a unit or app."""

    on = CertificatesRequirerCharmEvents()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: CharmBase,
        relationship_name: str,
        certificate_requests: List[CertificateRequestAttributes],
        mode: Mode = Mode.UNIT,
        refresh_events: List[BoundEvent] = [],
        private_key: Optional[PrivateKey] = None,
        renewal_relative_time: float = 0.9,
    ):
        """Create a new instance of the TLSCertificatesRequiresV4 class.

        Args:
            charm (CharmBase): The charm instance to relate to.
            relationship_name (str): The name of the relation that provides the certificates.
            certificate_requests (List[CertificateRequestAttributes]):
                A list with the attributes of the certificate requests.
            mode (Mode): Whether to use unit or app certificates mode. Default is Mode.UNIT.
                In UNIT mode the requirer will place the csr in the unit relation data.
                Each unit will manage its private key,
                certificate signing request and certificate.
                UNIT mode is for use cases where each unit has its own identity.
                If you don't know which mode to use, you likely need UNIT.
                In APP mode the leader unit will place the csr in the app relation databag.
                APP mode is for use cases where the underlying application needs the certificate
                for example using it as an intermediate CA to sign other certificates.
                The certificate can only be accessed by the leader unit.
            refresh_events (List[BoundEvent]): A list of events to trigger a refresh of
              the certificates.
            private_key (Optional[PrivateKey]): The private key to use for the certificates.
                If provided, it will be used instead of generating a new one.
                If the key is not valid an exception will be raised.
                Using this parameter is discouraged,
                having to pass around private keys manually can be a security concern.
                Allowing the library to generate and manage the key is the more secure approach.
            renewal_relative_time (float): The time to renew the certificate relative to its
                expiry.
                Default is 0.9, meaning 90% of the validity period.
                The minimum value is 0.5, meaning 50% of the validity period.
                If an invalid value is provided, an exception will be raised.
        """
        super().__init__(charm, relationship_name)
        if not JujuVersion.from_environ().has_secrets:
            logger.warning("This version of the TLS library requires Juju secrets (Juju >= 3.0)")
        if not self._mode_is_valid(mode):
            raise TLSCertificatesError("Invalid mode. Must be Mode.UNIT or Mode.APP")
        for certificate_request in certificate_requests:
            if not certificate_request.is_valid():
                raise TLSCertificatesError("Invalid certificate request")
        self.charm = charm
        self.relationship_name = relationship_name
        self.certificate_requests = certificate_requests
        self.mode = mode
        if private_key and not private_key.is_valid():
            raise TLSCertificatesError("Invalid private key")
        if renewal_relative_time <= 0.5 or renewal_relative_time > 1.0:
            raise TLSCertificatesError(
                "Invalid renewal relative time. Must be between 0.5 and 1.0"
            )
        self._private_key = private_key
        self.renewal_relative_time = renewal_relative_time
        self.framework.observe(charm.on[relationship_name].relation_created, self._configure)
        self.framework.observe(charm.on[relationship_name].relation_changed, self._configure)
        self.framework.observe(charm.on.secret_expired, self._on_secret_expired)
        self.framework.observe(charm.on.secret_remove, self._on_secret_remove)
        for event in refresh_events:
            self.framework.observe(event, self._configure)
        self._security_logger = _OWASPLogger(application=f"tls-certificates-{charm.app.name}")

    def _configure(self, _: Optional[EventBase] = None):
        """Handle TLS Certificates Relation Data.

        This method is called during any TLS relation event.
        It will generate a private key if it doesn't exist yet.
        It will send certificate requests if they haven't been sent yet.
        It will find available certificates and emit events.
        """
        if not self._tls_relation_created():
            logger.debug("TLS relation not created yet.")
            return
        self._ensure_private_key()
        self._cleanup_certificate_requests()
        self._send_certificate_requests()
        self._find_available_certificates()

    def _mode_is_valid(self, mode: Mode) -> bool:
        return mode in [Mode.UNIT, Mode.APP]

    def _validate_secret_exists(self, secret: Secret) -> None:
        secret.get_info()  # Will raise `SecretNotFoundError` if the secret does not exist

    def _on_secret_remove(self, event: SecretRemoveEvent) -> None:
        """Handle Secret Removed Event."""
        try:
            # Ensure the secret exists before trying to remove it, otherwise
            # the unit could be stuck in an error state. See the docstring of
            # `remove_revision` and the below issue for more information.
            # https://github.com/juju/juju/issues/19036
            self._validate_secret_exists(event.secret)
            event.secret.remove_revision(event.revision)
        except SecretNotFoundError:
            logger.warning(
                "No such secret %s, nothing to remove",
                event.secret.label or event.secret.id,
            )
            return

    def _on_secret_expired(self, event: SecretExpiredEvent) -> None:
        """Handle Secret Expired Event.

        Renews certificate requests and removes the expired secret.
        """
        if not event.secret.label or not event.secret.label.startswith(f"{LIBID}-certificate"):
            return
        try:
            csr_str = event.secret.get_content(refresh=True)["csr"]
        except ModelError:
            logger.error("Failed to get CSR from secret - Skipping")
            return
        csr = CertificateSigningRequest.from_string(csr_str)
        self._renew_certificate_request(csr)
        event.secret.remove_all_revisions()

    def sync(self) -> None:
        """Sync TLS Certificates Relation Data.

        This method allows the requirer to sync the TLS certificates relation data
        without waiting for the refresh events to be triggered.
        """
        self._configure()

    def renew_certificate(self, certificate: ProviderCertificate) -> None:
        """Request the renewal of the provided certificate."""
        certificate_signing_request = certificate.certificate_signing_request
        secret_label = self._get_csr_secret_label(certificate_signing_request)
        try:
            secret = self.model.get_secret(label=secret_label)
        except SecretNotFoundError:
            logger.warning("No matching secret found - Skipping renewal")
            return
        current_csr = secret.get_content(refresh=True).get("csr", "")
        if current_csr != str(certificate_signing_request):
            logger.warning("No matching CSR found - Skipping renewal")
            return
        self._renew_certificate_request(certificate_signing_request)
        secret.remove_all_revisions()

    def _renew_certificate_request(self, csr: CertificateSigningRequest):
        """Remove existing CSR from relation data and create a new one."""
        self._remove_requirer_csr_from_relation_data(csr)
        self._send_certificate_requests()
        logger.info("Renewed certificate request")

    def _remove_requirer_csr_from_relation_data(self, csr: CertificateSigningRequest) -> None:
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            logger.debug("No relation: %s", self.relationship_name)
            return
        if not self.get_csrs_from_requirer_relation_data():
            logger.info("No CSRs in relation data - Doing nothing")
            return
        app_or_unit = self._get_app_or_unit()
        try:
            requirer_relation_data = _RequirerData.load(relation.data[app_or_unit])
        except DataValidationError:
            logger.warning("Invalid relation data - Skipping removal of CSR")
            return
        new_relation_data = copy.deepcopy(requirer_relation_data.certificate_signing_requests)
        for requirer_csr in new_relation_data:
            if requirer_csr.certificate_signing_request.strip() == str(csr).strip():
                new_relation_data.remove(requirer_csr)
        try:
            _RequirerData(certificate_signing_requests=new_relation_data).dump(
                relation.data[app_or_unit]
            )
            logger.info("Removed CSR from relation data")
        except ModelError:
            logger.warning("Failed to update relation data")

    def _get_app_or_unit(self) -> Union[Application, Unit]:
        """Return the unit or app object based on the mode."""
        if self.mode == Mode.UNIT:
            return self.model.unit
        elif self.mode == Mode.APP:
            return self.model.app
        raise TLSCertificatesError("Invalid mode")

    @property
    def private_key(self) -> Optional[PrivateKey]:
        """Return the private key."""
        if self._private_key:
            return self._private_key
        if not self._private_key_generated():
            return None
        secret = self.charm.model.get_secret(label=self._get_private_key_secret_label())
        private_key = secret.get_content(refresh=True)["private-key"]
        return PrivateKey.from_string(private_key)

    def _ensure_private_key(self) -> None:
        """Make sure there is a private key to be used.

        It will make sure there is a private key passed by the charm using the private_key
        parameter or generate a new one otherwise.
        """
        # Remove the generated private key
        # if one has been passed by the charm using the private_key parameter
        if self._private_key:
            self._remove_private_key_secret()
            return
        if self._private_key_generated():
            logger.debug("Private key already generated")
            return
        self._generate_private_key()

    def regenerate_private_key(self) -> None:
        """Regenerate the private key.

        Generate a new private key, remove old certificate requests and send new ones.

        Raises:
            TLSCertificatesError: If the private key is passed by the charm using the
                private_key parameter.
        """
        if self._private_key:
            raise TLSCertificatesError(
                "Private key is passed by the charm through the private_key parameter, "
                "this function can't be used"
            )
        if not self._private_key_generated():
            logger.warning("No private key to regenerate")
            return
        self._generate_private_key()
        self._cleanup_certificate_requests()
        self._send_certificate_requests()

    def _generate_private_key(self) -> None:
        """Generate a new private key and store it in a secret.

        This is the case when the private key used is generated by the library.
            and not passed by the charm using the private_key parameter.
        """
        self._store_private_key_in_secret(generate_private_key())
        logger.info("Private key generated")

    def _private_key_generated(self) -> bool:
        """Check if a private key is stored in a secret.

        This is the case when the private key used is generated by the library.
        This should not exist when the private key used
            is passed by the charm using the private_key parameter.
        """
        try:
            secret = self.charm.model.get_secret(label=self._get_private_key_secret_label())
            secret.get_content(refresh=True)
            return True
        except SecretNotFoundError:
            return False

    def _store_private_key_in_secret(self, private_key: PrivateKey) -> None:
        try:
            secret = self.charm.model.get_secret(label=self._get_private_key_secret_label())
            secret.set_content({"private-key": str(private_key)})
            secret.get_content(refresh=True)
        except SecretNotFoundError:
            self.charm.unit.add_secret(
                content={"private-key": str(private_key)},
                label=self._get_private_key_secret_label(),
            )

    def _remove_private_key_secret(self) -> None:
        """Remove the private key secret."""
        try:
            secret = self.charm.model.get_secret(label=self._get_private_key_secret_label())
            secret.remove_all_revisions()
        except SecretNotFoundError:
            logger.warning("Private key secret not found, nothing to remove")

    def _csr_matches_certificate_request(
        self, certificate_signing_request: CertificateSigningRequest, is_ca: bool
    ) -> bool:
        for certificate_request in self.certificate_requests:
            if certificate_request == CertificateRequestAttributes.from_csr(
                certificate_signing_request,
                is_ca,
            ):
                return True
        return False

    def _certificate_requested(self, certificate_request: CertificateRequestAttributes) -> bool:
        if not self.private_key:
            return False
        csr = self._certificate_requested_for_attributes(certificate_request)
        if not csr:
            return False
        if not csr.certificate_signing_request.matches_private_key(key=self.private_key):
            return False
        return True

    def _certificate_requested_for_attributes(
        self,
        certificate_request: CertificateRequestAttributes,
    ) -> Optional[RequirerCertificateRequest]:
        for requirer_csr in self.get_csrs_from_requirer_relation_data():
            if certificate_request == CertificateRequestAttributes.from_csr(
                requirer_csr.certificate_signing_request,
                requirer_csr.is_ca,
            ):
                return requirer_csr
        return None

    def get_csrs_from_requirer_relation_data(self) -> List[RequirerCertificateRequest]:
        """Return list of requirer's CSRs from relation data."""
        if self.mode == Mode.APP and not self.model.unit.is_leader():
            logger.debug("Not a leader unit - Skipping")
            return []
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            logger.debug("No relation: %s", self.relationship_name)
            return []
        app_or_unit = self._get_app_or_unit()
        try:
            requirer_relation_data = _RequirerData.load(relation.data[app_or_unit])
        except DataValidationError:
            logger.warning("Invalid relation data")
            return []
        requirer_csrs = []
        for csr in requirer_relation_data.certificate_signing_requests:
            requirer_csrs.append(
                RequirerCertificateRequest(
                    relation_id=relation.id,
                    certificate_signing_request=CertificateSigningRequest.from_string(
                        csr.certificate_signing_request
                    ),
                    is_ca=csr.ca if csr.ca else False,
                )
            )
        return requirer_csrs

    def get_provider_certificates(self) -> List[ProviderCertificate]:
        """Return list of certificates from the provider's relation data."""
        return self._load_provider_certificates()

    def _load_provider_certificates(self) -> List[ProviderCertificate]:
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            logger.debug("No relation: %s", self.relationship_name)
            return []
        if not relation.app:
            logger.debug("No remote app in relation: %s", self.relationship_name)
            return []
        try:
            provider_relation_data = _ProviderApplicationData.load(relation.data[relation.app])
        except DataValidationError:
            logger.warning("Invalid relation data")
            return []
        return [
            certificate.to_provider_certificate(relation_id=relation.id)
            for certificate in provider_relation_data.certificates
        ]

    def _request_certificate(self, csr: CertificateSigningRequest, is_ca: bool) -> None:
        """Add CSR to relation data."""
        if self.mode == Mode.APP and not self.model.unit.is_leader():
            logger.debug("Not a leader unit - Skipping")
            return
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            logger.debug("No relation: %s", self.relationship_name)
            return
        new_csr = _CertificateSigningRequest(
            certificate_signing_request=str(csr).strip(), ca=is_ca
        )
        app_or_unit = self._get_app_or_unit()
        try:
            requirer_relation_data = _RequirerData.load(relation.data[app_or_unit])
        except DataValidationError:
            requirer_relation_data = _RequirerData(
                certificate_signing_requests=[],
            )
        new_relation_data = copy.deepcopy(requirer_relation_data.certificate_signing_requests)
        new_relation_data.append(new_csr)
        try:
            _RequirerData(certificate_signing_requests=new_relation_data).dump(
                relation.data[app_or_unit]
            )
            logger.info("Certificate signing request added to relation data.")
        except ModelError:
            logger.warning("Failed to update relation data")

    def _send_certificate_requests(self):
        if not self.private_key:
            logger.debug("Private key not generated yet.")
            return
        for certificate_request in self.certificate_requests:
            if not self._certificate_requested(certificate_request):
                csr = certificate_request.generate_csr(
                    private_key=self.private_key,
                )
                if not csr:
                    logger.warning("Failed to generate CSR")
                    continue
                self._request_certificate(csr=csr, is_ca=certificate_request.is_ca)

    def get_assigned_certificate(
        self, certificate_request: CertificateRequestAttributes
    ) -> Tuple[Optional[ProviderCertificate], Optional[PrivateKey]]:
        """Get the certificate that was assigned to the given certificate request."""
        for requirer_csr in self.get_csrs_from_requirer_relation_data():
            if certificate_request == CertificateRequestAttributes.from_csr(
                requirer_csr.certificate_signing_request,
                requirer_csr.is_ca,
            ):
                return self._find_certificate_in_relation_data(requirer_csr), self.private_key
        return None, None

    def get_assigned_certificates(
        self,
    ) -> Tuple[List[ProviderCertificate], Optional[PrivateKey]]:
        """Get a list of certificates that were assigned to this or app."""
        assigned_certificates = []
        for requirer_csr in self.get_csrs_from_requirer_relation_data():
            if cert := self._find_certificate_in_relation_data(requirer_csr):
                assigned_certificates.append(cert)
        return assigned_certificates, self.private_key

    def _find_certificate_in_relation_data(
        self, csr: RequirerCertificateRequest
    ) -> Optional[ProviderCertificate]:
        """Return the certificate that matches the given CSR, validated against the private key."""
        if not self.private_key:
            return None
        for provider_certificate in self.get_provider_certificates():
            if provider_certificate.certificate_signing_request == csr.certificate_signing_request:
                if provider_certificate.certificate.is_ca and not csr.is_ca:
                    logger.warning("Non CA certificate requested, got a CA certificate, ignoring")
                    continue
                elif not provider_certificate.certificate.is_ca and csr.is_ca:
                    logger.warning("CA certificate requested, got a non CA certificate, ignoring")
                    continue
                if not provider_certificate.certificate.matches_private_key(self.private_key):
                    logger.warning(
                        "Certificate does not match the private key. Ignoring invalid certificate."
                    )
                    continue
                return provider_certificate
        return None

    def _find_available_certificates(self):
        """Find available certificates and emit events.

        This method will find certificates that are available for the requirer's CSRs.
        If a certificate is found, it will be set as a secret and an event will be emitted.
        If a certificate is revoked, the secret will be removed and an event will be emitted.
        """
        requirer_csrs = self.get_csrs_from_requirer_relation_data()
        csrs = [csr.certificate_signing_request for csr in requirer_csrs]
        provider_certificates = self.get_provider_certificates()
        for provider_certificate in provider_certificates:
            if provider_certificate.certificate_signing_request in csrs:
                secret_label = self._get_csr_secret_label(
                    provider_certificate.certificate_signing_request
                )
                if provider_certificate.revoked:
                    with suppress(SecretNotFoundError):
                        logger.debug(
                            "Removing secret with label %s",
                            secret_label,
                        )
                        secret = self.model.get_secret(label=secret_label)
                        secret.remove_all_revisions()
                else:
                    if not self._csr_matches_certificate_request(
                        certificate_signing_request=provider_certificate.certificate_signing_request,
                        is_ca=provider_certificate.certificate.is_ca,
                    ):
                        logger.debug("Certificate requested for different attributes - Skipping")
                        continue
                    try:
                        secret = self.model.get_secret(label=secret_label)
                        logger.debug("Setting secret with label %s", secret_label)
                        # Juju < 3.6 will create a new revision even if the content is the same
                        if secret.get_content(refresh=True).get("certificate", "") == str(
                            provider_certificate.certificate
                        ):
                            logger.debug(
                                "Secret %s with correct certificate already exists", secret_label
                            )
                            continue
                        secret.set_content(
                            content={
                                "certificate": str(provider_certificate.certificate),
                                "csr": str(provider_certificate.certificate_signing_request),
                            }
                        )
                        secret.set_info(
                            expire=calculate_relative_datetime(
                                target_time=provider_certificate.certificate.expiry_time,
                                fraction=self.renewal_relative_time,
                            ),
                        )
                        secret.get_content(refresh=True)
                    except SecretNotFoundError:
                        logger.debug("Creating new secret with label %s", secret_label)
                        secret = self.charm.unit.add_secret(
                            content={
                                "certificate": str(provider_certificate.certificate),
                                "csr": str(provider_certificate.certificate_signing_request),
                            },
                            label=secret_label,
                            expire=calculate_relative_datetime(
                                target_time=provider_certificate.certificate.expiry_time,
                                fraction=self.renewal_relative_time,
                            ),
                        )
                    self.on.certificate_available.emit(
                        certificate_signing_request=provider_certificate.certificate_signing_request,
                        certificate=provider_certificate.certificate,
                        ca=provider_certificate.ca,
                        chain=provider_certificate.chain,
                    )

    def _cleanup_certificate_requests(self):
        """Clean up certificate requests.

        Remove any certificate requests that falls into one of the following categories:
        - The CSR attributes do not match any of the certificate requests defined in
        the charm's certificate_requests attribute.
        - The CSR public key does not match the private key.
        """
        for requirer_csr in self.get_csrs_from_requirer_relation_data():
            if not self._csr_matches_certificate_request(
                certificate_signing_request=requirer_csr.certificate_signing_request,
                is_ca=requirer_csr.is_ca,
            ):
                self._remove_requirer_csr_from_relation_data(
                    requirer_csr.certificate_signing_request
                )
                logger.info(
                    "Removed CSR from relation data because it did not match any certificate request"  # noqa: E501
                )
            elif (
                self.private_key
                and not requirer_csr.certificate_signing_request.matches_private_key(
                    self.private_key
                )
            ):
                self._remove_requirer_csr_from_relation_data(
                    requirer_csr.certificate_signing_request
                )
                logger.info(
                    "Removed CSR from relation data because it did not match the private key"  # noqa: E501
                )

    def _tls_relation_created(self) -> bool:
        relation = self.model.get_relation(self.relationship_name)
        if not relation:
            return False
        return True

    def _get_private_key_secret_label(self) -> str:
        if self.mode == Mode.UNIT:
            return f"{LIBID}-private-key-{self._get_unit_number()}-{self.relationship_name}"
        elif self.mode == Mode.APP:
            return f"{LIBID}-private-key-{self.relationship_name}"
        else:
            raise TLSCertificatesError("Invalid mode. Must be Mode.UNIT or Mode.APP.")

    def _get_csr_secret_label(self, csr: CertificateSigningRequest) -> str:
        csr_in_sha256_hex = csr.get_sha256_hex()
        if self.mode == Mode.UNIT:
            return f"{LIBID}-certificate-{self._get_unit_number()}-{csr_in_sha256_hex}"
        elif self.mode == Mode.APP:
            return f"{LIBID}-certificate-{csr_in_sha256_hex}"
        else:
            raise TLSCertificatesError("Invalid mode. Must be Mode.UNIT or Mode.APP.")

    def _get_unit_number(self) -> str:
        return self.model.unit.name.split("/")[1]


class TLSCertificatesProvidesV4(Object):
    """TLS certificates provider class to be instantiated by TLS certificates providers."""

    def __init__(self, charm: CharmBase, relationship_name: str):
        super().__init__(charm, relationship_name)
        self.framework.observe(charm.on[relationship_name].relation_joined, self._configure)
        self.framework.observe(charm.on[relationship_name].relation_changed, self._configure)
        self.framework.observe(charm.on.update_status, self._configure)
        self.charm = charm
        self.relationship_name = relationship_name
        self._security_logger = _OWASPLogger(application=f"tls-certificates-{charm.app.name}")

    def _configure(self, _: EventBase) -> None:
        """Handle update status and tls relation changed events.

        This is a common hook triggered on a regular basis.

        Revoke certificates for which no csr exists
        """
        if not self.model.unit.is_leader():
            return
        self._remove_certificates_for_which_no_csr_exists()

    def _remove_certificates_for_which_no_csr_exists(self) -> None:
        provider_certificates = self.get_provider_certificates()
        requirer_csrs = [
            request.certificate_signing_request for request in self.get_certificate_requests()
        ]
        for provider_certificate in provider_certificates:
            if provider_certificate.certificate_signing_request not in requirer_csrs:
                tls_relation = self._get_tls_relations(
                    relation_id=provider_certificate.relation_id
                )
                self._remove_provider_certificate(
                    certificate=provider_certificate.certificate,
                    relation=tls_relation[0],
                )

    def _get_tls_relations(self, relation_id: Optional[int] = None) -> List[Relation]:
        return (
            [
                relation
                for relation in self.model.relations[self.relationship_name]
                if relation.id == relation_id
            ]
            if relation_id is not None
            else self.model.relations.get(self.relationship_name, [])
        )

    def get_certificate_requests(
        self, relation_id: Optional[int] = None
    ) -> List[RequirerCertificateRequest]:
        """Load certificate requests from the relation data."""
        relations = self._get_tls_relations(relation_id)
        requirer_csrs: List[RequirerCertificateRequest] = []
        for relation in relations:
            for unit in relation.units:
                requirer_csrs.extend(self._load_requirer_databag(relation, unit))
            requirer_csrs.extend(self._load_requirer_databag(relation, relation.app))
        return requirer_csrs

    def _load_requirer_databag(
        self, relation: Relation, unit_or_app: Union[Application, Unit]
    ) -> List[RequirerCertificateRequest]:
        try:
            requirer_relation_data = _RequirerData.load(relation.data.get(unit_or_app, {}))
        except DataValidationError:
            logger.debug("Invalid requirer relation data for %s", unit_or_app.name)
            return []
        return [
            RequirerCertificateRequest(
                relation_id=relation.id,
                certificate_signing_request=CertificateSigningRequest.from_string(
                    csr.certificate_signing_request
                ),
                is_ca=csr.ca if csr.ca else False,
            )
            for csr in requirer_relation_data.certificate_signing_requests
        ]

    def _add_provider_certificate(
        self,
        relation: Relation,
        provider_certificate: ProviderCertificate,
    ) -> None:
        chain = [str(certificate) for certificate in provider_certificate.chain]
        if chain[0] != str(provider_certificate.certificate):
            logger.warning(
                "The order of the chain from the TLS Certificates Provider is incorrect. "
                "The leaf certificate should be the first element of the chain."
            )
        elif not chain_has_valid_order(chain):
            logger.warning(
                "The order of the chain from the TLS Certificates Provider is partially incorrect."
            )
        new_certificate = _Certificate(
            certificate=str(provider_certificate.certificate),
            certificate_signing_request=str(provider_certificate.certificate_signing_request),
            ca=str(provider_certificate.ca),
            chain=chain,
        )
        provider_certificates = self._load_provider_certificates(relation)
        if new_certificate in provider_certificates:
            logger.info("Certificate already in relation data - Doing nothing")
            return
        provider_certificates.append(new_certificate)
        self._dump_provider_certificates(relation=relation, certificates=provider_certificates)

    def _load_provider_certificates(self, relation: Relation) -> List[_Certificate]:
        try:
            provider_relation_data = _ProviderApplicationData.load(relation.data[self.charm.app])
        except DataValidationError:
            logger.debug("Invalid provider relation data")
            return []
        return copy.deepcopy(provider_relation_data.certificates)

    def _dump_provider_certificates(self, relation: Relation, certificates: List[_Certificate]):
        try:
            _ProviderApplicationData(certificates=certificates).dump(relation.data[self.model.app])
            logger.info("Certificate relation data updated")
        except ModelError:
            logger.warning("Failed to update relation data")

    def _remove_provider_certificate(
        self,
        relation: Relation,
        certificate: Optional[Certificate] = None,
        certificate_signing_request: Optional[CertificateSigningRequest] = None,
    ) -> None:
        """Remove certificate based on certificate or certificate signing request."""
        provider_certificates = self._load_provider_certificates(relation)
        for provider_certificate in provider_certificates:
            if certificate and provider_certificate.certificate == str(certificate):
                provider_certificates.remove(provider_certificate)
            if (
                certificate_signing_request
                and provider_certificate.certificate_signing_request
                == str(certificate_signing_request)
            ):
                provider_certificates.remove(provider_certificate)
        self._dump_provider_certificates(relation=relation, certificates=provider_certificates)

    def revoke_all_certificates(self) -> None:
        """Revoke all certificates of this provider.

        This method is meant to be used when the Root CA has changed.
        """
        if not self.model.unit.is_leader():
            logger.warning("Unit is not a leader - will not set relation data")
            return
        relations = self._get_tls_relations()
        for relation in relations:
            provider_certificates = self._load_provider_certificates(relation)
            for certificate in provider_certificates:
                certificate.revoked = True
            self._dump_provider_certificates(relation=relation, certificates=provider_certificates)
        self._security_logger.log_event(
            event="all_certificates_revoked",
            level=logging.WARNING,
            description="All certificates revoked",
        )

    def set_relation_certificate(
        self,
        provider_certificate: ProviderCertificate,
    ) -> None:
        """Add certificates to relation data.

        Args:
            provider_certificate (ProviderCertificate): ProviderCertificate object

        Returns:
            None
        """
        if not self.model.unit.is_leader():
            logger.warning("Unit is not a leader - will not set relation data")
            return
        certificates_relation = self.model.get_relation(
            relation_name=self.relationship_name, relation_id=provider_certificate.relation_id
        )
        if not certificates_relation:
            raise TLSCertificatesError(f"Relation {self.relationship_name} does not exist")
        self._remove_provider_certificate(
            relation=certificates_relation,
            certificate_signing_request=provider_certificate.certificate_signing_request,
        )
        self._add_provider_certificate(
            relation=certificates_relation,
            provider_certificate=provider_certificate,
        )
        self._security_logger.log_event(
            event="certificate_provided",
            level=logging.INFO,
            description="Certificate provided to requirer",
            relation_id=str(provider_certificate.relation_id),
            common_name=provider_certificate.certificate.common_name,
        )

    def get_issued_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return a List of issued (non revoked) certificates.

        Returns:
            List: List of ProviderCertificate objects
        """
        if not self.model.unit.is_leader():
            logger.warning("Unit is not a leader - will not read relation data")
            return []
        provider_certificates = self.get_provider_certificates(relation_id=relation_id)
        return [certificate for certificate in provider_certificates if not certificate.revoked]

    def get_provider_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return a List of issued certificates."""
        certificates: List[ProviderCertificate] = []
        relations = self._get_tls_relations(relation_id)
        for relation in relations:
            if not relation.app:
                logger.warning("Relation %s does not have an application", relation.id)
                continue
            for certificate in self._load_provider_certificates(relation):
                certificates.append(certificate.to_provider_certificate(relation_id=relation.id))
        return certificates

    def get_unsolicited_certificates(
        self, relation_id: Optional[int] = None
    ) -> List[ProviderCertificate]:
        """Return provider certificates for which no certificate requests exists.

        Those certificates should be revoked.
        """
        unsolicited_certificates: List[ProviderCertificate] = []
        provider_certificates = self.get_provider_certificates(relation_id=relation_id)
        requirer_csrs = self.get_certificate_requests(relation_id=relation_id)
        list_of_csrs = [csr.certificate_signing_request for csr in requirer_csrs]
        for certificate in provider_certificates:
            if certificate.certificate_signing_request not in list_of_csrs:
                unsolicited_certificates.append(certificate)
        return unsolicited_certificates

    def get_outstanding_certificate_requests(
        self, relation_id: Optional[int] = None
    ) -> List[RequirerCertificateRequest]:
        """Return CSR's for which no certificate has been issued.

        Args:
            relation_id (int): Relation id

        Returns:
            list: List of RequirerCertificateRequest objects.
        """
        requirer_csrs = self.get_certificate_requests(relation_id=relation_id)
        outstanding_csrs: List[RequirerCertificateRequest] = []
        for relation_csr in requirer_csrs:
            if not self._certificate_issued_for_csr(
                csr=relation_csr.certificate_signing_request,
                relation_id=relation_id,
            ):
                outstanding_csrs.append(relation_csr)
        return outstanding_csrs

    def _certificate_issued_for_csr(
        self, csr: CertificateSigningRequest, relation_id: Optional[int]
    ) -> bool:
        """Check whether a certificate has been issued for a given CSR."""
        issued_certificates_per_csr = self.get_issued_certificates(relation_id=relation_id)
        for issued_certificate in issued_certificates_per_csr:
            if issued_certificate.certificate_signing_request == csr:
                return csr.matches_certificate(issued_certificate.certificate)
        return False
