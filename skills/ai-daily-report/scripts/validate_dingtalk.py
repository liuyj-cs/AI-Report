"""Check the published text and native heading outline against the final daily."""
import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


def validate_heading_outline(html_path: Path, block_payload: dict) -> None:
    if block_payload.get('success') is not True or block_payload.get('hasMore') is not False:
        raise ValueError('DingTalk block readback must succeed and contain every page')
    soup = BeautifulSoup(html_path.read_text(encoding='utf-8'), 'html.parser')
    container = soup.select_one('.container')
    if container is None:
        raise ValueError('Report HTML has no .container')
    for node in container.select('nav, footer'):
        node.decompose()
    # Recompute the complete expected outline from the published source.
    normalize = lambda text: ' '.join(text.split())
    expected = [(int(node.name[1]), normalize(node.get_text()))
                for node in container.find_all(re.compile(r'^h[1-6]$'))]
    actual = []
    for block in block_payload['blocks']:
        if block['blockType'] != 'heading':
            continue
        heading = block['element']['heading']
        level = heading['level']
        actual.append((int(str(level).removeprefix('heading-')), normalize(heading['text'])))
    if not expected or actual != expected:
        raise ValueError(f'DingTalk heading outline differs from HTML: expected={expected!r}, actual={actual!r}')


def _normalize_markdown(text: str) -> str:
    # DingTalk changes list/table spacing, drops URL angle brackets, and escapes
    # punctuation. Keep content punctuation such as C++ and model-name hyphens.
    text = re.sub(r'^\s*\|?[\s:|-]+\|?\s*$', '', text, flags=re.M)
    text = re.sub(r'^\s*(?:#+\s*|-\s*)', '', text, flags=re.M)
    return re.sub(r'[\s`*|<>\\]', '', text)


def validate_readback_text(markdown_path: Path, read_payload: dict) -> None:
    if read_payload.get('success') is not True or not isinstance(read_payload.get('markdown'), str):
        raise ValueError('DingTalk full-text readback must succeed')
    expected = _normalize_markdown(markdown_path.read_text(encoding='utf-8'))
    actual = _normalize_markdown(read_payload['markdown'])
    if not expected or actual != expected:
        raise ValueError('DingTalk full text differs from final Markdown after formatting normalization')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html_path', type=Path)
    parser.add_argument('blocks_json', type=Path)
    parser.add_argument('markdown_path', type=Path)
    parser.add_argument('readback_json', type=Path)
    args = parser.parse_args()
    validate_heading_outline(args.html_path, json.loads(args.blocks_json.read_text(encoding='utf-8')))
    validate_readback_text(args.markdown_path, json.loads(args.readback_json.read_text(encoding='utf-8')))
    print('DingTalk full text and heading outline verified')


if __name__ == '__main__':
    main()
