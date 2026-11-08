import os
import time
import re
import json
import hashlib
import fnmatch
from PIL import Image
from io import BytesIO
from http.client import IncompleteRead
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from os import cpu_count
import argparse
import sys
from pathlib import Path

import requests as std_requests
try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

import sites

if curl_requests is not None:
    from curl_cffi.requests.errors import RequestsError as CurlRequestsError
    RequestExceptions = (std_requests.RequestException, CurlRequestsError)
else:
    RequestExceptions = (std_requests.RequestException,)

def get_user_agent():
    try:
        cfg = globals().get("config")
        if cfg and hasattr(cfg, "USERNAME"):
            username = cfg.USERNAME
        else:
            username = None
    except Exception:
        username = None
        
    if username and username not in ("", "your_danbooru_name", "your_danbooru_account_api"):
        return f"DanbooruDownloader/1.0 (by {username})"
    return "DanbooruDownloader/1.0"

def http_get(url, params=None, max_attempts=2, max_retry_delay=30.0, **kwargs):
    headers = kwargs.pop("headers", None) or {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = get_user_agent()
    kwargs["headers"] = headers

    attempts = 0
    while True:
        if curl_requests is not None:
            response = curl_requests.get(url, params=params, impersonate="chrome", **kwargs)
        else:
            response = std_requests.get(url, params=params, **kwargs)

        status = getattr(response, "status_code", 0)
        if status in (429, 500, 502, 503) and attempts < max_attempts:
            delay = 2.0 * (attempts + 1)
            try:
                ra = response.headers.get("Retry-After")
                if ra:
                    delay = max(delay, float(ra))
            except Exception:
                pass
            delay = min(delay, max_retry_delay)
            logging.warning(f"⏳ {status} from server - retrying in {delay:.0f}s "
                            f"({url if len(str(url)) < 80 else '...'})")
            time.sleep(delay)
            attempts += 1
            continue
        return response

def http_head(url, **kwargs):
    headers = kwargs.get("headers", {})
    if "User-Agent" not in headers:
        headers["User-Agent"] = get_user_agent()
        kwargs["headers"] = headers
    
    if curl_requests is not None:
        return curl_requests.head(url, impersonate="chrome", **kwargs)
    else:
        return std_requests.head(url, **kwargs)



API_URL = "https://danbooru.donmai.us/posts.json"

TAG_CATEGORIES = {
    0: "General",
    1: "Artist",
    3: "Copyright",
    4: "Character",
    5: "Meta"
}

FILTER_PREFIXES = (
    'order:', 'rating:', 'score:', 'id:', 'favcount:', 'date:', 'age:',
    'status:', 'parent:', 'source:', 'user:', 'approver:', 'commenter:',
    'width:', 'height:', 'mpixels:', 'ratio:', 'filesize:', 'filetype:',
    'md5:', 'tagcount:', 'arttags:', 'chartags:', 'copytags:', 'gentags:',
    'metatags:', 'pool:', 'note:', 'upvote:'
)

def fetch_tag_suggestions(query, limit=10):
    if not query or not query.strip():
        return []
    query = query.strip()
    try:
        url = "https://danbooru.donmai.us/autocomplete.json"
        params = {
            "search[query]": query,
            "search[type]": "tag_query",
            "version": "1",
            "limit": limit
        }
        resp = http_get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for item in data[:limit]:
                val = item.get("value", "")
                label = item.get("label", val)
                cat = item.get("category", 0)
                count = item.get("post_count", 0)
                is_autocorrect = item.get("type") == "tag-autocorrect"
                antecedent = item.get("antecedent", "")
                results.append({
                    "value": val,
                    "label": label,
                    "category": cat,
                    "category_name": TAG_CATEGORIES.get(cat, "General"),
                    "post_count": count,
                    "is_autocorrect": is_autocorrect,
                    "antecedent": antecedent
                })
            return results
    except Exception as e:
        logging.debug(f"fetch_tag_suggestions error: {e}")
    return []

def check_tag_details(tag_name):
    if not tag_name or not tag_name.strip():
        return {"exists": False, "name": tag_name, "post_count": 0, "category": 0, "is_filter": False}
    
    tag = tag_name.strip().lower()
    for prefix in FILTER_PREFIXES:
        if tag.startswith(prefix):
            return {
                "exists": True,
                "name": tag,
                "post_count": None,
                "category": 5,
                "category_name": "Filter",
                "is_filter": True
            }
    
    tag_info = {
        "exists": False,
        "name": tag,
        "post_count": 0,
        "category": 0,
        "category_name": "General",
        "is_filter": False,
        "is_deprecated": False,
        "suggestion": None,
        "suggestion_count": 0,
        "suggestion_category": 0,
        "is_autocorrect": False
    }
    
    try:
        url = "https://danbooru.donmai.us/tags.json"
        resp = http_get(url, params={"search[name_matches]": tag}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            for t in data:
                if t.get("name") == tag:
                    tag_info["exists"] = True
                    tag_info["post_count"] = t.get("post_count", 0)
                    tag_info["category"] = t.get("category", 0)
                    tag_info["category_name"] = TAG_CATEGORIES.get(tag_info["category"], "General")
                    tag_info["is_deprecated"] = t.get("is_deprecated", False)
                    break
        
        if not tag_info["exists"] or tag_info["post_count"] == 0:
            auto_url = "https://danbooru.donmai.us/autocomplete.json"
            auto_resp = http_get(auto_url, params={"search[query]": tag, "search[type]": "tag_query", "version": "1"}, timeout=5)
            if auto_resp.status_code == 200:
                auto_data = auto_resp.json()
                for item in auto_data:
                    if item.get("value") == tag:
                        tag_info["exists"] = True
                        tag_info["post_count"] = item.get("post_count", 0)
                        tag_info["category"] = item.get("category", 0)
                        tag_info["category_name"] = TAG_CATEGORIES.get(tag_info["category"], "General")
                        break
                if (not tag_info["exists"] or tag_info["post_count"] == 0) and auto_data:
                    top = auto_data[0]
                    tag_info["suggestion"] = top.get("value")
                    tag_info["suggestion_count"] = top.get("post_count", 0)
                    tag_info["suggestion_category"] = top.get("category", 0)
                    tag_info["is_autocorrect"] = top.get("type") == "tag-autocorrect"
    except Exception as e:
        logging.debug(f"check_tag_details error: {e}")
        
    return tag_info


class Config:
    USERNAME = ""
    API_KEY = ""
    SOURCES = dict(sites.DEFAULT_SOURCES)
    GELBOORU_API_KEY = ""
    GELBOORU_USER_ID = ""
    
    TAGS = "tag1 tag2"
    LIMIT_PER_PAGE = 200
    MAX_PAGES = None
    START_PAGE = 1
    END_PAGE = float('inf')
    
    SAVE_FOLDER_BASE = "danbooru_downloads"
    SAVE_FOLDER_NAME_OPTION = "custom"
    SAVE_FOLDER_CUSTOM_NAME = "my_custom_folder_name"
    SAVE_FOLDER_MAX_LENGTH = 50
    SAVE_FOLDER = None
    
    TAGS_TO_TRIGGER_WORDS = False
    ADD_OWN_TRIGGER_WORDS = ""
    
    INCLUDE_ARTIST_TAGS = False
    INCLUDE_CHARACTER_TAGS = True
    INCLUDE_COPYRIGHT_TAGS = True
    INCLUDE_GENERAL_TAGS = True
    INCLUDE_META_TAGS = False
    BLACKLIST_TAGS = {
        "explicit", "nsfw", "nude", "naked", "nipples", "pussy", "penis", "sex", "hentai",
        "erotic", "topless", "bottomless", "uncensored", "masturbation", "fellatio", "cunnilingus",
        "vaginal", "anal", "oral", "penetration", "ejaculation", "cum", "creampie", "orgasm"
    }
    
    REMOVE_FROM_TXT_FILES = {
    }
    
    MIN_IMAGE_WIDTH = 480
    MIN_IMAGE_HEIGHT = 480
    MAX_IMAGE_WIDTH = 32000
    MAX_IMAGE_HEIGHT = 32000
    MIN_DATE = "1900-01-01"
    MAX_DATE = "2035-12-31"
    MIN_SCORE = None
    MAX_SCORE = None
    MIN_ID = None
    MAX_ID = None
    ALLOWED_RATINGS = {"g"}
    
    MAX_RETRIES = 5
    REQUEST_TIMEOUT = 30
    RATE_LIMIT_DELAY = 1.0
    MAX_WORKERS = max(1, cpu_count() - 1)
    MAX_FILENAME_LENGTH = 220
    MAX_TAGS_IN_FILENAME = 20
    
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "mp4", "webm", "zip"}
    PREFER_ORIGINAL_SIZE = True
    
    RESUME_DOWNLOAD = True
    SAVE_PROGRESS = True
    PROGRESS_FILE = "download_progress.json"
    CANCELLED = False
    PAUSED = False
    TAG_FOLDER_SPACES = True
    ALLOWED_RATINGS = {"g"}
    MAX_DOWNLOADS = None
    SAVE_TXT_TAGS = False
    REQUIRED_TAGS = set()
    EXCLUDED_TAGS = set()
    WILDCARD_TAGS = set()
    
    ON_PREVIEW_CALLBACK = None
    ON_PROGRESS_CALLBACK = None
    ON_STATUS_CALLBACK = None

config = Config()

HARD_BLOCKED_TAG_NAMES = frozenset({
    "loli", "shota", "toddlercon", "babycon", "oppai_loli",
})

HARD_BLOCKED_FRANCHISES = (
    "blue_archive",
    "zenless_zone_zero",
    "azur_lane",
    "strawberry_marshmallow",
    "ichigo_mashimaro",
    "maidragon",
    "nekopara",
    "onii-chan_wa_oshimai",
    "genshin_impact",
    "valorant",
    "league_of_legends",
)


def is_hard_blocked_tag_name(tag: str) -> bool:
    tag = (tag or "").strip().lower()
    if not tag:
        return False
    if tag in HARD_BLOCKED_TAG_NAMES:
        return True
    for franchise in HARD_BLOCKED_FRANCHISES:
        if franchise in tag:
            return True
    return False


def strip_hard_blocked_tags(tags_str: str) -> str:
    kept = [
        token for token in (tags_str or "").split()
        if not is_hard_blocked_tag_name(token)
    ]
    return " ".join(kept)


def hard_block_reason(post) -> str | None:
    tags = (post.get("tag_string", "") or "").split()
    for tag in tags:
        if is_hard_blocked_tag_name(tag):
            return f"hard blocked tag: {tag}"
    return None

def wait_if_paused():
    while getattr(config, "PAUSED", False) and not config.CANCELLED:
        time.sleep(0.15)

def setup_logging():
    if config.SAVE_FOLDER is None:
        config.SAVE_FOLDER = create_save_folder()
    
    log_folder = os.path.join(config.SAVE_FOLDER, "logs")
    os.makedirs(log_folder, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_folder, f"download_{timestamp}.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

def create_save_folder():
    if config.SAVE_FOLDER_NAME_OPTION == "danbooru_downloads":
        folder_name = "danbooru_downloads"
    elif config.SAVE_FOLDER_NAME_OPTION == "custom":
        safe_name = re.sub(r'[^a-zA-Z0-9_ ]', '', config.SAVE_FOLDER_CUSTOM_NAME).strip()
        folder_name = safe_name[:config.SAVE_FOLDER_MAX_LENGTH] if safe_name else "custom_downloads"
    elif config.SAVE_FOLDER_NAME_OPTION == "tags":
        safe_tags = re.sub(r'[^a-zA-Z0-9_]', '', config.TAGS.replace(' ', '_'))
        if getattr(config, "TAG_FOLDER_SPACES", False):
            safe_tags = safe_tags.replace('_', ' ').strip()
        folder_name = safe_tags[:config.SAVE_FOLDER_MAX_LENGTH] if safe_tags else "tag_downloads"
    else:
        folder_name = "danbooru_downloads"
    
    if not config.RESUME_DOWNLOAD:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{folder_name}_{timestamp}"
    
    full_path = os.path.join(config.SAVE_FOLDER_BASE, folder_name)
    os.makedirs(full_path, exist_ok=True)
    return full_path

def load_progress_data():
    if not config.SAVE_PROGRESS or not config.RESUME_DOWNLOAD:
        return set(), set()

    progress_file = os.path.join(config.SAVE_FOLDER, config.PROGRESS_FILE)
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return (
                    set(data.get('downloaded_ids', [])),
                    set(data.get('downloaded_md5s', [])),
                )
        except Exception as e:
            logging.warning(f"Could not load progress file: {e}")
    return set(), set()

def load_progress():
    return load_progress_data()[0]

def save_progress(downloaded_ids, downloaded_md5s=None):
    if not config.SAVE_PROGRESS:
        return

    progress_file = os.path.join(config.SAVE_FOLDER, config.PROGRESS_FILE)
    try:
        progress_data = {
            'downloaded_ids': list(downloaded_ids),
            'downloaded_md5s': list(downloaded_md5s or []),
            'last_update': datetime.now().isoformat(),
            'tags': config.TAGS,
            'total_downloaded': len(downloaded_ids)
        }
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save progress file: {e}")

def get_post_tags_for_filename(post):
    tags_file_name = []
    
    if config.INCLUDE_CHARACTER_TAGS:
        tags_file_name.extend(post.get("tag_string_character", "").split())
    if config.INCLUDE_COPYRIGHT_TAGS:
        tags_file_name.extend(post.get("tag_string_copyright", "").split())
    if config.INCLUDE_GENERAL_TAGS:
        tags_file_name.extend(post.get("tag_string_general", "").split())
    if config.INCLUDE_ARTIST_TAGS:
        tags_file_name.extend(post.get("tag_string_artist", "").split())
    if config.INCLUDE_META_TAGS:
        tags_file_name.extend(post.get("tag_string_meta", "").split())
    
    if not tags_file_name and post.get("tag_string"):
        tags_file_name = post.get("tag_string", "").split()
    
    tags_file_name = tags_file_name[:config.MAX_TAGS_IN_FILENAME]
    
    invalid_chars = r'[\/:*?"<>|]'
    tags_file_name = [re.sub(invalid_chars, "_", tag) for tag in tags_file_name]
    
    return tags_file_name

def get_post_tags_for_txt(post):
    tag_types = {}
    
    if config.INCLUDE_ARTIST_TAGS:
        tag_types["artist"] = post.get("tag_string_artist", "").split()
    if config.INCLUDE_COPYRIGHT_TAGS:
        tag_types["copyright"] = post.get("tag_string_copyright", "").split()
    if config.INCLUDE_CHARACTER_TAGS:
        tag_types["character"] = post.get("tag_string_character", "").split()
    if config.INCLUDE_GENERAL_TAGS:
        tag_types["general"] = post.get("tag_string_general", "").split()
    if config.INCLUDE_META_TAGS:
        tag_types["meta"] = post.get("tag_string_meta", "").split()
    
    if not any(tag_types.values()) and post.get("tag_string"):
        tag_types["general"] = post.get("tag_string", "").split()
    
    return tag_types

def calculate_file_hash(filepath):
    try:
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None

def post_matches_tags(post, required_tags=None, excluded_tags=None, wildcard_tags=None):
    if not (required_tags or excluded_tags or wildcard_tags):
        return True, "ok"

    post_tags = {tag.lower() for tag in post.get("tag_string", "").split()}

    if required_tags:
        missing_tags = set(required_tags) - post_tags
        if missing_tags:
            return False, f"missing required tags: {', '.join(sorted(missing_tags))}"

    if excluded_tags:
        blocked_tags = set(excluded_tags) & post_tags
        if blocked_tags:
            return False, f"excluded tags: {', '.join(sorted(blocked_tags))}"

    if wildcard_tags:
        for pattern in wildcard_tags:
            if not any(fnmatch.fnmatch(tag, pattern) for tag in post_tags):
                return False, f"no tag matching: {pattern}"

    return True, "ok"


def should_download_post(post, downloaded_ids):
    post_id = post['id']
    progress_key = sites.post_key(post)
    
    hard_reason = hard_block_reason(post)
    if hard_reason:
        logging.info(f"⛔ Skipped post {post_id}: {hard_reason}")
        return False, hard_reason
    
    if config.RESUME_DOWNLOAD:
        if progress_key in downloaded_ids:
            return False, "already downloaded"
        if (post.get("site") or "danbooru") == "danbooru" and (
                post_id in downloaded_ids
                or str(post_id) in downloaded_ids):
            return False, "already downloaded"
    
    blacklisted_tags = [tag for tag in post.get("tag_string", "").split() if tag in config.BLACKLIST_TAGS]
    if blacklisted_tags:
        return False, f"blacklisted tags: {', '.join(blacklisted_tags)}"

    tags_ok, tags_reason = post_matches_tags(
        post,
        getattr(config, "REQUIRED_TAGS", None),
        getattr(config, "EXCLUDED_TAGS", None),
        getattr(config, "WILDCARD_TAGS", None),
    )
    if not tags_ok:
        return False, tags_reason
    
    width, height = post.get("image_width", 0), post.get("image_height", 0)
    if width < config.MIN_IMAGE_WIDTH or height < config.MIN_IMAGE_HEIGHT:
        return False, f"small size: {width}x{height}"
    if width >= config.MAX_IMAGE_WIDTH or height >= config.MAX_IMAGE_HEIGHT:
        return False, f"large size: {width}x{height}"
    
    if config.MIN_ID is not None and post_id < config.MIN_ID:
        return False, f"ID below minimum: {post_id}"
    if config.MAX_ID is not None and post_id > config.MAX_ID:
        return False, f"ID above maximum: {post_id}"
    
    try:
        created_at = post.get("created_at")
        if created_at:
            post_date = datetime.fromisoformat(created_at).replace(tzinfo=None)
            if config.MIN_DATE and post_date < datetime.fromisoformat(config.MIN_DATE):
                return False, f"date too early: {post_date}"
            if config.MAX_DATE and post_date > datetime.fromisoformat(config.MAX_DATE):
                return False, f"date too late: {post_date}"
    except Exception:
        return False, "invalid date format"
    
    score = post.get("score", 0)
    if config.MIN_SCORE is not None and score < config.MIN_SCORE:
        return False, f"low score: {score}"
    if config.MAX_SCORE is not None and score > config.MAX_SCORE:
        return False, f"high score: {score}"
    
    if post.get("rating") != "g":
        return False, f"rating not safe: {post.get('rating')}"
    
    return True, "ok"

def download_image_with_retries(image_url, retries=config.MAX_RETRIES):
    attempt = 0
    last_exception = None
    
    while attempt < retries:
        try:
            response = http_get(
                image_url, 
                timeout=config.REQUEST_TIMEOUT,
                stream=True
            )
            if response.status_code == 429:
                retry_after = 2.0 * (attempt + 1)
                try:
                    retry_after = float(response.headers.get(
                        "Retry-After", retry_after))
                except Exception:
                    pass
                logging.warning(f"⏳ File download throttled (429). "
                                f"Waiting {retry_after:.0f}s...")
                response.close()
                time.sleep(retry_after)
                attempt += 1
                continue
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            chunks = []
            
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    chunks.append(chunk)
                    downloaded_size += len(chunk)
            
            return b''.join(chunks)
            
        except RequestExceptions + (IncompleteRead,) as e:
            attempt += 1
            last_exception = e
            logging.warning(f"Retry {attempt}/{retries} for {image_url}: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    
    raise Exception(f"Failed to download image after {retries} attempts: {last_exception}")

def set_file_timestamp(filepath, iso_date_str):
    try:
        if not iso_date_str:
            return
        dt = datetime.fromisoformat(iso_date_str)
        timestamp = dt.timestamp()
        os.utime(filepath, (timestamp, timestamp))
    except Exception as e:
        logging.debug(f"Failed to set timestamp on {filepath}: {e}")

def create_safe_filename(post):
    post_id = post['id']
    site = post.get("site") or "danbooru"
    
    year_str = ""
    try:
        if post.get("created_at"):
            year_str = str(datetime.fromisoformat(post["created_at"]).year)
    except Exception:
        pass
    
    tags_file_name = get_post_tags_for_filename(post)
    
    if site == "danbooru":
        filename = f"{post_id}_{year_str}" if year_str else f"{post_id}"
    else:
        filename = (
            f"{site}_{post_id}_{year_str}" if year_str
            else f"{site}_{post_id}")
    
    for tag in tags_file_name:
        if len(filename) + len(tag) + 1 <= config.MAX_FILENAME_LENGTH:
            filename += f"_{tag}"
        else:
            break
    
    return filename[:config.MAX_FILENAME_LENGTH]

def get_file_extension(image_url):
    ext = os.path.splitext(image_url)[1].lower().lstrip('.')
    if not ext or ext not in config.ALLOWED_EXTENSIONS:
        try:
            response = http_head(image_url, timeout=5)
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type or 'jpg' in content_type:
                return 'jpg'
            elif 'png' in content_type:
                return 'png'
            elif 'gif' in content_type:
                return 'gif'
            elif 'webp' in content_type:
                return 'webp'
        except:
            pass
        return 'jpg'
    return ext

def sanitize_sfw_query(tags_str):
    tokens = tags_str.strip().split() if tags_str else []
    clean_tokens = []
    for t in tokens:
        if is_hard_blocked_tag_name(t):
            continue
        if t.lower().startswith("rating:"):
            continue
        elif t.lower() in config.BLACKLIST_TAGS:
            continue
        else:
            clean_tokens.append(t)

    if not clean_tokens:
        return ""

    clean_tokens.append("rating:general")
    clean_tokens.append("-is:deleted")
    clean_tokens.append("-is:banned")
    return " ".join(clean_tokens)


def split_search_tags(tags_str):
    plain_tags = []
    meta_tokens = []
    for token in (tags_str or "").split():
        if token.lower() in config.BLACKLIST_TAGS:
            continue
        if token.lower().startswith(FILTER_PREFIXES) or token.startswith(("-", "~")) or "*" in token or ".." in token:
            meta_tokens.append(token)
        else:
            plain_tags.append(token)
    return plain_tags, meta_tokens


def get_excluded_tags(tags_str):
    excluded = []
    for token in (tags_str or "").split():
        if not token.startswith("-") or len(token) < 2:
            continue
        name = token[1:]
        if name.lower().startswith(FILTER_PREFIXES) or "*" in name:
            continue
        excluded.append(name.lower())
    return excluded


def get_wildcard_tags(tags_str):
    wildcards = []
    for token in (tags_str or "").split():
        if "*" in token and not token.startswith(("-", "~")):
            wildcards.append(token.lower())
    return wildcards


def is_tag_limit_error(response):
    if getattr(response, "status_code", None) != 422:
        return False
    try:
        return response.json().get("error") == "PostQuery::TagLimitError"
    except Exception:
        return False


def fetch_posts_for_preview(tags_str, page=1, limit=40, start_raw=None,
                            max_raw_pages=4, session="preview", reset=False):
    tags_str = (tags_str or "").strip()
    if not tags_str:
        return [], "", False, None

    raw_page = int(start_raw) if start_raw else int(page)
    raw_page = max(1, raw_page)
    limit = max(1, min(200, int(limit)))
    return sites.fetch_combined(
        tags_str, limit=limit, page=raw_page, session=session,
        reset=reset or start_raw is None)


def download_images():
    downloaded_ids, downloaded_md5s = load_progress_data()
    downloaded_formats = defaultdict(int)
    failed_downloads = []
    total_downloaded = len(downloaded_ids)
    
    logging.info(f"Starting download. Already downloaded: {total_downloaded}")
    logging.info(f"Save folder: {config.SAVE_FOLDER}")
    enabled = sites.enabled_sources()
    logging.info(f"Sources: {', '.join(sites.site_name(k) for k in enabled)}")
    
    logging.info("Tag configuration:")
    logging.info(f"  - Artist tags: {config.INCLUDE_ARTIST_TAGS}")
    logging.info(f"  - Character tags: {config.INCLUDE_CHARACTER_TAGS}")
    logging.info(f"  - Copyright tags: {config.INCLUDE_COPYRIGHT_TAGS}")
    logging.info(f"  - General tags: {config.INCLUDE_GENERAL_TAGS}")
    logging.info(f"  - Meta tags: {config.INCLUDE_META_TAGS}")

    plain_tags, meta_tokens = split_search_tags(config.TAGS)
    required_tags = {tag.lower() for tag in plain_tags}
    excluded_tags = set(get_excluded_tags(config.TAGS))
    wildcard_tags = set(get_wildcard_tags(config.TAGS))

    config.REQUIRED_TAGS = required_tags
    config.EXCLUDED_TAGS = excluded_tags
    config.WILDCARD_TAGS = wildcard_tags
    logging.info(f"🔎 Search query: {config.TAGS}")
    if plain_tags:
        logging.info(f"   Required tags: {', '.join(plain_tags)}")
    
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS, thread_name_prefix="DL") as executor:
        futures = []
        page = config.START_PAGE
        
        while page < config.END_PAGE:
            if config.CANCELLED:
                logging.info("⏹️ Download cancelled by user")
                break
            wait_if_paused()
            if config.MAX_PAGES and page > config.MAX_PAGES:
                break
                
            logging.info(f"📄 Fetching page {page}...")
            
            try:
                posts, note, has_more, _next_raw = sites.fetch_download_page(
                    config.TAGS, page, config.LIMIT_PER_PAGE,
                    reset=(page == config.START_PAGE))
                if note:
                    logging.warning(note)
                if not posts:
                    if has_more:
                        page += 1
                        continue
                    logging.info("✅ No more posts to download.")
                    break
                
                for post in posts:
                    if config.CANCELLED:
                        break
                    if config.MAX_DOWNLOADS is not None and (sum(downloaded_formats.values()) + len(futures)) >= config.MAX_DOWNLOADS:
                        config.CANCELLED = True
                        logging.info(f"🛑 Reached download limit of {config.MAX_DOWNLOADS} files. Stopping.")
                        break
                    post_id = post['id']
                    
                    should_download, reason = should_download_post(post, downloaded_ids)
                    if not should_download:
                        logging.debug(f"⏩ Skipped post {post_id}: {reason}")
                        continue
                    
                    image_url = post.get("file_url")
                    if not image_url:
                        continue
                    
                    future = executor.submit(
                        process_single_post, post, image_url,
                        downloaded_formats, downloaded_md5s)
                    futures.append((future, sites.post_key(post), post_id))
                
                for future, progress_key, post_id in list(futures):
                    if future.done():
                        futures.remove((future, progress_key, post_id))
                        try:
                            success = future.result()
                            if success:
                                downloaded_ids.add(progress_key)
                                total_downloaded += 1
                                if getattr(config, "ON_PROGRESS_CALLBACK", None):
                                    try:
                                        config.ON_PROGRESS_CALLBACK(total_downloaded, total_downloaded + len(futures))
                                    except Exception:
                                        pass
                        except Exception as e:
                            failed_downloads.append(post_id)
                            logging.error(f"❌ Failed to download post {post_id}: {e}")

                if config.CANCELLED:
                    logging.info("⏹️ Download cancelled by user")
                    break

                wait_if_paused()

                if not has_more:
                    break
                page += 1
                time.sleep(config.RATE_LIMIT_DELAY)
                
            except Exception as e:
                if config.CANCELLED:
                    break
                logging.error(f"❌ Error fetching page {page}: {e}")
                break
        
        pending_remaining = len(futures)
        if futures and getattr(config, "ON_PROGRESS_CALLBACK", None):
            try:
                config.ON_PROGRESS_CALLBACK(total_downloaded, total_downloaded + pending_remaining)
            except Exception:
                pass

        for future, progress_key, post_id in futures:
            pending_remaining -= 1
            if config.CANCELLED and future.cancel():
                if getattr(config, "ON_PROGRESS_CALLBACK", None):
                    try:
                        config.ON_PROGRESS_CALLBACK(total_downloaded, total_downloaded + pending_remaining)
                    except Exception:
                        pass
                continue
            try:
                success = future.result(timeout=120)
                if success:
                    downloaded_ids.add(progress_key)
                    total_downloaded += 1
                    if total_downloaded % 5 == 0:
                        save_progress(downloaded_ids, downloaded_md5s)
                if getattr(config, "ON_PROGRESS_CALLBACK", None):
                    try:
                        config.ON_PROGRESS_CALLBACK(total_downloaded, total_downloaded + pending_remaining)
                    except Exception:
                        pass
            except Exception as e:
                failed_downloads.append(post_id)
                logging.error(f"❌ Failed to download post {post_id}: {e}")
    
    save_progress(downloaded_ids, downloaded_md5s)
    
    logging.info("=" * 50)
    logging.info("📊 DOWNLOAD SUMMARY")
    logging.info("=" * 50)
    logging.info(f"✅ Successfully downloaded: {total_downloaded} files")
    logging.info(f"❌ Failed downloads: {len(failed_downloads)}")
    for ext, count in downloaded_formats.items():
        logging.info(f"📁 Format {ext.upper()}: {count} files")
    
    if failed_downloads:
        logging.info(f"Failed IDs: {failed_downloads[:10]}")
    
    return total_downloaded, failed_downloads


def download_posts(posts, max_workers=None):
    posts = list(posts or [])
    if not posts:
        return 0, []

    os.makedirs(config.SAVE_FOLDER, exist_ok=True)
    total_target = len(posts)
    downloaded_formats = defaultdict(int)
    downloaded_ids, downloaded_md5s = load_progress_data()
    failed_downloads = []
    total_downloaded = 0

    old_max_downloads = config.MAX_DOWNLOADS
    config.MAX_DOWNLOADS = None
    config.CANCELLED = False

    logging.info(f"Starting selected download: {total_target} post(s)")
    logging.info(f"Save folder: {config.SAVE_FOLDER}")

    try:
        workers = max(1, int(max_workers or config.MAX_WORKERS))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="SEL") as executor:
            futures = {}
            for post in posts:
                if config.CANCELLED:
                    break
                wait_if_paused()
                if hard_block_reason(post) or post.get("rating") != "g":
                    logging.info("⛔ Skipped unsafe post in selection")
                    continue
                post_id = post.get("id")
                image_url = post.get("file_url")
                if not image_url:
                    failed_downloads.append(post_id)
                    continue
                future = executor.submit(
                    process_single_post, post, image_url,
                    downloaded_formats, downloaded_md5s)
                futures[future] = (sites.post_key(post), post_id)

            for future in as_completed(futures):
                progress_key, post_id = futures[future]
                try:
                    success = future.result()
                    if success:
                        total_downloaded += 1
                        downloaded_ids.add(progress_key)
                    else:
                        failed_downloads.append(post_id)
                except Exception as e:
                    failed_downloads.append(post_id)
                    logging.error(f"❌ Failed to download post {post_id}: {e}")

                if getattr(config, "ON_PROGRESS_CALLBACK", None):
                    try:
                        config.ON_PROGRESS_CALLBACK(total_downloaded, total_target)
                    except Exception:
                        pass

                if total_downloaded % 5 == 0:
                    save_progress(downloaded_ids, downloaded_md5s)
    finally:
        config.MAX_DOWNLOADS = old_max_downloads

    save_progress(downloaded_ids, downloaded_md5s)

    logging.info("=" * 50)
    logging.info("📊 SELECTED DOWNLOAD SUMMARY")
    logging.info("=" * 50)
    logging.info(f"✅ Successfully downloaded: {total_downloaded} / {total_target} files")
    logging.info(f"❌ Failed downloads: {len(failed_downloads)}")
    if failed_downloads:
        logging.info(f"Failed IDs: {failed_downloads[:10]}")

    return total_downloaded, failed_downloads


def process_single_post(post, image_url, downloaded_formats, downloaded_md5s=None):
    if config.MAX_DOWNLOADS is not None and sum(downloaded_formats.values()) >= config.MAX_DOWNLOADS:
        return False
    downloaded_md5s = downloaded_md5s if downloaded_md5s is not None else set()
    try:
        filename_base = create_safe_filename(post)
        full_path = os.path.join(config.SAVE_FOLDER, filename_base)
        site = post.get("site") or "danbooru"
        if site == "danbooru":
            prefixes = (f"{post['id']}_", f"{post['id']}.")
        else:
            prefixes = (f"{site}_{post['id']}_", f"{site}_{post['id']}.")
        
        existing_files = [f for f in os.listdir(config.SAVE_FOLDER) 
                         if f.startswith(prefixes)]
        if existing_files and config.RESUME_DOWNLOAD:
            logging.info(f"⏩ Skipped existing file: {existing_files[0]}")
            if hasattr(config, "ON_PREVIEW_CALLBACK") and config.ON_PREVIEW_CALLBACK:
                config.ON_PREVIEW_CALLBACK(os.path.join(config.SAVE_FOLDER, existing_files[0]))
            return True
        
        known_md5 = (post.get("md5") or "").strip().lower()
        if known_md5 and known_md5 in downloaded_md5s:
            logging.info(f"⏩ Skipped duplicate image: {known_md5}")
            return True
        
        image_data = download_image_with_retries(image_url)
        if not image_data:
            return False
        
        image_md5 = hashlib.md5(image_data).hexdigest()
        if image_md5 in downloaded_md5s:
            logging.info(f"⏩ Skipped duplicate image: {image_md5}")
            return True
        
        file_ext = get_file_extension(image_url)
        
        if file_ext in {"mp4", "webm", "swf", "zip", "avif"}:
            filepath = f"{full_path}.{file_ext}"
            with open(filepath, "wb") as f:
                f.write(image_data)
            downloaded_formats[file_ext] += 1
            downloaded_md5s.add(image_md5)
            logging.info(f"🎥 Downloaded: {os.path.basename(filepath)}")
            if post.get("created_at"):
                set_file_timestamp(filepath, post["created_at"])
            if hasattr(config, "ON_PREVIEW_CALLBACK") and config.ON_PREVIEW_CALLBACK:
                config.ON_PREVIEW_CALLBACK(filepath)
        else:
            try:
                image = Image.open(BytesIO(image_data))
                file_ext = "png"
                filepath = f"{full_path}.png"
                
                if image.mode in ("CMYK",):
                    image = image.convert("RGB")
                
                year_str = ""
                try:
                    if post.get("created_at"):
                        year_str = str(datetime.fromisoformat(post["created_at"]).year)
                except Exception:
                    pass
                
                if year_str:
                    from PIL.PngImagePlugin import PngInfo
                    metadata = PngInfo()
                    metadata.add_text("Year", year_str)
                    image.save(filepath, "PNG", pnginfo=metadata)
                else:
                    image.save(filepath, "PNG")
                    
                downloaded_formats["png"] += 1
                downloaded_md5s.add(image_md5)
                logging.info(f"🖼️ Downloaded & Converted to PNG: {os.path.basename(filepath)} ({image.width}x{image.height})")
                if post.get("created_at"):
                    set_file_timestamp(filepath, post["created_at"])
                if hasattr(config, "ON_PREVIEW_CALLBACK") and config.ON_PREVIEW_CALLBACK:
                    config.ON_PREVIEW_CALLBACK(filepath)
            except Exception as e:
                logging.error(f"❌ Invalid image or failed to convert to PNG for post {post['id']}: {e}")
                return False
        
        if getattr(config, "SAVE_TXT_TAGS", False):
            save_post_tags(post, full_path)
        return True
        
    except Exception as e:
        logging.error(f"❌ Error processing post {post['id']}: {e}")
        return False

def save_post_tags(post, filename_base):
    tag_types = get_post_tags_for_txt(post)
    
    all_tags = []
    for tags in tag_types.values():
        all_tags.extend(tags)
        
    try:
        if post.get("created_at"):
            post_date = datetime.fromisoformat(post["created_at"])
            all_tags.append(f"year_{post_date.year}")
    except Exception:
        pass
    
    filtered_tags = [tag for tag in all_tags if tag not in config.REMOVE_FROM_TXT_FILES]
    
    tags_string = ", ".join(filtered_tags)
    formatted_tags = tags_string.replace("_", " ")
    
    tags_file = f"{filename_base}.txt"
    try:
        with open(tags_file, "w", encoding="utf-8") as f:
            f.write(formatted_tags)
        logging.debug(f"📝 Tags saved: {os.path.basename(tags_file)} ({len(filtered_tags)} tags)")
        if post.get("created_at"):
            set_file_timestamp(tags_file, post["created_at"])
    except Exception as e:
        logging.error(f"❌ Could not save tags for {post['id']}: {e}")

def search_tags_to_triggers():
    if not config.TAGS_TO_TRIGGER_WORDS:
        return
    
    tags_to_prioritize = {tag.replace('_', ' ') for tag in config.TAGS.split()}
    logging.info(f"📄 Start of replacing search tags to triggers...")
    
    processed_files = 0
    for filename in os.listdir(config.SAVE_FOLDER):
        if filename.endswith(".txt"):
            filepath = os.path.join(config.SAVE_FOLDER, filename)
            
            with open(filepath, "r", encoding="utf-8") as file:
                tags = file.read().strip().split(", ")
            
            prioritized_tags = [tag for tag in tags_to_prioritize if tag in tags]
            other_tags = [tag for tag in tags if tag not in tags_to_prioritize]
            
            sorted_tags = prioritized_tags + other_tags
            
            with open(filepath, "w", encoding="utf-8") as file:
                file.write(", ".join(sorted_tags))
            
            processed_files += 1
    
    logging.info(f"📄 End of replacing search tags to triggers. Processed {processed_files} files.")

def add_own_triggers():
    if config.ADD_OWN_TRIGGER_WORDS.strip() == "":
        return
        
    logging.info(f"📄 Start of own trigger word adding...")
    processed_files = 0
    
    for filename in os.listdir(config.SAVE_FOLDER):
        if filename.endswith(".txt"):
            filepath = os.path.join(config.SAVE_FOLDER, filename)
            
            with open(filepath, "r", encoding="utf-8") as file:
                content = file.read().strip()

            with open(filepath, "w", encoding="utf-8") as file:
                content = config.ADD_OWN_TRIGGER_WORDS + ", " + content
                content = content.replace(", ,", ",")
                content = content.replace(",,", ",")
                content = content.replace("  ", " ")
                content = content.replace("  ", " ")
                
                file.write(content)
                processed_files += 1
                    
    logging.info(f"📄 End of own trigger word processing. Processed {processed_files} files.")

def remove_tags_from_txt_files():
    if not config.REMOVE_FROM_TXT_FILES:
        logging.info("📄 No tags to remove from text files.")
        return
        
    logging.info(f"📄 Start of removing tags from text files...")
    removed_count = 0
    file_count = 0
    
    for filename in os.listdir(config.SAVE_FOLDER):
        if filename.endswith(".txt"):
            filepath = os.path.join(config.SAVE_FOLDER, filename)
            file_count += 1
            
            with open(filepath, "r", encoding="utf-8") as file:
                content = file.read().strip()
            
            tags = [tag.strip() for tag in content.split(",")]
            original_count = len(tags)
            filtered_tags = [tag for tag in tags if tag not in config.REMOVE_FROM_TXT_FILES]
            
            if len(filtered_tags) != original_count:
                removed_count += (original_count - len(filtered_tags))
                with open(filepath, "w", encoding="utf-8") as file:
                    file.write(", ".join(filtered_tags))
    
    logging.info(f"📄 Removed {removed_count} tags from {file_count} text files.")

def main():
    parser = argparse.ArgumentParser(description='Danbooru Image Downloader')
    parser.add_argument('--tags', help='Search tags')
    parser.add_argument('--config', help='Config file path')
    parser.add_argument('--resume', action='store_true', help='Resume previous download')
    parser.add_argument('--no-progress', action='store_true', help='Disable progress saving')
    
    parser.add_argument('--include-artist', action='store_true', help='Include artist tags')
    parser.add_argument('--include-meta', action='store_true', help='Include meta tags')
    parser.add_argument('--no-character', action='store_true', help='Exclude character tags')
    parser.add_argument('--no-copyright', action='store_true', help='Exclude copyright tags')
    parser.add_argument('--no-general', action='store_true', help='Exclude general tags')
    
    args = parser.parse_args()
    
    if args.tags:
        config.TAGS = args.tags
    if args.resume:
        config.RESUME_DOWNLOAD = True
    if args.no_progress:
        config.SAVE_PROGRESS = False
    
    if args.include_artist:
        config.INCLUDE_ARTIST_TAGS = True
    if args.include_meta:
        config.INCLUDE_META_TAGS = True
    if args.no_character:
        config.INCLUDE_CHARACTER_TAGS = False
    if args.no_copyright:
        config.INCLUDE_COPYRIGHT_TAGS = False
    if args.no_general:
        config.INCLUDE_GENERAL_TAGS = False
    
    try:
        config.SAVE_FOLDER = create_save_folder()
        setup_logging()
        
        logging.info("🚀 Starting Danbooru Downloader")
        logging.info(f"🔍 Search tags: {config.TAGS}")
        logging.info(f"📁 Save folder: {config.SAVE_FOLDER}")
        
        total_downloaded, failed_downloads = download_images()
        
        if config.TAGS_TO_TRIGGER_WORDS:
            search_tags_to_triggers()
        if config.ADD_OWN_TRIGGER_WORDS.strip():
            add_own_triggers()
        if config.REMOVE_FROM_TXT_FILES:
            remove_tags_from_txt_files()
        
        logging.info("✅ Download completed successfully!")
        
    except KeyboardInterrupt:
        logging.info("⏹️ Download interrupted by user")
    except Exception as e:
        logging.error(f"💥 Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
