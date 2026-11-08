import os
import re
import subprocess
import tempfile

import requests

APP_VERSION = "1.2.1"
REPO = "Acemoneyprod/Safe-for-work-danbooru-downloader"
API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO
USER_AGENT = "SFW-Danbooru-Downloader"


def version_tuple(text):
    parts = re.findall(r"\d+", (text or "").strip().lstrip("vV"))
    return tuple(int(p) for p in parts[:4]) if parts else (0,)


def is_newer(latest, current=APP_VERSION):
    return version_tuple(latest) > version_tuple(current)


def check_latest():
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/vnd.github+json"}
    response = requests.get(API_URL, headers=headers, timeout=20)
    if response.status_code != 200:
        return {"error": "GitHub returned %s" % response.status_code}
    data = response.json()
    tag = data.get("tag_name") or data.get("name") or ""
    assets = data.get("assets") or []
    installer = None
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe") and ("setup" in name or "install" in name):
            installer = asset.get("browser_download_url")
            break
    if installer is None:
        for asset in assets:
            if (asset.get("name") or "").lower().endswith(".exe"):
                installer = asset.get("browser_download_url")
                break
    return {
        "version": tag,
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
        "page": data.get("html_url") or RELEASES_URL,
        "installer": installer,
        "published": data.get("published_at") or "",
    }


def download_installer(url, progress=None, dest_dir=None):
    dest_dir = dest_dir or os.path.join(tempfile.gettempdir(),
                                        "SFWDanbooruUpdate")
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.basename(url.split("?")[0]) or "update-setup.exe"
    dest = os.path.join(dest_dir, name)
    headers = {"User-Agent": USER_AGENT}
    with requests.get(url, headers=headers, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(1024 * 128):
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                if progress is not None:
                    try:
                        progress(done, total)
                    except Exception:
                        pass
    return dest


def launch_installer(path):
    subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True)
