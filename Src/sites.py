import html
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


SOURCE_ORDER = (
    "danbooru", "konachan", "yandere", "sakugabooru", "safebooru", "gelbooru",
)

SOURCE_INFO = {
    "danbooru": {
        "name": "Danbooru",
        "default": True,
        "needs_key": False,
        "base": "https://danbooru.donmai.us",
    },
    "konachan": {
        "name": "Konachan",
        "default": True,
        "needs_key": False,
        "base": "https://konachan.com",
    },
    "yandere": {
        "name": "Yande.re",
        "default": True,
        "needs_key": False,
        "base": "https://yande.re",
    },
    "sakugabooru": {
        "name": "Sakugabooru",
        "default": True,
        "needs_key": False,
        "base": "https://www.sakugabooru.com",
    },
    "safebooru": {
        "name": "Safebooru",
        "default": False,
        "needs_key": False,
        "base": "https://safebooru.org",
    },
    "gelbooru": {
        "name": "Gelbooru",
        "default": False,
        "needs_key": True,
        "base": "https://gelbooru.com",
    },
}

DEFAULT_SOURCES = {
    key: info["default"] for key, info in SOURCE_INFO.items()
}

IMAGE_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "mp4", "webm",
}

DANBOORU_ONLY_EXCLUSIONS = (
    "is:", "status:", "user:", "approver:", "commenter:", "note:",
    "pool:", "arttags:", "chartags:", "copytags:", "gentags:",
    "metatags:", "upvote:",
)

MOE_META_PREFIXES = (
    "order:", "score:", "date:", "id:", "width:", "height:", "mpixels:",
    "ratio:", "filesize:", "filetype:", "md5:", "tagcount:",
)


def site_name(key):
    return SOURCE_INFO.get(key, {}).get("name", key or "Danbooru")


def post_key(post):
    site = (post or {}).get("site") or "danbooru"
    return f"{site}:{(post or {}).get('id')}"


def post_signature(post):
    md5 = ((post or {}).get("md5") or "").strip().lower()
    if md5:
        return "md5:" + md5
    for field in ("file_url", "large_file_url", "preview_file_url"):
        url = (post or {}).get(field)
        if url:
            return "url:" + _normalize_url(url)
    return "id:" + post_key(post)


def _normalize_url(url):
    text = html.unescape(str(url or "")).strip().lower()
    text = text.split("#", 1)[0].split("?", 1)[0]
    return text.rstrip("/")


def _ext_from_url(url):
    path = str(url or "").split("?", 1)[0].split("#", 1)[0]
    if "." not in path:
        return ""
    ext = path.rsplit(".", 1)[-1].lower()
    return ext if ext in IMAGE_EXTENSIONS else ""


def _to_iso(value):
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                float(value), timezone.utc).replace(tzinfo=None).isoformat()
        except Exception:
            return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        try:
            return datetime.fromtimestamp(
                int(text), timezone.utc).replace(tzinfo=None).isoformat()
        except Exception:
            return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None).isoformat()
    except Exception:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        return parsed.replace(tzinfo=None).isoformat()
    except Exception:
        return ""


def _safe_rating(value):
    rating = str(value or "").strip().lower()
    if rating in ("g", "general", "s", "safe"):
        return "g"
    return rating


def _clean_tags(value):
    text = html.unescape(html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _base_post(site, raw):
    return {
        "id": raw.get("id"),
        "site": site,
        "site_name": site_name(site),
        "rating": "",
        "tag_string": "",
        "tag_string_general": "",
        "tag_string_character": "",
        "tag_string_copyright": "",
        "tag_string_artist": "",
        "tag_string_meta": "",
        "score": 0,
        "image_width": 0,
        "image_height": 0,
        "file_url": "",
        "preview_file_url": "",
        "large_file_url": "",
        "file_ext": "",
        "file_size": 0,
        "md5": "",
        "source": "",
        "created_at": "",
        "page_url": "",
        "media_asset": {},
    }


def _normalize_danbooru(raw):
    post = _base_post("danbooru", raw)
    media = raw.get("media_asset") or {}
    tags = _clean_tags(raw.get("tag_string"))
    post["rating"] = _safe_rating(raw.get("rating"))
    post["tag_string"] = tags
    post["tag_string_general"] = _clean_tags(raw.get("tag_string_general"))
    post["tag_string_character"] = _clean_tags(raw.get("tag_string_character"))
    post["tag_string_copyright"] = _clean_tags(raw.get("tag_string_copyright"))
    post["tag_string_artist"] = _clean_tags(raw.get("tag_string_artist"))
    post["tag_string_meta"] = _clean_tags(raw.get("tag_string_meta"))
    if not post["tag_string"]:
        post["tag_string"] = " ".join(filter(None, (
            post["tag_string_artist"], post["tag_string_character"],
            post["tag_string_copyright"], post["tag_string_general"],
            post["tag_string_meta"],
        )))
    post["score"] = int(raw.get("score") or 0)
    post["image_width"] = int(
        raw.get("image_width") or media.get("image_width") or 0)
    post["image_height"] = int(
        raw.get("image_height") or media.get("image_height") or 0)
    post["file_url"] = raw.get("file_url") or raw.get("large_file_url") or ""
    post["preview_file_url"] = (
        raw.get("preview_file_url") or raw.get("preview_url") or "")
    post["large_file_url"] = (
        raw.get("large_file_url") or post["file_url"])
    post["file_ext"] = (
        raw.get("file_ext") or _ext_from_url(post["file_url"])).lower()
    post["file_size"] = int(
        media.get("file_size") or raw.get("file_size") or 0)
    post["md5"] = (
        raw.get("md5") or media.get("md5") or "").lower()
    post["source"] = raw.get("source") or ""
    post["created_at"] = _to_iso(raw.get("created_at"))
    post["page_url"] = (
        f"https://danbooru.donmai.us/posts/{raw.get('id')}")
    post["media_asset"] = media
    if raw.get("is_deleted") or raw.get("is_banned"):
        return None
    return post


def _normalize_moebooru(site, raw):
    if raw.get("is_pending") or raw.get("status") == "deleted":
        return None
    post = _base_post(site, raw)
    tags = _clean_tags(raw.get("tags"))
    post["rating"] = _safe_rating(raw.get("rating"))
    post["tag_string"] = tags
    post["tag_string_general"] = tags
    post["score"] = int(raw.get("score") or 0)
    post["image_width"] = int(raw.get("width") or 0)
    post["image_height"] = int(raw.get("height") or 0)
    post["file_url"] = (
        raw.get("file_url") or raw.get("jpeg_url") or "")
    post["preview_file_url"] = (
        raw.get("preview_url") or raw.get("jpeg_url") or "")
    post["large_file_url"] = (
        raw.get("sample_url") or raw.get("jpeg_url") or post["file_url"])
    post["file_ext"] = (
        raw.get("file_ext") or _ext_from_url(post["file_url"])).lower()
    post["file_size"] = int(raw.get("file_size") or 0)
    post["md5"] = (raw.get("md5") or "").lower()
    post["source"] = raw.get("source") or ""
    post["created_at"] = _to_iso(
        raw.get("created_at") or raw.get("updated_at"))
    post["page_url"] = (
        f"{SOURCE_INFO[site]['base']}/post/show/{raw.get('id')}")
    post["media_asset"] = {"file_size": post["file_size"]}
    return post


def _normalize_gelbooru(site, raw):
    if raw.get("status") == "deleted":
        return None
    post = _base_post(site, raw)
    tags = _clean_tags(raw.get("tags"))
    post["rating"] = _safe_rating(raw.get("rating"))
    post["tag_string"] = tags
    post["tag_string_general"] = tags
    post["score"] = int(raw.get("score") or 0)
    post["image_width"] = int(raw.get("width") or 0)
    post["image_height"] = int(raw.get("height") or 0)
    post["file_url"] = (
        raw.get("file_url") or raw.get("sample_url") or "")
    post["preview_file_url"] = raw.get("preview_url") or ""
    post["large_file_url"] = (
        raw.get("sample_url") or post["file_url"])
    post["file_ext"] = (
        raw.get("file_ext") or _ext_from_url(raw.get("image"))
        or _ext_from_url(post["file_url"])).lower()
    post["file_size"] = int(raw.get("file_size") or 0)
    post["md5"] = (
        raw.get("md5") or raw.get("hash") or "").lower()
    post["source"] = raw.get("source") or ""
    post["created_at"] = _to_iso(
        raw.get("created_at") or raw.get("change"))
    if site == "gelbooru":
        post["page_url"] = (
            "https://gelbooru.com/index.php?page=post&s=view&id="
            f"{raw.get('id')}")
    else:
        post["page_url"] = (
            "https://safebooru.org/index.php?page=post&s=view&id="
            f"{raw.get('id')}")
    post["media_asset"] = {"file_size": post["file_size"]}
    return post


def _tokens(tags):
    import downloader
    clean = []
    for token in (tags or "").split():
        if downloader.is_hard_blocked_tag_name(token):
            continue
        low = token.lower()
        if low.startswith("rating:"):
            continue
        if low in downloader.config.BLACKLIST_TAGS:
            continue
        clean.append(token)
    return clean


def _all_tokens_blocked(tags):
    import downloader
    saw_token = False
    for token in (tags or "").split():
        saw_token = True
        low = token.lower()
        if low.startswith("rating:") or ":" in token:
            return False
        if token.startswith(("-", "~")) or "*" in token:
            return False
        if downloader.is_hard_blocked_tag_name(token):
            continue
        if low in downloader.config.BLACKLIST_TAGS:
            continue
        return False
    return saw_token


def _query_tokens(tags, allowed_prefixes, rating_tag):
    out = []
    for token in _tokens(tags):
        low = token.lower()
        if low.startswith("-"):
            if low[1:].startswith(DANBOORU_ONLY_EXCLUSIONS):
                continue
            out.append(token)
            continue
        if ":" in token:
            if low.startswith(allowed_prefixes):
                out.append(token)
            elif low == "order:score":
                out.append("sort:score")
            continue
        out.append(token)
    out.append(rating_tag)
    return " ".join(out)


def _get(url, params, browser=False):
    import downloader
    headers = {"User-Agent": _BROWSER_UA} if browser else None
    return downloader.http_get(
        url, params=params, headers=headers,
        timeout=downloader.config.REQUEST_TIMEOUT,
        max_attempts=1, max_retry_delay=2.0)


class _Adapter:
    key = ""
    api_url = ""
    max_limit = 100
    rating_tag = ""

    def fetch(self, tags, limit, page):
        raise NotImplementedError


class DanbooruAdapter(_Adapter):
    key = "danbooru"
    api_url = "https://danbooru.donmai.us/posts.json"
    max_limit = 200
    rating_tag = "rating:general"

    def fetch(self, tags, limit, page):
        import downloader
        query = downloader.sanitize_sfw_query(tags)
        if not query:
            return [], ""
        params = {
            "tags": query,
            "limit": min(limit, self.max_limit),
            "page": page,
        }
        username = downloader.config.USERNAME
        api_key = downloader.config.API_KEY
        if username and username not in ("", "your_danbooru_name"):
            params["login"] = username
        if api_key and api_key not in ("", "your_danbooru_account_api"):
            params["api_key"] = api_key
        response = _get(self.api_url, params)
        note = ""
        if response.status_code == 422:
            try:
                error = response.json().get("error")
            except Exception:
                error = ""
            if error == "PostQuery::TagLimitError":
                plain, meta = downloader.split_search_tags(tags)
                base = plain[:2] if len(plain) > 1 else plain[:1]
                fallback_meta = [
                    token for token in meta
                    if not token.startswith(("-", "~"))
                    and not token.lower().startswith("order:")
                    and "*" not in token
                ]
                params["tags"] = downloader.sanitize_sfw_query(
                    " ".join(base + fallback_meta))
                response = _get(self.api_url, params)
                note = ("Danbooru limits searches to 2 tags; "
                        "filtering locally.")
        if response.status_code == 410:
            return [], note
        if response.status_code == 401:
            raise RuntimeError("Danbooru rejected the API credentials.")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = []
        posts = [p for p in (_normalize_danbooru(raw) for raw in data) if p]
        return posts, note


class MoebooruAdapter(_Adapter):
    def __init__(self, key):
        self.key = key
        self.api_url = SOURCE_INFO[key]["base"] + "/post.json"
        self.max_limit = 100
        self.rating_tag = "rating:safe"

    def fetch(self, tags, limit, page):
        import downloader
        query = _query_tokens(tags, MOE_META_PREFIXES, self.rating_tag)
        response = _get(self.api_url, {
            "tags": query,
            "limit": min(limit, self.max_limit),
            "page": page,
        }, browser=True)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = []
        posts = [
            p for p in (_normalize_moebooru(self.key, raw) for raw in data) if p
        ]
        return posts, ""


class GelbooruAdapter(_Adapter):
    def __init__(self, key):
        self.key = key
        self.api_url = SOURCE_INFO[key]["base"] + "/index.php"
        self.max_limit = 100
        self.rating_tag = (
            "rating:general" if key == "gelbooru" else "rating:safe")

    def fetch(self, tags, limit, page):
        import downloader
        query = _query_tokens(tags, (), self.rating_tag)
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "limit": min(limit, self.max_limit),
            "pid": max(0, page - 1),
            "tags": query,
        }
        if self.key == "gelbooru":
            api_key = (getattr(downloader.config, "GELBOORU_API_KEY", "")
                       or "").strip()
            user_id = (getattr(downloader.config, "GELBOORU_USER_ID", "")
                       or "").strip()
            if not api_key or not user_id:
                raise RuntimeError(
                    "Needs an API key and user ID. Add them in Settings.")
            params["api_key"] = api_key
            params["user_id"] = user_id
        response = _get(self.api_url, params, browser=True)
        if response.status_code == 401:
            raise RuntimeError(
                "Rejected the API key or user ID. Check both and make sure "
                "API access is enabled in your Gelbooru account options.")
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error") or data.get("message")
            if error:
                raise RuntimeError(f"Gelbooru: {error}")
            data = data.get("post") or []
        if not isinstance(data, list):
            data = []
        posts = [
            p for p in (_normalize_gelbooru(self.key, raw) for raw in data) if p
        ]
        return posts, ""


ADAPTERS = {
    "danbooru": DanbooruAdapter(),
    "konachan": MoebooruAdapter("konachan"),
    "yandere": MoebooruAdapter("yandere"),
    "sakugabooru": MoebooruAdapter("sakugabooru"),
    "safebooru": GelbooruAdapter("safebooru"),
    "gelbooru": GelbooruAdapter("gelbooru"),
}


def enabled_sources():
    import downloader
    configured = getattr(downloader.config, "SOURCES", None) or {}
    return [
        key for key in SOURCE_ORDER
        if bool(configured.get(key, DEFAULT_SOURCES[key]))
    ]


def source_status(key):
    import downloader
    configured = getattr(downloader.config, "SOURCES", None) or {}
    if not bool(configured.get(key, DEFAULT_SOURCES[key])):
        return "Off"
    if SOURCE_INFO[key]["needs_key"]:
        api_key = (getattr(downloader.config, "GELBOORU_API_KEY", "")
                   or "").strip()
        user_id = (getattr(downloader.config, "GELBOORU_USER_ID", "")
                   or "").strip()
        if not api_key or not user_id:
            return "Needs API key"
    return "Ready"


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def _to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _tag_category(type_id):
    import downloader
    return downloader.TAG_CATEGORIES.get(_to_int(type_id), "General")


def _tag_entry(name, count, type_id):
    return {
        "value": name,
        "label": name,
        "category": _to_int(type_id),
        "category_name": _tag_category(type_id),
        "post_count": _to_int(count),
        "is_autocorrect": False,
        "antecedent": "",
    }


def _parse_tag_items(response):
    try:
        data = response.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        error = data.get("error") or data.get("message")
        if error:
            raise RuntimeError(str(error))
        data = data.get("tag") or data.get("tags") or []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    text = (response.text or "").strip()
    if text.startswith("<"):
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(text)
            return [dict(element.attrib) for element in root.findall("tag")]
        except Exception:
            return []
    return []


def _tag_items(key, query, pattern=False):
    import downloader
    if key in ("konachan", "yandere", "sakugabooru"):
        url = SOURCE_INFO[key]["base"] + "/tag.json"
        response = downloader.http_get(
            url, params={"name": query, "limit": 20}, timeout=6,
            max_attempts=0, headers={"User-Agent": _BROWSER_UA})
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    if key in ("safebooru", "gelbooru"):
        url = SOURCE_INFO[key]["base"] + "/index.php"
        params = {
            "page": "dapi",
            "s": "tag",
            "q": "index",
            "json": "1",
            "limit": 20,
        }
        if pattern:
            params["name_pattern"] = query
        else:
            params["name"] = query
        if key == "gelbooru":
            api_key = (getattr(downloader.config, "GELBOORU_API_KEY", "")
                       or "").strip()
            user_id = (getattr(downloader.config, "GELBOORU_USER_ID", "")
                       or "").strip()
            if not api_key or not user_id:
                raise RuntimeError("Gelbooru needs an API key and user ID.")
            params["api_key"] = api_key
            params["user_id"] = user_id
        response = downloader.http_get(
            url, params=params, timeout=8, max_attempts=0,
            headers={"User-Agent": _BROWSER_UA})
        if response.status_code == 401:
            raise RuntimeError("Gelbooru rejected the API key or user ID.")
        response.raise_for_status()
        return _parse_tag_items(response)
    return []


def tag_lookup(key, query, limit=10):
    query = (query or "").strip().lower()
    if not query:
        return None, []
    items = _tag_items(key, query, pattern=False)
    exact = None
    suggestions = []
    seen = set()
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        count = _to_int(item.get("count"))
        type_id = _to_int(item.get("type"))
        if name.lower() == query:
            exact = _tag_entry(name, count, type_id)
        if name.lower().startswith(query) and name.lower() not in seen:
            seen.add(name.lower())
            suggestions.append(_tag_entry(name, count, type_id))

    if key in ("safebooru", "gelbooru") and len(suggestions) < limit:
        try:
            for item in _tag_items(key, query, pattern=True):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                count = _to_int(item.get("count"))
                type_id = _to_int(item.get("type"))
                if name.lower() == query and exact is None:
                    exact = _tag_entry(name, count, type_id)
                if name.lower().startswith(query) and name.lower() not in seen:
                    seen.add(name.lower())
                    suggestions.append(_tag_entry(name, count, type_id))
        except Exception:
            pass

    suggestions = suggestions[:max(1, int(limit))]
    if exact is not None:
        details = {
            "exists": True,
            "name": query,
            "post_count": exact["post_count"],
            "category": exact["category"],
            "category_name": exact["category_name"],
            "is_filter": False,
            "is_deprecated": False,
            "suggestion": None,
            "suggestion_count": 0,
            "suggestion_category": 0,
            "is_autocorrect": False,
            "source": site_name(key),
        }
    else:
        top = suggestions[0] if suggestions else None
        details = {
            "exists": False,
            "name": query,
            "post_count": 0,
            "category": 0,
            "category_name": "General",
            "is_filter": False,
            "is_deprecated": False,
            "suggestion": top["value"] if top else None,
            "suggestion_count": top["post_count"] if top else 0,
            "suggestion_category": top["category"] if top else 0,
            "is_autocorrect": False,
            "source": site_name(key),
        }
    return details, suggestions


def test_gelbooru(api_key, user_id):
    import downloader
    api_key = (api_key or "").strip()
    user_id = (user_id or "").strip()
    if not api_key or not user_id:
        return False, "Gelbooru needs an API key and user ID."
    try:
        response = downloader.http_get(
            "https://gelbooru.com/index.php",
            params={
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "limit": 1,
                "tags": "rating:general",
                "api_key": api_key,
                "user_id": user_id,
            },
            timeout=15, max_attempts=0,
            headers={"User-Agent": _BROWSER_UA})
    except Exception as exc:
        return False, f"Connection failed: {_short_error(exc)}"
    if response.status_code == 401:
        return False, ("Gelbooru rejected the API key or user ID. "
                       "Check both and make sure API access is enabled "
                       "in your Gelbooru account options.")
    if response.status_code != 200:
        return False, f"Gelbooru returned HTTP {response.status_code}."
    try:
        data = response.json()
    except Exception:
        return False, "Gelbooru returned a non-JSON response."
    if isinstance(data, dict):
        error = data.get("error") or data.get("message")
        if error:
            return False, str(error)
        posts = data.get("post") or []
    elif isinstance(data, list):
        posts = data
    else:
        posts = []
    if posts:
        return True, "Gelbooru API works."
    return True, "Gelbooru API responded, but returned no posts."


def _short_error(exc):
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return f"HTTP {status}"
    text = str(exc).strip()
    if not text:
        text = type(exc).__name__
    return text[:120]


def _keep_post(post, tags):
    import downloader
    if not post or not post.get("id") or not post.get("file_url"):
        return False
    if post.get("rating") != "g":
        return False
    if downloader.hard_block_reason(post):
        return False
    post_tags = set((post.get("tag_string") or "").split())
    if downloader.config.BLACKLIST_TAGS and (
            post_tags & downloader.config.BLACKLIST_TAGS):
        return False
    plain, _ = downloader.split_search_tags(tags)
    required = {tag.lower() for tag in plain}
    excluded = set(downloader.get_excluded_tags(tags))
    wildcards = set(downloader.get_wildcard_tags(tags))
    matched, _ = downloader.post_matches_tags(
        post, required, excluded, wildcards)
    return matched


def _interleave(buckets, keys):
    out = []
    positions = {key: 0 for key in keys}
    while True:
        added = False
        for key in keys:
            bucket = buckets.get(key) or []
            index = positions[key]
            if index < len(bucket):
                out.append(bucket[index])
                positions[key] = index + 1
                added = True
        if not added:
            break
    return out


_DEDUPE_LOCK = threading.Lock()
_DEDUPE = {}
_PAGE_LOCK = threading.Lock()
_PAGE_LOCKS = {}
_PAGE_CACHE = {}
_PAGE_CACHE_LIMIT = 40


def _dedupe(posts, session, query, reset):
    with _DEDUPE_LOCK:
        state = _DEDUPE.get(session)
        if state is None or reset or state.get("query") != query:
            state = {"query": query, "seen": set()}
            _DEDUPE[session] = state
            if len(_DEDUPE) > 12:
                for old in list(_DEDUPE)[:-6]:
                    _DEDUPE.pop(old, None)
        seen = state["seen"]
        out = []
        for post in posts:
            signature = post_signature(post)
            if signature in seen:
                continue
            seen.add(signature)
            out.append(post)
        if len(seen) > 50000:
            state["seen"] = set(list(seen)[-25000:])
        return out


def _page_mutex(key):
    with _PAGE_LOCK:
        lock = _PAGE_LOCKS.get(key)
        if lock is None:
            if len(_PAGE_LOCKS) > 500:
                _PAGE_LOCKS.clear()
            lock = threading.Lock()
            _PAGE_LOCKS[key] = lock
        return lock


def _clear_page_cache(session):
    with _PAGE_LOCK:
        for key in [k for k in _PAGE_CACHE if k[0] == session]:
            _PAGE_CACHE.pop(key, None)


def _store_page(key, result):
    with _PAGE_LOCK:
        _PAGE_CACHE[key] = result
        while len(_PAGE_CACHE) > _PAGE_CACHE_LIMIT:
            _PAGE_CACHE.pop(next(iter(_PAGE_CACHE)))


def fetch_combined(tags, limit=40, page=1, session="preview", reset=False):
    if not (tags or "").strip():
        return [], "", False, None
    keys = enabled_sources()
    if not keys:
        return [], "No sources enabled.", False, None
    if _all_tokens_blocked(tags):
        return [], "All of those tags are permanently blocked.", False, None

    page = max(1, int(page))
    limit = max(1, int(limit))
    if reset:
        _clear_page_cache(session)
    cache_key = (session, tags, page, limit)
    with _page_mutex(cache_key):
        cached = _PAGE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        result = _fetch_combined_uncached(
            tags, limit, page, session, reset, keys)
        _store_page(cache_key, result)
        return result


def _fetch_combined_uncached(tags, limit, page, session, reset, keys):
    per_site = max(1, limit // max(1, len(keys)))
    results = {}
    raw_counts = {}
    notes = []
    ok_count = 0

    with ThreadPoolExecutor(
            max_workers=len(keys), thread_name_prefix="SRC") as pool:
        futures = {
            pool.submit(ADAPTERS[key].fetch, tags, per_site, page): key
            for key in keys
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                posts, note = future.result()
                ok_count += 1
                raw_counts[key] = len(posts)
                results[key] = posts
                if note:
                    notes.append(note)
            except Exception as exc:
                raw_counts[key] = 0
                results[key] = []
                notes.append(f"{SOURCE_INFO[key]['name']}: "
                             f"{_short_error(exc)}")

    if ok_count == 0:
        raise RuntimeError("; ".join(notes) or "All sources failed.")

    kept = {
        key: [p for p in results.get(key, []) if _keep_post(p, tags)]
        for key in keys
    }
    merged = _interleave(kept, keys)
    merged = _dedupe(merged, session, tags, reset)
    has_more = any(raw_counts.get(key, 0) >= per_site for key in keys)
    next_raw = page + 1 if has_more else None
    note = " · ".join(dict.fromkeys(notes))
    return merged, note, has_more, next_raw


def fetch_download_page(tags, page, limit, reset=False):
    return fetch_combined(
        tags, limit=limit, page=page, session="download", reset=reset)
