import os
import sys

from lxml import html

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from javsp.web.javdb import _extract_actress


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
