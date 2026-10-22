"""The question templates of the web picker (chapter 27.2).

`config/templates.yaml` holds 5 templates: public comparables, risk
benchmark, portfolio review, regulatory scan, and a memo paragraph. Each
text has the placeholders `{companies}` and `{period}`, and a default
period for an empty one. `GET /api/templates` serves them; the picker and
`keel template` fill them. A filled template is an ordinary question: it
goes through question understanding and makes 1 model request.
"""

from __future__ import annotations

import pathlib
import re

import pydantic

from keel import config
from keel import errors

COMPANIES = "{companies}"
PERIOD = "{period}"
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
MAX_VALUE_CHARS = 300


class Template(pydantic.BaseModel):
    """1 question template.

    Attributes:
        id: The template key.
        label: The button label.
        text: The question with `{companies}` and `{period}`.
        default_period: The period of an empty period field.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    id: str = pydantic.Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = pydantic.Field(min_length=1, max_length=40)
    text: str = pydantic.Field(min_length=1, max_length=600)
    default_period: str = pydantic.Field(min_length=1, max_length=80)

    @pydantic.field_validator("text")
    @classmethod
    def _placeholders(cls, text: str) -> str:
        found = sorted(PLACEHOLDER.findall(text))
        if found != sorted([COMPANIES, PERIOD]):
            raise ValueError(
                "a template text holds {companies} and {period} once each"
            )
        return " ".join(text.split())


def load(path: pathlib.Path) -> list[Template]:
    """Read the templates file.

    Args:
        path: `pilot.templates`.

    Returns:
        The templates in file order.

    Raises:
        ConfigError: The file is absent or a template is not valid.
    """
    data = config.read_yaml(path)
    try:
        return [
            Template.model_validate({"id": str(key), **value})
            for key, value in data.items()
        ]
    except (TypeError, pydantic.ValidationError) as error:
        raise errors.ConfigError(
            f"invalid question template in {path}: {error}"
        ) from error


def _value(text: str, field: str) -> str:
    value = " ".join(text.split())
    if len(value) > MAX_VALUE_CHARS:
        raise errors.TemplateError(
            f"the {field} field has at most {MAX_VALUE_CHARS} characters"
        )
    return value


def fill(template: Template, companies: str, period: str = "") -> str:
    """Fill a template into a question.

    The values replace the placeholders as plain text: a brace in a value
    stays a brace and never opens another placeholder.

    Args:
        template: The template.
        companies: Company names, tickers, or a comp set phrase.
        period: The time scope; empty takes the default period.

    Returns:
        The question.

    Raises:
        TemplateError: The companies field is empty, or a field is too
            long.
    """
    names = _value(companies, "companies")
    if not names:
        raise errors.TemplateError("name at least 1 company or a comp set")
    scope = _value(period, "period") or template.default_period
    head, tail = template.text.split(COMPANIES, 1)
    parts = [part.replace(PERIOD, scope) for part in (head, tail)]
    return names.join(parts)


def find(templates: list[Template], template_id: str) -> Template:
    """Find a template by its ID.

    Args:
        templates: The loaded templates.
        template_id: The ID.

    Returns:
        The template.

    Raises:
        TemplateError: No template has the ID.
    """
    for template in templates:
        if template.id == template_id:
            return template
    raise errors.TemplateError(f"no question template {template_id!r}")
