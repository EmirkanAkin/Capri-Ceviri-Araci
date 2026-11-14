"""
Topluluk yamaları: Capri'nin "Toplulukla paylaş" düğmesi GitHub'da "Yama: <oyun> (<dil>)" başlıklı bir konu açar ve
kullanıcı yama dosyasını (.zip) konuya ekler. Bu modül o konuları arar, oyun/motor/dil/satır bilgisini ve ekli dosya
bağlantılarını çıkarır, dosyayı yalnızca GitHub'ın kendi adreslerinden indirir.

Not: GitHub, depo sahibi olmayanların URL ile verdiği etiketi yok sayar; bu yüzden arama etiketle değil başlıkla yapılır.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List

TITLE_PREFIX = "Yama:"
MAX_DOWNLOAD = 50 * 1024 * 1024
_TITLE = re.compile(r"^\s*Yama:\s*(?P<game>.+?)\s*(?:\((?P<lang>[\w-]+)\))?\s*$")
_FIELD = re.compile(r"^(Oyun|Motor|Satır|Dil):\s*(.+?)\s*$", re.MULTILINE)
_ATTACHMENT = re.compile(
    r"https://github\.com/(?:user-attachments/files/\d+|[\w.-]+/[\w.-]+/files/\d+)/[^\s)\]\"'<>]+\.(?:zip|capripatch)"
    r"(?=[\s)\]\"'<>]|$)",
    re.IGNORECASE)


def search_url(repo: str, query: str = "") -> str:
    q = f'repo:{repo} is:issue is:open in:title "{TITLE_PREFIX}"'
    if query.strip():
        q += " " + query.strip()
    return "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": q, "sort": "updated", "order": "desc", "per_page": 50})


def parse_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    body = issue.get("body") or ""
    fields = dict(_FIELD.findall(body))
    title = _TITLE.match(issue.get("title") or "")
    lines = re.sub(r"\D", "", fields.get("Satır", ""))
    files = list(dict.fromkeys(_ATTACHMENT.findall(body)))
    return {
        "number": issue.get("number"),
        "game": (title.group("game") if title else fields.get("Oyun", "")) or issue.get("title", ""),
        "target": (title.group("lang") if title and title.group("lang") else fields.get("Dil", "")),
        "engine": fields.get("Motor", ""),
        "lines": int(lines) if lines else None,
        "url": issue.get("html_url", ""),
        "user": (issue.get("user") or {}).get("login", ""),
        "updated": (issue.get("updated_at") or "")[:10],
        "files": files,
    }


def allowed_download(url: str) -> bool:
    """Yalnızca GitHub'ın konu eki adresleri (indirme oradan GitHub'ın dosya sunucusuna yönlenir)."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == "github.com" and bool(_ATTACHMENT.fullmatch(url))


def search(repo: str, query: str = "", timeout: float = 15) -> List[Dict[str, Any]]:
    import requests
    response = requests.get(search_url(repo, query), timeout=timeout,
                            headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
    response.raise_for_status()
    return [parse_issue(item) for item in response.json().get("items", []) if "pull_request" not in item]


def download(url: str, folder: Path, timeout: float = 60) -> Path:
    if not allowed_download(url):
        raise ValueError("Bu bağlantıdan indirme yapılmaz (yalnızca GitHub konu ekleri).")
    import requests
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.\-]+", "_", urllib.parse.unquote(url.rsplit("/", 1)[-1]))[-120:] or "yama.zip"
    target = folder / name
    size = 0
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Capri"}) as response:
        response.raise_for_status()
        with open(target, "wb") as handle:
            for chunk in response.iter_content(1 << 16):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("Yama dosyası çok büyük (50 MB üstü).")
                handle.write(chunk)
    return target
