"""Public MIDI search/download providers; no audio recognition or paid API.

Providers: Mutopia, Ichigo's, 8notes, MIDIWorld and MIDI Collection.
All provider parsing code is original. Individual music licenses and provenance
are returned separately; the software does not claim ownership of downloaded music.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import hashlib
from html.parser import HTMLParser
import io
import ipaddress
from pathlib import Path
import re
import socket
import struct
import tempfile
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_MIDI_BYTES = 2 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = 12
BASE_URL = "https://www.mutopiaproject.org/"
_ALLOWED_HOSTS = frozenset(("www.mutopiaproject.org", "mutopiaproject.org", "ichigos.com", "www.ichigos.com",
                            "www.8notes.com", "media.8notes.com", "www.midiworld.com", "midicollection.com"))

# Query aliases only: every returned candidate still comes from a live provider.
# Multiple established English titles help repositories with different naming.
TITLE_ALIASES = {
    "致爱丽丝": ("Fur Elise",),
    "献给爱丽丝": ("Fur Elise",),
    "月光奏鸣曲": ("Moonlight Sonata", "Sonata Op. 27 No. 2"),
    "土耳其进行曲": ("Turkish March", "Alla Turca"),
    "卡农": ("Canon in D", "Pachelbel Canon", "Canon"),
    "小星星": ("Twinkle Twinkle", "Ah vous dirai-je maman"),
    "梦幻曲": ("Traumerei",),
    "欢乐颂": ("Ode to Joy",),
    "贝多芬": ("Beethoven",),
    "莫扎特": ("Mozart",),
    "肖邦": ("Chopin",),
    "巴赫": ("Bach",),
    "德彪西": ("Debussy",),
    "舒曼": ("Schumann",),
    "萨蒂": ("Satie",),
    "菊次郎的夏天": ("Summer",),
    "菊次郎之夏": ("Summer",),
    "菊次郎の夏": ("Summer",),
    "菊次郎的夏": ("Summer",),
    "天空之城": ("Kimi wo Nosete", "Carrying You"),
    "永远同在": ("Itsumo Nando Demo", "Always with Me"),
    "生命之名": ("Inochi no Namae", "The Name of Life"),
    "人生的旋转木马": ("Merry Go Round of Life",),
    "哈尔的移动城堡": ("Merry Go Round of Life",),
    "风之甬道": ("Path of the Wind",),
    "起风了": ("Hikoukigumo",),
    "龙猫": ("My Neighbor Totoro",),
    "梦中的婚礼": ("Mariage d Amour",),
    "雨的印记": ("Kiss the Rain",),
    "水边的阿狄丽娜": ("Ballade pour Adeline",),
    "你的心河": ("River Flows in You",),
    "帕赫贝尔": ("Pachelbel",),
    "理查德克莱德曼": ("Richard Clayderman",),
    "理查德·克莱德曼": ("Richard Clayderman",),
    "李闰珉": ("Yiruma",),
    "久石让": ("Joe Hisaishi",),
    "久石譲": ("Joe Hisaishi",),
}


class MidiSourceError(ValueError):
    """A network, match, or MIDI validation error suitable for local UI display."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def _validate_url(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise MidiSourceError("下载网址无效。") from exc
    if (parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or parsed.fragment):
        raise MidiSourceError("仅允许已配置公开 MIDI 来源的 HTTPS 地址。")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise MidiSourceError("无法解析 MIDI 来源地址。") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise MidiSourceError("已拒绝指向内网或非公开地址的 MIDI 来源。")
    return parsed


def _fetch(url, limit, data=None):
    opener = build_opener(_NoRedirect)
    for redirect in range(5):
        _validate_url(url)
        request = Request(url, data=data, headers={"User-Agent": "PianoLightStudio/0.1 (public MIDI lookup)",
                                                  "Accept-Encoding": "identity"})
        try:
            response = opener.open(request, timeout=REQUEST_TIMEOUT)
        except HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                exc.close()
                if not location or redirect == 4:
                    raise MidiSourceError("MIDI 来源重定向过多或缺少目标。") from exc
                # Every redirect is checked before any request reaches its target.
                url = urljoin(url, location)
                _validate_url(url)
                continue
            raise MidiSourceError(f"公开 MIDI 来源暂时无法访问（HTTP {exc.code}）。") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MidiSourceError("连接公开 MIDI 来源失败或超时。") from exc
        with response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) < 0 or int(declared) > limit:
                        raise MidiSourceError("来源响应超过大小限制。")
                except ValueError as exc:
                    if isinstance(exc, MidiSourceError):
                        raise
                    raise MidiSourceError("来源响应长度无效。") from exc
            data = response.read(limit + 1)
            if len(data) > limit:
                raise MidiSourceError("来源响应超过大小限制。")
            return data, url
    raise MidiSourceError("MIDI 来源重定向过多。")


def _text(value):
    return " ".join(value.split())


def _normal(value):
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold()
    return _text(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE))


def _query_variants(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 160:
        raise MidiSourceError("请输入 1–160 个字符的曲名，可附作曲家。")
    variants = [query.strip()]
    used = []
    for alias in sorted(TITLE_ALIASES, key=len, reverse=True):
        if alias not in query:
            continue
        used.append(alias)
        expanded = []
        for value in variants:
            for replacement in TITLE_ALIASES[alias]:
                expanded.append(value.replace(alias, f" {replacement} "))
        variants = expanded[:4]
    variants = list(dict.fromkeys(_text(value) for value in variants))
    if not any(any(c.isalnum() for c in value) for value in variants):
        raise MidiSourceError("请输入实际曲名。")
    return variants, used


def matches_local_title(query, title):
    """Match a converted score using the same translated titles as online search."""
    terms, _ = _query_variants(query)
    terms += [re.sub(r"\bJoe\s+Hisaishi\b", "", term, flags=re.I).strip() for term in terms]
    names, _ = _query_variants(title)
    actual = [_normal(value) for value in (title, *names)]
    if "卡农" in query or _normal(query) in ("canon", "canon in d", "pachelbel canon"):
        if "卡农" in title and not any(word in _normal(title).split() for word in ("rock", "bach")):
            return True
        if _normal(title) in ("canon in d", "canon in d long version", "canon in d easy version", "canon in d beginner version"):
            return True
        return _canonical_similarity("Canon in D", title, "", "", "卡农") >= .62
    for term in (query, *terms):
        if _normal(term) == "summer":
            if any(name.replace("joe hisaishi", "").replace("久石譲", "").replace("久石让", "").strip()
                   in ("summer", "summer full version") for name in actual):
                return True
            continue
        words = set(_normal(term).split())
        if words and any(words.issubset(set(name.split())) or
                         (len(_normal(term)) >= 2 and _normal(term) in name) for name in actual):
            return True
    return False


class _IchigoParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading = False
        self.italic = False
        self.anchor = False
        self.line = []
        self.last_line = ""
        self.work = ""
        self.page = "https://ichigos.com/search"
        self.song = ""
        self.instrument = ""
        self.sheets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span" and "title2" in attrs.get("class", "").split():
            self.heading = True
            self.work = ""
            self.song = ""
            self.line = []
        elif tag == "br":
            text = _text("".join(self.line)).strip(" |")
            if text:
                self.last_line = text
            self.line = []
        elif tag == "i":
            self.italic = True
            self.instrument = ""
            self.song = self.last_line
        elif tag == "a":
            self.anchor = True
            url = urljoin("https://ichigos.com/", attrs.get("href", ""))
            if self.heading and urlsplit(url).path.startswith("/sheets/"):
                self.page = url
            elif (self.song and urlsplit(url).path == "/res/getfile.php" and
                  parse_qs(urlsplit(url).query).get("type") == ["midi"]):
                self.sheets.append({"raw_title": self.song, "work": self.work,
                                    "instrument": self.instrument, "midi_url": url, "page_url": self.page})

    def handle_data(self, value):
        if self.heading:
            self.work += value
        elif self.italic:
            self.instrument += value
        elif not self.anchor:
            self.line.append(value)

    def handle_endtag(self, tag):
        if tag == "span" and self.heading:
            self.heading = False
        elif tag == "i":
            self.italic = False
        elif tag == "a":
            self.anchor = False


def _ichigo_search(term, all_terms, aliases, original_query):
    # The site's search form accepts POST; result links carry fresh download tokens.
    lookup = re.sub(r"\bJoe\s+Hisaishi\b", "", term, flags=re.I).strip()
    if not lookup:
        return []
    body = urlencode({"q": "1", "qtitle": lookup, "qdesc": "piano", "qauthor": ""}).encode()
    html, _ = _fetch("https://ichigos.com/sheets", MAX_HTML_BYTES, body)
    parser = _IchigoParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    candidates = []
    for sheet in parser.sheets:
        instrument = re.sub(r"^for\s+", "", sheet["instrument"].strip(), flags=re.I)
        if _normal(instrument) not in ("piano", "piano solo", "solo piano", "keyboard"):
            continue
        title = re.sub(r"\s*\(Transcribed by .*\)\s*$", "", sheet["raw_title"], flags=re.I).strip()
        transcriber = re.search(r"\(Transcribed by (.*)\)\s*$", sheet["raw_title"], flags=re.I)
        summer = _normal(lookup) == "summer" and _normal(sheet["work"]) == "kikujiro"
        composer = "Joe Hisaishi" if summer else ""
        similarity = max(_canonical_similarity(value, title, "", composer or "Joe Hisaishi", original_query)
                         for value in all_terms)
        score = min(1., similarity * .88 + .10 + (.02 if summer else 0))
        candidates.append({**sheet, "title": title, "composer": composer,
                           "provider": "Ichigo's Sheet Music", "license": "来源网站未注明开放许可",
                           "license_url": "https://ichigos.com/legal", "piano_solo": True,
                           "match_score": round(score, 6), "title_similarity": round(similarity, 6),
                           "composer_match": bool(composer), "opus": "", "query": original_query,
                           "transcriber": transcriber.group(1) if transcriber else "",
                           "search_terms": all_terms, "query_aliases_used": aliases})
    return candidates


class _MutopiaTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.current = None
        self.cell = None
        self.anchor = None
        self.tables = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif "result-table" in attrs.get("class", "").split():
                self.depth = 1
                self.current = {"cells": [], "links": []}
        if not self.depth:
            return
        if tag == "td":
            self.cell = []
        elif tag == "a":
            self.anchor = {"href": attrs.get("href", ""), "text": []}

    def handle_data(self, data):
        if not self.depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "a" and self.anchor is not None:
            self.anchor["text"] = _text(" ".join(self.anchor["text"]))
            self.current["links"].append(self.anchor)
            self.anchor = None
        elif tag == "td" and self.cell is not None:
            self.current["cells"].append(_text(" ".join(self.cell)))
            self.cell = None
        elif tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.tables.append(self.current)
                self.current = None


def _title_similarity(term, title, opus, composer):
    # A supplied composer helps distinguish arrangements, but an artist name on
    # its own is not treated as a matched song title.
    author_words = {word for word in _normal(composer).split() if len(word) >= 3}
    q_words = [word for word in _normal(term).split() if word not in author_words]
    query = " ".join(q_words)
    actual = _normal(title)
    if not query:
        return 0.0
    if query in {"canon", "sonata", "waltz", "nocturne", "prelude", "etude", "concerto"}:
        # Form names alone cannot identify a composition. An arbitrary work
        # containing "Canon" must never become the usual Pachelbel request.
        return 0.5
    if query == actual:
        return 1.0
    full = _normal(f"{title} {opus}")
    if len(query) >= 4 and query in actual:
        return 0.96
    if q_words and set(q_words).issubset(set(full.split())):
        return 0.93
    overlap = len(set(q_words) & set(full.split())) / max(1, len(set(q_words)))
    return max(SequenceMatcher(None, query, actual).ratio(),
               SequenceMatcher(None, query, full).ratio(), overlap * .85)


def _canonical_similarity(term, title, opus, composer, original_query):
    similarity = _title_similarity(term, title, opus, composer)
    identity = _normal(f"{title} {composer}")
    query = _normal(original_query)
    if "卡农" in original_query or query in ("canon", "canon in d", "pachelbel canon"):
        if "pachelbel" not in identity or "canon" not in identity or re.search(r"\b(rock|remix)\b", identity):
            return min(similarity, .3)
        # Repository titles often omit the key, but the named composer still
        # distinguishes Pachelbel's work from unrelated Bach/Scriabin canons.
        return max(similarity, .93 if re.search(r"\bcanon in d\b", identity) else .85)
    if "月光奏鸣曲" in original_query or "moonlight sonata" in query:
        if "beethoven" not in identity or not {"27", "2"}.issubset(set(_normal(opus).split())):
            # Non-Mutopia archives usually give the established title instead of opus.
            if "beethoven" not in identity or "moonlight" not in identity:
                return min(similarity, .3)
    if any(alias in original_query for alias in ("致爱丽丝", "献给爱丽丝")) and "beethoven" not in identity:
        return min(similarity, .3)
    return similarity


class _CatalogRows(HTMLParser):
    """Read the public result rows used by 8notes and MIDI Collection."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = {"attrs": attrs, "cells": {}, "links": [], "buttons": []}
        elif self.row is not None:
            if tag == "td":
                self.cell = (attrs.get("class", "").split(), [])
            elif tag == "a":
                self.row["links"].append(attrs)
            elif tag == "button":
                self.row["buttons"].append(attrs)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[1].append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None and self.row is not None:
            classes, parts = self.cell
            for name in classes:
                self.row["cells"][name] = _text("".join(parts))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = self.cell = None


class _MidiLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and urlsplit(attrs.get("href", "")).path.lower().endswith((".mid", ".midi")):
            self.links.append(attrs["href"])


def _catalog_candidate(title, composer, provider, page_url, midi_url, terms, aliases, query, *, solo=False):
    similarity = max(_canonical_similarity(term, title, "", composer, query) for term in terms)
    author_words = {word for word in _normal(composer).split() if len(word) >= 3}
    composer_match = bool(author_words & {word for term in terms for word in _normal(term).split()})
    score = min(1., similarity * .88 + (.10 if solo else .04) + (.02 if composer_match else 0))
    if re.search(r"\b(beginner|easy|simplified)\b", title, re.I):
        score -= .03
    return {"title": title, "composer": composer, "provider": provider,
            "page_url": page_url, "midi_url": midi_url, "license": "来源网站未注明开放许可",
            "license_url": page_url, "instrument": "Piano" if solo else "待检查乐器",
            "piano_solo": solo, "requires_piano_check": True,
            "match_score": round(score, 6), "title_similarity": round(similarity, 6),
            "composer_match": composer_match, "opus": "", "query": query,
            "search_terms": terms, "query_aliases_used": aliases}


def _eightnotes_search(term, all_terms, aliases, original_query):
    query_url = "https://www.8notes.com/school/search_fsm.asp?" + urlencode({"keyword": f"{term} piano"})
    html, actual_url = _fetch(query_url, MAX_HTML_BYTES)
    parser = _CatalogRows()
    parser.feed(html.decode("utf-8", errors="replace"))
    editions = []
    for row in parser.rows:
        cells = row["cells"]
        target = re.search(r"['\"](/scores/\d+\.asp)['\"]", row["attrs"].get("onclick", ""))
        if not target or _normal(cells.get("level_type", "")) != "piano" or not cells.get("fsmtitle"):
            continue
        entry = _catalog_candidate(cells["fsmtitle"], cells.get("artname", ""), "8notes",
                                   urljoin(actual_url, target.group(1)), "", all_terms, aliases, original_query, solo=True)
        if entry["title_similarity"] >= .62 and entry["match_score"] >= .70:
            editions.append(entry)
    candidates = []
    for entry in sorted(editions, key=lambda item: -item["match_score"])[:2]:
        try:
            html, page_url = _fetch(entry["page_url"], MAX_HTML_BYTES)
        except MidiSourceError:
            continue
        links = _MidiLinks()
        links.feed(html.decode("utf-8", errors="replace"))
        if links.links:
            candidates.append({**entry, "page_url": page_url, "midi_url": urljoin(page_url, links.links[0])})
    return candidates


class _MidiWorldParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.line = None
        self.entries = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li":
            self.line = []
        elif tag == "a" and self.line is not None:
            url = urljoin("https://www.midiworld.com/", attrs.get("href", ""))
            if re.fullmatch(r"/download/\d+", urlsplit(url).path):
                text = _text("".join(self.line))
                match = re.fullmatch(r"(.*?)\s+\(([^()]*)\)\s*-", text)
                if match:
                    self.entries.append((match.group(1).strip(), match.group(2).strip(), url))
            self.line = None

    def handle_data(self, value):
        if self.line is not None:
            self.line.append(value)

    def handle_endtag(self, tag):
        if tag == "li":
            self.line = None


def _midiworld_search(term, all_terms, aliases, original_query):
    html, actual_url = _fetch("https://www.midiworld.com/search/?" + urlencode({"q": term}), MAX_HTML_BYTES)
    parser = _MidiWorldParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    return [_catalog_candidate(title, composer, "MIDIWorld", actual_url, midi_url,
                               all_terms, aliases, original_query) for title, composer, midi_url in parser.entries]


def _collection_search(term, all_terms, aliases, original_query):
    html, actual_url = _fetch("https://midicollection.com/search", MAX_HTML_BYTES,
                             urlencode({"page": 1, "search": term}).encode())
    parser = _CatalogRows()
    parser.feed(html.decode("utf-8", errors="replace"))
    candidates = []
    for row in parser.rows:
        title = row["attrs"].get("data-title", "")
        button = next((item for item in row["buttons"] if item.get("data-url")), None)
        page = next((item.get("href") for item in row["links"] if item.get("href", "").startswith("/song/")), None)
        if title and button and page:
            candidates.append(_catalog_candidate(title, row["attrs"].get("data-artist", ""), "MIDI Collection",
                              urljoin(actual_url, page), urljoin(actual_url, button["data-url"]),
                              all_terms, aliases, original_query))
    return candidates


def _mutopia_search(term, all_terms, aliases, original_query):
    query_url = BASE_URL + "cgibin/make-table.cgi?" + urlencode({
        "searchingfor": term, "Instrument": "Piano", "solo": "1"})
    html, actual_url = _fetch(query_url, MAX_HTML_BYTES)
    parser = _MutopiaTableParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    candidates = []
    for table in parser.tables:
        cells, links = table["cells"], table["links"]
        midi = next((link for link in links if urlsplit(link["href"]).path.lower().endswith((".mid", ".midi"))), None)
        info = next((link for link in links if "piece-info.cgi?" in link["href"]), None)
        license_link = next((link for link in links if "legal.html" in link["href"]), None)
        if not midi or len(cells) < 5:
            continue
        title = cells[0]
        composer = re.sub(r"^by\s+", "", cells[1], flags=re.I)
        instrument = re.sub(r"^for\s+", "", cells[4], flags=re.I)
        opus = cells[2]
        solo = _normal(instrument) in ("piano", "pianoforte", "solo piano")
        similarity = max(_canonical_similarity(value, title, opus, composer, original_query) for value in all_terms)
        # Common Chinese titles identify specific works. Preserve that identity
        # when the site's broad text search also returns other canons/sonatas.
        canonical = _normal(original_query)
        required_composer = None
        required_opus = ()
        if "卡农" in original_query:
            required_composer = "pachelbel"
        elif "月光奏鸣曲" in original_query or "moonlight sonata" in canonical:
            required_composer, required_opus = "beethoven", ("27", "2")
        elif any(alias in original_query for alias in ("致爱丽丝", "献给爱丽丝")):
            required_composer = "beethoven"
        if required_composer and required_composer not in _normal(composer):
            similarity = min(similarity, .3)
        if required_opus and not set(required_opus).issubset(set(_normal(opus).split())):
            similarity = min(similarity, .3)
        author_words = {word for word in _normal(composer).split() if len(word) >= 3}
        query_words = {word for value in all_terms for word in _normal(value).split()}
        composer_match = bool(author_words & query_words)
        score = min(1.0, similarity * .88 + (0.10 if solo else 0.02) + (0.02 if composer_match else 0.0))
        license_name = license_link["text"] if license_link else "unknown"
        midi_url = urljoin(actual_url, midi["href"])
        page_url = urljoin(actual_url, info["href"]) if info else actual_url
        candidates.append({"title": title, "composer": composer, "provider": "Mutopia Project",
                           "license": license_name, "license_url": urljoin(actual_url, license_link["href"]) if license_link else None,
                           "page_url": page_url, "midi_url": midi_url,
                           "match_score": round(score, 6), "title_similarity": round(similarity, 6),
                           "instrument": instrument, "piano_solo": solo,
                           "composer_match": composer_match, "opus": opus,
                           "query": original_query, "search_terms": all_terms,
                           "query_aliases_used": aliases, "search_url": actual_url})
    return candidates


def search(query):
    """Search the live catalogs; a missing or broken source cannot hide the others."""
    terms, aliases = _query_variants(query)
    candidates = {}
    failures = []

    def lookup(provider):
        entries, errors = {}, []
        for term in terms[:4]:
            try:
                found = provider(term, terms, aliases, query.strip())
            except MidiSourceError as exc:
                errors.append(str(exc))
                continue
            for candidate in found:
                old = entries.get(candidate["midi_url"])
                if old is None or candidate["match_score"] > old["match_score"]:
                    entries[candidate["midi_url"]] = candidate
            if any(c["piano_solo"] and c["title_similarity"] >= .9 and c["match_score"] >= .9
                   for c in entries.values()):
                break
        return entries, errors

    providers = (_ichigo_search, _mutopia_search, _eightnotes_search, _midiworld_search, _collection_search)
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        for entries, errors in pool.map(lookup, providers):
            candidates.update(entries)
            failures.extend(errors)
    if not candidates and failures:
        raise MidiSourceError(failures[0])
    ranked = sorted(candidates.values(), key=lambda c: (-c["match_score"], -c["title_similarity"], c["title"], c["midi_url"]))
    counts, shortlist = {}, []
    for candidate in ranked:
        name = candidate["provider"]
        if counts.get(name, 0) < 3:
            shortlist.append(candidate)
            counts[name] = counts.get(name, 0) + 1
    return shortlist


def _validate_midi(data):
    if len(data) > MAX_MIDI_BYTES or len(data) < 22 or data[:4] != b"MThd":
        raise MidiSourceError("下载内容不是有效 MIDI，或超过 2 MB。")
    header_length = int.from_bytes(data[4:8], "big")
    if header_length < 6 or 8 + header_length + 8 > len(data):
        raise MidiSourceError("MIDI 文件头长度无效。")
    kind, tracks, division = struct.unpack(">HHH", data[8:14])
    if kind not in (0, 1) or tracks < 1 or division == 0:
        raise MidiSourceError("MIDI 类型、轨道数或时钟无效；支持 type 0/1。")
    if kind == 0 and tracks != 1:
        raise MidiSourceError("MIDI type 0 必须只有一个轨道。")
    position = 8 + header_length
    for _ in range(tracks):
        if position + 8 > len(data) or data[position:position + 4] != b"MTrk":
            raise MidiSourceError("MIDI 轨道块无效。")
        size = int.from_bytes(data[position + 4:position + 8], "big")
        position += 8 + size
        if position > len(data):
            raise MidiSourceError("MIDI 轨道数据被截断。")
    return {"format": kind, "tracks": tracks, "division": division}


def _validate_piano(data):
    """Archives contain bands as well as piano; inspect sounding instruments."""
    import mido
    try:
        midi = mido.MidiFile(file=io.BytesIO(data))
        programs = [0] * 16
        notes = 0
        for message in mido.merge_tracks(midi.tracks):
            if message.type == "program_change":
                programs[message.channel] = message.program
            elif message.type == "note_on" and message.velocity:
                if message.channel == 9 or programs[message.channel] not in range(8):
                    raise MidiSourceError("该版本包含其他乐器，继续寻找钢琴独奏版本。")
                notes += 1
        if not notes:
            raise MidiSourceError("该文件没有可练习的钢琴音符。")
        return {"piano_notes": notes}
    except (OSError, ValueError, EOFError, KeyError) as exc:
        if isinstance(exc, MidiSourceError):
            raise
        raise MidiSourceError("无法读取该版本的钢琴音轨。") from exc


def download_best(query, directory, progress=None):
    """Download the best sufficiently relevant solo-piano result, without execution."""
    if progress:
        progress("正在搜索 5 个在线曲谱来源…")
    candidates = search(query)
    eligible = [c for c in candidates if (c["piano_solo"] or c.get("requires_piano_check"))
                and c["title_similarity"] >= .62 and c["match_score"] >= .70]
    if not eligible:
        raise MidiSourceError("本机及在线曲库暂未找到匹配的钢琴曲谱。可补充完整曲名，或导入音乐文件自动转谱。")
    errors = []
    attempts = {}
    # Try independent sources even when an earlier high-scoring link is broken.
    for candidate in eligible:
        provider = candidate["provider"]
        if attempts.get(provider, 0) >= 3:
            continue
        attempts[provider] = attempts.get(provider, 0) + 1
        if progress:
            progress(f"正在下载 {candidate['title']}（{candidate['provider']}）…")
        try:
            data, actual_url = _fetch(candidate["midi_url"], MAX_MIDI_BYTES)
            midi_info = _validate_midi(data)
            if candidate.get("requires_piano_check"):
                midi_info.update(_validate_piano(data))
        except MidiSourceError as exc:
            errors.append(str(exc))
            continue
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        slug = re.sub(r"[^\w\-]+", "-", _normal(candidate["title"]))[:60].strip("-") or "practice"
        target = directory / f"{slug}-{digest[:12]}.mid"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".midi-", suffix=".part", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if progress:
            progress("MIDI 已验证，正在准备自动分手与指法…")
        return {**candidate, "piano_solo": True, "instrument": "Piano", "path": target, "midi_url": actual_url,
                "original_midi_url": candidate["midi_url"], "sha256": digest,
                "bytes": len(data), "midi_header": midi_info, "candidates": candidates}
    raise MidiSourceError("匹配曲目的 MIDI 暂时无法下载：" + "; ".join(dict.fromkeys(errors)))
