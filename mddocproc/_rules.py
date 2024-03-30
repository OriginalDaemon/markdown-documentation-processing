from __future__ import annotations

import re
import os
import logging
import inspect
import functools

from pathlib import Path
from fnmatch import fnmatch
from urllib.parse import unquote
from typing import Callable, Tuple, List, TYPE_CHECKING
from ._consts import Passes, DeploymentStyle, regex_const_macro, regex_function_macro, regex_markdown_link

if TYPE_CHECKING:
    from ._processing import ProcessingContext
    from ._document import Document


logger = logging.getLogger(__name__)


class DocumentRule(object):
    def __init__(
        self,
        function: Callable[[ProcessingContext, Document], None],
        file_filter: str,
        pass_index: Passes = Passes.FIRST,
    ):
        """
        Function decorator to create a document processor function. These functions will be called by a
        ProcessingContext to apply augmentations to a file that is loaded in memory.
        :param function: The function being decorated as a document processor.
        :param file_filter: fnmatch style file filter.
        :param pass_index: The index of the "pass" of the documents in which to operate. Sometimes rule_set need to wait
                           for other rule_set to run first.
        """
        self.function = function
        self.file_filter = file_filter
        self.pass_index = pass_index
        functools.update_wrapper(self, self.function)

    def _applies(self, document: Document):
        return fnmatch(document.input_path, self.file_filter)

    def __call__(self, context: ProcessingContext, document: Document):
        if self._applies(document):
            self.function(context, document)


def document_rule(
    file_filter: str = "*.*", pass_index: Passes = Passes.FIRST
) -> Callable[[Callable[[ProcessingContext, Document], None]], DocumentRule]:
    """
    A wrapper to make simple DocumentRules from functions.
    :param file_filter: fnmatch style file filter string.
    :param pass_index: The index of the "pass" of the documents in which to operate. Sometimes rule_set need to wait for
                       other rule_set to run first.
    :return: A document rule type.
    """

    def _inner(func):
        return DocumentRule(func, file_filter, pass_index)

    return _inner


def _get_next_match(document: Document, pointer: int, regex: re.Pattern) -> Tuple[re.Match | None, int, int]:
    match = re.search(regex, document.contents[pointer:])
    """:type: re.Match"""
    if not match:
        return None, 0, 0
    start, end = match.span(0)[0] + pointer, match.span(0)[1] + pointer
    return match, start, end


def _replace_span(document: Document, start: int, end: int, replacement: str) -> str:
    return "".join([document.contents[:start], replacement, document.contents[end:]])


def _calculate_toc_indent_for_heading(line) -> int:
    """:return: the indent to use for a heading link in a toc based on the heading size."""
    return (max(0, len(line) - len(line.lstrip("#")) - 1)) * 2


def _create_toc_from_sections(lines):
    from ._utils import format_markdown_link

    table_entries = []
    for line in map(lambda x: x.strip(), lines):
        if line.startswith("#"):
            indent_size = _calculate_toc_indent_for_heading(line)
            stripped = line.lstrip("#").strip()
            table_entries.append((indent_size, " - {}".format(format_markdown_link(stripped, "#{}".format(stripped)))))

    # Use smallest_indent to shift entire toc leftwards as much as we can...
    smallest_indent = min(x[0] for x in table_entries) if table_entries else 0
    toc = "\n".join(["{}{}".format(" " * (x[0] - smallest_indent), x[1]) for x in table_entries])

    return toc


@document_rule("*.md")
def create_table_of_contents(context: ProcessingContext, document: Document):
    """
    Create a table of contents wherever the document has the variable ${create_table_of_contents}
    :param context: The ProcessingContext.
    :param document: The document being processed.
    """
    TABLE_OF_CONTENTS_VARIABLE = "${create_table_of_contents}"
    lines = document.contents.split("\n")
    processed = []
    for i, line in enumerate(lines):
        if TABLE_OF_CONTENTS_VARIABLE in line:
            table = _create_toc_from_sections(lines[i + 1 :])
            line = line.replace(TABLE_OF_CONTENTS_VARIABLE, table)
        processed.append(line)
    document.contents = "\n".join(processed)


def _replace_const_macros(context: ProcessingContext, document: Document):
    pointer = 0
    while pointer < len(document.contents):
        match, start, end = _get_next_match(document, pointer, regex_const_macro)
        if not match:
            break
        macroName = match.group(1)
        macro = context.settings.macros.get(macroName, None)
        if macro is not None and not callable(macro):
            document.contents = _replace_span(document, start, end, context.settings.macros[macroName])
            pointer = start
        elif macro is not None and callable(macro):
            logger.exception(
                f"Exception encountered trying to resolve {match.group(0)} as {macroName} is a function, not a "
                f"const."
            )
            pointer = end
        else:
            logger.warning(
                f"Invalid macro: found {match.group(0)} in {document.input_path}, but no matching macro is defined."
            )
            pointer = end


def _extract_args(value: str) -> Tuple[str]:
    args = tuple()
    if value:
        args = tuple(map(lambda x: x.strip(), value.split(",")))
    return args


def _run_function_macro(
    context: ProcessingContext, functionName: str, args: Tuple[str], origin_match: str
) -> Tuple[bool, str | None]:
    if callable(context.settings.macros[functionName]):
        # noinspection PyBroadException
        try:
            return True, context.settings.macros[functionName](*args)
        except Exception:
            signature = inspect.signature(context.settings.macros[functionName])
            if len(args) != len(signature.parameters):
                logger.exception(
                    f"Exception encountered trying to resolve {origin_match} using {signature}. "
                    f"Expected {len(signature.parameters)} args, got {len(args)}."
                )
            else:
                logger.exception(f"Exception encountered trying to resolve {origin_match} using {signature}.")
    else:
        logger.exception(f"Exception encountered trying to resolve {origin_match} as {functionName} is not a function.")
    return False, None


def _replace_function_macros(context: ProcessingContext, document: Document):
    pointer = 0
    while pointer < len(document.contents):
        match, start, end = _get_next_match(document, pointer, regex_function_macro)
        if not match:
            break
        macroName = match.group(1)
        success = False
        if macroName in context.settings.macros:
            args = _extract_args(match.group(2))
            success, value = _run_function_macro(context, macroName, args, match.group(0))
            if success:
                document.contents = _replace_span(document, start, end, value)
        else:
            logger.warning(
                f"Invalid macro: found {match.group(0)} in {document.input_path}, but no matching macro is defined."
            )
        if success:
            pointer = start
        else:
            pointer = end


@document_rule("*.md")
def apply_macros(context: ProcessingContext, document: Document):
    """
    Applies any defined macros to the document.
    :param context: The ProcessingContext.
    :param document: The document being processed.
    """
    _replace_const_macros(context, document)
    _replace_function_macros(context, document)


@document_rule("*.md")
def santize_internal_links(context: ProcessingContext, document: Document):
    """
    Find any "internal" markdown links and make sure they use the form ()[<path to item>]
    :param context: The ProcessingContext.
    :param document: The document being processed.
    """
    pointer = 0
    while pointer < len(document.contents):
        match, start, end = _get_next_match(document, pointer, regex_markdown_link)
        if not match:
            break
        pointer = end
        text, link = match.group(1), match.group(2)
        link = unquote(link)
        path = Path(document.input_path.parent).joinpath(link).resolve()
        if path.exists():
            reformatted_link = f"[{text}](<{link}>)"
            document.contents = _replace_span(document, start, end, reformatted_link)


@document_rule()
def move_to_target_dir_relative(context: ProcessingContext, document: Document):
    """
    Move the target_path file to save a document to, to the same place under the target_path directory.
    :param context: The ProcessingContext.
    :param document: The document being processed.
    """
    if context.settings.target_directory and context.settings.root_directory != context.settings.target_directory:
        rel_path = os.path.relpath(context.settings.root_directory, document.input_path)
        document.target_path = os.path.join(context.settings.target_directory, rel_path)


@document_rule("*.md")
def rename_uniquely_for_confluence(context: ProcessingContext, document: Document):
    """
    Renames each page so that it contains its own tree as part of its name for the purpose of making the file
    uniquely named. This is to comply with the need in confluence for all pages to have unique names. This also
    renames "README.md" files after their parent directory.

    This will also place the version_name as the root directory.
    So, given a page:
      - "something/else/aswell.md
    this rule will rename it to
      - "develop/something/else/something - else - aswell.md
    :param context: The ProcessingContext.
    :param document: The document being processed.
    """
    rel_path = os.path.relpath(context.settings.root_directory, document.input_path)
    rel_path = rel_path.replace(".md", "")  # remove file extension, we know it's .md
    parts = [context.settings.version_name] + rel_path.split(os.path.sep)
    parent_dir = os.path.dirname(os.path.dirname(rel_path))
    basename = os.path.basename(document.input_path)
    if basename.lower() == "readme.md" or basename == f"{parent_dir}.md":
        parts = parts[:-1] + [" - ".join(parts[:-1]) + ".md"]
    else:
        parts = parts[:-1] + [" - ".join(parts) + ".md"]
    context.target = os.path.join(context.settings.target_directory, *parts)


def GetRulesForStyle(style: DeploymentStyle) -> List[DocumentRule] | KeyError:
    """
    Get the rule set to use for a given deployment style.
    """
    StandardRulesTable = {
        DeploymentStyle.GITHUB: [santize_internal_links, move_to_target_dir_relative],
        DeploymentStyle.CONFLUENCE: [
            create_table_of_contents,
            apply_macros,
            santize_internal_links,
            rename_uniquely_for_confluence,
        ],
        DeploymentStyle.CUSTOM: [],
    }
    return list(StandardRulesTable[style])
