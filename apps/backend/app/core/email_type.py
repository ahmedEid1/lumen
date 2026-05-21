"""Project-specific email type.

Pydantic's stock ``EmailStr`` defers to ``email_validator`` with the
``globally_deliverable=True`` default, which rejects any TLD listed
in RFC 6761 as reserved — including ``.test`` (and ``.invalid``,
``.localhost``, ``.example``).

That collides with our own conventions:

* the seeded demo accounts use ``student@lumen.test`` /
  ``teacher@lumen.test`` /  ``admin@lumen.test`` — ``.test`` is the
  *spec-approved* TLD for, well, testing. Pydantic refusing it
  means a fresh ``make up`` + ``make seed`` + click-Sign-in fails
  with a "value is not a valid email" 422 the user can't act on.
* test fixtures (``make_user``) generate
  ``u-<random>@lumen.test`` for the same reason.

Allowing reserved TLDs at the application level is the deliberate
choice for an LMS that needs to remain bootable with documentation-
grade demo data. Real validation (does the user own this address?)
happens at the email-verification step via a token we mail them.
"""

from __future__ import annotations

from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


class _Email(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: Any
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(min_length=3, max_length=320),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _schema: CoreSchema, _handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "format": "email"}

    @classmethod
    def _validate(cls, value: str) -> str:
        try:
            result = validate_email(
                value,
                check_deliverability=False,
                # The deliberate divergence from stock EmailStr:
                # ``test_environment=True`` opts into accepting the
                # RFC 6761 reserved TLDs (``.test``, ``.invalid``,
                # ``.localhost``, ``.example``) so seed accounts and
                # integration-test fixtures keep working without
                # per-environment overrides. Earlier versions used a
                # ``globally_deliverable=False`` flag for the same
                # effect; ``test_environment`` is the supported
                # spelling in email-validator ≥2.x.
                test_environment=True,
            )
        except EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc
        return result.normalized


Email = Annotated[str, _Email]
"""Drop-in replacement for :class:`pydantic.EmailStr` that accepts
``.test`` and other RFC 6761 reserved TLDs."""
