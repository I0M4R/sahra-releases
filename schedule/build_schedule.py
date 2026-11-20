"""Builds schedule.json.gz for the Sahra app: channel display name -> programmes for the next ~40 h.

Source: the free XMLTV files epgshare01.online publishes (the same files iptv-org/epg reuses).
Python stdlib only. Mirrors tool/build_schedule.dart in the app repo; the app matches names itself.

    python schedule/build_schedule.py out/schedule.json.gz
"""
import gzip
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = 'https://epgshare01.online/epgshare01/epg_ripper_'
SOURCES = ['BEIN1', 'AE1', 'SA2']  # the first source to name a channel wins


def bein_name(cid):
    """beIN feed id -> readable name; None for English copies (same schedule as the Arabic feed)."""
    if '_AR' not in cid:
        return None
    u = cid.upper()
    m = re.search(r'ALKASS_(\d+)', u)
    if m:
        return f'Alkass {m[1]}'
    if 'NEWS' in u:
        return 'beIN Sports News'
    if 'FTA' in u:
        return 'beIN Sports FTA'
    if u.startswith('4K'):
        return None
    for kind in ['MAX', 'XTRA', 'ENGLISH', 'FRENCH']:
        m = re.search(kind + r'[_-]*(?:DIGITAL_)?0*(\d+)', u)
        if not m and kind in ('ENGLISH', 'FRENCH'):
            m = re.search(r'SPORTS(\d+)_' + kind, u)
        if m:
            return f'beIN Sports {kind.capitalize()} {m[1]}'
    m = re.search(r'SPORTS(\d+)', u)
    return f'beIN Sports {m[1]}' if m else None


def unescape(s):
    return html.unescape(html.unescape(s))  # some entities are double-encoded


def xmltv_time(v):
    m = re.match(r'(\d{14})\s*([+-]\d{4})?', v or '')
    if not m:
        return None
    t = datetime.strptime(m[1], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp()
    off = m[2] or '+0000'
    sec = (int(off[1:3]) * 60 + int(off[3:5])) * 60
    return int(t - sec if off[0] == '+' else t + sec)


def parse(xml, tag, start, stop):
    names = {}
    for m in re.finditer(r'<channel id="([^"]*)"[^>]*>(.*?)</channel>', xml, re.S):
        cid = unescape(m[1])
        dn = re.search(r'<display-name[^>]*>([^<]*)</display-name>', m[2])
        names[cid] = bein_name(cid.replace('.bein', '')) if tag == 'BEIN1' else unescape(dn[1] if dn else cid).strip()
    out = {}
    for m in re.finditer(r'<programme\s+([^>]*)>(.*?)</programme>', xml, re.S):
        a = m[1]
        ch = unescape((re.search(r'channel="([^"]*)"', a) or [None, ''])[1])
        name = names.get(ch, ch if tag != 'BEIN1' else bein_name(ch.replace('.bein', '')))
        if not name:
            continue
        s = xmltv_time((re.search(r'start="([^"]*)"', a) or [None, ''])[1])
        e = xmltv_time((re.search(r'stop="([^"]*)"', a) or [None, ''])[1])
        if s is None or e is None or e <= start or s >= stop:
            continue
        titles = re.findall(r'<title([^>]*)>([^<]*)</title>', m[2])
        if not titles:
            continue
        title = next((t for attrs, t in titles if '"ar"' in attrs), titles[0][1])
        title = unescape(title).strip()
        if title:
            out.setdefault(name, []).append([s, e, title])
    for v in out.values():
        v.sort(key=lambda p: p[0])
    return out


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else 'schedule.json.gz'
    now = int(time.time())
    start, stop = now - 3 * 3600, now + 40 * 3600
    channels, status = {}, {}
    for tag in SOURCES:
        try:
            req = urllib.request.Request(f'{BASE}{tag}.xml.gz', headers={'User-Agent': 'sahra-schedule-builder'})
            raw = urllib.request.urlopen(req, timeout=120).read()
            parsed = parse(gzip.decompress(raw).decode('utf-8', 'replace'), tag, start, stop)
            added = 0
            for k, v in parsed.items():
                if k not in channels:
                    channels[k] = v
                    added += 1
            status[tag] = 'ok'
            print(f'{tag}: ok, {added} channels', file=sys.stderr)
        except Exception as e:  # one source failing must not stop the others
            status[tag] = f'failed ({e})'
            print(f'{tag}: {status[tag]}', file=sys.stderr)
    if len(channels) < 50:
        sys.exit(f'only {len(channels)} channels; not publishing (the last good file stays up)')
    data = json.dumps({'v': 1, 'generated': now, 'sources': status, 'channels': channels},
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with open(dest, 'wb') as f:
        f.write(gzip.compress(data, 9))
    print(f'wrote {dest}: {len(channels)} channels, {len(data) // 1024} KB json', file=sys.stderr)


if __name__ == '__main__':
    main()
