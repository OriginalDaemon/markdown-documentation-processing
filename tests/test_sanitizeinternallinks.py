import os
import unittest

from pathlib import Path
from mddocproc import ProcessingSettings, ProcessingContext, Document, rules


class TestSanitizeInternalLinks(unittest.TestCase):
    @staticmethod
    def _create_test_data(link):
        doc_root = Path(os.path.join(os.path.dirname(__file__), "data", "docs"))
        context = ProcessingContext(ProcessingSettings(doc_root))
        context.add_document(Document(doc_root / Path("sub dir/relative - file.md"), "### sub - section"))
        doc = Document(Path(doc_root / "test dir/test.md"), link)
        context.add_document(doc)
        return context, doc

    def test_external_link_unchanged(self):
        context = ProcessingContext(ProcessingSettings())
        input_md = "[link](https://www.google.com)"
        expected = input_md
        doc = Document(Path("test.md"), input_md)
        rules.santize_internal_links(context, doc)
        self.assertEqual(expected, doc.contents)

    def test_internal_file_relative_link(self):
        cases = [
            "[link](<../sub dir/relative - file.md>)",
            "[link](../sub%20dir/relative%20-%20file.md)",
            "[link](<../sub%20dir/relative%20-%20file.md>)",
        ]
        expected = "[link](<../sub dir/relative - file.md>)"
        for i, case in enumerate(cases):
            with self.subTest(i=i):
                context, doc = self._create_test_data(case)
                rules.santize_internal_links(context, doc)
                self.assertEqual(expected, doc.contents)

    def test_internal_file_relative_link_with_subsection(self):
        cases = [
            "[link](<../sub dir/relative - file.md#sub - section>)",
            "[link](../sub%20dir/relative%20-%20file.md#sub%20-%20section)",
            "[link](<../sub%20dir/relative%20-%20file.md#sub%20-%20section>)",
            "[link](../sub%20dir/relative%20-%20file.md#sub---section)",
            "[link](<../sub%20dir/relative%20-%20file.md#sub---section>)",
        ]
        expected = "[link](<../sub dir/relative - file.md#sub - section>)"
        for i, case in enumerate(cases):
            with self.subTest(i=i):
                context, doc = self._create_test_data(case)
                rules.santize_internal_links(context, doc)
                self.assertEqual(expected, doc.contents)

    def test_internal_root_relative_link(self):
        cases = [
            "[link](<sub dir/relative - file.md>)",
            "[link](sub%20dir/relative%20-%20file.md)",
            "[link](<sub%20dir/relative%20-%20file.md>)",
        ]
        expected = "[link](<../sub dir/relative - file.md>)"
        for i, case in enumerate(cases):
            with self.subTest(i=i):
                context, doc = self._create_test_data(case)
                rules.santize_internal_links(context, doc)
                self.assertEqual(expected, doc.contents)

    def test_internal_root_relative_link_with_subsection(self):
        cases = [
            "[link](<sub dir/relative - file.md#sub - section>)",
            "[link](sub%20dir/relative%20-%20file.md#sub%20-%20section)",
            "[link](<sub%20dir/relative%20-%20file.md#sub%20-%20section>)",
            "[link](sub%20dir/relative%20-%20file.md#sub---section)",
            "[link](<sub%20dir/relative%20-%20file.md#sub---section>)",
        ]
        expected = "[link](<../sub dir/relative - file.md#sub - section>)"
        for i, case in enumerate(cases):
            with self.subTest(i=i):
                context, doc = self._create_test_data(case)
                rules.santize_internal_links(context, doc)
                self.assertEqual(expected, doc.contents)