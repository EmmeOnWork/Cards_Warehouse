"""What a page shows, read as a person reads it: the text of its cells and of its choices."""

from html.parser import HTMLParser


def text(html: str) -> str:
    """All the text a person reads on the page, in one line: tags and line breaks are a space, entities are read."""
    parser = _Reader()
    parser.feed(html)
    return " ".join("".join(parser.text).split())


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


def form_fields(html: str) -> dict[str, list[str]]:
    """What the page's form sends when submitted as it is, without its buttons: every value of each field, by name.

    The text of the fields and of the hidden ones, the boxes ticked, and the choice of each <select>: the one
    selected, or else the first.
    """
    parser = _Reader()
    parser.feed(html)
    return parser.fields


def buttons(html: str) -> dict[str, tuple[str, dict[str, str]]]:
    """What each button of a form sends, by what it says to a person: its label, or else its text.

    The address of its form, and the button's own name and value, if it has them.
    """
    parser = _Reader()
    parser.feed(html)
    return parser.buttons


def copies(html: str) -> dict[str, str]:
    """What each copy button puts in the clipboard, by what it says to a person."""
    parser = _Reader()
    parser.feed(html)
    return parser.copies


def checkboxes(html: str, name: str) -> dict[str, str]:
    """What each box with that name sends when ticked, by the text of its label."""
    parser = _Reader()
    parser.feed(html)
    return parser.checkboxes.get(name, {})


def sections(html: str) -> dict[str, str]:
    """The HTML of each <section> of the page, by its heading: one part of a page, to read as the others read it."""
    parser = _Sections(html)
    parser.feed(html)
    return parser.sections


_UNREAD = ("head", "script", "style")
_HEADINGS = ("h1", "h2", "h3")


class _Sections(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self._html = html
        # Where each line of the page starts: the parser tells where a tag is by its line and column.
        self._line_starts = [0]
        for line in html.split("\n"):
            self._line_starts.append(self._line_starts[-1] + len(line) + 1)
        self.sections: dict[str, str] = {}
        # The sections being read, the innermost last: where each starts, and the text of its heading.
        self._open: list[tuple[int, list[str]]] = []
        self._heading: list[str] | None = None

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "section":
            self._open.append((self._here(), []))
        elif tag in _HEADINGS and self._open and not self._open[-1][1]:
            self._heading = self._open[-1][1]

    def handle_endtag(self, tag) -> None:
        if tag in _HEADINGS:
            self._heading = None
        elif tag == "section" and self._open:
            start, heading = self._open.pop()
            end = self._html.index(">", self._here()) + 1
            self.sections[" ".join("".join(heading).split())] = self._html[start:end]

    def handle_data(self, data) -> None:
        if self._heading is not None:
            self._heading.append(data)

    def _here(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.options: dict[str, list[str]] = {}
        self.links: dict[str, str] = {}
        self.images: list[str] = []
        self.image_labels: list[str] = []
        self.buttons: dict[str, tuple[str, dict[str, str]]] = {}
        self.checkboxes: dict[str, dict[str, str]] = {}
        self.copies: dict[str, str] = {}
        self.suggestions: dict[str, dict[str, list[str]]] = {}
        self.text: list[str] = []
        # Inside <head>, <script> or <style>: text a person does not read on the page.
        self._unread = 0
        self.fields: dict[str, list[str]] = {}
        # The value of each option of the <select> being read, and of the one selected, if any.
        self._choices: list[str] = []
        self._chosen: str | None = None
        self._option: dict[str, str | None] = {}
        self._textarea: list[str] | None = None
        self._textarea_name = ""
        self._datalist: list[str] | None = None
        self._form_action = ""
        self._button: dict[str, str] | None = None
        self._button_text: list[str] = []
        self._text: list[str] | None = None
        self._select: str | None = None
        self._href: str | None = None
        self._link_text: list[str] = []
        # The text of the <label> being read, and the name and value of the box inside it, if any.
        self._label: list[str] | None = None
        self._labelled_box: tuple[str, str] | None = None

    def handle_starttag(self, tag, attrs) -> None:
        self.text.append(" ")
        if tag in _UNREAD:
            self._unread += 1
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
            self._choices, self._chosen = [], None
        elif tag in ("td", "option"):
            self._text = []
            if tag == "option":
                self._option = dict(attrs)
        elif tag == "input":
            self._input(dict(attrs))
        elif tag == "textarea":
            self._textarea_name = dict(attrs)["name"]
            self._textarea = []
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
        elif tag == "label":
            self._label, self._labelled_box = [], None

    def handle_endtag(self, tag) -> None:
        self.text.append(" ")
        if tag in _UNREAD:
            self._unread -= 1
        if tag == "datalist":
            self._datalist = None
        if tag == "select" and self._select is not None:
            if self._choices:
                self.fields.setdefault(self._select, []).append(self._chosen or self._choices[0])
            self._select = None
        if tag == "textarea" and self._textarea is not None:
            self.fields.setdefault(self._textarea_name, []).append("".join(self._textarea))
            self._textarea = None
        if tag == "button" and self._button is not None:
            label = self._button.get("aria-label") or " ".join("".join(self._button_text).split())
            sent = {self._button["name"]: self._button.get("value", "")} if "name" in self._button else {}
            self.buttons[label] = (self._form_action, sent)
            if "data-copy" in self._button:
                self.copies[label] = self._button["data-copy"]
            self._button = None
        if tag == "label" and self._label is not None:
            if self._labelled_box is not None:
                name, value = self._labelled_box
                self.checkboxes.setdefault(name, {})[" ".join("".join(self._label).split())] = value
            self._label = None
        if tag == "a" and self._href is not None:
            self.links[" ".join("".join(self._link_text).split())] = self._href
            self._href = None
        if self._text is None:
            return
        if tag == "td":
            self.rows[-1].append(self._joined())
        elif tag == "option" and self._select is not None:
            text = self._joined()
            self.options[self._select].append(text)
            value = self._option.get("value", text)
            self._choices.append(value)
            if "selected" in self._option:
                self._chosen = value

    def _input(self, attributes: dict[str, str | None]) -> None:
        kind = attributes.get("type", "text")
        if kind == "checkbox" and "name" in attributes and self._label is not None:
            self._labelled_box = (attributes["name"], attributes.get("value") or "on")
        if "name" not in attributes or kind in ("submit", "button", "file", "image", "reset"):
            return
        if kind in ("checkbox", "radio") and "checked" not in attributes:
            return
        default = "on" if kind in ("checkbox", "radio") else ""
        self.fields.setdefault(attributes["name"], []).append(attributes.get("value") or default)

    def handle_data(self, data) -> None:
        if not self._unread:
            self.text.append(data)
        if self._textarea is not None:
            self._textarea.append(data)
        if self._text is not None:
            self._text.append(data)
        if self._href is not None:
            self._link_text.append(data)
        if self._button is not None:
            self._button_text.append(data)
        if self._label is not None:
            self._label.append(data)

    def _joined(self) -> str:
        text = " ".join("".join(self._text).split())
        self._text = None
        return text
