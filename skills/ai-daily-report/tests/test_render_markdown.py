from bs4 import BeautifulSoup

from render_html import render
from render_markdown import render_markdown, table_markdown


def test_daily_export_preserves_reader_content(tmp_path, sample_daily_report):
    import json
    source = tmp_path / 'report.json'
    source.write_text(json.dumps(sample_daily_report))
    html = render(source)
    md = render_markdown(html, tmp_path / 'report.md').read_text()
    for section in sample_daily_report['sections'].values():
        assert section['title'] in md
    for item in sample_daily_report['sections']['frontier_models']['items']:
        assert item['headline'] in md
        assert item['source_url'] in md
    assert '【核心发布】' in md
    assert 'fetch_status' not in md
    assert '降级路径' not in md
    assert '<style>' not in md
    assert '](<#' not in md


def test_score_table_keeps_numbers_and_explanations(tmp_path):
    html = tmp_path / 'report.html'
    html.write_text('''<div class="container"><h1>Report</h1><table>
    <tr><th>指标</th><th>本模型</th><th>对照</th></tr>
    <tr><td>任务 A</td><td>73%</td><td>65%</td></tr>
    <tr><td colspan="3">同框架，相差 8 个百分点。</td></tr>
    <tr><td>指数 B</td><td>-2</td><td>0</td></tr>
    </table><p>最后一段</p></div>''')
    md = render_markdown(html, tmp_path / 'report.md').read_text()
    assert '| 任务 A | 73% | 65% |' in md
    assert '同框架，相差 8 个百分点。' in md
    assert '| 指数 B | -2 | 0 |' in md
    assert md.count('| 指标 | 本模型 | 对照 |') == 2
    assert md.endswith('最后一段\n')


def test_headerless_table_does_not_crash():
    table = BeautifulSoup('<table><tr><td>A</td><td>1</td></tr></table>', 'html.parser').table
    assert '| A | 1 |' in table_markdown(table)
