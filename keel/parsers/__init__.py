"""The filing parsers, registered by form code (chapter 17.4).

A new filing type adds a module with a parser class and 1 entry in
`PARSERS`. The corpus pass in `keel.parsers.corpus` picks the parser by the
form in the file name.
"""

from keel.parsers import base
from keel.parsers import form_10k_10q

_TEN_K_TEN_Q = form_10k_10q.TenKTenQParser()
PARSERS: dict[str, base.FilingParser] = dict.fromkeys(
    _TEN_K_TEN_Q.forms, _TEN_K_TEN_Q
)


def parser_for(form: str | None) -> base.FilingParser:
    """Return the parser of a form.

    Args:
        form: A form such as `10-K`, or None when the file name has none.

    Returns:
        The registered parser. An unknown form gets the 10-K and 10-Q
        parser, whose header check then quarantines the file.
    """
    return PARSERS.get(form or "", _TEN_K_TEN_Q)
