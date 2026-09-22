#!/usr/bin/env python3
"""Convert rendered report content to Markdown for an online document.

The HTML remains the presentation source of truth. No editorial content is
regenerated here; navigation, CSS, and collection diagnostics are omitted.
"""
import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


def inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if node.name == "br":
        return " / "
    content = "".join(inline(child) for child in node.children).strip()
    if "badge" in node.get("class", []):
        return f"【{content}】"
    if node.name == "a":
        url = node.get("href", "")
        if url.startswith(("https://", "http://")):
            return f"[{content}](<{url}>)"
        return content
    if node.name in ("strong", "b"):
        # Spaces keep punctuation-ending Chinese labels valid in Markdown.
        return f" **{content}** " if content else ""
    if node.name == "code":
        return f"`{content}`"
    return content


def table_markdown(table: Tag) -> str:
    lines = []
    header = separator = ""
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        # Full-width explanation rows become prose between metric tables.
        if len(cells) == 1 and int(cells[0].get("colspan", 1)) > 1:
            lines.extend(["", inline(cells[0]), ""])
            continue
        values = [inline(cell).replace("|", "\\|") for cell in cells]
        if cells[0].name == "th":
            header = "| " + " | ".join(values) + " |"
            separator = "| " + " | ".join("---" for _ in values) + " |"
            lines.extend([header, separator])
        else:
            # A preceding colspan row ended the table; repeat the column labels.
            if lines and lines[-1] == "" and table.find("th"):
                lines.extend([header, separator])
            lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def blocks(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node).strip()
    if re.fullmatch(r"h[1-6]", node.name):
        return "#" * int(node.name[1]) + " " + inline(node)
    if node.name == "table":
        return table_markdown(node)
    if node.name in ("ul", "ol"):
        return "\n".join(
            f"{str(index) + '.' if node.name == 'ol' else '-'} {inline(item)}"
            for index, item in enumerate(node.find_all("li", recursive=False), 1)
        )
    if node.name == "blockquote":
        return "> " + inline(node)
    classes = node.get("class", [])
    if "headline" in classes:
        return "### " + inline(node)
    if not node.find(["div", "p", "section", "article", "aside", "header", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"]):
        return inline(node)
    return "\n\n".join(part for child in node.children if (part := blocks(child)))


def render_markdown(html_path: Path, output_path: Path) -> Path:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    container = soup.select_one(".container")
    if container is None:
        raise ValueError("Report HTML has no .container")
    for node in container.select("nav, footer, .guide-detail-link"):
        node.decompose()
    text = blocks(container)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    output_path.write_text(text, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(render_markdown(args.html_path, args.output))


if __name__ == "__main__":
    main()
