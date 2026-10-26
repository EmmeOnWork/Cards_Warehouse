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


def suggestions(html: str, field: str) -> dict[str, list[str]]:
    """The values a text field suggests, by the game they are offered for: "" when for every game."""
    parser = _Reader()
    parser.feed(html)
    return parser.suggestions.get(field, {})


def links(html: str) -> dict[str, str]:
    """Where each link goes, by the text a person taps."""
    parser = _Reader()
    parser.feed(html)
    return parser.links


def images(html: str) -> list[str]:
    """The address of each image, in the order the page shows them."""
    parser = _Reader()
    parser.feed(html)
    return parser.images


def image_labels(html: str) -> list[str]:
    """The text that stands for each image, as a screen reader says it, in the same order."""
    parser = _Reader()
    parser.feed(html)
    return parser.image_labels


def buttons(html: str) -> dict[str, tuple[str, dict[str, str]]]:
    """What each button of a form sends, by what it says to a person: its label, or else its text.

    The address of its form, and the button's own name and value, if it has them.
    """
    parser = _Reader()
    parser.feed(html)
    return parser.buttons


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.options: dict[str, list[str]] = {}
        self.links: dict[str, str] = {}
        self.images: list[str] = []
        self.image_labels: list[str] = []
        self.buttons: dict[str, tuple[str, dict[str, str]]] = {}
        self.suggestions: dict[str, dict[str, list[str]]] = {}
        self._datalist: list[str] | None = None
        self._form_action = ""
        self._button: dict[str, str] | None = None
        self._button_text: list[str] = []
        self._text: list[str] | None = None
        self._select: str | None = None
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        # A suggestion is a value, not a choice of a <select>: it is read before the options of those.
        if tag == "datalist":
            attributes = dict(attrs)
            by_game = self.suggestions.setdefault(attributes["data-field"], {})
            self._datalist = by_game.setdefault(attributes.get("data-game", ""), [])
        elif tag == "option" and self._datalist is not None:
            self._datalist.append(dict(attrs)["value"])
        elif tag == "tr":
            self.rows.append([])
        elif tag == "select":
            self._select = dict(attrs)["name"]
            self.options[self._select] = []
        elif tag in ("td", "option"):
            self._text = []
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        elif tag == "img":
            self.images.append(dict(attrs)["src"])
            self.image_labels.append(dict(attrs).get("alt", ""))
        elif tag == "form":
            self._form_action = dict(attrs).get("action", "")
        elif tag == "button":
            self._button = dict(attrs)
            self._button_text = []

    def handle_endtag(self, tag) -> None:
        if tag == "datalist":
            self._datalist = None
        if tag == "button" and self._button is not None:
            label = self._button.get("aria-label") or " ".join("".join(self._button_text).split())
            sent = {self._button["name"]: self._button.get("value", "")} if "name" in self._button else {}
            self.buttons[label] = (self._form_action, sent)
            self._button = None
        if tag == "a" and self._href is not None:
            self.links[" ".join("".join(self._link_text).split())] = self._href
            self._href = None
        if self._text is None:
            return
        if tag == "td":
            self.rows[-1].append(self._joined())
        elif tag == "option" and self._select is not None:
            self.options[self._select].append(self._joined())

    def handle_data(self, data) -> None:
        if self._text is not None:
            self._text.append(data)
        if self._href is not None:
            self._link_text.append(data)
        if self._button is not None:
            self._button_text.append(data)

    def _joined(self) -> str:
        text = " ".join("".join(self._text).split())
        self._text = None
        return text
