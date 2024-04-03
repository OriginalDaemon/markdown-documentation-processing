import difflib

from pathlib import Path


class Document(object):
    def __init__(self, input_path: Path, data: str = ""):
        """
        Holds a file, referenced by relative_path, and it's contents, for manipulation by document rule_set.
        :param input_path: The relative_path to the input file.
        """
        self.input_path: Path = input_path
        self.target_path: Path = Path(input_path)
        self.original_contents: str = data
        self.contents: str = data

    @property
    def unchanged(self):
        """
        :return: True if the document is currently unchanged compared to its original contents.
        """
        return self.original_contents == self.contents

    @property
    def changes(self):
        if not self.unchanged:
            a = self.original_contents.split("\n")
            b = self.contents.split("\n")
            result = ""
            for text in difflib.unified_diff(a, b):
                if text[:3] not in ('+++', '---', '@@ '):
                    result += text + "\n"
            return result
        else:
            return ""


def load_document(path: Path):
    """
    Load a document from a given path.
    :param path: The path to the file to load.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory, expected a file relative_path.")
    with open(path, "r") as fd:
        return Document(path, fd.read())


def save_document(document: Document):
    """
    Save the contents of a Document to the set target_path.
    :param document: The document to save.
    """
    document.target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(document.target_path, "w+") as fd:
        fd.write(document.contents)
