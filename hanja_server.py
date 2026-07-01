#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한자 익힘 - 로컬 서버
------------------------------------------------------------------
이 서버는:
  1) 앱(hanja-practice.html)을 브라우저로 띄워주고,
  2) 한자를 검색하면 한국어 훈음(모일 회)과 일본어 음독·훈독을 찾아 돌려줘요.

데이터(둘 다 무료, 처음 실행 시 자동 다운로드):
  - 한국어 훈음: hanjaDic (myungcheol/hanja, GitHub) — 예: 會 → 모일 회
  - 일본어 음독·훈독: KANJIDIC2 © Jim Breen/EDRDG, CC BY-SA 4.0

필요한 것: 파이썬 3.7+ (설치할 라이브러리 없음)
같은 폴더에 hanja-practice.html 을 두세요.

실행:  python3 hanja_server.py
접속:  http://localhost:8000   (파일을 직접 열지 말고 이 주소로!)
"""

import os
import sys
import gzip
import json
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(HERE, "hanja-practice.html")
GZ_FILE = os.path.join(HERE, "kanjidic2.xml.gz")
HUN_FILE = os.path.join(HERE, "hanjaDic.js")
PORT = int(os.environ.get("PORT", "8000"))

KANJIDIC_URLS = [
    "https://www.edrdg.org/kanjidic/kanjidic2.xml.gz",
    "http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz",
]
HUNMAP_URLS = [
    "https://raw.githubusercontent.com/myungcheol/hanja/master/hanjaDic.js",
]

ENTRIES = {}    # char -> {"on":[...], "kun":[...], "kor":[...], "en":[...]}  (KANJIDIC2)
KOR_HUN = {}    # char -> [{"kor":음, "def":뜻}, ...]  (한국어 훈음)
KOR_INDEX = {}  # 음(한글) -> [char, ...]


def _download(urls, dest, name):
    if os.path.exists(dest):
        return True
    for url in urls:
        try:
            print(name + " 내려받는 중… (" + url + ")")
            req = urllib.request.Request(url, headers={"User-Agent": "hanja-app/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
                out.write(r.read())
            print("  완료: " + dest)
            return True
        except Exception as e:
            print("  실패: " + str(e))
    print("[안내] " + name + " 을(를) 자동으로 못 받았어요. 아래에서 직접 받아 이 폴더에 두세요:\n  " + urls[0])
    return False


def clean_reading(s):
    return (s or "").replace(".", "").replace("-", "").strip()


def load_kanjidic():
    print("일본어 사전(KANJIDIC2)을 읽는 중…")
    count = 0
    with gzip.open(GZ_FILE, "rb") as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != "character":
                continue
            lit = elem.findtext("literal")
            if not lit:
                elem.clear()
                continue
            on, kun, kor, en = [], [], [], []
            freq = None
            misc = elem.find("misc")
            if misc is not None:
                ft = misc.findtext("freq")
                if ft and ft.isdigit():
                    freq = int(ft)
            rmg = elem.find("reading_meaning")
            if rmg is not None:
                for grp in rmg.findall("rmgroup"):
                    for r in grp.findall("reading"):
                        t = r.get("r_type")
                        if t == "ja_on" and r.text:
                            on.append(r.text.strip())
                        elif t == "ja_kun" and r.text:
                            ck = clean_reading(r.text)
                            if ck:
                                kun.append(ck)
                        elif t == "korean_h" and r.text:
                            kor.append(r.text.strip())
                    for m in grp.findall("meaning"):
                        if m.get("m_lang") is None and m.text:
                            en.append(m.text.strip())

            def dedupe(seq):
                seen, out = set(), []
                for x in seq:
                    if x and x not in seen:
                        seen.add(x)
                        out.append(x)
                return out

            ENTRIES[lit] = {"on": dedupe(on), "kun": dedupe(kun),
                            "kor": dedupe(kor), "en": dedupe(en), "freq": freq}
            count += 1
            elem.clear()
    print("  한자 %d자 (음독·훈독)" % count)


def load_hunmap():
    print("한국어 훈음 사전을 읽는 중…")
    with open(HUN_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    i, j = text.find("{"), text.rfind("}")
    obj = json.loads(text[i:j + 1])
    for ch, arr in obj.items():
        if not isinstance(arr, list):
            continue
        KOR_HUN[ch] = arr
        for e in arr:
            k = (e.get("kor") or "").strip()
            if k:
                KOR_INDEX.setdefault(k, []).append(ch)
    print("  한자 %d자 (한국어 훈음)" % len(KOR_HUN))


def hun_reading(ch, eum=None):
    arr = KOR_HUN.get(ch)
    if arr:
        if eum:
            for e in arr:
                if (e.get("kor") or "").strip() == eum:
                    return (str(e.get("def", "")).strip() + " " + eum).strip()
        parts = []
        for e in arr:
            d = str(e.get("def", "")).strip()
            k = str(e.get("kor", "")).strip()
            if d or k:
                parts.append((d + " " + k).strip())
        return " / ".join(parts[:2])
    e = ENTRIES.get(ch)
    if e:
        kor = "/".join(e.get("kor", [])) if e.get("kor") else ""
        en = ", ".join(e.get("en", [])[:2])
        if kor and en:
            return kor + " (" + en + ")"
        return kor or en or ""
    return ""


def to_result(ch, eum=None):
    e = ENTRIES.get(ch, {})
    return {
        "hanja": ch,
        "reading": hun_reading(ch, eum),
        "on": e.get("on", [])[:4],
        "kun": e.get("kun", [])[:6],
    }


def _rank(ch):
    e = ENTRIES.get(ch)
    if e and e.get("freq"):
        return e["freq"]        # 1 = 가장 흔함
    if e:
        return 5000             # 일본어에서 쓰지만 빈도 정보 없음
    return 100000               # 한국어 사전에만 있음(드묾)


def search(q, limit=8):
    q = (q or "").strip()
    if not q:
        return []
    seen = set()
    exact = []          # 직접 입력한 한자
    eum_matches = []    # (char, 음)

    for ch in q:
        if (ch in KOR_HUN or ch in ENTRIES) and ch not in seen:
            seen.add(ch)
            exact.append(ch)
    for tok in q.replace(",", " ").replace("\u00b7", " ").split():
        for ch in KOR_INDEX.get(tok, []):
            if ch not in seen:
                seen.add(ch)
                eum_matches.append((ch, tok))
    def _def_for(ch, eum):
        for e in KOR_HUN.get(ch, []):
            if (e.get("kor") or "").strip() == eum:
                return str(e.get("def", "")).strip()
        return ""

    def _sort_key(ce):
        ch, eum = ce
        d = _def_for(ch, eum)
        boost = 0 if (d and d in q) else 1   # 뜻이 검색어에 있으면 위로
        return (boost, _rank(ch))

    eum_matches.sort(key=_sort_key)

    combined = [(ch, None) for ch in exact] + eum_matches
    if not combined:  # 영어 뜻 fallback
        ql = q.lower()
        for ch, e in ENTRIES.items():
            if any(ql in (m or "").lower() for m in e.get("en", [])):
                combined.append((ch, None))
                if len(combined) >= limit:
                    break
    return [to_result(ch, eum) for ch, eum in combined[:limit]]


INJECT = '<script>window.HANJA_API="/api/han";</script>'


def serve_html():
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    if "</head>" in html:
        html = html.replace("</head>", INJECT + "</head>", 1)
    else:
        html = INJECT + html
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/han":
            q = parse_qs(parsed.query).get("q", [""])[0]
            try:
                self._send(200, json.dumps(search(q), ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode("utf-8"))
            return
        if path in ("/", "/index.html", "/hanja-practice.html"):
            if not os.path.exists(HTML_FILE):
                self._send(404, b"hanja-practice.html not found next to server", "text/plain; charset=utf-8")
                return
            self._send(200, serve_html(), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


def main():
    ok1 = _download(KANJIDIC_URLS, GZ_FILE, "KANJIDIC2 사전(약 4MB)")
    ok2 = _download(HUNMAP_URLS, HUN_FILE, "한국어 훈음 사전")
    if not (ok1 and ok2):
        sys.exit(1)
    load_kanjidic()
    load_hunmap()
    if not os.path.exists(HTML_FILE):
        print("\n[주의] 같은 폴더에 hanja-practice.html 이 없어요. 앱은 안 열리지만 /api/han 은 동작해요.")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("\n서버 시작됨 → http://localhost:%d   (파일을 직접 열지 말고 이 주소로 접속!)" % PORT)
    print("같은 와이파이면 http://<이컴퓨터IP>:%d · 끄려면 Ctrl+C\n" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
