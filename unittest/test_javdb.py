import os
import sys

import pytest
from lxml import html

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import javsp.web.javdb as javdb
from javsp.datatype import MovieInfo
from javsp.prompt import is_waiting_for_input
from javsp.web.exceptions import MovieSkipped, SitePermissionError
from javsp.web.javdb import (
    _choose_search_result,
    _extract_actress,
    _search_result_candidates,
    _search_result_label,
)


def test_extract_actress_uses_current_actor_class():
    info = html.fromstring(
        '<nav><strong>演員:</strong><span>'
        '<a class="actor-female">female</a>, <a>male</a>'
        '</span></nav>'
    )

    assert _extract_actress(info) == ['female']


def test_extract_actress_supports_legacy_gender_markers():
    info = html.fromstring(
        '<nav><strong>演員:</strong><span>'
        '<strong>♀</strong><a>female</a>, '
        '<strong>♂</strong><a>male</a>'
        '</span></nav>'
    )

    assert _extract_actress(info) == ['female']


def test_extract_actress_ignores_missing_actor_section():
    info = html.fromstring('<nav><strong>日期:</strong><span>2025</span></nav>')

    assert _extract_actress(info) == []


def test_search_result_candidates_match_exact_id_and_deduplicate_urls():
    search = html.fromstring(
        '<div>'
        '<a class="box" href="https://javdb580.com/v/one">'
        '<div class="video-title"><strong>ABF-017</strong></div>'
        '</a>'
        '<a class="box" href="https://javdb580.com/v/one">'
        '<div class="video-title"><strong>ABF-017</strong></div>'
        '</a>'
        '<a class="box" href="https://javdb580.com/v/two">'
        '<div class="video-title"><strong>ABF-017-C</strong></div>'
        '</a>'
        '<a class="box" href="https://javdb580.com/v/three">'
        '<div class="video-title"><strong>ABF-018</strong></div>'
        '</a>'
        '</div>'
    )

    candidates = _search_result_candidates(search, 'ABF-017')

    assert [box.get('href') for box in candidates] == ['https://javdb580.com/v/one']


def test_choose_search_result_retries_invalid_input():
    search = html.fromstring(
        '<div>'
        '<a class="box" href="https://javdb580.com/v/one" title="第一条"></a>'
        '<a class="box" href="https://javdb580.com/v/two" title="第二条"></a>'
        '</div>'
    )
    answers = iter(['x', '2'])

    selected = _choose_search_result(
        'ABF-017', list(search.xpath('//a[@class="box"]')), lambda _prompt: next(answers)
    )

    assert selected == 1


def test_search_result_candidates_deduplicate_urls_with_query_string():
    search = html.fromstring(
        '<div>'
        '<a class="box" href="https://javdb580.com/v/one">'
        '<div class="video-title"><strong>ABF-017</strong></div>'
        '</a>'
        '<a class="box" href="https://javdb580.com/v/one?locale=zh">'
        '<div class="video-title"><strong>ABF-017</strong></div>'
        '</a>'
        '</div>'
    )

    candidates = _search_result_candidates(search, 'ABF-017')

    assert len(candidates) == 1


def test_search_result_label_renders_title_meta_and_score():
    box = html.fromstring(
        '<a class="box" href="https://javdb580.com/v/one" title="标题一">'
        '<div class="meta">2024-10-01</div>'
        '<div class="score"><span class="value">4.70分, 由100人評價</span></div>'
        '</a>'
    )

    assert _search_result_label(box) == '标题一（2024-10-01 ｜ 4.70分, 由100人評價）'


def test_choose_search_result_skips_on_empty_input():
    search = html.fromstring(
        '<div>'
        '<a class="box" href="https://javdb580.com/v/one" title="第一条"></a>'
        '<a class="box" href="https://javdb580.com/v/two" title="第二条"></a>'
        '</div>'
    )

    with pytest.raises(MovieSkipped) as exc_info:
        _choose_search_result(
            'ABF-017', list(search.xpath('//a[@class="box"]')), lambda _prompt: ''
        )

    assert '未选择搜索结果' in str(exc_info.value)


def test_choose_search_result_marks_waiting_state_only_while_prompting():
    search = html.fromstring(
        '<div><a class="box" href="https://javdb580.com/v/one" title="第一条"></a></div>'
    )
    observed = []

    def fake_input(_prompt):
        observed.append(is_waiting_for_input())
        return '1'

    _choose_search_result('ABF-017', list(search.xpath('//a[@class="box"]')), fake_input)

    assert observed == [True]
    assert is_waiting_for_input() is False


def test_parse_data_falls_back_to_search_result_when_detail_is_limited(monkeypatch):
    search_page = html.fromstring(
        '<div><a class="box" href="https://javdb580.com/v/one" title="标题一">'
        '<div class="video-title"><strong>ABF-017</strong></div>'
        '<div class="img"><img src="https://example.com/cover.jpg"></div>'
        '<div class="score"><span><span></span>4.70分, 由100人評價</span></div>'
        '<div class="meta">2024-10-01</div>'
        '</a></div>'
    )

    def fake_get_html_wrapper(url):
        if url.endswith('ABF-017'):
            return search_page
        raise SitePermissionError('此资源被限制为仅VIP可见')

    monkeypatch.setattr(javdb, 'get_html_wrapper', fake_get_html_wrapper)
    movie = MovieInfo('ABF-017')

    javdb.parse_data(movie)

    assert movie.url == 'https://javdb580.com/v/one'
    assert movie.title == '标题一'
    assert movie.cover == 'https://example.com/cover.jpg'
    assert movie.score == '9.40'
    assert movie.publish_date == '2024-10-01'
