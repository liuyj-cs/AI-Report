from copy import deepcopy

import pytest

from validate_dingtalk import validate_heading_outline, validate_readback_text


def test_readback_rejects_flattening_missing_and_reordered_headings(tmp_path):
    html = tmp_path / 'report.html'
    outline = [(1, '报告'), (2, '模型'), (3, 'A'), (4, '能力评测'), (5, '独立评测'), (3, 'B')]
    html.write_text('<div class="container">' + ''.join(f'<h{n}>{t}</h{n}>' for n, t in outline) + '</div>')
    payload = {'success': True, 'hasMore': False, 'blocks': [
        {'blockType': 'heading', 'element': {'heading': {'level': f'heading-{n}', 'text': t}}} for n, t in outline]}
    validate_heading_outline(html, payload)
    for mutation in ['flatten', 'missing', 'reordered', 'incomplete', 'failed']:
        bad = deepcopy(payload)
        if mutation == 'flatten': bad['blocks'][3]['element']['heading']['level'] = 'heading-3'
        elif mutation == 'missing': bad['blocks'].pop()
        elif mutation == 'reordered': bad['blocks'].reverse()
        elif mutation == 'incomplete': bad['hasMore'] = True
        else: bad['success'] = False
        with pytest.raises(ValueError):
            validate_heading_outline(html, bad)


def test_readback_rejects_markdown_content_loss(tmp_path):
    markdown = tmp_path / 'report.md'
    markdown.write_text('# 报告\n\n| 项目 | 分数 |\n|---|---|\n| C/C++ | 69.6% |\n\n[来源](<https://example.com/a-b>)\n\n末段。')
    normalized = '# 报告\n| 项目 | 分数 |\n| --- | --- |\n| C/C++ | 69.6% |\n\n[来源](https://example.com/a-b)\n\n末段。'
    validate_readback_text(markdown, {'success': True, 'markdown': normalized})
    for changed in ['C/C<u>', '69.5%', 'https://example.com/other', '末尾。']:
        bad = normalized.replace('C/C++', changed) if changed == 'C/C<u>' else (
            normalized.replace('69.6%', changed) if changed == '69.5%' else (
                normalized.replace('https://example.com/a-b', changed) if changed.startswith('https') else normalized.replace('末段。', changed)))
        with pytest.raises(ValueError):
            validate_readback_text(markdown, {'success': True, 'markdown': bad})
