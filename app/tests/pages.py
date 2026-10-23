"""What a page shows, read as a person reads it: the text of its cells and of its choices."""

from html.parser import HTMLParser


def table_rows(html: str) -> list[list[str]]:
    """The text of each data cell, row by row; the header row, made of <th>, is left out."""
    parser = _Reader()
    parser.feed(html)
    return [row for row in parser.rows if row]


def select_options(html: str, name: str) -> list[str]:
    """The text of the choices of the <select> with that name, in their order."""
    parser = _Reader()
    parser.feed(html)
    return parser.options.get(name, [])


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.options: dict[str, list[str]] = {}
        self._text: list[str] | None = None
        self._select: str | None = None

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag == "select":
            self._select = dict(attrs)["name"]
            self.options[self._select] = []
        elif tag in ("td", "option"):
            self._text = []

    def handle_endtag(self, tag) -> None:
        if self._text is None:
            return
        if tag == "td":
            self.rows[-1].append(self._joined())
        elif tag == "option" and self._select is not None:
            self.options[self._select].append(self._joined())

    def handle_data(self, data) -> None:
        if self._text is not None:
            self._text.append(data)

    def _joined(self) -> str:
        text = " ".join("".join(self._text).split())
        self._text = None
        return text
