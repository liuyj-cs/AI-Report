from copy import deepcopy

import pytest

from validate_dingtalk import validate_heading_outline


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
