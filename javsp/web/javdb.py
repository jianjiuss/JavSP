"""从JavDB抓取数据"""
import os
import re
import logging

from javsp.web.base import Request, resp2html
from javsp.web.exceptions import *
from javsp.func import *
from javsp.avid import guess_av_type
from javsp.config import Cfg, CrawlerID
from javsp.datatype import MovieInfo, GenreMap
from javsp.chromium import get_browsers_cookies
from javsp.prompt import waiting_for_input


# 初始化Request实例。使用scraper绕过CloudFlare后，需要指定网页语言，否则可能会返回其他语言网页，影响解析
request = Request(use_scraper=True)
request.headers['Accept-Language'] = 'zh-CN,zh;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6,ja;q=0.5'

logger = logging.getLogger(__name__)
genre_map = GenreMap('data/genre_javdb.csv')
permanent_url = 'https://javdb.com'
if Cfg().network.proxy_server is not None:
    base_url = permanent_url
else:
    base_url = str(Cfg().network.proxy_free[CrawlerID.javdb])


def get_html_wrapper(url):
    """包装外发的request请求并负责转换为可xpath的html，同时处理Cookies无效等问题"""
    global request, cookies_pool
    r = request.get(url, delay_raise=True)
    if r.status_code == 200:
        # 发生重定向可能仅仅是域名重定向，因此还要检查url以判断是否被跳转到了登录页
        # curl_cffi 跟随重定向时 r.history 始终为空，改为直接判断最终 URL
        redirected = r.url != url
        if '/login' in r.url:
            # 仅在需要时去读取Cookies
            if 'cookies_pool' not in globals():
                try:
                    cookies_pool = get_browsers_cookies()
                except (PermissionError, OSError) as e:
                    logger.warning(f"无法从浏览器Cookies文件获取JavDB的登录凭据({e})，可能是安全软件在保护浏览器Cookies文件", exc_info=True)
                    cookies_pool = []
                except Exception as e:
                    logger.warning(f"获取JavDB的登录凭据时出错({e})，你可能使用的是国内定制版等非官方Chrome系浏览器", exc_info=True)
                    cookies_pool = []
                # 浏览器 Cookies 不可用时，回退到配置文件中手动填写的 Cookie
                if not cookies_pool:
                    javdb_cookie_str = Cfg().crawler.javdb_cookie
                    if javdb_cookie_str:
                        parsed = {k.strip(): v.strip() for k, v in
                                  (pair.split('=', 1) for pair in javdb_cookie_str.split(';') if '=' in pair)}
                        if parsed.get('locale') != 'zh':
                            logger.warning('config 中 javdb_cookie 的 locale 不是 zh，JavDB 可能返回英文页面导致解析失败')
                        cookies_pool = [{'cookies': parsed, 'profile': 'config', 'site': 'javdb.com'}]
                        logger.debug('使用 config 中手动配置的 javdb_cookie')
            if len(cookies_pool) > 0:
                item = cookies_pool.pop()
                # 更换Cookies时需要创建新的request实例，curl_cffi需要手动将Cookies同步到Session才能生效
                request = Request(use_scraper=True)
                request.headers['Accept-Language'] = 'zh-CN,zh;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6,ja;q=0.5'
                request.cookies = item['cookies']
                if request.scraper:
                    request.scraper.cookies.update(request.cookies)
                cookies_source = (item['profile'], item['site'])
                logger.debug(f'未携带有效Cookies而发生重定向，尝试更换Cookies为: {cookies_source}')
                return get_html_wrapper(url)
            else:
                raise CredentialError('JavDB: 所有浏览器Cookies均已过期')
        elif redirected and 'pay' in r.url.split('/')[-1]:
            raise SitePermissionError(f"JavDB: 此资源被限制为仅VIP可见: '{url}'")
        else:
            html = resp2html(r)
            return html
    elif r.status_code in (403, 503):
        html = resp2html(r)
        code_tag = html.xpath("//span[@class='code-label']/span")
        error_code = code_tag[0].text if code_tag else None
        if error_code:
            if error_code == '1020':
                block_msg = f'JavDB: {r.status_code} 禁止访问: 站点屏蔽了来自日本地区的IP地址，请使用其他地区的代理服务器'
            else:
                block_msg = f'JavDB: {r.status_code} 禁止访问: {url} (Error code: {error_code})'
        else:
            block_msg = f'JavDB: {r.status_code} 禁止访问: {url}'
        raise SiteBlocked(block_msg)
    else:
        raise WebsiteError(f'JavDB: {r.status_code} 非预期状态码: {url}')


def get_user_info(site, cookies):
    """获取cookies对应的JavDB用户信息"""
    try:
        request.cookies = cookies
        html = request.get_html(f'https://{site}/users/profile')
    except Exception as e:
        logger.info('JavDB: 获取用户信息时出错')
        logger.debug(e, exc_info=1)
        return
    # 扫描浏览器得到的Cookies对应的临时域名可能会过期，因此需要先判断域名是否仍然指向JavDB的站点
    if 'JavDB' in html.text:
        email = html.xpath("//div[@class='user-profile']/ul/li[1]/span/following-sibling::text()")[0].strip()
        username = html.xpath("//div[@class='user-profile']/ul/li[2]/span/following-sibling::text()")[0].strip()
        return email, username
    else:
        logger.debug('JavDB: 域名已过期: ' + site)


def get_valid_cookies():
    """扫描浏览器，获取一个可用的Cookies"""
    # 经测试，Cookies所发往的域名不需要和登录时的域名保持一致，只要Cookies有效即可在多个域名间使用
    for d in cookies_pool:
        info = get_user_info(d['site'], d['cookies'])
        if info:
            return d['cookies']
        else:
            logger.debug(f"{d['profile']}, {d['site']}: Cookies无效")


def _extract_actress(info):
    """从影片信息面板中提取女演员，兼容 JavDB 新旧页面标记。"""
    actors_tags = info.xpath(
        ".//strong[normalize-space()='演員:']/following-sibling::span[1]"
    )
    if not actors_tags:
        return []

    actress = []
    for actor in actors_tags[0].xpath(".//a"):
        name = ''.join(actor.itertext()).strip()
        if not name:
            continue

        # 新版页面使用 actor-female class；旧版页面在演员链接前放置性别 strong。
        classes = (actor.get('class') or '').split()
        is_female = 'actor-female' in classes
        if not is_female:
            gender_tag = actor.xpath("./preceding-sibling::*[1][self::strong]")
            is_female = bool(
                gender_tag and gender_tag[0].text_content().strip() == '♀'
            )
        if is_female:
            actress.append(name)
    return actress


def _search_result_candidates(html, dvdid):
    """提取搜索页中与番号完全匹配的结果，并去除重复链接。"""
    target = dvdid.lower()
    candidates = []
    seen_urls = set()
    boxes = html.xpath(
        "//a[contains(concat(' ', normalize-space(@class), ' '), ' box ')]"
    )
    for box in boxes:
        id_text = ''.join(box.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' video-title ')]"
            "/strong//text()"
        )).strip()
        url = box.get('href')
        key = url.split('?')[0].split('#')[0] if url else url
        if id_text.lower() == target and url and key not in seen_urls:
            candidates.append(box)
            seen_urls.add(key)
    return candidates


def _element_text(node):
    """将节点内的文本片段合并为单行文本。"""
    return ' '.join(' '.join(node.itertext()).split())


def _search_result_label(box):
    """生成搜索结果的可读描述，兼容 JavDB 搜索页字段变化。"""
    title = (box.get('title') or '').strip()
    if not title:
        title = ' '.join(''.join(box.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' video-title ')]//text()"
        )).split())
    meta = ' '.join(_element_text(node) for node in box.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' meta ')]"
    ))
    score = ' '.join(_element_text(node) for node in box.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' score ')]"
    ))
    details = ' ｜ '.join(i for i in (meta, score) if i)
    if details:
        return f'{title}（{details}）'
    return title or box.get('href', '')


def _choose_search_result(dvdid, candidates, input_func=None):
    """交互式选择一个重复番号的搜索结果，返回其下标。"""
    if input_func is None:
        input_func = input

    print(f"JavDB 找到 {len(candidates)} 个番号为 '{dvdid}' 的结果，请选择正确的影片：")
    for index, box in enumerate(candidates, start=1):
        print(f'  [{index}] {_search_result_label(box)}')
        print(f"      地址: {box.get('href', '')}")

    while True:
        try:
            with waiting_for_input():
                value = input_func(
                    f'请输入结果编号（1-{len(candidates)}），直接回车跳过本次整理：'
                ).strip()
        except EOFError:
            value = ''
        if not value:
            # 提示信息使用print输出，确保不受日志级别限制而始终可见
            print('未选择搜索结果，已跳过本次整理')
            raise MovieSkipped('未选择搜索结果，已跳过')
        try:
            selected = int(value)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(candidates):
            return selected - 1
        print(f'输入无效，请输入 1-{len(candidates)} 的数字。')


def _fill_from_search_result(movie: MovieInfo, box, url):
    """无法访问影片详情页时，退而使用搜索结果中能提取到的信息"""
    movie.url = url
    movie.title = box.get('title')
    cover_tag = box.xpath("div/img/@src")
    if cover_tag:
        movie.cover = cover_tag[0]
    score_tag = box.xpath("div[@class='score']/span/span")
    if score_tag and score_tag[0].tail:
        match = re.search(r'([\d.]+)分', score_tag[0].tail)
        if match:
            movie.score = "{:.2f}".format(float(match.group(1)) * 2)
    meta_tag = box.xpath("div[@class='meta']/text()")
    if meta_tag:
        movie.publish_date = meta_tag[0].strip()


def parse_data(movie: MovieInfo):
    """从网页抓取并解析指定番号的数据
    Args:
        movie (MovieInfo): 要解析的影片信息，解析后的信息直接更新到此变量内
    """
    # JavDB搜索番号时会有多个搜索结果，从中查找匹配番号的那个
    html = get_html_wrapper(f'{base_url}/search?q={movie.dvdid}')
    candidates = _search_result_candidates(html, movie.dvdid)
    match_count = len(candidates)
    if match_count == 0:
        ids = list(map(str.lower, html.xpath("//div[@class='video-title']/strong/text()")))
        raise MovieNotFoundError(__name__, movie.dvdid, ids)
    elif match_count == 1:
        box = candidates[0]
        new_url = box.get('href')
        try:
            html2 = get_html_wrapper(new_url)
        except (SitePermissionError, CredentialError):
            # 不开VIP不让看，过分。决定榨出能获得的信息，毕竟有时候只有这里能找到标题和封面
            _fill_from_search_result(movie, box, new_url)
            return
    else:
        if not Cfg().other.interactive:
            raise MovieDuplicateError(
                __name__, movie.dvdid, match_count,
                [box.get('href') for box in candidates]
            )
        index = _choose_search_result(movie.dvdid, candidates)
        box = candidates[index]
        new_url = box.get('href')
        try:
            html2 = get_html_wrapper(new_url)
        except (SitePermissionError, CredentialError):
            _fill_from_search_result(movie, box, new_url)
            return

    container = html2.xpath("/html/body/section/div/div[@class='video-detail']")[0]
    info = container.xpath("//nav[@class='panel movie-panel-info']")[0]
    title = container.xpath("h2/strong[@class='current-title']/text()")[0]
    show_orig_title = container.xpath("//a[contains(@class, 'meta-link') and not(contains(@style, 'display: none'))]")
    if show_orig_title:
        movie.ori_title = container.xpath("h2/span[@class='origin-title']/text()")[0]
    cover = container.xpath("//img[@class='video-cover']/@src")[0]
    preview_pics = container.xpath("//a[@class='tile-item'][@data-fancybox='gallery']/@href")
    preview_video_tag = container.xpath("//video[@id='preview-video']/source/@src")
    if preview_video_tag:
        preview_video = preview_video_tag[0]
        if preview_video.startswith('//'):
            preview_video = 'https:' + preview_video
        movie.preview_video = preview_video
    dvdid = info.xpath("div/span")[0].text_content()
    publish_date = info.xpath("div/strong[text()='日期:']")[0].getnext().text
    duration = info.xpath("div/strong[text()='時長:']")[0].getnext().text.replace('分鍾', '').strip()
    director_tag = info.xpath("div/strong[text()='導演:']")
    if director_tag:
        movie.director = director_tag[0].getnext().text_content().strip()
    av_type = guess_av_type(movie.dvdid)
    if av_type != 'fc2':
        producer_tag = info.xpath("div/strong[text()='片商:']")
    else:
        producer_tag = info.xpath("div/strong[text()='賣家:']")
    if producer_tag:
        movie.producer = producer_tag[0].getnext().text_content().strip()
    publisher_tag = info.xpath("div/strong[text()='發行:']")
    if publisher_tag:
        movie.publisher = publisher_tag[0].getnext().text_content().strip()
    serial_tag = info.xpath("div/strong[text()='系列:']")
    if serial_tag:
        movie.serial = serial_tag[0].getnext().text_content().strip()
    score_tag = info.xpath("//span[@class='score-stars']")
    if score_tag:
        score_str = score_tag[0].tail
        score = re.search(r'([\d.]+)分', score_str).group(1)
        movie.score = "{:.2f}".format(float(score)*2)
    genre_tags = info.xpath("//strong[text()='類別:']/../span/a")
    genre, genre_id = [], []
    for tag in genre_tags:
        pre_id = tag.get('href').split('/')[-1]
        genre.append(tag.text)
        genre_id.append(pre_id)
        # 判定影片有码/无码
        subsite = pre_id.split('?')[0]
        movie.uncensored = {'uncensored': True, 'tags':False}.get(subsite)
    # JavDB目前同时提供男女优信息，根据用来标识性别的符号筛选出女优
    actress = _extract_actress(info)
    magnet = container.xpath("//div[@class='magnet-name column is-four-fifths']/a/@href")

    movie.dvdid = dvdid
    movie.url = new_url.replace(base_url, permanent_url)
    movie.title = title.replace(dvdid, '').strip()
    movie.cover = cover
    movie.preview_pics = preview_pics
    movie.publish_date = publish_date
    movie.duration = duration
    movie.genre = genre
    movie.genre_id = genre_id
    movie.actress = actress
    movie.magnet = [i.replace('[javdb.com]','') for i in magnet]


def parse_clean_data(movie: MovieInfo):
    """解析指定番号的影片数据并进行清洗"""
    try:
        parse_data(movie)
        # 检查封面URL是否真的存在对应图片
        if movie.cover is not None:
            r = request.head(movie.cover)
            if r.status_code != 200:
                movie.cover = None
    except SiteBlocked:
        raise
        logger.error('JavDB: 可能触发了反爬虫机制，请稍后再试')
    if movie.genre_id and (not movie.genre_id[0].startswith('fc2?')):
        movie.genre_norm = genre_map.map(movie.genre_id)
        movie.genre_id = None   # 没有别的地方需要再用到，清空genre id（表明已经完成转换）


def collect_actress_alias(type=0, use_original=True):
    """
    收集女优的别名
    type: 0-有码, 1-无码, 2-欧美
    use_original: 是否使用原名而非译名，True-田中レモン，False-田中檸檬
    """
    import json
    import time
    import random

    actressAliasMap = {}

    actressAliasFilePath = "data/actress_alias.json"
    # 检查文件是否存在
    if not os.path.exists(actressAliasFilePath):
        # 如果文件不存在，创建文件并写入空字典
        with open(actressAliasFilePath, "w", encoding="utf-8") as file:
            json.dump({}, file)

    typeList = ["censored", "uncensored", "western"]
    page_url = f"{base_url}/actors/{typeList[type]}"
    while True:
        try:
            html = get_html_wrapper(page_url)
            actors = html.xpath("//div[@class='box actor-box']/a")

            count = 0
            for actor in actors:
                count += 1
                actor_name = actor.xpath("strong/text()")[0].strip()
                actor_url = actor.xpath("@href")[0]
                # actor_url = f"https://javdb.com{actor_url}"  # 构造演员主页的完整URL

                # 进入演员主页，获取更多信息
                actor_html = get_html_wrapper(actor_url)
                # 解析演员所有名字信息
                names_span = actor_html.xpath("//span[@class='actor-section-name']")[0]
                aliases_span_list = actor_html.xpath("//span[@class='section-meta']")
                aliases_span = aliases_span_list[0]

                names_list = [name.strip() for name in names_span.text.split(",")]
                if len(aliases_span_list) > 1:
                    aliases_list = [
                        alias.strip() for alias in aliases_span.text.split(",")
                    ]
                else:
                    aliases_list = []

                # 将信息添加到actressAliasMap中
                actressAliasMap[names_list[-1 if use_original else 0]] = (
                    names_list + aliases_list
                )
                print(
                    f"{count} --- {names_list[-1 if use_original else 0]}: {names_list + aliases_list}"
                )

                if count == 10:
                    # 将数据写回文件
                    with open(actressAliasFilePath, "r", encoding="utf-8") as file:
                        existing_data = json.load(file)

                    # 合并现有数据和新爬取的数据
                    existing_data.update(actressAliasMap)

                    # 将合并后的数据写回文件
                    with open(actressAliasFilePath, "w", encoding="utf-8") as file:
                        json.dump(existing_data, file, ensure_ascii=False, indent=2)

                    actressAliasMap = {}  # 重置actressAliasMap

                    print(
                        f"已爬取 {count} 个女优，数据已更新并写回文件:",
                        actressAliasFilePath,
                    )

                    # 重置计数器
                    count = 0

                time.sleep(max(1, 10 * random.random()))  # 随机等待 1-10 秒

            # 判断是否有下一页按钮
            next_page_link = html.xpath(
                "//a[@rel='next' and @class='pagination-next']/@href"
            )
            if not next_page_link:
                break  # 没有下一页，结束循环
            else:
                next_page_url = f"{next_page_link[0]}"
                page_url = next_page_url

        except SiteBlocked:
            raise

    with open(actressAliasFilePath, "r", encoding="utf-8") as file:
        existing_data = json.load(file)

    # 合并现有数据和新爬取的数据
    existing_data.update(actressAliasMap)

    # 将合并后的数据写回文件
    with open(actressAliasFilePath, "w", encoding="utf-8") as file:
        json.dump(existing_data, file, ensure_ascii=False, indent=2)

    print(f"已爬取 {count} 个女优，数据已更新并写回文件:", actressAliasFilePath)


if __name__ == "__main__":
    # collect_actress_alias()
    movie = MovieInfo('FC2-2735981')
    try:
        parse_clean_data(movie)
        print(movie)
    except CrawlerError as e:
        print(repr(e))
