import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

import javsp.__main__ as main
import javsp.web.javdb as javdb
from javsp.config import CrawlerID, UseJavDBCover
from javsp.datatype import Movie, MovieInfo


class Selection(dict):
    """同时支持下标和属性访问，用于模拟Cfg().crawler.selection"""

    def __getattr__(self, item):
        return self[item]


def make_cfg(use_javdb_cover=UseJavDBCover.fallback):
    return SimpleNamespace(
        crawler=SimpleNamespace(
            selection=Selection(normal=[CrawlerID.javdb], fc2=[], cid=[], getchu=[], gyutto=[]),
            required_keys=['cover', 'title'],
            respect_site_avid=True,
            normalize_actress_name=False,
            use_javdb_cover=use_javdb_cover,
        ),
        summarizer=SimpleNamespace(title=SimpleNamespace(remove_trailing_actor_name=False)),
        network=SimpleNamespace(retry=1, timeout=SimpleNamespace(total_seconds=lambda: 1)),
    )


def make_movie(dvdid='ABF-017'):
    movie = Movie(dvdid)
    # info_summary会通过文件名判断内嵌字幕/无码等属性，因此需要关联文件
    movie.files = [f'{dvdid}.mp4']
    return movie


def make_info(dvdid='ABF-017', title='标题', cover='http://example.com/cover.jpg', genre=None):
    info = MovieInfo(dvdid)
    info.title = title
    info.cover = cover
    info.genre = genre
    return info


def test_parallel_crawler_keeps_crawler_names(monkeypatch):
    def fake_parse_data(info):
        info.title = '标题'
        info.cover = 'http://example.com/cover.jpg'

    monkeypatch.setattr(javdb, 'parse_data', fake_parse_data)
    monkeypatch.setattr(main, 'Cfg', lambda: make_cfg())

    result = main.parallel_crawler(make_movie(), None)

    assert list(result) == ['javdb']


def test_info_summary_prefers_javdb_genre(monkeypatch):
    monkeypatch.setattr(main, 'Cfg', lambda: make_cfg())
    other_info = make_info(cover='http://example.com/other.jpg', genre=['其他站点的分类'])
    javdb_info = make_info(genre=['JavDB的分类'])
    movie = make_movie()

    assert main.info_summary(movie, {'airav': other_info, 'javdb': javdb_info}) is True

    assert movie.info.genre == ['JavDB的分类']


@pytest.mark.parametrize('mode, expected_covers', [
    (UseJavDBCover.yes, ['http://example.com/javdb.jpg', 'http://example.com/other.jpg']),
    (UseJavDBCover.fallback, ['http://example.com/other.jpg', 'http://example.com/javdb.jpg']),
    (UseJavDBCover.no, ['http://example.com/other.jpg']),
])
def test_info_summary_applies_javdb_cover_strategy(monkeypatch, mode, expected_covers):
    monkeypatch.setattr(main, 'Cfg', lambda: make_cfg(use_javdb_cover=mode))
    other_info = make_info(cover='http://example.com/other.jpg')
    javdb_info = make_info(cover='http://example.com/javdb.jpg')
    movie = make_movie()

    assert main.info_summary(movie, {'airav': other_info, 'javdb': javdb_info}) is True

    assert movie.info.covers == expected_covers
