import unittest

from novelterm.css_selectors import SelectorError, parse_selector
from novelterm.html_tree import parse_html

PAGE = """
<div id="main" class="page wide">
  <ul class="list"><li><a class="item" href="/1">One</a></li><li><a href="/2">Two</a></li></ul>
  <div class="nested"><ul class="list"><li><span><a href="/3">Three</a></span></li></ul></div>
</div>
"""


class SelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_html(PAGE)

    def hrefs(self, selector: str) -> list[str]:
        return [element.get("href") or "" for element in parse_selector(selector).select(self.document)]

    def test_descendant(self) -> None:
        self.assertEqual(self.hrefs("ul.list a"), ["/1", "/2", "/3"])

    def test_child(self) -> None:
        self.assertEqual(self.hrefs("ul.list > li > a"), ["/1", "/2"])

    def test_id_and_multiple_classes(self) -> None:
        self.assertEqual(self.hrefs("div#main.page.wide > ul a.item"), ["/1"])

    def test_select_first(self) -> None:
        element = parse_selector("div.nested a").select_first(self.document)
        self.assertIsNotNone(element)
        self.assertEqual(element.get("href") if element else None, "/3")

    def test_invalid_selectors(self) -> None:
        for text in ["", "> a", "ul >", "a[href]", "div#one#two"]:
            with self.subTest(text=text), self.assertRaises(SelectorError):
                parse_selector(text)


if __name__ == "__main__":
    unittest.main()
