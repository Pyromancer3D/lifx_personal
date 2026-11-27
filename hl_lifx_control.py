#!/usr/bin/env python3
"""hl_lifx_control: local LIFX controller. Speaks the LIFX LAN UDP protocol and serves a web UI + JSON API.
Standard library only (Python 3.8+). See README.md."""
import datetime as dt, ipaddress, json, math, os, random, socket, struct, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = '2.2.1'  # bump on every release and add an entry to CHANGELOG.md
PORT = int(os.environ.get('PORT', 8080))
LIFX = 56700
SRC = 0x4C494658
HERE = os.path.dirname(os.path.abspath(__file__))
CONF_DIR = os.path.join(HERE, '.config')
FILES = {k: os.path.join(CONF_DIR, k + '.json') for k in ('config', 'devices', 'routines')}
CONFIG_KEYS = ('broadcast', 'ips', 'scan', 'poll', 'transition', 'lat', 'lon')  # what config.json holds

# In memory, 'settings' is one flat dict (the page sees it that way); on disk it is split three ways:
#   .config/config.json   : CONFIG_KEYS (network, location, default fade)
#   .config/devices.json  : light_order + groups (with their presets)
#   .config/routines.json : schedules and routines
db = {'settings': {'broadcast': '255.255.255.255', 'ips': [], 'poll': 3, 'transition': 0.5, 'scan': [],
                   'lat': None, 'lon': None, 'light_order': []}, 'groups': [], 'schedules': []}
save_lock = threading.Lock()


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:  # unreadable or damaged: set it aside instead of overwriting it later
        bad = f'{path}.corrupt-{int(time.time())}'
        try:
            os.replace(path, bad)
        except OSError:
            bad = path
        print(f'WARNING: could not read {path} ({e}); kept as {bad} and starting from defaults for it')
        return None


def _write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)  # atomic: a crash mid-write can't leave a half-written file


def save(*which):
    """Write the named files ('config', 'devices', 'routines'); no arguments writes all three."""
    which = which or tuple(FILES)
    with save_lock:
        os.makedirs(CONF_DIR, exist_ok=True)
        if 'config' in which:
            _write_json(FILES['config'], {k: db['settings'][k] for k in CONFIG_KEYS})
        if 'devices' in which:
            _write_json(FILES['devices'], {'light_order': db['settings']['light_order'], 'groups': db['groups']})
        if 'routines' in which:
            _write_json(FILES['routines'], {'schedules': db['schedules']})


def _migrate_v1():
    """1.x kept everything in one config.json (or data.json) beside the script. Split it into .config/."""
    old = next((p for p in (os.path.join(HERE, 'config.json'), os.path.join(HERE, 'data.json')) if os.path.exists(p)), None)
    data = _read_json(old) if old else None
    if not isinstance(data, dict):
        return
    db['settings'].update(data.get('settings') or {})
    db['groups'] = data.get('groups') or []
    db['schedules'] = data.get('schedules') or []
    save()
    os.replace(old, old + '.migrated-v1')  # keep the original, just out of the way
    print(f'Migrated {old} into {CONF_DIR} (original kept as {os.path.basename(old)}.migrated-v1)')


def load():
    if not any(os.path.exists(p) for p in FILES.values()):
        return _migrate_v1()
    c = _read_json(FILES['config']) or {}
    d = _read_json(FILES['devices']) or {}
    r = _read_json(FILES['routines']) or {}
    db['settings'].update({k: c[k] for k in CONFIG_KEYS if k in c})
    if isinstance(d.get('light_order'), list):
        db['settings']['light_order'] = d['light_order']
    if isinstance(d.get('groups'), list):
        db['groups'] = d['groups']
    if isinstance(r.get('schedules'), list):
        db['schedules'] = r['schedules']


load()

lock = threading.Lock()
devices = {}
_seq = 0
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.bind(('', 0))


def packet(mtype, mac=None, payload=b''):
    global _seq
    _seq = (_seq + 1) & 255
    flags = 1024 | 0x1000 | (0 if mac else 0x2000)  # protocol, addressable, tagged if broadcast
    target = (bytes.fromhex(mac) if mac else b'\0' * 6) + b'\0\0'
    hdr = struct.pack('<HHI8s6sBB8sH2s', 36 + len(payload), flags, SRC, target,
                      b'\0' * 6, 1, _seq, b'\0' * 8, mtype, b'\0\0')  # res_required = 1
    return hdr + payload


def tx(buf, ip):
    try:
        sock.sendto(buf, (ip, LIFX))
    except OSError as e:
        print('send error:', ip, e)


stats = {'replies': 0}


def local_ip(target):
    for t in (target, '8.8.8.8'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((t, LIFX))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            pass
    return None


def scan_targets():
    """Unicast addresses to probe: configured CIDR ranges, else the /24 around this machine."""
    nets = []
    for c in db['settings'].get('scan', []):
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            pass
    if not nets:
        ip = local_ip(db['settings']['broadcast'])
        if ip:
            nets.append(ipaddress.ip_network(ip + '/24', strict=False))
    return [str(h) for n in nets if n.num_addresses <= 1024 for h in n.hosts()]


def rx_loop():
    while True:
        try:
            m, (ip, _) = sock.recvfrom(1024)
        except OSError:
            continue
        if len(m) < 36 or struct.unpack_from('<I', m, 4)[0] != SRC:
            continue
        mtype = struct.unpack_from('<H', m, 32)[0]
        mac = m[8:14].hex()
        if mtype == 3:
            stats['replies'] += 1
        if mtype in (3, 107):
            with lock:
                d = devices.setdefault(mac, {'mac': mac, 'label': mac, 'h': 0, 's': 0, 'b': 0, 'k': 3500, 'on': False})
                d['ip'] = ip
                d['seen'] = time.time()
                if mtype == 107:
                    h, s, b, k, _, power = struct.unpack_from('<HHHHhH', m, 36)
                    d.update(on=power > 0)
                    if time.time() >= d.get('fx_until', 0):  # during an effect the bulb reports transient colors
                        d.update(h=h, s=s, b=b, k=k)
                        d.pop('fx', None)
                    d['label'] = m[48:80].split(b'\0')[0].decode('utf8', 'replace') or mac


def poll_loop():
    n = 0
    while True:
        try:
            poll_once(n)
        except Exception as e:
            print('poll error:', repr(e))
        n += 1
        time.sleep(max(1, db['settings']['poll']))


def poll_once(n):
    if True:
        s = db['settings']
        tx(packet(2), s['broadcast'])  # GetService: discovers new lights
        tx(packet(2), '255.255.255.255')
        for ip in s['ips']:
            tx(packet(2), ip)
        if not devices or n % 10 == 0:  # broadcasts can be filtered; also probe each address directly
            for ip in scan_targets():
                tx(packet(2), ip)
        with lock:
            known = [(d['mac'], d['ip']) for d in devices.values()]
        for mac, ip in known:
            tx(packet(101, mac), ip)  # LightGet: current state


def u16(v, mx):
    return max(0, min(65535, round(v / mx * 65535)))


def set_light(d, c, dur=None):
    """Apply color and/or power changes. dur is the fade in ms (default: the Settings fade time)."""
    d['fx_until'] = 0  # manual control cancels our idea of a running effect
    d.pop('fx', None)
    d.pop('fl', None)
    if dur is None:
        dur = round(db['settings']['transition'] * 1000)
    turning_on = c.get('power') is True and not d.get('on')
    if any(k in c for k in ('h', 's', 'b', 'k')):
        h = c.get('h', d['h'] / 65535 * 360)
        s = c.get('s', d['s'] / 65535 * 100)
        b = c.get('b', d['b'] / 65535 * 100)
        k = int(max(1500, min(9000, c.get('k', d['k']))))
        hh, ss, bb = u16(h % 360, 360), u16(s, 100), u16(b, 100)
        # a light that is off and about to turn on gets its color instantly, so the power-on fade rises smoothly to it
        tx(packet(102, d['mac'], struct.pack('<BHHHHI', 0, hh, ss, bb, k, 0 if turning_on else dur)), d['ip'])
        d.update(h=hh, s=ss, b=bb, k=k)
    if 'power' in c:
        tx(packet(117, d['mac'], struct.pack('<HI', 65535 if c['power'] else 0, dur)), d['ip'])
        d['on'] = bool(c['power'])


def clamp_secs(v, hi):
    try:
        return max(0.0, min(float(hi), float(v)))
    except (TypeError, ValueError):
        return None


def apply(macs, c):
    """Apply changes to lights. An optional 'transition' (seconds, max 7200) overrides the default fade for this call."""
    c = dict(c)
    t = clamp_secs(c.pop('transition', None), 7200)
    dur = None if t is None else round(t * 1000)
    with lock:
        for m in macs:
            if m in devices:
                set_light(devices[m], c, dur)


# ---- Effects: the bulb itself runs LIFX "SetWaveform" (type 103), so no cloud and no flicker from network lag ----
# kind -> (waveform id, period in ms, dip: fraction of own brightness used when no color is given)
WAVES = {'breathe': (1, 3000, 0.03), 'pulse': (4, 1000, 0.0), 'strobe': (4, 100, 0.0)}  # 1 = SINE, 4 = PULSE
CONTINUOUS_SECONDS = 3600  # toggled-on breathe/pulse/flicker run up to an hour; strobe is capped at 60 s
EFFECTS = set(WAVES) | {'flicker'}
# 'flicker' (candle) has no bulb-side waveform, so the server emulates it: see flicker_loop()


def is_online(d):
    return time.time() - d['seen'] < db['settings']['poll'] * 4 + 3


def run_effect(macs, kind, color=None, times=None, seconds=None):
    """Breathe/pulse/strobe lights that are ON, then the bulb returns to its previous color by itself."""
    if kind == 'stop':
        return stop_effect(macs)
    if kind == 'flicker':
        return start_flicker(macs, color, seconds)
    wave, period, dip = WAVES[kind]
    if kind == 'strobe':
        cycles = min(float(seconds or 30), 60) * 1000 / period
    else:
        cycles = min(float(times), 1000) if times else CONTINUOUS_SECONDS * 1000 / period
    with lock:
        for m in macs:
            d = devices.get(m)
            if not d or not d.get('on') or not is_online(d):
                continue  # lights that are off (or unreachable) are skipped
            if time.time() >= d.get('fx_until', 0):
                d['base'] = (d['h'], d['s'], d['b'], d['k'])  # remember the real state, polls are gated during the effect
            bh, bs, bb, bk = d['base']
            if d.get('fx') == 'flicker':  # leaving candle mode: snap back so the wave returns to the real color
                tx(packet(102, m, struct.pack('<BHHHHI', 0, bh, bs, bb, bk, 0)), d['ip'])
                d.pop('fl', None)
            if color:
                h, s, b, k = u16(color['h'] % 360, 360), u16(color['s'], 100), u16(color['b'], 100), int(color.get('k', 3500))
            else:
                h, s, b, k = bh, bs, int(bb * dip), bk
            payload = struct.pack('<BBHHHHIfhB', 0, 1, h, s, b, max(1500, min(9000, k)), period, cycles, 0, wave)
            tx(packet(103, m, payload), d['ip'])
            d['fx'] = kind
            d['fx_until'] = time.time() + cycles * period / 1000 + 1


def start_flicker(macs, color, seconds):
    """Candle flicker: the flicker_loop thread sends randomized SetColor commands until the time is up."""
    secs = min(float(seconds or CONTINUOUS_SECONDS), CONTINUOUS_SECONDS)
    now = time.time()
    with lock:
        for m in macs:
            d = devices.get(m)
            if not d or not d.get('on') or not is_online(d):
                continue
            if now >= d.get('fx_until', 0):
                d['base'] = (d['h'], d['s'], d['b'], d['k'])
            if color:
                peak = (u16(color['h'] % 360, 360), u16(color['s'], 100), u16(color['b'], 100), int(color.get('k', 3500)))
            else:
                peak = d['base']
            d['fx'] = 'flicker'
            d['fl'] = {'end': now + secs, 'next': now, 'peak': peak, 'lvl': 1.0}
            d['fx_until'] = now + secs + 2  # keep polls from overwriting the saved state while we run and restore


def flicker_step(d, now):
    """One candle update for a bulb (called under the lock). Returns False when its flicker is over."""
    f = d.get('fl')
    if d.get('fx') != 'flicker' or not f:
        return False  # cancelled by hand or replaced by another effect: leave the bulb alone
    h, s, b, k = f['peak']
    if now >= f['end']:
        bh, bs, bb, bk = d['base']
        tx(packet(102, d['mac'], struct.pack('<BHHHHI', 0, bh, bs, bb, bk, 400)), d['ip'])  # fade back
        d.pop('fx', None)
        d.pop('fl', None)
        return False
    if now < f['next']:
        return True
    r = random.random()  # mostly gentle wobble, sometimes a deeper gust
    target = random.uniform(0.7, 1.0) if r < 0.7 else random.uniform(0.45, 0.7) if r < 0.93 else random.uniform(0.25, 0.45)
    f['lvl'] += (target - f['lvl']) * 0.8
    gap = random.uniform(0.15, 0.4)
    if s > 0:  # colored light: wiggle the hue a few degrees
        h = (h + random.randint(-700, 700)) % 65536
    else:      # white light: wiggle the warmth
        k = max(1500, min(9000, k + random.randint(-250, 250)))
    tx(packet(102, d['mac'], struct.pack('<BHHHHI', 0, h, s, max(1, int(b * f['lvl'])), k, int(gap * 1000))), d['ip'])
    f['next'] = now + gap
    return True


def flicker_loop():
    while True:
        try:
            now = time.time()
            with lock:
                for d in list(devices.values()):
                    if d.get('fx') == 'flicker':
                        flicker_step(d, now)
        except Exception as e:
            print('flicker error:', repr(e))
        time.sleep(0.05)


def stop_effect(macs):
    with lock:
        for m in macs:
            d = devices.get(m)
            if d and d.get('base') and d.get('fx_until', 0) > time.time():
                h, s, b, k = d['base']
                tx(packet(102, m, struct.pack('<BHHHHI', 0, h, s, b, k, 0)), d['ip'])
                d.update(h=h, s=s, b=b, k=k, fx_until=0)
                d.pop('fx', None)
                d.pop('fl', None)


def view(d):
    online = time.time() - d['seen'] < db['settings']['poll'] * 4 + 3
    return {'mac': d['mac'], 'label': d['label'], 'ip': d['ip'], 'online': online, 'on': d['on'],
            'h': round(d['h'] / 65535 * 360), 's': round(d['s'] / 65535 * 100),
            'b': round(d['b'] / 65535 * 100), 'k': d['k'],
            'fx': d.get('fx') if time.time() < d.get('fx_until', 0) else None}


# ---- Schedules: run by a background thread, so they work with the browser closed ----
fired = {}  # schedule id -> date it last ran


def sun_event(day, lat, lon, rise):
    """Sunrise/sunset (Almanac for Computers algorithm, good to a few minutes) as a local datetime, or None."""
    n = day.timetuple().tm_yday
    lng = lon / 15
    tt = n + ((6 if rise else 18) - lng) / 24
    M = 0.9856 * tt - 3.289
    L = (M + 1.916 * math.sin(math.radians(M)) + 0.02 * math.sin(math.radians(2 * M)) + 282.634) % 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    RA = (RA + (math.floor(L / 90) - math.floor(RA / 90)) * 90) / 15
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(90.833)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
    if not -1 <= cos_h <= 1:
        return None  # sun never rises/sets that day (polar)
    H = math.degrees(math.acos(cos_h))
    H = (360 - H if rise else H) / 15
    ut = (H + RA - 0.06571 * tt - 6.622 - lng) % 24
    loc = (dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc) + dt.timedelta(hours=ut)).astimezone()
    for _ in range(2):  # keep it on the requested local date
        if loc.date() < day:
            loc += dt.timedelta(days=1)
        elif loc.date() > day:
            loc -= dt.timedelta(days=1)
    return loc


def fire_time(s, day):
    w = s.get('when', {})
    if w.get('type') == 'time':
        h, m = (int(x) for x in str(w.get('time', '00:00')).split(':')[:2])
        return dt.datetime.combine(day, dt.time(h, m)).astimezone()
    lat, lon = db['settings'].get('lat'), db['settings'].get('lon')
    if lat is None or lon is None:
        return None
    t0 = sun_event(day, lat, lon, w.get('type') == 'sunrise')
    return t0 + dt.timedelta(minutes=int(w.get('offset') or 0)) if t0 else None


def next_fire(s):
    if s.get('enabled', True) is False:
        return None
    now = dt.datetime.now().astimezone()
    for i in range(9):
        day = now.date() + dt.timedelta(days=i)
        if day.weekday() in (s.get('days') or range(7)):
            ft = fire_time(s, day)
            if ft and ft > now:
                return ft.isoformat()
    return None


def eff_fade(a):
    """The fade for an action: its own 'fade' (seconds) when set, otherwise the default from Settings."""
    f = clamp_secs(a.get('fade'), 7200) if a.get('fade') not in (None, '') else None
    return db['settings']['transition'] if f is None else f


def est_secs(a):
    """How long an action takes to complete (matches what do_action reports), without running it."""
    kind = a.get('type')
    if kind == 'strobe':
        return min(float(a.get('seconds') or 30), 60)
    if kind == 'flicker':
        return min(float(a.get('seconds') or CONTINUOUS_SECONDS), CONTINUOUS_SECONDS)
    if kind in WAVES:
        return min(float(a.get('times') or 1), 1000) * WAVES[kind][1] / 1000
    return float(eff_fade(a)) if kind in ('on', 'off', 'preset') else 0.0


def do_action(a):
    """Run one action now. Returns (seconds until the action is complete, the lights it acts on)."""
    tgt, kind = a.get('target', 'all'), a.get('type')
    g = next((g for g in db['groups'] if g['id'] == tgt), None)
    with lock:
        macs = list(devices) if tgt == 'all' else (list(g['members']) if g else [])
    fade = eff_fade(a)
    if kind in ('on', 'off'):
        apply(macs, {'power': kind == 'on', 'transition': fade})
        return fade, macs
    if kind in EFFECTS:  # effects keep their own timing; the fade setting doesn't apply
        run_effect(macs, kind, a.get('color'), a.get('times'), a.get('seconds'))
        if kind == 'strobe':
            secs = min(float(a.get('seconds') or 30), 60)
        elif kind == 'flicker':
            secs = min(float(a.get('seconds') or CONTINUOUS_SECONDS), CONTINUOUS_SECONDS)
        else:
            secs = min(float(a.get('times') or 1), 1000) * WAVES[kind][1] / 1000
        return secs, macs
    if kind == 'preset' and g:
        p = next((p for p in g.get('presets', []) if p['id'] == a.get('preset')), None)
        for mac, c in (p['lights'].items() if p else []):
            if mac in g['members']:
                apply([mac], {'h': c['h'], 's': c['s'], 'b': c['b'], 'k': c['k'], 'power': c['on'], 'transition': fade})
        return fade, macs
    return 0.0, macs


# A routine is a schedule's first action plus optional steps. Each step waits "delay" seconds AFTER the previous
# step has completed (its fade or effect finished), then runs its own action. Runs live only in memory.
running = {}  # schedule id -> {'step', 'of', 'stop' (Event), 'macs', 'kind'}
run_lock = threading.Lock()


def start_routine(s):
    """Start a schedule/routine in its own thread. False if it is already running."""
    sid = s['id']
    steps = [{'delay': 0, 'action': s.get('action') or {}}] + [x for x in (s.get('steps') or []) if isinstance(x, dict)]
    r = {'step': 1, 'of': len(steps), 'stop': threading.Event(), 'macs': [], 'kind': None, 'ends': None}
    with run_lock:
        if sid in running:
            return False
        running[sid] = r
    threading.Thread(target=_routine_thread, args=(s.get('name'), sid, steps, r), daemon=True).start()
    return True


def _routine_thread(name, sid, steps, r):
    try:
        # tail[i] = estimated seconds from the start of step i's delay to the end of the routine
        tail = [0.0] * (len(steps) + 1)
        for i in range(len(steps) - 1, -1, -1):
            tail[i] = (clamp_secs(steps[i].get('delay'), 86400) or 0 if i else 0) + est_secs(steps[i].get('action') or {}) + tail[i + 1]
        for i, st in enumerate(steps):
            r['ends'] = time.time() + tail[i]
            if i and r['stop'].wait(clamp_secs(st.get('delay'), 86400) or 0):
                break
            r['step'] = i + 1
            a = st.get('action') or {}
            secs, macs = do_action(a)
            r['ends'] = time.time() + secs + tail[i + 1]
            r['macs'], r['kind'] = macs, a.get('type')
            print(f"[schedule] '{name}' step {i + 1}/{len(steps)}: {a.get('type')} {a.get('target', 'all')}")
            if r['stop'].is_set():  # stopped while this step was starting
                if r['kind'] in EFFECTS:
                    stop_effect(macs)
                break
            if r['stop'].wait(secs):
                break
    except Exception as e:
        print('routine error:', repr(e))
    finally:
        with run_lock:
            running.pop(sid, None)


def stop_routine(sid):
    """Stop where it is: remaining steps never run and any effect it started ends. A fade in progress finishes by itself."""
    with run_lock:
        r = running.get(sid)
    if not r:
        return False
    r['stop'].set()
    if r['kind'] in EFFECTS:
        stop_effect(r['macs'])
    print(f'[schedule] stopped {sid} at step {r["step"]}/{r["of"]}')
    return True


def running_view(sid):
    r = running.get(sid)
    return {'step': r['step'], 'of': r['of'], 'ends': r['ends']} if r else None


def schedule_loop():
    while True:
        try:
            now = dt.datetime.now().astimezone()
            for s in list(db['schedules']):
                if s.get('enabled', True) is False or fired.get(s['id']) == now.date():
                    continue
                if now.weekday() not in (s.get('days') or range(7)):
                    continue
                ft = fire_time(s, now.date())
                if ft and ft <= now < ft + dt.timedelta(minutes=5):  # missed runs older than 5 min are skipped
                    fired[s['id']] = now.date()
                    if start_routine(s):  # skipped if it is somehow still running from before
                        s['runs'] = s.get('runs', 0) + 1
                        save('routines')
        except Exception as e:
            print('schedule error:', repr(e))
        time.sleep(15)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            b = json.loads(self.rfile.read(n) or b'{}')
            return b if isinstance(b, dict) else {}
        except Exception:
            return {}

    def route(self, method):
        try:
            self._route(method)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self.send_json({'ok': False, 'error': f'Server error: {e!r}'}, 500)
            except OSError:
                pass

    def _route(self, method):
        path = self.path.split('?')[0]
        parts = [p for p in path.split('/') if p]
        if not parts or parts[0] != 'api':
            try:
                with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self.send_json({'error': 'index.html missing'}, 500)
            return
        b = {} if method == 'GET' else self.read_body()
        if path == '/api/state':
            with lock:
                lights = [view(d) for d in devices.values()]
            now = dt.datetime.now().astimezone()
            return self.send_json({'lights': lights, 'groups': db['groups'], 'settings': db['settings'],
                                   'schedules': [dict(s, next=next_fire(s), running=running_view(s['id'])) for s in db['schedules']],
                                   'server_time': {'epoch': time.time(), 'utc_offset': int(now.utcoffset().total_seconds()),
                                                   'hms': now.strftime('%H:%M:%S')},
                                   'version': VERSION,
                                   'diag': {'local_ip': local_ip(db['settings']['broadcast']), 'replies': stats['replies']}})
        if len(parts) == 3 and parts[1] == 'light':
            apply([parts[2]], b)
            return self.send_json({'ok': True})
        if parts[1] == 'all':
            with lock:
                macs = list(devices)
            apply(macs, b)
            return self.send_json({'ok': True})
        if len(parts) == 3 and parts[1] == 'group':
            g = next((g for g in db['groups'] if g['id'] == parts[2]), None)
            if g:
                apply(g['members'], b)
            return self.send_json({'ok': bool(g)})
        if len(parts) == 3 and parts[1] == 'effect':
            tgt = parts[2]
            g = next((g for g in db['groups'] if g['id'] == tgt), None)
            kind = b.get('effect')
            if tgt != 'all' and not g and tgt not in devices:
                return self.send_json({'ok': False, 'error': 'unknown group or light'}, 404)
            if kind not in EFFECTS and kind != 'stop':
                return self.send_json({'ok': False, 'error': 'effect must be breathe, pulse, strobe, flicker or stop'}, 400)
            with lock:
                macs = list(devices) if tgt == 'all' else list(g['members']) if g else [tgt]
            run_effect(macs, kind, b.get('color'), b.get('times'), b.get('seconds'))
            return self.send_json({'ok': True})
        if len(parts) == 4 and parts[1] == 'schedule' and parts[3] in ('run', 'stop'):
            s = next((s for s in db['schedules'] if s['id'] == parts[2]), None)
            if not s:
                return self.send_json({'ok': False}, 404)
            if parts[3] == 'stop':
                return self.send_json({'ok': stop_routine(s['id'])})
            if not start_routine(s):
                return self.send_json({'ok': False, 'error': 'already running'}, 409)
            s['manual_runs'] = s.get('manual_runs', 0) + 1
            save('routines')
            return self.send_json({'ok': True})
        if path == '/api/schedules' and method == 'PUT':
            lst = b.get('schedules')
            old = {o['id']: o for o in db['schedules']}
            db['schedules'] = [s for s in lst if isinstance(s, dict) and 'id' in s] if isinstance(lst, list) else []
            for s in db['schedules']:
                s.pop('next', None)
                s.pop('running', None)
                if 'steps' in s:  # routine steps: [{"delay": seconds after the previous step completes, "action": {...}}]
                    s['steps'] = [dict(x, delay=clamp_secs(x.get('delay'), 86400) or 0) for x in (s['steps'] or [])
                                  if isinstance(x, dict) and isinstance(x.get('action'), dict)]
                o = old.get(s['id'], {})  # counters belong to the server; a stale page can't overwrite them
                s['runs'] = o.get('runs', 0)
                s['manual_runs'] = o.get('manual_runs', 0)
            save('routines')
            return self.send_json({'ok': True})
        if path == '/api/groups' and method == 'PUT':
            groups = b.get('groups')
            db['groups'] = groups if isinstance(groups, list) else []
            save('devices')
            return self.send_json({'ok': True})
        if path == '/api/settings' and method == 'PUT':
            s = db['settings']
            if isinstance(b.get('broadcast'), str) and b['broadcast'].strip():
                s['broadcast'] = b['broadcast'].strip()
            if isinstance(b.get('ips'), list):
                s['ips'] = [str(x).strip() for x in b['ips'] if str(x).strip()]
            for k, lim in (('lat', 90), ('lon', 180)):
                if k in b:
                    try:
                        v = float(b[k])
                        s[k] = v if abs(v) <= lim else s.get(k)
                    except (TypeError, ValueError):
                        s[k] = None
            if isinstance(b.get('light_order'), list):
                s['light_order'] = [str(x) for x in b['light_order']]
            if isinstance(b.get('scan'), list):
                s['scan'] = [str(x).strip() for x in b['scan'] if str(x).strip()]
            try:
                if float(b.get('poll', 0)) >= 1:
                    s['poll'] = float(b['poll'])
                if float(b.get('transition', -1)) >= 0:
                    s['transition'] = float(b['transition'])
            except (TypeError, ValueError):
                pass
            try:
                save('config', 'devices')  # light_order is stored with the devices
            except OSError as e:
                return self.send_json({'ok': False, 'error': f'Could not write the files in {CONF_DIR}: {e}'}, 500)
            return self.send_json({'ok': True})
        self.send_json({'error': 'not found'}, 404)

    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PUT(self): self.route('PUT')


if __name__ == '__main__':
    threading.Thread(target=rx_loop, daemon=True).start()
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=schedule_loop, daemon=True).start()
    threading.Thread(target=flicker_loop, daemon=True).start()
    print(f'hl_lifx_control v{VERSION} running at http://localhost:{PORT}')
    try:
        ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
    except OSError as e:
        print(f'\nCould not start on port {PORT}: {e}\nAnother program is probably using it. '
              f'Stop it, or run with a different port, e.g. PORT=9000 python3 hl_lifx_control.py')
    except KeyboardInterrupt:
        pass
