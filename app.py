#!/usr/bin/env python3
"""Claquete - organizador de eventos e faturas para freelancers (so biblioteca standard)."""
import base64, json, os, re, socket, ssl, time, math, hmac, html, hashlib, secrets, sqlite3, smtplib, calendar, threading, struct, zlib
from functools import lru_cache
import datetime as dt
from email.message import EmailMessage
from email.utils import formataddr
from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote, unquote
import i18n, ws, guide, guide_art, export, people, mailer
import threading as _th
THR = _th.local()
from i18n import tx, M0, M1

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(HERE, "app.js"), encoding="utf-8") as _f: JS = _f.read()
except OSError: JS = ""
JSV = hashlib.md5(JS.encode()).hexdigest()[:8]
SW = """/* Claquete: service worker minimo. Nao guarda dados privados; so mostra um aviso se estiveres sem rede. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(function () {
    return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0;text-align:center"><div><h2>Sem ligação</h2><p>Volta a tentar quando tiveres rede.</p></div>', { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }));
});
"""
DB = os.environ.get("DB_PATH", "/data/claquete.db")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
INVITE = os.environ.get("INVITE_CODE", "")
MES = "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split()

e = lambda s: M0 + html.escape("" if s is None else str(s)) + M1      # texto de utilizadores: nunca é traduzido
eh = lambda s: html.escape("" if s is None else str(s))              # texto fixo do código: é traduzido
now_str = lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M")
def dsep(): return "." if i18n.lang() == "en" else ","
today = lambda: dt.date.today()
D = dt.date.fromisoformat

def eur(v):
    s, l = f"{(v or 0):,.2f}", i18n.lang()
    if l == "en": return "€" + s
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", {"pt": " ", "es": ".", "it": ".", "fr": "\u202f"}[l]) + " €"
def short(v):
    s = f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"
    return s.replace(".", ",") if v >= 1000 and i18n.lang() != "en" else s
def num(s):
    s = str(s).replace(" ", "").replace("\u202f", "")
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else: s = s.replace(",", ".")
    try: return float(s)
    except ValueError: return 0.0
def okdate(s):
    try: return D(s).isoformat()
    except Exception: return None
def ds(s): d = D(s); return f"{d.day} {MES[d.month - 1][:3]}"
def drange(a, b):
    A, B = D(a), D(b)
    if a == b: return f"{ds(a)} {B.year}"
    return f"{ds(a)}{' ' + str(A.year) if A.year != B.year else ''} – {ds(b)} {B.year}"
def ndays(a, b): return (D(b) - D(a)).days + 1
def ini(n): return "".join(w[0] for w in (n or "?").split()[:2]).upper()
def month_nav(m):
    try: f = dt.datetime.strptime(m, "%Y-%m").date()
    except ValueError: f = today().replace(day=1)
    return f, (f - dt.timedelta(1)).strftime("%Y-%m"), (f + dt.timedelta(32)).replace(day=1).strftime("%Y-%m")

# ---------------------------------------------------------------- base de dados
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("pragma foreign_keys=on"); return c
def rows(q, a=()):
    c = db()
    try: return c.execute(q, a).fetchall()
    finally: c.close()
def one(q, a=()):
    r = rows(q, a); return r[0] if r else None
def run(q, a=()):
    c = db()
    try:
        cur = c.execute(q, a); c.commit(); return cur.lastrowid
    finally: c.close()

BACKUP_DIR = os.path.join(os.path.dirname(DB), "backups")
BK_RE = r"^claquete-\d{8}-\d{6}-[a-z]+\.db$"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
COLOR_KEYS = ("c_brand", "c_todo", "c_inv", "c_paid")
DEFAULTS = {
    "site_name": "Claquete",
    "hero_title": "Sabe sempre o que falta faturar e o que falta receber.",
    "hero_text": "Eventos, clientes e faturas num só sítio, feito para freelancers de audiovisual. Não emite faturas: só te ajuda a não perder nenhuma.",
    "c_brand": "#3b4cdb", "c_todo": "#e5484d", "c_inv": "#f0a020", "c_paid": "#2fa56b",
    "reg_open": "1", "invite": "", "lang": "pt",
    "ad_on": "0", "ad_img": "", "ad_link": "", "ad_text": "", "ad_app": "1", "ad_auth": "0",
}

# ---------------------------------------------------------------- configuração do site (editável no Admin)
def cfg():
    d = dict(DEFAULTS)
    for r in rows("select k, v from kv where k like 'cfg.%'"): d[r["k"][4:]] = r["v"]
    for k in COLOR_KEYS:
        if not HEX.match(d[k] or ""): d[k] = DEFAULTS[k]
    return d

def set_cfg(d):
    c = db()
    try:
        for k, v in d.items(): c.execute("insert into kv values(?,?) on conflict(k) do update set v=excluded.v", ("cfg." + k, v))
        c.commit()
    finally: c.close()

def SN(): return cfg()["site_name"]
def reg_allowed(c): return c["reg_open"] == "1" or not one("select 1 from users")

def migrate(c):
    cols = {r[1] for r in c.execute("pragma table_info(users)")}
    ec = {r[1] for r in c.execute("pragma table_info(events)")}
    for name, ddl in (("vat_mode", "text default 'none'"), ("vat_rate", "real default 0"), ("wh_rate", "real default 0")):
        if ec and name not in ec: c.execute(f"alter table events add column {name} {ddl}")
    cc = {r[1] for r in c.execute("pragma table_info(clients)")}
    if cc and "email" not in cc: c.execute("alter table clients add column email text")
    fc = {r[1] for r in c.execute("pragma table_info(friends)")}
    if fc and "intro" not in fc: c.execute("alter table friends add column intro text")
    mc = {r[1] for r in c.execute("pragma table_info(chat_msgs)")}
    if mc and "img" not in mc: c.execute("alter table chat_msgs add column img integer default 0")
    for name, ddl in (("is_admin", "integer default 0"), ("disabled", "integer default 0"), ("last_seen", "text"), ("av_v", "integer default 0"), ("guide_seen", "integer default 0"), ("theme", "text default 'auto'"), ("iban", "text"), ("vat_country", "text default 'PT'"), ("vat_def", "text default 'none'"), ("wh_def", "real default 0"), ("ss_on", "integer default 0"), ("ss_rate", "real default 21.4"), ("ss_coef", "real default 70")):
        if name not in cols: c.execute(f"alter table users add column {name} {ddl}")
    if not c.execute("select 1 from users where is_admin=1").fetchone():
        c.execute("update users set is_admin=1 where id=(select min(id) from users)")
    adm = os.environ.get("ADMIN_USER", "").strip()
    if adm: c.execute("update users set is_admin=1 where username=?", (adm,))
    if INVITE and not c.execute("select 1 from kv where k='cfg.invite'").fetchone():
        c.execute("insert into kv values('cfg.invite',?)", (INVITE,))

# ---------------------------------------------------------------- backups
def make_backup(tag="manual"):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"claquete-{dt.datetime.now():%Y%m%d-%H%M%S}-{tag}.db")
    src, dst = db(), sqlite3.connect(path)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    prune()
    return path

def list_backups():
    if not os.path.isdir(BACKUP_DIR): return []
    return [(fn, os.path.getsize(os.path.join(BACKUP_DIR, fn))) for fn in sorted(os.listdir(BACKUP_DIR), reverse=True) if re.match(BK_RE, fn)]

def prune():
    groups = {}
    for fn, _ in list_backups(): groups.setdefault(fn.rsplit("-", 1)[1][:-3], []).append(fn)
    for tag, fns in groups.items():
        for fn in fns[(14 if tag == "auto" else 20):]:
            try: os.remove(os.path.join(BACKUP_DIR, fn))
            except OSError: pass

def backup_loop():
    while True:
        try:
            day = f"claquete-{dt.date.today():%Y%m%d}-"
            if not any(fn.startswith(day) and fn.endswith("-auto.db") for fn, _ in list_backups()): make_backup("auto")
        except Exception as ex: print("ERRO backup automático:", ex, flush=True)
        time.sleep(3600)

def pl(n, w): return f"{n} {w}" if n == 1 else f"{n} {w}s"

def fsize(b):
    return f"{b / 1048576:.1f} MB".replace(".", ",") if b >= 1048576 else f"{max(1, round(b / 1024))} KB"

# ---------------------------------------------------------------- tema, logo, favicon
def rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
def lum(h):
    f = lambda x: x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4
    r, g, b = (f(x / 255) for x in rgb(h)); return .2126 * r + .7152 * g + .0722 * b
def on(h): return "#fff" if lum(h) < .22 else "#0d1117"
def mixhex(h, k=.68): return "#" + "".join(f"{round(x * k + 255 * (1 - k)):02x}" for x in rgb(h))

def theme_css(c):
    if all(c[k].lower() == DEFAULTS[k] for k in COLOR_KEYS): return ""
    names = ("brand", "todo", "inv", "paid")
    def block(P):
        o = ":root{" + ";".join(f"--{n}:{v}" for n, v in P.items()) + "}"
        return o + (f".btn.p,button.p,.cell.now span,.me{{color:{on(P['brand'])}}}.chip.on.p2,.bar.paid{{color:{on(P['paid'])}}}"
                    f".chip.on.f,.bar.inv{{color:{on(P['inv'])}}}.bar.todo{{color:{on(P['todo'])}}}")
    L = dict(zip(names, (c[k] for k in COLOR_KEYS))); Dk = {n: mixhex(v) for n, v in L.items()}
    return darkify(block(L) + "@media(prefers-color-scheme:dark){" + block(Dk) + "}") + f".hero{{background:color-mix(in srgb,{L['brand']} 24%,#080b1a)}}"

def logo(c, standalone=False):
    x = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ' class="lg"'
    return (f'<svg{x} viewBox="0 0 28 28"><rect width="28" height="28" rx="8" fill="{c["c_brand"]}"/><rect x="6" y="7" width="16" height="3.6" rx="1.8" fill="{c["c_todo"]}"/>'
            f'<rect x="6" y="12.2" width="11" height="3.6" rx="1.8" fill="{c["c_inv"]}"/><rect x="9" y="17.4" width="13" height="3.6" rx="1.8" fill="{c["c_paid"]}"/></svg>')

def fav(c):
    v = hashlib.sha256("".join(c[k] for k in COLOR_KEYS).encode()).hexdigest()[:6]
    return (f'<link rel="icon" type="image/svg+xml" href="/favicon.svg?v={v}"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png?v={v}">'
            f'<link rel="apple-touch-icon" href="/apple-touch-icon.png?v={v}">')

@lru_cache(maxsize=32)
def png_icon(size, cols):
    base, todo, inv, paid = (rgb(x) for x in cols)
    shapes = [(0, 0, 28, 28, 8, base), (6, 7, 16, 3.6, 1.8, todo), (6, 12.2, 11, 3.6, 1.8, inv), (9, 17.4, 13, 3.6, 1.8, paid)]
    def inside(x, y, sx, sy, w, h, r):
        if x < sx or x > sx + w or y < sy or y > sy + h: return False
        cx, cy = min(max(x, sx + r), sx + w - r), min(max(y, sy + r), sy + h - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    S, k, raw = 3, 28 / size, bytearray()
    for py in range(size):
        raw.append(0)
        for px in range(size):
            r = g = b = a = 0
            for sy in range(S):
                for sx in range(S):
                    x, y = (px + (sx + .5) / S) * k, (py + (sy + .5) / S) * k
                    col = None
                    if inside(x, y, *shapes[0][:5]):
                        col = shapes[0][5]
                        for s in shapes[1:]:
                            if inside(x, y, *s[:5]): col = s[5]
                    if col: r += col[0]; g += col[1]; b += col[2]; a += 1
            raw += bytes((r // a, g // a, b // a, 255 * a // (S * S))) if a else b"\0\0\0\0"
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))

# ---------------------------------------------------------------- publicidade (só banner de imagem ou texto)
def ad_html(c, where):
    if c["ad_on"] != "1" or c["ad_" + where] != "1": return ""
    img, link, txt = c["ad_img"], c["ad_link"], e(c["ad_text"])
    if not (img or txt): return ""
    inner = f'<img src="{e(img)}" alt="{txt}" loading="lazy" referrerpolicy="no-referrer">' if img else f"<span>{txt}</span>"
    box = f'<a class="ad" href="{e(link)}" target="_blank" rel="sponsored noopener noreferrer">{inner}</a>' if link else f'<div class="ad">{inner}</div>'
    return f'<div class="adw"><small>Publicidade</small>{box}</div>'

# ---------------------------------------------------------------- consola SQL
def sql_run(q, write):
    c = db()
    try:
        if write: make_backup("presql")
        else: c.execute("pragma query_only=1")
        cur = c.execute(q)
        if cur.description: return [d[0] for d in cur.description], cur.fetchmany(201), ""
        c.commit(); return None, None, f"Executado. Linhas alteradas: {cur.rowcount}."
    except sqlite3.Error as ex:
        m = str(ex)
        return None, None, ("Esta instrução altera dados. Marca a caixa de confirmação para a executar (é criado um backup antes)." if "readonly" in m else "Erro: " + m)
    finally: c.close()

def sql_table(cols, data):
    if cols is None: return ""
    ki = cols.index("k") if "k" in cols else -1
    def cell(r, i):
        v = r[i]
        if cols[i].lower() in ("pw", "h") or (ki >= 0 and r[ki] == "secret" and cols[i] == "v"): return "•••"
        return e("" if v is None else str(v)[:120])
    th = "".join(f'<th class="l">{e(c)}</th>' for c in cols)
    tr = "".join("<tr>" + "".join(f'<td class="l">{cell(r, i)}</td>' for i in range(len(cols))) + "</tr>" for r in data[:200])
    more = '<p class="m">A mostrar as primeiras 200 linhas.</p>' if len(data) > 200 else ""
    return f'<div class="card sc"><table class="tb"><tr>{th}</tr>{tr or "<tr><td class=l>Sem resultados.</td></tr>"}</table></div>{more}'

def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = db()
    c.executescript("""
    create table if not exists users(id integer primary key, username text unique collate nocase, email text unique collate nocase,
      name text, phone text, pw text, ics text, created text);
    create table if not exists resets(h text primary key, user_id integer references users(id) on delete cascade, exp integer);
    create table if not exists clients(id integer primary key, user_id integer not null, name text not null, nif text, contact text,
      rate text, terms text, notes text, logo text);
    create table if not exists events(id integer primary key, user_id integer not null, title text not null, start_date text not null,
      end_date text not null, client_id integer references clients(id) on delete set null, amount real default 0, invoice_date text,
      invoice_no text, paid integer default 0, paid_date text, notes text);
    create table if not exists items(id integer primary key, event_id integer references events(id) on delete cascade, label text, amount real);
    create table if not exists kv(k text primary key, v text);
    create table if not exists tickets(id integer primary key, token text unique, user_id integer, name text, email text, subject text, status text default 'open',
      lang text, created text, updated text, unread_admin integer default 1, unread_user integer default 0);
    create table if not exists pro(user_id integer primary key, visible integer default 0, headline text, city text, travel text default 'no', roles text, roles_other text,
      software text, gear text, career text, companies text, projects text, updated text);
    create table if not exists contact_req(id integer primary key, a integer not null, b integer not null, status text default 'pending', s_email integer default 0, s_phone integer default 0, created text, unique(a, b));
    create table if not exists invoice_files(event_id integer primary key references events(id) on delete cascade, name text, size integer, data blob, created text);
    create table if not exists mailcfg(user_id integer primary key, host text, port integer default 587, sec text default 'starttls', username text, pw_enc text, from_name text, from_email text, reply_to text,
      subject text, body text, signature text, send_pdf integer default 0, footer integer default 1);
    create table if not exists mail_log(id integer primary key, user_id integer, event_id integer, to_addr text, subject text, status text, error text, created text);
    create table if not exists friends(id integer primary key, a integer not null, b integer not null, status text default 'pending', created text, unique(a, b));
    create table if not exists chats(id integer primary key, kind text, name text, owner integer, created text);
    create table if not exists chat_members(chat_id integer references chats(id) on delete cascade, user_id integer, last_read integer default 0, primary key(chat_id, user_id));
    create table if not exists chat_msgs(id integer primary key, chat_id integer references chats(id) on delete cascade, user_id integer, body text, created text);
    create table if not exists chat_imgs(id integer primary key, chat_id integer, mime text, data text, created text);
    create table if not exists avatars(user_id integer primary key, mime text, data text);
    create table if not exists notifs(id integer primary key, title text, body text, tr text, created text, author integer);
    create table if not exists notif_seen(user_id integer, notif_id integer, primary key(user_id, notif_id));
    create table if not exists tmsgs(id integer primary key, ticket_id integer references tickets(id) on delete cascade, from_admin integer default 0, body text, created text);""")
    if not c.execute("select 1 from kv where k='secret'").fetchone():
        c.execute("insert into kv values('secret',?)", (secrets.token_hex(32),))
    migrate(c)
    c.commit(); c.close()

def sign(s): return hmac.new(one("select v from kv where k='secret'")["v"].encode(), s.encode(), hashlib.sha256).hexdigest()
def hash_pw(p, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 300000).hex()
def check_pw(p, stored): return hmac.compare_digest(hash_pw(p, bytes.fromhex(stored.split("$")[0])), stored)
def session_cookie(u, secure):
    x = int(time.time()) + 30 * 86400
    return ("Set-Cookie", f"s={u['id']}.{x}.{sign(f'{u['id']}.{x}.{u['pw'][-16:]}')}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if secure else ""))

# Email: por omissao usa o Gmail. Basta definir SMTP_USER (o teu Gmail) e SMTP_PASSWORD (palavra-passe de app).
# NUNCA escrevas a palavra-passe aqui no codigo: o repositorio e publico. Define-a nas variaveis do Portainer.
def smtp_conf():
    """Email do sistema: o que o admin guardou no painel tem prioridade; senão as variáveis do Portainer."""
    k = {r["k"][5:]: r["v"] for r in rows("select k, v from kv where k like 'smtp.%'")}
    if k.get("user") and k.get("pw"):
        sec = one("select v from kv where k='secret'")
        pw = mailer.dec(sec["v"], k["pw"]) if sec else None
        if pw: return {"src": "db", "host": k.get("host") or "smtp.gmail.com", "port": int(k.get("port") or 587), "sec": k.get("sec") or "starttls", "user": k["user"], "pw": pw, "frm": k.get("from") or k["user"]}
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        port = int(os.environ.get("SMTP_PORT") or 587)
        return {"src": "env", "host": os.environ.get("SMTP_HOST") or "smtp.gmail.com", "port": port, "sec": "ssl" if port == 465 else "starttls", "user": os.environ["SMTP_USER"], "pw": os.environ["SMTP_PASSWORD"], "frm": os.environ.get("SMTP_FROM") or os.environ["SMTP_USER"]}
    return None

def smtp_ready(): return smtp_conf() is not None

def send_mail(to, subject, body, strict=False):
    try:
        c = smtp_conf(); m = EmailMessage()
        m["From"] = formataddr((SN(), c["frm"])); m["To"] = to; m["Subject"] = subject; m.set_content(body)
        ctx = ssl.create_default_context()
        if c["sec"] == "ssl": s = smtplib.SMTP_SSL(c["host"], c["port"], timeout=20, context=ctx)
        else:
            s = smtplib.SMTP(c["host"], c["port"], timeout=20)
            if c["sec"] != "none" or not mailer.DEV: s.starttls(context=ctx)
        s.login(c["user"], c["pw"]); s.send_message(m, from_addr=c["frm"]); s.quit()
        print(f"Email enviado: {subject} -> {to}", flush=True)
    except Exception as ex:
        print("ERRO SMTP:", ex, flush=True)
        if strict: raise

def mail_async(to, subject, body):
    if smtp_ready(): threading.Thread(target=send_mail, args=(to, subject, body), daemon=True).start()

# ---------------------------------------------------------------- estilo
CSS = """
:root{--bg:#f1f3f6;--sf:#fff;--ink:#12161c;--mut:#67717e;--line:#e2e6eb;--brand:#3b4cdb;--todo:#e5484d;--inv:#f0a020;--paid:#2fa56b;--r:14px;--lh:24px}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--sf:#151b23;--ink:#e8ecf1;--mut:#8a95a3;--line:#242d38;--brand:#8c9bff;--inv:#f5b13d;--paid:#3fbf82}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",Roboto,"Helvetica Neue",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}h1{font-size:1.7rem;letter-spacing:-.03em;margin:0 0 6px;font-weight:700}h2{font-size:1.05rem;margin:28px 0 10px;letter-spacing:-.01em}
.sub{color:var(--mut);margin:0 0 20px}.m{color:var(--mut);font-size:.88rem}
.shell{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100vh}
.side{position:sticky;top:0;height:100vh;padding:20px 14px;display:flex;flex-direction:column;gap:2px;border-right:1px solid var(--line);background:var(--sf)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.15rem;letter-spacing:-.02em;padding:2px 10px 20px;text-decoration:none}
.lg{width:28px;height:28px;flex:none}.sp{flex:1}
.nl{display:flex;gap:12px;align-items:center;padding:10px 12px;border-radius:10px;text-decoration:none;color:var(--mut);font-weight:560}
.nl svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.nl:hover{color:var(--ink)}.nl.on{background:color-mix(in srgb,var(--brand) 13%,transparent);color:var(--brand)}
.nl.acct span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.top{display:none}.main{padding:30px clamp(14px,4vw,44px) 96px;max-width:1080px;width:100%}
.bar-h{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.btn,button{font:inherit;font-weight:600;padding:9px 16px;border-radius:10px;border:1px solid var(--line);background:var(--sf);color:var(--ink);cursor:pointer;text-decoration:none;display:inline-block}
.btn.p,button.p{background:var(--brand);border-color:var(--brand);color:#fff}@media(prefers-color-scheme:dark){.btn.p,button.p{color:#0d1117}}
button.d{color:var(--todo)}.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chips a{padding:6px 13px;border-radius:99px;border:1px solid var(--line);background:var(--sf);text-decoration:none;font-size:.88rem;color:var(--mut)}.chips a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.mn{display:flex;align-items:center;gap:8px;margin-bottom:12px}.mn b{min-width:130px;text-align:center;text-transform:capitalize}.mn a{padding:4px 12px}
.strip{display:grid;grid-template-columns:repeat(4,1fr);background:var(--sf);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.st{padding:16px 18px 14px;border-left:1px solid var(--line);border-top:3px solid var(--c,var(--line))}.st:first-child{border-left:0}
.st b{display:block;font-size:1.6rem;letter-spacing:-.03em;font-variant-numeric:tabular-nums;line-height:1.25;margin-top:2px}.st span{color:var(--mut);font-size:.85rem}
.list{background:var(--sf);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}.list>.empty{padding:18px;color:var(--mut)}
.er{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px 14px;border-top:1px solid var(--line);box-shadow:inset 3px 0 0 var(--c,transparent)}
.er:first-child{border-top:0}.todo{--c:var(--todo)}.plan{--c:#5f6b8a}.inv{--c:var(--inv)}.paid{--c:var(--paid)}
.eh{display:flex;gap:12px;align-items:center;text-decoration:none;min-width:0;flex:1}.eh b{display:block;font-weight:620}.eh small{color:var(--mut);display:block;font-size:.85rem}
.eh>div{min-width:0}.ea{display:flex;align-items:center;gap:12px;justify-content:flex-end}.amt{font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap}
.late{color:var(--todo);font-style:normal;font-weight:600}
.av{width:38px;height:38px;border-radius:10px;object-fit:contain;background:var(--bg);display:inline-grid;place-items:center;font-weight:700;font-size:.8rem;color:var(--mut);flex:none;border:1px solid var(--line)}
.tg{display:flex;gap:6px}.tg form{margin:0}.chip{font:inherit;font-size:.8rem;font-weight:600;padding:5px 11px;border-radius:99px;border:1px solid var(--line);background:none;color:var(--mut);cursor:pointer}
.chip.on.f{background:var(--inv);border-color:var(--inv);color:#1b1300}.chip.on.p2{background:var(--paid);border-color:var(--paid);color:#fff}
.card{background:var(--sf);border:1px solid var(--line);border-radius:var(--r);padding:18px;margin-bottom:14px}.card h2{margin-top:0}
form.f label{display:block;margin:14px 0 4px;font-weight:600;font-size:.86rem;color:var(--mut)}form.f label:first-child{margin-top:0}
form.f input:not([type=checkbox]),form.f select,form.f textarea{width:100%;font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
input:focus,select:focus,textarea:focus,button:focus-visible,a:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
form.f label.c{display:flex;gap:10px;align-items:center;color:var(--ink);font-size:1rem;font-weight:500}form.f input[type=checkbox]{width:20px;height:20px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.it{display:grid;grid-template-columns:1fr 140px;gap:8px;margin-bottom:8px}
.sum{display:flex;justify-content:space-between;align-items:center;padding:10px 2px;font-weight:700}.sum span{font-size:1.3rem;font-variant-numeric:tabular-nums}
.info{background:color-mix(in srgb,var(--brand) 10%,transparent);padding:10px 12px;border-radius:10px;margin-top:8px;font-size:.9rem}.info[hidden]{display:none}
details summary{cursor:pointer;color:var(--todo);margin-top:18px}.msg{padding:10px 12px;border-radius:10px;margin:0 0 14px;font-size:.92rem}.msg.err{background:color-mix(in srgb,var(--todo) 14%,transparent);color:var(--todo)}.msg.ok{background:color-mix(in srgb,var(--paid) 16%,transparent)}
.cal{background:var(--sf);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.dh,.wk{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}.dh div{padding:9px 8px;color:var(--mut);font-size:.8rem;font-weight:600;border-left:1px solid var(--line)}.dh div:first-child{border-left:0}.dh{border-bottom:1px solid var(--line)}
.wk{min-height:98px;border-top:1px solid var(--line)}.wk:nth-of-type(2){border-top:0}
.cell{border-left:1px solid var(--line);padding:6px 8px;text-decoration:none;font-size:.82rem;font-weight:600}.cell.c0{border-left:0}.cell:hover{background:color-mix(in srgb,var(--brand) 7%,transparent)}
.cell.we{background:color-mix(in srgb,var(--bg) 55%,transparent)}.cell.out{opacity:.45}.cell.now span{background:var(--brand);color:#fff;border-radius:99px;padding:2px 8px}
@media(prefers-color-scheme:dark){.cell.now span{color:#0d1117}}
.bar{z-index:1;height:calc(var(--lh) - 2px);line-height:calc(var(--lh) - 2px);margin:1px 0;padding:0 8px;font-size:.78rem;font-weight:600;color:#fff;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:var(--c)}
.bar.inv{color:#1b1300}.bar.cs{border-radius:7px 0 0 7px;margin-left:5px}.bar.ce{border-radius:0 7px 7px 0;margin-right:5px}.bar.cs.ce{border-radius:7px}
.lgd{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}.lgd span:before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--c);margin-right:6px}
.lds{display:flex;gap:6px;flex-wrap:wrap}.ld{font-size:.78rem;padding:3px 10px;border-radius:99px;border:1px solid var(--line)}.ld:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-right:6px}.ld b{margin-right:4px}.card .fl{margin-bottom:10px}.ch{width:100%;height:auto}.ch text{fill:var(--mut);font-size:11px}.ch .gl{stroke:var(--line)}.ch .b1{fill:var(--brand)}.ch .b2{fill:var(--paid)}
.hb{display:grid;grid-template-columns:minmax(70px,170px) 1fr auto;gap:10px;align-items:center;padding:5px 0}.hb .t{background:var(--bg);border-radius:99px;height:10px}.hb i{display:block;height:10px;border-radius:99px;background:var(--brand)}.hb b{font-variant-numeric:tabular-nums;font-size:.9rem}
.sc{overflow-x:auto}.tb{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}.tb th,.tb td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}.tb th:first-child,.tb td:first-child{text-align:left}.tb th{color:var(--mut);font-weight:600;font-size:.82rem}
.tb tr.best td{background:color-mix(in srgb,var(--paid) 12%,transparent)}.tb tr.worst td{background:color-mix(in srgb,var(--todo) 10%,transparent)}
.auth{display:grid;grid-template-columns:1.15fr 1fr;min-height:100vh}.hero{background:#0f1635;color:#e9edff;padding:clamp(28px,6vw,72px);display:flex;flex-direction:column;justify-content:center;gap:22px}
.hero h1{font-size:clamp(1.9rem,3.4vw,2.9rem);line-height:1.1;max-width:15em;margin:0}.hero p{color:#aab4e6;max-width:30em;margin:0}.hero .brand{padding:0}
.tl{display:grid;gap:8px;margin-top:8px}.tl div{position:relative;height:34px;background:#18214a;border-radius:8px}.tl i{position:absolute;top:4px;bottom:4px;border-radius:6px;font:600 .75rem/26px inherit;font-style:normal;padding:0 9px;color:#fff;overflow:hidden;white-space:nowrap;background:var(--c)}.tl i.inv{color:#1b1300}
.hero .lgd{color:#aab4e6;font-size:.85rem}.ap{display:grid;place-items:center;padding:28px 18px}.ac{width:100%;max-width:400px}.ac h1{font-size:1.5rem}.ac .l2{margin-top:16px;text-align:center}.ac .l2 a{color:var(--brand)}
@media(max-width:820px){.shell{display:block}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:var(--sf);border-bottom:1px solid var(--line)}.top .brand{padding:0}
.me{width:34px;height:34px;border-radius:99px;background:var(--brand);color:#fff;display:grid;place-items:center;font-weight:700;font-size:.8rem;text-decoration:none}
.side{position:fixed;top:auto;bottom:0;left:0;right:0;height:auto;flex-direction:row;padding:4px 4px calc(4px + env(safe-area-inset-bottom));border-top:1px solid var(--line);border-right:0;z-index:20}
.side .brand,.side .sp,.side .acct{display:none}.nl{flex:1;flex-direction:column;gap:1px;padding:6px 2px;font-size:.68rem;align-items:center;text-align:center}
.main{padding-top:18px}.strip{grid-template-columns:1fr 1fr}.st:nth-child(3){border-left:0}.st:nth-child(n+3){border-top:3px solid var(--c)}.st b{font-size:1.3rem}
.er{flex-wrap:wrap}.ea{width:100%;justify-content:space-between}:root{--lh:20px}.bar{font-size:.68rem;padding:0 4px}.cell{padding:3px 4px;font-size:.74rem}.wk{min-height:84px}
.auth{grid-template-columns:1fr}.hero{padding:24px 18px;gap:12px}.hero .tl,.hero .lgd,.hero p{display:none}.hero h1{font-size:1.5rem}.g2{grid-template-columns:1fr}.it{grid-template-columns:1fr 110px}.hb{grid-template-columns:90px 1fr auto}}
"""
CSS += guide_art.CSS

def darkify(css):
    """converte cada @media(prefers-color-scheme:dark){...} para funcionar tambem com data-theme=dark e respeitar data-theme=light"""
    out, i, key = [], 0, "@media(prefers-color-scheme:dark){"
    while True:
        j = css.find(key, i)
        if j < 0: out.append(css[i:]); break
        out.append(css[i:j]); k = j + len(key); depth = 1; m = k
        while depth:
            ch = css[m]; depth += (ch == "{") - (ch == "}"); m += 1
        inner = css[k:m - 1]; auto, forced = [], []
        for rule in inner.split("}"):
            if "{" not in rule: continue
            sel, body = rule.split("{", 1)
            sels = [x.strip() for x in sel.split(",")]
            auto.append(",".join(":root:not([data-theme=light])" + ("" if x == ":root" else " " + x) for x in sels) + "{" + body + "}")
            forced.append(",".join(":root[data-theme=dark]" + ("" if x == ":root" else " " + x) for x in sels) + "{" + body + "}")
        out.append("@media(prefers-color-scheme:dark){" + "".join(auto) + "}" + "".join(forced)); i = m
    return "".join(out)

CSS += people.CSS
CSS = darkify(CSS)

CSS += """
.adw{margin:0 0 18px}.adw small{display:block;color:var(--mut);font-size:.7rem;margin-bottom:3px}
.ad{display:block;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--sf);text-decoration:none;text-align:center}
.ad img{display:block;margin:0 auto;max-width:100%;max-height:120px;object-fit:contain}.ad span{display:block;padding:12px 14px;font-weight:600}
.tb td.l,.tb th.l{text-align:left}.tb td a{text-decoration:none}
.bd{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--line);color:var(--mut)}
.bd.a{background:color-mix(in srgb,var(--brand) 18%,transparent);color:var(--brand)}.bd.s{background:color-mix(in srgb,var(--todo) 18%,transparent);color:var(--todo)}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}form.f .g4 input[type=color]{padding:3px;height:44px;cursor:pointer}
.pre{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.pre button{font-size:.85rem;padding:6px 12px}
code,textarea.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.88rem}
.bk{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:9px 0;border-top:1px solid var(--line)}.bk:first-of-type{border-top:0}
.row2{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row2 form{margin:0}
@media(max-width:820px){.g4{grid-template-columns:1fr 1fr}}
.lang{display:flex;gap:5px;justify-content:center;flex-wrap:wrap}.lang a{font-size:.75rem;font-weight:700;padding:3px 9px;border-radius:99px;border:1px solid var(--line);text-decoration:none;color:var(--mut)}
.lang a:hover{color:var(--ink)}.lang a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}.lang.full{justify-content:flex-start}.lang.full a{font-size:.9rem;padding:7px 14px}
.ft{margin-top:40px;display:flex;flex-direction:column;gap:12px;align-items:center;text-align:center}.fl{display:flex;gap:18px}.fl a{color:var(--mut);text-decoration:none;font-size:.9rem;font-weight:560}.fl a:hover{color:var(--ink)}
.flag{width:18px;height:12px;vertical-align:-1px;border-radius:2px}.pub{max-width:660px;margin:0 auto;padding:28px clamp(14px,4vw,24px) 40px}.pub .brand{padding-left:0}
.btn.sup{width:100%;text-align:center}.btn.sup svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px;margin-right:6px}
.msgs{display:flex;flex-direction:column;gap:10px;margin:16px 0}.mg{max-width:90%;padding:10px 14px;border-radius:14px;background:var(--sf);border:1px solid var(--line);white-space:pre-wrap;overflow-wrap:anywhere}
.mg.a{align-self:flex-end;background:color-mix(in srgb,var(--brand) 12%,var(--sf));border-color:color-mix(in srgb,var(--brand) 30%,var(--line))}.mg small{display:block;color:var(--mut);font-size:.75rem;margin-bottom:2px}
.main.chat{max-width:none;padding:14px 18px}
.cw{display:grid;grid-template-columns:350px minmax(0,1fr);height:calc(100vh - 28px);background:var(--sf);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.cw input{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);width:100%}
.cl{display:flex;flex-direction:column;border-right:1px solid var(--line);min-height:0}.cl .ch{display:flex;justify-content:space-between;align-items:center;padding:14px 16px 6px;font-size:1.25rem}
.cl>input{width:auto;margin:6px 12px}.tabs{display:flex;gap:4px;padding:0 10px 8px;border-bottom:1px solid var(--line)}
.tabs button{flex:1;border:0;background:none;border-radius:8px;padding:7px 4px;font-size:.85rem;font-weight:600;color:var(--mut)}.tabs button.on{background:color-mix(in srgb,var(--brand) 13%,transparent);color:var(--brand)}
.tabs .nb{margin:0 0 0 5px}.pn{overflow:auto;flex:1;min-height:0}.pn[hidden]{display:none}.cl .msg{margin:6px 12px}
.ci{display:flex;gap:11px;align-items:center;width:100%;padding:10px 14px;border:0;border-radius:0;background:none;text-align:left;text-decoration:none;color:inherit;font-weight:400;cursor:pointer}
.ci:hover{background:var(--bg)}.ci.on{background:color-mix(in srgb,var(--brand) 10%,transparent)}.ci[hidden]{display:none}
.ct{flex:1;min-width:0}.ct b{display:block;font-weight:620;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ct small{display:block;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.82rem}
.cm{display:flex;flex-direction:column;align-items:flex-end;gap:4px;font-size:.72rem;color:var(--mut)}.cm .nb{margin:0}
.avw{position:relative;flex:none;display:inline-block}.av.u{border-radius:50%;object-fit:cover}.av.g{background:color-mix(in srgb,var(--brand) 18%,var(--bg));color:var(--brand)}
.dot{position:absolute;inset:-3px;border-radius:50%;border:3px solid var(--paid);pointer-events:none}.dot[hidden]{display:none}
.sh{padding:12px 14px 4px;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);font-weight:700}.pn .empty{padding:18px 14px;color:var(--mut);font-size:.9rem}
.ca{display:flex;gap:6px;padding:10px 12px;margin:0}.ca input{flex:1;min-width:0}.rq{display:flex;align-items:center;gap:8px;padding:6px 14px}.rq form{margin:0}.rq button{padding:4px 10px;font-size:.82rem}
.crm{display:flex;flex-direction:column;min-width:0;min-height:0}.rh{display:flex;gap:12px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);position:relative}
.rh .back{display:none;text-decoration:none;font-size:1.7rem;line-height:1;padding:0 6px}.rt{flex:1;min-width:0}.rt b{display:block}.rt small{color:var(--mut)}.rt small.ty{color:var(--paid);font-style:italic}
.rm{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:5px;background:var(--bg);min-height:0}
.rm .mg{align-self:flex-start;padding:6px 11px 4px;max-width:min(80%,540px);border-top-left-radius:4px}.rm .mg.a{align-self:flex-end;border-top-left-radius:14px;border-top-right-radius:4px}
.who{display:block;font-weight:700;font-size:.74rem;color:var(--brand);margin:0}.tm{float:right;margin:7px 0 0 12px;font-size:.66rem;color:var(--mut)}.tk{font-style:normal;margin-left:4px}.tk.rd{color:var(--brand)}
.ds{align-self:center;background:var(--sf);border:1px solid var(--line);color:var(--mut);font-size:.72rem;padding:2px 12px;border-radius:99px;margin:8px 0}
#more{align-self:center;font-size:.8rem;padding:4px 14px;margin-bottom:6px}.rc{display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--line);margin:0}.rc input{flex:1}
.gi{margin-left:auto;position:static}.gi summary{cursor:pointer;list-style:none;font-size:1.3rem;padding:2px 10px;color:var(--mut)}.gi summary::-webkit-details-marker{display:none}
.gi .gp{position:absolute;right:10px;top:100%;z-index:20;width:min(340px,92vw);background:var(--sf);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:0 10px 36px #0003}
.gi .gp select{width:100%;margin:6px 0}.gi .mb{display:flex;align-items:center;gap:8px;margin:5px 0}.gi .mb span{flex:1}.gi .mb button{padding:2px 8px;font-size:.78rem}
.ro{display:grid;place-items:center;height:100%;text-align:center;color:var(--mut);padding:30px}.ro .big{font-size:3rem}.gf{max-height:46vh;overflow:auto;margin:8px 0}
.gnew{padding:18px;overflow:auto}.gnew h2{margin-top:0}.gnew .back{display:none}
.toast{position:fixed;right:16px;top:16px;z-index:60;background:var(--ink);color:var(--bg);padding:12px 16px;border-radius:12px;text-decoration:none;box-shadow:0 8px 30px #0005;transition:.4s;max-width:320px;font-weight:600}.toast.go{opacity:0;transform:translateY(-10px)}
.ib{border:0;background:none;padding:2px 6px;font-size:1rem}.ib[hidden]{display:none}.nt{margin-bottom:12px}.nt h2{margin:0 0 4px}.nt .bd{margin-left:6px}.nt p{white-space:pre-wrap;margin:8px 0 0}
.me{overflow:hidden;position:relative}.me img{width:100%;height:100%;object-fit:cover;display:block}.bell{position:relative;display:inline-flex}.bell svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.bell .nb{position:absolute;top:-6px;right:-8px;margin:0}.avset{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.avset .av{width:72px;height:72px;font-size:1.5rem}
@media(max-width:820px){.main.chat{padding:0}.cw{grid-template-columns:1fr;height:calc(100dvh - 56px - 68px);border-radius:0;border-left:0;border-right:0}.cw.open .cl{display:none}.cw:not(.open) .crm{display:none}.rh .back,.gnew .back{display:block}}
.tip{display:flex;align-items:center;gap:6px;background:color-mix(in srgb,var(--brand) 11%,var(--sf));border:1px solid color-mix(in srgb,var(--brand) 30%,var(--line));border-radius:12px;padding:8px 8px 8px 14px;margin-bottom:14px}.tip a{flex:1;text-decoration:none;color:var(--ink);font-weight:600;font-size:.92rem}.tip form{margin:0}.tip .ib{color:var(--mut)}
.tl{display:block;text-align:right;color:var(--mut);font-size:.78rem;font-variant-numeric:tabular-nums}.cu{margin-top:6px}.cu[hidden]{display:none}.tx div{display:flex;justify-content:space-between;padding:3px 2px;color:var(--mut);font-variant-numeric:tabular-nums}.tx .tt{color:var(--ink);font-weight:700;font-size:1.05rem;border-top:1px solid var(--line);margin-top:4px;padding-top:8px}
.gc{display:flex;gap:14px;align-items:center;text-decoration:none;color:inherit;margin-bottom:10px}.gc:hover{border-color:var(--brand)}.gn{width:30px;height:30px;border-radius:50%;background:var(--brand);color:#fff;display:grid;place-items:center;font-weight:700;font-size:.85rem;flex:none}.gi2{font-size:1.5rem}.gt p,.gt li{font-size:1.02rem;line-height:1.55}.gt li{margin:8px 0}
.nb[hidden]{display:none}.av.s{width:18px;height:18px;font-size:.6rem;border-radius:50%;vertical-align:middle;margin-right:5px;display:inline-grid;place-items:center;object-fit:cover}
.mi{display:block;max-width:100%;max-height:300px;border-radius:10px;margin:2px 0 4px;cursor:zoom-in}.mx{color:var(--mut);font-style:italic}
.rc .ib{font-size:1.35rem;padding:4px 8px;background:none;border:0;color:var(--mut)}.rc{position:relative;align-items:center}
.ep{position:absolute;bottom:100%;left:8px;z-index:30;width:min(340px,94vw);max-height:230px;overflow:auto;background:var(--sf);border:1px solid var(--line);border-radius:12px;padding:8px;box-shadow:0 10px 36px #0003;display:grid;grid-template-columns:repeat(8,1fr);gap:2px}
.ep[hidden]{display:none}.ep button{border:0;background:none;font-size:1.35rem;padding:3px;border-radius:8px;cursor:pointer}.ep button:hover{background:var(--bg)}
.nb[hidden]{display:none}.nl{position:relative}.nb{background:var(--todo);color:#fff;border-radius:99px;font-size:.68rem;font-weight:700;padding:0 6px;min-width:18px;text-align:center;line-height:18px;font-style:normal;margin-left:auto}
@media(max-width:820px){.nl .nb{position:absolute;top:1px;left:calc(50% + 6px);margin:0}}
.chatbox{height:min(58vh,520px);overflow:auto;margin:14px 0;padding:4px 2px}.chatbox .msgs{margin:0}.row2 input[type=text],.row2 input:not([type]){flex:1;min-width:180px}
.ab li{margin:7px 0}.ab ul{padding-left:20px;margin:6px 0}.cr{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
"""

IC = {"home": '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
      "cal": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
      "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
      "users": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
      "chart": '<path d="M5 20V11M12 20V4M19 20v-6"/>',
      "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9L7 7M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>'}
NAV = [("/", "Início", "home"), ("/calendar", "Calendário", "cal"), ("/events", "Eventos", "list"), ("/clients", "Clientes", "users"), ("/chat", "Chat", "chat"), ("/people", "AV Freelancers", "net"), ("/stats", "Estatísticas", "chart")]
IC["shield"] = '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>'
IC["net"] = '<circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M12 7.5v4M12 11.5l-5.5 4.5M12 11.5l5.5 4.5"/>'
IC["chat"] = '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'
FLAG = ('<svg class="flag" viewBox="0 0 30 20" role="img" aria-label="Portugal"><rect width="30" height="20" fill="#d4202c"/><rect width="12" height="20" fill="#046a38"/>'
        '<circle cx="12" cy="10" r="4" fill="#ffd400" stroke="#fff" stroke-width=".7"/></svg>')
SUPBTN = f'<p class="l2"><a class="btn sup" href="/support"><svg viewBox="0 0 24 24">{IC["chat"]}</svg>Suporte</a></p>'

def langbar(full=False):
    cur, nx = i18n.lang(), quote(i18n.path(), safe="")
    return (f'<div class="lang{" full" if full else ""}">' + "".join(
        f'<a href="/lang?l={k}&amp;next={nx}" hreflang="{k}"{" class=on aria-current=true" if k == cur else ""}>{v if full else k.upper()}</a>' for k, v in i18n.LANGS.items()) + "</div>")

def foot(n=0):
    b = f' <span class="bd s">{n}</span>' if n else ""
    return (f'<footer class="ft">{langbar()}<div class="fl"><a href="/support">Suporte{b}</a><a href="/guide">Como funciona</a><a href="/about">Sobre</a></div>'
            f'<div class="m">Feito por Daniel Nunes · Made in Portugal {FLAG}</div></footer>')

def head(t, c):
    th = getattr(THR, "theme", "auto"); th = th if th in ("light", "dark") else ""
    return ('<!doctype html><html lang="' + i18n.lang() + '"' + (f' data-theme="{th}"' if th else "") + '><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="'
            + c["c_brand"] + '"><link rel="manifest" href="/manifest.webmanifest"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="' + html.escape(SN()) + '"><meta name="apple-mobile-web-app-status-bar-style" content="default"><title>' + t + '</title>' + fav(c) + '<style>' + CSS + theme_css(c) + '</style></head><body>')

def page(title, body, active, u):
    c = cfg(); sn = e(c["site_name"]); lg = logo(c)
    cb = chat_badge(u["id"]); nn = notif_unread(u)
    pq = one("select count(*) from contact_req where b=? and status='pending'", (u["id"],))[0]
    pnb = f'<i class="nb" data-k="people"{"" if pq else " hidden"}>{pq}</i>'
    chatnb = f'<i class="nb" data-k="chat"{"" if cb else " hidden"}>{cb}</i>'
    nav = "".join(f'<a class="nl{" on" if h == active else ""}" href="{h}"><svg viewBox="0 0 24 24">{IC[i]}</svg>{'<span><b class="lg">' + n + '</b><b class="sm">Rede</b></span>' if h == "/people" else '<span>' + n + '</span>'}{chatnb if h == "/chat" else pnb if h == "/people" else ""}</a>' for h, n, i in NAV)
    nbn = f'<i class="nb" data-k="notif"{"" if nn else " hidden"}>{nn}</i>'
    adm = f'<a class="nl acct{" on" if active == "/admin" else ""}" href="/admin"><svg viewBox="0 0 24 24">{IC["shield"]}</svg><span>Admin</span></a>' if u["is_admin"] else ""
    madm = '<a class="btn" style="padding:4px 12px" href="/admin">Admin</a>' if u["is_admin"] else ""
    nu = one("select count(*) from tickets where user_id=? and unread_user=1", (u["id"],))[0]
    madm += f'<a class="btn" style="padding:4px 12px" href="/support">💬 {nu}</a>' if nu else ""
    adm = f'<a class="nl acct{" on" if active == "/notifications" else ""}" href="/notifications"><svg viewBox="0 0 24 24">{IC["bell"]}</svg><span>Novidades</span>{nbn}</a>' + adm
    madm = f'<a class="btn bell" style="padding:5px 10px" href="/notifications" aria-label="Novidades"><svg viewBox="0 0 24 24">{IC["bell"]}</svg>{nbn}</a>' + madm
    acct = f'<a class="nl acct{" on" if active == "/settings" else ""}" href="/settings"><svg viewBox="0 0 24 24">{IC["gear"]}</svg><span>{e(u["name"] or u["username"])}</span></a>'
    top = (f'<div class="top"><a class="brand" href="/guide" title="Como funciona">{lg}{sn}</a><div style="display:flex;gap:10px;align-items:center">{madm}'
           f'<a class="me" href="/settings" aria-label="Conta">{f'<img src="/avatar/{u["id"]}?v={u["av_v"]}" alt="">' if u["av_v"] else e(ini(u["name"] or u["username"]))}</a></div></div>')
    return (head(eh(title) + " · " + sn, c) + f'<div class="shell"><nav class="side"><a class="brand" href="/guide" title="Como funciona">{lg}{sn}</a>{nav}<div class="sp"></div>{adm}{acct}</nav>'
            f'<div>{top}<main class="main{" chat" if active == "/chat" else ""}">{"" if active == "/chat" else ad_html(c, "app")}{body}{"" if active == "/chat" else foot(nu)}</main></div>'
            f'<div id="i18n" hidden data-online="{eh(tx("online"))}" data-seen="{eh(tx("visto por último"))}" data-typing="{eh(tx("a escrever..."))}" data-today="{eh(tx("Hoje"))}" data-yest="{eh(tx("Ontem"))}" data-gone="{eh(tx("Imagem expirada"))}"></div>'
            f'<script src="/app.js?v={JSV}" data-uid="{u["id"]}" defer></script></body></html>')

TL = ('<div class="tl"><div><i class="paid" style="left:2%;width:30%">Casamento</i><i class="inv" style="left:38%;width:24%">Conferência</i></div>'
      '<div><i class="todo" style="left:12%;width:26%">Videoclip</i><i class="paid" style="left:46%;width:40%">Festival · 3 dias</i></div>'
      '<div><i class="inv" style="left:0;width:20%">Spot</i><i class="todo" style="left:44%;width:30%">Institucional</i></div></div>'
      '<div class="lgd"><span style="--c:var(--todo)">por faturar</span><span style="--c:var(--inv)">faturada</span><span style="--c:var(--paid)">paga</span></div>')

def auth_page(title, inner):
    c = cfg(); sn = e(c["site_name"]); lg = logo(c)
    ht = eh(c["hero_title"]) if c["hero_title"] == DEFAULTS["hero_title"] else e(c["hero_title"])
    hx = eh(c["hero_text"]) if c["hero_text"] == DEFAULTS["hero_text"] else e(c["hero_text"])
    return (head(eh(title) + " · " + sn, c) + f'<div class="auth"><section class="hero"><a class="brand" href="/guide" title="Como funciona">{lg}{sn}</a>'
            f'<h1>{ht}</h1><p>{hx}</p>{TL}</section><section class="ap"><div class="ac">{inner}{ad_html(c, "auth")}{foot()}</div></section></div></body></html>')

def pub_page(title, body):
    c = cfg(); sn = e(c["site_name"]); lg = logo(c)
    return head(eh(title) + " · " + sn, c) + f'<div class="pub"><a class="brand" href="/guide" title="Como funciona">{lg}{sn}</a><main>{ad_html(c, "auth")}{body}{foot()}</main></div></body></html>'

COUNTRIES = {"PT": ("Portugal (continente)", (23, 13, 6)), "PT-MA": ("Portugal (Madeira)", (22, 12, 4)), "PT-AC": ("Portugal (Açores)", (16, 9, 4)),
             "ES": ("España", (21, 10, 4)), "FR": ("France", (20, 10, 5.5)), "IT": ("Italia", (22, 10, 5)), "GB": ("United Kingdom", (20, 5))}
WH_RATES = (23, 16.5, 11.5)
VATSQL = "(case when vat_mode='rate' then amount*vat_rate/100.0 else 0 end)"
WHSQL = "(amount*wh_rate/100.0)"
CASHSQL = f"(amount+{VATSQL}-{WHSQL})"

def pct(x): return f"{x:g}".replace(".", dsep())
def vat_code(mode, rate): return mode if mode in ("none", "rc") else f"{rate:g}"
def parse_vat(code, custom=""):
    if code == "rc": return "rc", 0.0
    r = num(custom) if code == "custom" else (0.0 if code in ("none", "", None) else num(code))
    return ("rate", min(r, 100.0)) if r > 0 else ("none", 0.0)
def parse_wh(code, custom=""):
    r = num(custom) if code == "custom" else num(code or "0"); return min(max(r, 0.0), 60.0)
def tax_of(r):
    base = r["amount"] or 0; v = base * (r["vat_rate"] or 0) / 100 if r["vat_mode"] == "rate" else 0.0; w = base * (r["wh_rate"] or 0) / 100
    return v, w, base + v - w

def vat_select(country, code, name="vat", cname="vatc", cval=""):
    rates = COUNTRIES.get(country, COUNTRIES["PT"])[1]
    opts = [("none", "Sem IVA (isento)")] + [(f"{x:g}", f"IVA {pct(x)}%") for x in rates] + [("rc", "IVA liquidado pelo cliente (autoliquidação)")]
    if code not in {o[0] for o in opts}: opts.insert(1, (code, f"IVA {pct(num(code))}%"))
    opts.append(("custom", "Outra taxa..."))
    o = "".join(f'<option value="{k}"{" selected" if k == code else ""}>{l}</option>' for k, l in opts)
    return f'<select name="{name}" data-cu="{cname}">{o}</select><input class="cu" name="{cname}" inputmode="decimal" placeholder="%" value="{e(cval)}" hidden>'

def wh_select(rate, name="wh", cname="whc"):
    code = f"{rate:g}" if rate else "0"
    opts = [("0", "Sem retenção")] + [(f"{x:g}", f"Retenção {pct(x)}%") for x in WH_RATES]
    if code not in {o[0] for o in opts}: opts.insert(1, (code, f"Retenção {pct(rate)}%"))
    opts.append(("custom", "Outra taxa..."))
    o = "".join(f'<option value="{k}"{" selected" if k == code else ""}>{l}</option>' for k, l in opts)
    return f'<select name="{name}" data-cu="{cname}">{o}</select><input class="cu" name="{cname}" inputmode="decimal" placeholder="%" hidden>'

CUJS = '<script nonce="__NONCE__">document.querySelectorAll("select[data-cu]").forEach(function(s){var i=s.parentNode.querySelector("[name="+s.dataset.cu+"]");function t(){i.hidden=s.value!="custom";if(!i.hidden)i.focus()}s.addEventListener("change",t)})</script>'

def uname(r): return (r["name"] or r["username"]) if r else "?"
IC["bell"] = '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'

def uav(r, extra=""):
    if r is not None and r["av_v"]: return f'<img class="av u{extra}" src="/avatar/{r["id"]}?v={r["av_v"]}" alt="" loading="lazy">'
    return f'<span class="av u{extra}">{e(ini(uname(r)))}</span>'

def day_label(d):
    if d == today().isoformat(): return eh("Hoje")
    if d == (today() - dt.timedelta(1)).isoformat(): return eh("Ontem")
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}"

def pres_text(r):
    if is_online(r["id"]): return eh("online")
    ls = r["last_seen"]
    if not ls: return ""
    d = ls[:10]
    return eh("visto por último") + " " + (ls[11:16] if d == today().isoformat() else (eh("ontem") + " " + ls[11:16]) if d == (today() - dt.timedelta(1)).isoformat() else f"{ls[8:10]}/{ls[5:7]}")

def hm(ts):
    if not ts: return ""
    return ts[11:16] if ts[:10] == today().isoformat() else day_label(ts[:10]) if ts[:10] == (today() - dt.timedelta(1)).isoformat() else f"{ts[8:10]}/{ts[5:7]}"

def notif_unread(u):
    return one("select count(*) from notifs n where substr(n.created,1,10) >= ? and n.id not in (select notif_id from notif_seen where user_id=?)", (u["created"] or "", u["id"]))[0]

def notif_text(n):
    try: v = (json.loads(n["tr"] or "{}")).get(i18n.lang()) or {}
    except ValueError: v = {}
    return v.get("t") or n["title"], v.get("b") or n["body"]

PULSE = {}
def is_online(uid): return ws.hub.online(uid) or time.time() - PULSE.get(uid, 0) < 45

def purge_imgs():
    lim = (dt.datetime.now() - dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
    run("delete from chat_imgs where created < ?", (lim,))

def img_loop():
    while True:
        try: purge_imgs()
        except Exception: pass
        time.sleep(3600)

def push_sync(*uids): ws.hub.push([x for x in uids if x], {"e": "sync"})
def member_ids(cid): return [r["user_id"] for r in rows("select user_id from chat_members where chat_id=?", (cid,))]

def presence(uid, on):
    if not on: run("update users set last_seen=? where id=?", (now_str(), uid))
    ws.hub.push([x["id"] for x in friends_of(uid)], {"e": "presence", "u": uid, "on": on, "ls": now_str()})

def msg_html(x, me, dm, plr):
    mine = x["user_id"] == me
    who = "" if mine or dm else f'<small class="who">{uav(dict(id=x["user_id"], av_v=x["av_v"], name=x["name"], username=x["username"]), " s")}{e(uname(x))}</small>'
    tk = (f'<i class="tk{" rd" if x["id"] <= plr else ""}">{"✓✓" if x["id"] <= plr else "✓"}</i>') if mine and dm else ""
    im = ""
    if x["img"]: im = (f'<a href="/chat/img/{x["img"]}" target="_blank" rel="noopener"><img class="mi" src="/chat/img/{x["img"]}" loading="lazy" alt=""></a>' if x["ie"] else f'<span class="mx">📷 {eh("Imagem expirada")}</span> ')
    return f'<div class="mg{" a" if mine else ""}" data-id="{x["id"]}" data-day="{x["created"][:10]}">{who}{im}{e(x["body"])}<span class="tm">{x["created"][11:16]}{tk}</span></div>'

def chat_panels(u, cur=0):
    me = u["id"]
    cs = rows("select c.*, m.last_read from chats c join chat_members m on m.chat_id=c.id and m.user_id=?", (me,))
    ids = [c["id"] for c in cs]; last, unread, peer, nmem = {}, {}, {}, {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in rows(f"select * from chat_msgs where id in (select max(id) from chat_msgs where chat_id in ({q}) group by chat_id)", ids): last[r["chat_id"]] = r
        for r in rows(f"select m.chat_id, count(*) n from chat_msgs m join chat_members cm on cm.chat_id=m.chat_id and cm.user_id=? where m.chat_id in ({q}) and m.id>cm.last_read and m.user_id!=? group by m.chat_id", [me] + ids + [me]): unread[r["chat_id"]] = r["n"]
        for r in rows(f"select cm.chat_id, u.* from chat_members cm join users u on u.id=cm.user_id where cm.chat_id in ({q}) and cm.user_id!=?", ids + [me]): peer[r["chat_id"]] = r
        for r in rows(f"select chat_id, count(*) n from chat_members where chat_id in ({q}) group by chat_id", ids): nmem[r["chat_id"]] = r["n"]
    cs.sort(key=lambda c: (last[c["id"]]["id"] if c["id"] in last else 0, c["id"]), reverse=True)
    def item(c, sub=None):
        dm = c["kind"] == "dm"; o = peer.get(c["id"]); title = uname(o) if dm else c["name"]
        av = uav(o) if dm and o else f'<span class="av u g">{e(ini(title))}</span>'
        dot = f'<i class="dot" data-pres="{o["id"]}"{"" if is_online(o["id"]) else " hidden"}></i>' if dm and o else ""
        l = last.get(c["id"]); n = unread.get(c["id"], 0)
        if sub is None:
            lb = (l["body"][:70] or "") if l and not l["img"] else (("📷 ") if l else "")
            ph = lambda: eh("Foto") if l and l["img"] and not l["body"] else ""
            if not l: sub = eh("Sem mensagens.")
            elif l["user_id"] == me: sub = eh("Tu:") + " " + e(lb) + ph() + e(l["body"][:60] if l["img"] else "")
            elif dm: sub = e(lb) + ph() + e(l["body"][:60] if l["img"] else "")
            else: sub = e(uname(one("select * from users where id=?", (l["user_id"],))) + ": ") + e(lb) + ph() + e(l["body"][:60] if l["img"] else "")
        return (f'<a class="ci{" on" if c["id"] == cur else ""}" href="/chat/{c["id"]}" data-cid="{c["id"]}" data-q="{e(title.lower())}"><span class="avw">{av}{dot}</span>'
                f'<span class="ct"><b>{e(title)}</b><small>{sub}</small></span><span class="cm"><span>{hm(l["created"]) if l else ""}</span>'
                f'{f"<i class=nb>{n}</i>" if n else ""}</span></a>')
    convs = "".join(item(c) for c in cs) or '<div class="empty">Ainda não tens conversas. Adiciona um amigo para começar.</div>'
    groups = "".join(item(c, pl(nmem.get(c["id"], 1), "membro")) for c in sorted((c for c in cs if c["kind"] == "group"), key=lambda c: c["name"].lower()))
    groups = '<div style="padding:10px 12px"><a class="btn p" href="/chat/new" style="width:100%;text-align:center">Novo grupo</a></div>' + (groups or '<div class="empty">Ainda não tens grupos.</div>')
    fr = friends_of(me); fr.sort(key=lambda r: (not is_online(r["id"]), uname(r).lower()))
    pin = rows("select f.id fid, f.intro intro, u.* from friends f join users u on u.id=f.a where f.b=? and f.status='pending' order by f.id", (me,))
    pout = rows("select f.id fid, u.* from friends f join users u on u.id=f.b where f.a=? and f.status='pending' order by f.id", (me,))
    btn = lambda url, label, cls="": f'<form method="post" action="{url}"><button class="{cls}">{label}</button></form>'
    rq = lambda r, acts: f'<div class="rq"><span class="avw">{uav(r)}</span><span class="ct"><b>{e(uname(r))}</b><small>@{e(r["username"])}</small>{"<small>" + e(r["intro"]) + "</small>" if "intro" in r.keys() and r["intro"] else ""}</span>{acts}</div>'
    cont = ('<form class="ca" method="post" action="/chat/friend/add"><input name="q" maxlength="120" required autocomplete="off" placeholder="Utilizador ou email do teu amigo"><button class="p">Adicionar</button></form>')
    if pin: cont += '<div class="sh">Pedidos de amizade</div>' + "".join(rq(r, btn("/chat/friend/accept/" + str(r["fid"]), "Aceitar", "p") + btn("/chat/friend/remove/" + str(r["fid"]), "Recusar")) for r in pin)
    cont += "".join(f'<form method="post" action="/chat/dm/{r["id"]}"><button class="ci" data-q="{e((uname(r) + " " + r["username"]).lower())}"><span class="avw">{uav(r)}'
                    f'<i class="dot" data-pres="{r["id"]}"{"" if is_online(r["id"]) else " hidden"}></i></span><span class="ct"><b>{e(uname(r))}</b><small data-ps="{r["id"]}">{pres_text(r)}</small></span></button></form>' for r in fr)
    if not fr: cont += '<div class="empty">Ainda não tens contactos. Adiciona o primeiro amigo acima.</div>'
    if pout: cont += '<div class="sh">Pedidos enviados</div>' + "".join(rq(r, btn("/chat/friend/remove/" + str(r["fid"]), "Cancelar pedido")) for r in pout)
    return {"c": convs, "f": cont, "g": groups, "bc": sum(unread.values()), "bf": len(pin)}

def friends_of(uid):
    return rows("select u.* from friends f join users u on u.id = case when f.a=? then f.b else f.a end where f.status='ok' and (f.a=? or f.b=?) and u.disabled=0 order by lower(coalesce(nullif(u.name,''),u.username))", (uid, uid, uid))

def accept_friend(r):
    run("update friends set status='ok' where id=?", (r["id"],)); cid = dm_chat(r["a"], r["b"])
    if r["intro"]: run("insert into chat_msgs(chat_id,user_id,body,created) values(?,?,?,?)", (cid, r["a"], r["intro"], now_str()))
    push_sync(r["a"], r["b"])

def chat_member(cid, uid): return one("select * from chat_members where chat_id=? and user_id=?", (cid, uid))

def dm_chat(a, b):
    r = one("select c.id from chats c join chat_members x on x.chat_id=c.id and x.user_id=? join chat_members y on y.chat_id=c.id and y.user_id=? where c.kind='dm'", (a, b))
    if r: return r["id"]
    cid = run("insert into chats(kind,name,owner,created) values('dm','',?,?)", (a, now_str()))
    run("insert into chat_members(chat_id,user_id) values(?,?)", (cid, a)); run("insert into chat_members(chat_id,user_id) values(?,?)", (cid, b))
    return cid

def chat_badge(uid):
    un = one("select count(*) from chat_msgs m join chat_members cm on cm.chat_id=m.chat_id and cm.user_id=? where m.id>cm.last_read and m.user_id!=?", (uid, uid))[0]
    return un + one("select count(*) from friends where b=? and status='pending'", (uid,))[0]

def purge_user(tid):
    run("delete from events where user_id=?", (tid,)); run("delete from clients where user_id=?", (tid,)); run("delete from tickets where user_id=?", (tid,))
    run("delete from friends where a=? or b=?", (tid, tid)); run("delete from pro where user_id=?", (tid,)); run("delete from mailcfg where user_id=?", (tid,)); run("delete from mail_log where user_id=?", (tid,)); run("delete from contact_req where a=? or b=?", (tid, tid))
    run("delete from chats where kind='dm' and id in (select chat_id from chat_members where user_id=?)", (tid,))
    run("delete from chat_msgs where user_id=?", (tid,))
    run("update chats set owner=(select user_id from chat_members where chat_id=chats.id and user_id!=? limit 1) where owner=?", (tid, tid))
    run("delete from chat_members where user_id=?", (tid,))
    run("delete from chats where id not in (select chat_id from chat_members)")
    run("delete from avatars where user_id=?", (tid,)); run("delete from notif_seen where user_id=?", (tid,))
    run("delete from users where id=?", (tid,))

def shell(title, body, u, active=""): return page(title, body, active, u) if u else pub_page(title, body)

def notify_admins(subject, text):
    if smtp_ready():
        for r in rows("select email from users where is_admin=1 and disabled=0"): mail_async(r["email"], subject, text)

def fld(label, name, typ="text", val="", extra=""):
    return f'<label>{label}</label><input name="{name}" type="{typ}" value="{e(val)}" {extra}>'

# ---------------------------------------------------------------- componentes
EV = "select e.*, c.name cn, c.logo cl from events e left join clients c on c.id=e.client_id "
def state(r): return "paid" if r["paid"] else "inv" if r["invoice_date"] else "plan" if r["end_date"] > today().isoformat() else "todo"

def avatar(name, logo):
    if logo: return f'<img class="av" src="{e(logo)}" alt="" referrerpolicy="no-referrer" loading="lazy">'
    return f'<span class="av">{e(ini(name))}</span>'

def tog(r, nxt):
    def b(f, label, on, cl):
        return f'<form method="post" action="/toggle/{r["id"]}/{f}"><input type="hidden" name="next" value="{e(nxt)}"><button class="chip {cl}{" on" if on else ""}">{"✓ " if on else ""}{label}</button></form>'
    return '<div class="tg">' + b("invoiced", "Faturada", r["invoice_date"], "f") + b("paid", "Paga", r["paid"], "p2") + "</div>"

def ev_row(r, nxt):
    v_, w_, t_ = tax_of(r)
    tl = f'<small class="tl" title="{eh("Total a receber")}">= {eur(t_)}</small>' if (v_ or w_) else ""
    meta = f'{drange(r["start_date"], r["end_date"])} · {(e(r["cn"]) if r["cn"] else "sem cliente")}'
    if r["invoice_date"]: meta += f' · faturada {ds(r["invoice_date"])}'
    elif r["end_date"] < today().isoformat(): meta += ' · <em class="late">terminou, falta faturar</em>'
    return (f'<div class="er {state(r)}"><a class="eh" href="/event/{r["id"]}">{avatar(r["cn"] or "?", r["cl"])}<div><b>{e(r["title"])}</b><small>{meta}</small></div></a>'
            f'<div class="ea"><span class="amt">{eur(r["amount"])}</span>{tl}{tog(r, nxt)}</div></div>')

def lst(rs, nxt, empty): return '<div class="list">' + ("".join(ev_row(r, nxt) for r in rs) or f'<div class="empty">{empty}</div>') + "</div>"

# ---------------------------------------------------------------- servidor
class H(BaseHTTPRequestHandler):
    fails = {}
    def log_message(self, *a): pass

    def user(self):
        ck = cookies.SimpleCookie(self.headers.get("Cookie", "")); THR.theme = (ck.get("theme").value if ck.get("theme") else "auto")
        m = ck.get("s")
        try:
            i, x, sig = m.value.split("."); u = one("select * from users where id=?", (i,))
            if u and not u["disabled"] and int(x) > time.time() and hmac.compare_digest(sig, sign(f"{i}.{x}.{u['pw'][-16:]}")):
                PULSE[u["id"]] = time.time(); THR.theme = u["theme"] or "auto"
                now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
                if (u["last_seen"] or "")[:15] != now[:15]: run("update users set last_seen=? where id=?", (now, u["id"]))
                return u
        except Exception: pass
        return None

    def https(self): return self.headers.get("X-Forwarded-Proto") == "https"

    def pick_lang(self):
        m = cookies.SimpleCookie(self.headers.get("Cookie", "")).get("lang")
        return m.value if m and m.value in i18n.LANGS else i18n.best_accept(self.headers.get("Accept-Language"), cfg()["lang"])

    def out(self, body, code=200, ctype="text/html; charset=utf-8", hd=()):
        if isinstance(body, str) and ctype.startswith("text/html"): body = i18n.finish(body)
        n = secrets.token_urlsafe(12); b = body if isinstance(body, bytes) else body.replace("__NONCE__", n).encode(); self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(b))), ("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"),
                     ("Content-Security-Policy", f"default-src 'self'; style-src 'unsafe-inline'; script-src 'self' 'nonce-{n}'; connect-src 'self' ws: wss:; img-src 'self' https: data:; form-action 'self'; frame-ancestors 'none'"), *hd):
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def go(self, to, hd=()):
        self.send_response(303); self.send_header("Location", to)
        for k, v in hd: self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        u_ = urlparse(self.path); q = parse_qs(u_.query); p = u_.path; g = lambda k, d="": q.get(k, [d])[0]
        i18n.set_lang(self.pick_lang(), self.path)
        if p == "/lang":
            nx = g("next", "/"); nx = nx if nx.startswith("/") and not nx.startswith("//") else "/"
            ck = f"lang={g('l')}; Max-Age=31536000; Path=/; SameSite=Lax" + ("; Secure" if self.https() else "")
            return self.go(nx, [("Set-Cookie", ck)] if g("l") in i18n.LANGS else [])
        if p == "/app.js": return self.out(JS.encode(), 200, "application/javascript; charset=utf-8", (("Cache-Control", "public, max-age=3600"),))
        if p == "/calendar.ics": return self.ics(g("k"))
        if p in ("/favicon.svg", "/favicon.ico", "/favicon-32.png", "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"): return self.icon(p)
        if p == "/manifest.webmanifest": return self.manifest()
        if p == "/sw.js": return self.out(SW.encode(), 200, "application/javascript; charset=utf-8", (("Cache-Control", "no-cache"), ("Service-Worker-Allowed", "/")))
        u = self.user()
        if p in ("/login", "/register", "/forgot", "/reset"):
            if u: return self.go("/")
            return self.out({"/login": lambda: self.login_page(ok=g("ok")), "/register": self.register_page, "/forgot": self.forgot_page, "/reset": lambda: self.reset_page(g("t"))}[p]())
        if p == "/ws": return self.websocket(u)
        if p == "/settings/mail" and u: return self.out(self.mail_settings(u, g("ok")))
        if u and re.match(r"^/event/\d+/(invoice|mail)$", p):
            try:
                eid = int(p.split("/")[2])
                if p.endswith("/invoice"): return self.invoice_get(u, eid)
                return self.out(self.mail_compose(u, eid, g("ok")))
            except (ValueError, KeyError): return self.go("/events")
        if p.startswith("/people") and u:
            try: return self.out(self.people_get(u, p, g))
            except (ValueError, KeyError, IndexError): return self.go("/people")
        if p == "/export" and u: return self.out(self.export_page(u, g))
        if p == "/export/run" and u: return self.export_run(u, g)
        if p == "/guide" or p.startswith("/guide/"):
            if u and p == "/guide" and not u["guide_seen"]: run("update users set guide_seen=1 where id=?", (u["id"],))
            try: return self.out(self.guide_page(u, p))
            except (ValueError, IndexError): return self.out(shell("Não encontrado", "<h1>Página não encontrada</h1>", u), 404)
        if p == "/about" or p.startswith("/support"):
            try: return self.out(self.about(u) if p == "/about" else self.support_get(u, p, g))
            except (ValueError, KeyError, IndexError): return self.out(shell("Não encontrado", "<h1>Página não encontrada</h1>", u), 404)
        if not u: return self.go("/login")
        parts = p.strip("/").split("/")
        try:
            if parts[0] == "admin": return self.admin_get(u, p, parts, g)
            if parts[0] == "chat": return self.chat_get(u, p, parts, g)
            if parts[0] == "avatar" and len(parts) == 2: return self.avatar(parts[1])
            if p == "/notifications": return self.out(self.notifications(u))
            if p == "/notifications/latest": return self.notif_latest(u)
            if p == "/": return self.out(self.home(u, g("m")))
            if p == "/calendar": return self.out(self.cal(u, g("m")))
            if p == "/events": return self.out(self.events(u, g("f", "todos")))
            if p == "/clients": return self.out(self.clients(u))
            if p == "/stats": return self.out(self.stats(u, g("y"), g))
            if p == "/settings": return self.out(self.settings(u, ok=g("ok")))
            if parts[0] == "event" and len(parts) == 2: return self.out(self.event_form(u, parts[1], g("date")))
            if parts[0] == "client" and len(parts) == 2: return self.out(self.client_form(u, parts[1]))
        except (ValueError, KeyError, TypeError): pass
        self.out(page("Não encontrado", "<h1>Página não encontrada</h1>", "", u), 404)

    def do_POST(self):
        i18n.set_lang(self.pick_lang(), "/")
        org, sf = self.headers.get("Origin"), self.headers.get("Sec-Fetch-Site")
        hosts = (self.headers.get("Host"), self.headers.get("X-Forwarded-Host"))
        if sf == "cross-site" or (not sf and org not in (None, "null") and urlparse(org).netloc not in hosts): return self.out("Pedido recusado", 403, "text/plain")
        if urlparse(self.path).path == "/admin/db/restore": return self.restore()
        if re.match(r"^/event/\d+/invoice/upload$", urlparse(self.path).path): return self.invoice_upload()
        n = int(self.headers.get("Content-Length", 0) or 0)
        self.fl = parse_qs(self.rfile.read(min(n, 700000 if self.path.endswith("/send") else 200000)).decode(), keep_blank_values=True); f = {k: v[0] for k, v in self.fl.items()}
        p = urlparse(self.path).path; parts = p.strip("/").split("/")
        if p.startswith("/support"):
            try: return self.support_post(self.user(), p, f)
            except (ValueError, KeyError, IndexError): return self.out(shell("Não encontrado", "<h1>Página não encontrada</h1>", self.user()), 404)
        pub = {"/login": self.do_login, "/register": self.do_register, "/forgot": self.do_forgot, "/reset": self.do_reset}
        if p in pub: return pub[p](f)
        u = self.user()
        if not u: return self.go("/login")
        if p == "/logout": return self.go("/login", [("Set-Cookie", "s=; Max-Age=0; Path=/")])
        if parts[0] == "admin": return self.admin_post(u, p, parts, f)
        if parts[0] == "chat":
            try: return self.chat_post(u, p, parts, f)
            except (ValueError, KeyError, IndexError): return self.go("/chat")
        if parts[0] == "people": return self.people_post(u, p, f)
        if p.startswith("/settings/mail"): return self.mail_settings_post(u, p, f)
        if re.match(r"^/event/\d+/(invoice/delete|mail/send)$", p): return self.mail_event_post(u, p, f)
        i = u["id"]; nxt = f.get("next", "/"); nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
        if parts[0] == "toggle" and len(parts) == 3:
            r = one("select * from events where id=? and user_id=?", (parts[1], i)); t = today().isoformat()
            if r and parts[2] == "invoiced":
                if r["invoice_date"]: run("update events set invoice_date=null, paid=0, paid_date=null where id=?", (r["id"],))
                else: run("update events set invoice_date=? where id=?", (t, r["id"]))
            elif r and parts[2] == "paid":
                if r["paid"]: run("update events set paid=0, paid_date=null where id=?", (r["id"],))
                else: run("update events set paid=1, paid_date=?, invoice_date=coalesce(invoice_date,?) where id=?", (t, t, r["id"]))
            return self.go(nxt)
        if p == "/event/save": return self.save_event(u, f)
        if parts[0] == "event" and len(parts) == 3 and parts[2] == "delete":
            run("delete from events where id=? and user_id=?", (parts[1], i)); return self.go("/events")
        if p == "/client/save":
            v = tuple(f.get(k, "").strip()[:300] for k in ("name", "nif", "contact", "rate", "terms", "notes")); em = ", ".join(mailer.emails_of(f.get("email", ""))[:5])
            logo = f.get("logo", "").strip(); logo = logo if re.match(r"^https?://", logo) else ""
            if not v[0]: return self.go("/clients")
            if f.get("id") and one("select 1 from clients where id=? and user_id=?", (f["id"], i)):
                run("update clients set name=?,nif=?,contact=?,rate=?,terms=?,notes=?,logo=?,email=? where id=? and user_id=?", v + (logo, em, f["id"], i))
            else: run("insert into clients(user_id,name,nif,contact,rate,terms,notes,logo,email) values(?,?,?,?,?,?,?,?,?)", (i,) + v + (logo, em))
            return self.go("/clients")
        if parts[0] == "client" and len(parts) == 3 and parts[2] == "delete":
            run("delete from clients where id=? and user_id=?", (parts[1], i)); return self.go("/clients")
        if p == "/guide/dismiss":
            run("update users set guide_seen=1 where id=?", (i,)); return self.go("/")
        if p == "/settings/avatar": return self.save_avatar(u, f)
        if p == "/settings/avatar/remove":
            run("delete from avatars where user_id=?", (i,)); run("update users set av_v=0 where id=?", (i,)); return self.go("/settings?ok=avatar_rm")
        if p == "/settings/ics": run("update users set ics=? where id=?", (secrets.token_hex(20), i)); return self.go("/settings?ok=ics")
        if p == "/settings/theme":
            t = f.get("t") if f.get("t") in ("auto", "light", "dark") else "auto"
            run("update users set theme=? where id=?", (t, u["id"]))
            return self.go("/settings?ok=theme", [("Set-Cookie", f"theme={t}; Path=/; Max-Age=31536000; SameSite=Lax")])
        if p == "/settings/tax":
            vm, vr = parse_vat(f.get("vat", "none"), f.get("vatc", "")); co = f.get("country", "PT") if f.get("country") in COUNTRIES else "PT"
            run("update users set vat_country=?, vat_def=?, wh_def=?, ss_on=?, ss_rate=?, ss_coef=? where id=?",
                (co, vat_code(vm, vr), parse_wh(f.get("wh", "0"), f.get("whc", "")), 1 if f.get("ss_on") else 0, min(max(num(f.get("ss_rate", "21.4")), 0), 60), min(max(num(f.get("ss_coef", "70")), 0), 100), u["id"]))
            return self.go("/settings?ok=tax")
        if p == "/settings/profile": return self.save_profile(u, f)
        if p == "/settings/password": return self.save_password(u, f)
        self.go("/")

    # ---- autenticação
    def login_page(self, err="", ok=""):
        msg = f'<p class="msg err">{err}</p>' if err else '<p class="msg ok">Palavra-passe alterada. Já podes entrar.</p>' if ok == "reset" else ""
        return auth_page("Entrar", f'<h1>Entrar</h1><p class="sub">Bem-vindo de volta.</p>{msg}<form class="f" method="post" action="/login">'
            + fld("Utilizador ou email", "u", extra='autocomplete="username" required autofocus') + fld("Palavra-passe", "p", "password", extra='autocomplete="current-password" required')
            + '<p><button class="p" style="width:100%">Entrar</button></p></form><p class="l2"><a href="/forgot">Esqueci-me da palavra-passe</a></p><p class="l2 m">Ainda não tens conta? <a href="/register">Criar conta</a></p><p class="l2 m">Novo aqui? <a href="/guide">Vê como funciona</a></p>' + SUPBTN)

    def do_login(self, f):
        ip = self.client_address[0]; n, t = self.fails.get(ip, (0, 0))
        if n >= 8 and time.time() - t < 300: return self.out(self.login_page("Demasiadas tentativas. Espera 5 minutos."), 429)
        x = f.get("u", "").strip(); u = one("select * from users where username=? or email=?", (x, x))
        if u and check_pw(f.get("p", ""), u["pw"]):
            if u["disabled"]: return self.out(self.login_page("Esta conta está suspensa. Fala com o administrador."), 403)
            self.fails.pop(ip, None); return self.go("/", [session_cookie(u, self.https())])
        self.fails[ip] = (n + 1, time.time()); self.out(self.login_page("Utilizador ou palavra-passe incorretos."), 401)

    def register_page(self, err="", v=None):
        v = v or {}; c = cfg()
        if not reg_allowed(c): return auth_page("Registo fechado", '<h1>Registo fechado</h1><p class="sub">De momento não estão a ser criadas contas novas.</p><p class="l2"><a href="/login">Entrar</a></p>')
        inv = fld("Código de convite", "code", extra="required") if c["invite"] and one("select 1 from users") else ""
        return auth_page("Criar conta", '<h1>Criar conta</h1><p class="sub">Demora menos de um minuto.</p>' + (f'<p class="msg err">{err}</p>' if err else "") + '<form class="f" method="post" action="/register">'
            + fld("Utilizador", "u", val=v.get("u", ""), extra='autocomplete="username" required autofocus') + fld("Email (para recuperar a palavra-passe)", "email", "email", v.get("email", ""), 'autocomplete="email" required')
            + fld("Palavra-passe (mínimo 8 caracteres)", "p", "password", extra='autocomplete="new-password" minlength="8" required') + fld("Repetir palavra-passe", "p2", "password", extra='autocomplete="new-password" minlength="8" required')
            + inv + '<p><button class="p" style="width:100%">Criar conta e entrar</button></p></form><p class="l2 m">Já tens conta? <a href="/login">Entrar</a></p><p class="l2 m">Novo aqui? <a href="/guide">Vê como funciona</a></p>' + SUPBTN)

    def do_register(self, f):
        v = {"u": f.get("u", "").strip(), "email": f.get("email", "").strip()}; err = ""
        c = cfg()
        if not reg_allowed(c): err = "O registo está fechado."
        elif c["invite"] and one("select 1 from users") and not hmac.compare_digest(f.get("code", ""), c["invite"]): err = "Código de convite incorreto."
        elif not re.match(r"^[\w.\-]{3,30}$", v["u"]): err = "O utilizador deve ter 3 a 30 caracteres (letras, números, . _ -)."
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v["email"]): err = "Email inválido."
        elif len(f.get("p", "")) < 8: err = "A palavra-passe tem de ter pelo menos 8 caracteres."
        elif f.get("p") != f.get("p2"): err = "As palavras-passe não coincidem."
        if not err:
            try:
                first = 0 if one("select 1 from users") else 1
                uid = run("insert into users(username,email,name,pw,ics,created,is_admin) values(?,?,?,?,?,?,?)", (v["u"], v["email"], v["u"], hash_pw(f["p"]), secrets.token_hex(20), today().isoformat(), first))
                run("update users set vat_def='23' where id=?", (uid,))
            except sqlite3.IntegrityError: err = "Esse utilizador ou email já está registado."
        if err: return self.out(self.register_page(err, v), 400)
        mail_async(v["email"], i18n.mail("welcome_s", site=SN()), i18n.mail("welcome_b", name=v["u"], site=SN(), user=v["u"], enter=i18n.mail("enter", url=BASE_URL) if BASE_URL else ""))
        self.go("/", [session_cookie(one("select * from users where id=?", (uid,)), self.https())])

    def forgot_page(self, sent=False):
        if sent: return auth_page("Recuperar", '<h1>Verifica o teu email</h1><p class="sub">Se esse email estiver registado, enviámos um link para definires uma nova palavra-passe. O link é válido durante 1 hora.</p><p class="l2"><a href="/login">Voltar a entrar</a></p>')
        return auth_page("Recuperar", '<h1>Recuperar palavra-passe</h1><p class="sub">Indica o email da tua conta.</p><form class="f" method="post" action="/forgot">' + fld("Email", "email", "email", extra="required autofocus")
            + '<p><button class="p" style="width:100%">Enviar link</button></p></form><p class="l2"><a href="/login">Voltar</a></p>' + SUPBTN)

    def do_forgot(self, f):
        ip = "f" + self.client_address[0]; n, t = self.fails.get(ip, (0, 0))
        if n >= 5 and time.time() - t < 900: return self.out(self.forgot_page(True))
        self.fails[ip] = (n + 1 if time.time() - t < 900 else 1, time.time())
        u = one("select * from users where email=?", (f.get("email", "").strip(),))
        if u:
            tok = secrets.token_urlsafe(32); run("delete from resets where user_id=? or exp<?", (u["id"], time.time()))
            run("insert into resets values(?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), u["id"], int(time.time()) + 3600))
            if BASE_URL and smtp_ready():
                mail_async(u["email"], i18n.mail("reset_s", site=SN()), i18n.mail("reset_b", name=u["name"], url=f"{BASE_URL}/reset?t={tok}"))
            else: print(f"[RECUPERAÇÃO] email/BASE_URL não configurado. Link para {u['username']}: http://{self.headers.get('Host')}/reset?t={tok}", flush=True)
        self.out(self.forgot_page(True))

    def reset_page(self, tok, err=""):
        if not one("select 1 from resets where h=? and exp>?", (hashlib.sha256(tok.encode()).hexdigest(), time.time())):
            return auth_page("Link inválido", '<h1>Link inválido ou expirado</h1><p class="sub">Pede um novo link para recuperar a palavra-passe.</p><p class="l2"><a href="/forgot">Pedir novo link</a></p>')
        return auth_page("Nova palavra-passe", '<h1>Nova palavra-passe</h1>' + (f'<p class="msg err">{err}</p>' if err else "") + f'<form class="f" method="post" action="/reset"><input type="hidden" name="t" value="{e(tok)}">'
            + fld("Nova palavra-passe (mínimo 8)", "p", "password", extra='autocomplete="new-password" minlength="8" required autofocus') + fld("Repetir", "p2", "password", extra='autocomplete="new-password" minlength="8" required') + '<p><button class="p" style="width:100%">Guardar</button></p></form>')

    def do_reset(self, f):
        tok = f.get("t", ""); h = hashlib.sha256(tok.encode()).hexdigest(); r = one("select * from resets where h=? and exp>?", (h, time.time()))
        if not r: return self.out(self.reset_page(tok))
        if len(f.get("p", "")) < 8 or f.get("p") != f.get("p2"): return self.out(self.reset_page(tok, "As palavras-passe têm de coincidir e ter 8+ caracteres."), 400)
        run("update users set pw=? where id=?", (hash_pw(f["p"]), r["user_id"])); run("delete from resets where user_id=?", (r["user_id"],)); self.go("/login?ok=reset")

    def icon(self, p):
        c = cfg(); hd = (("Cache-Control", "public, max-age=86400"),)
        if p == "/favicon.svg": return self.out(logo(c, True), 200, "image/svg+xml", hd)
        size = {"/favicon.ico": 48, "/favicon-32.png": 32, "/apple-touch-icon.png": 180, "/icon-192.png": 192, "/icon-512.png": 512}[p]
        self.out(png_icon(size, tuple(c[k] for k in COLOR_KEYS)), 200, "image/png", hd)

    def manifest(self):
        c = cfg(); v = hashlib.sha256("".join(c[k] for k in COLOR_KEYS).encode()).hexdigest()[:6]
        m = {"name": SN(), "short_name": SN()[:12], "description": "Eventos, clientes e faturação para freelancers.", "start_url": "/", "scope": "/", "display": "standalone",
             "background_color": "#ffffff", "theme_color": c["c_brand"], "lang": i18n.lang(),
             "icons": [{"src": f"/icon-192.png?v={v}", "sizes": "192x192", "type": "image/png", "purpose": "any"}, {"src": f"/icon-512.png?v={v}", "sizes": "512x512", "type": "image/png", "purpose": "any"}]}
        self.out(json.dumps(m, ensure_ascii=False), 200, "application/manifest+json", (("Cache-Control", "public, max-age=3600"),))

    # ---- admin
    TABS = [("/admin", "Resumo"), ("/admin/users", "Utilizadores"), ("/admin/site", "Site"), ("/admin/email", "Email"), ("/admin/ads", "Publicidade"), ("/admin/news", "Novidades"), ("/admin/support", "Suporte"), ("/admin/db", "Base de dados")]
    FLASH = {"texts": "Textos e registo guardados.", "colors": "Cores guardadas.", "reset": "Cores repostas.", "ads": "Publicidade guardada.", "user": "Dados guardados.",
             "pw": "Palavra-passe definida. A pessoa tem de entrar de novo.", "ics": "Link do calendário renovado.", "state": "Estado atualizado.", "mailsaved": "Email do sistema guardado.", "mailtest": "Email de teste enviado para o teu email de administrador.", "mailreset": "Voltou a usar as variáveis do Portainer.", "snap": "Backup criado.", "newadmin": "Administrador adicionado.",
             "reply": "Resposta enviada.", "closed": "Conversa fechada.", "reopened": "Conversa reaberta.", "deleted": "Conversa apagada.",
             "newspub": "Novidade publicada.", "newsdel": "Novidade apagada.", "bulkdel": "Contas apagadas.", "nosel": "Seleciona pelo menos uma conta e marca a confirmação.", "nouser": "Não encontrámos essa conta (ou já é administradora)."}

    def apage(self, u, tab, body, ok="", err=""):
        ns = one("select count(*) from tickets where unread_admin=1")[0]
        chips = "".join(f'<a class="{"on" if h == tab else ""}" href="{h}">{n}{f" <span class=\"bd s\">{ns}</span>" if ns and h == "/admin/support" else ""}</a>' for h, n in self.TABS)
        m = f'<p class="msg ok">{eh(self.FLASH[ok])}</p>' if ok in self.FLASH else (f'<p class="msg err">{eh(err)}</p>' if err else "")
        return page("Admin", f'<div class="bar-h"><div><h1>Admin</h1><p class="sub" style="margin:0">Gestão do site, das contas e dos dados.</p></div></div><div class="chips">{chips}</div>{m}{body}', "/admin", u)

    def send_file(self, path):
        if not os.path.isfile(path): raise ValueError
        with open(path, "rb") as fh: data = fh.read()
        self.out(data, 200, "application/octet-stream", (("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"'),))

    def admin_get(self, u, p, parts, g):
        if not u["is_admin"]: raise ValueError
        if p == "/admin": return self.out(self.a_home(u))
        if p == "/admin/users": return self.out(self.a_users(u, g("ok")))
        if p == "/admin/site": return self.out(self.a_site(u, g("ok")))
        if p == "/admin/email": return self.out(self.a_email(u, g("ok")))
        if p == "/admin/ads": return self.out(self.a_ads(u, g("ok")))
        if p == "/admin/db": return self.out(self.a_db(u, g("ok"), g("t")))
        if p == "/admin/support": return self.out(self.a_support(u, g("f", "open"), g("ok")))
        if p == "/admin/news": return self.out(self.a_news(u, g("ok")))
        if len(parts) == 3 and parts[1] == "support": return self.out(self.a_ticket(u, parts[2], g("ok")))
        if p == "/admin/backup.db": return self.send_file(make_backup("manual"))
        if len(parts) == 3 and parts[1] == "user": return self.out(self.a_user(u, parts[2], g("ok")))
        if len(parts) == 3 and parts[1] == "backups" and re.match(BK_RE, parts[2]): return self.send_file(os.path.join(BACKUP_DIR, parts[2]))
        raise ValueError

    def a_home(self, u):
        q = lambda s, a=(): one(s, a)[0]
        wk = (today() - dt.timedelta(7)).isoformat(); c = cfg(); size = os.path.getsize(DB) if os.path.exists(DB) else 0
        tile = lambda col, lab, val, sub: f'<div class="st" style="--c:{col}"><span>{lab}</span><b>{val}</b><span>{sub}</span></div>'
        strip = ('<div class="strip">' + tile("var(--brand)", "Contas", q("select count(*) from users"), f'+{q("select count(*) from users where created>=?", (wk,))} nos últimos 7 dias')
                 + tile("var(--paid)", "Ativas (7 dias)", q("select count(*) from users where last_seen>=?", (wk,)), "com acesso recente")
                 + tile("var(--inv)", "Eventos", q("select count(*) from events"), pl(q("select count(*) from clients"), "cliente"))
                 + tile("var(--todo)", "Base de dados", fsize(size), f"{len(list_backups())} backups") + "</div>")
        w = []
        if not smtp_ready(): w.append("O envio de emails está desligado (define SMTP_USER e SMTP_PASSWORD no Portainer).")
        if not BASE_URL: w.append("BASE_URL não está definido: os links nos emails não funcionam.")
        ns = q("select count(*) from tickets where unread_admin=1")
        if c["reg_open"] == "1" and not c["invite"]: w.append("Qualquer pessoa com o endereço do site pode criar conta. Define um código de convite em Site.")
        wl = [f"<li>{eh(x)}</li>" for x in w] + ([f'<li><a href="/admin/support">{eh("Mensagens de suporte por ler:")} <b>{ns}</b></a></li>'] if ns else [])
        wh = ("<ul style='margin:0;padding-left:20px'>" + "".join(wl) + "</ul>") if wl else '<p class="m" style="margin:0">Tudo em ordem.</p>'
        rec = "".join(f'<div class="er"><a class="eh" href="/admin/user/{x["id"]}"><span class="av">{e(ini(x["name"] or x["username"]))}</span><div><b>{e(x["name"] or x["username"])}</b>'
                      f'<small>{e(x["email"])} · registo {e(x["created"])}</small></div></a><span class="m">{e(x["last_seen"]) if x["last_seen"] else "nunca entrou"}</span></div>' for x in rows("select * from users order by id desc limit 6"))
        return self.apage(u, "/admin", f'{strip}<h2>Avisos</h2><div class="card">{wh}</div><h2>Últimas contas</h2><div class="list">{rec}</div><p><a class="btn" href="/admin/users">Ver todas as contas</a></p>')

    def a_users(self, u, ok=""):
        us = rows("select u.*, (select count(*) from events where user_id=u.id) ne, (select count(*) from clients where user_id=u.id) nc from users u order by id")
        bd = lambda x: ('<span class="bd a">Admin</span> ' if x["is_admin"] else "") + ('<span class="bd s">Suspensa</span>' if x["disabled"] else "")
        chk = lambda x: "" if x["id"] == u["id"] else f'<input type="checkbox" name="ids" value="{x["id"]}">'
        tr = "".join(f'<tr class="ur"><td>{chk(x)}</td><td><a href="/admin/user/{x["id"]}"><b>{e(x["name"] or x["username"])}</b></a><br><span class="m">@{e(x["username"])}</span></td><td class="l">{e(x["email"])}</td>'
                     f'<td>{e(x["created"])}</td><td>{e(x["last_seen"]) if x["last_seen"] else "nunca"}</td><td>{x["ne"]}</td><td>{x["nc"]}</td><td>{bd(x)}</td></tr>' for x in us)
        cand = "".join(f'<option value="{e(x["username"])}">{e(x["name"] or x["username"])} · {e(x["email"])}</option>' for x in us if not x["is_admin"] and not x["disabled"])
        adm = ", ".join(f'<a href="/admin/user/{x["id"]}"><b>{e(x["name"] or x["username"])}</b></a>' for x in us if x["is_admin"])
        addf = ('<form class="f card" method="post" action="/admin/users/promote"><h2>Administradores</h2><p class="m">Atuais: ' + adm + '. Os administradores veem e gerem todas as contas e dados. '
                'Para adicionar alguém, essa pessoa tem de ter criado conta primeiro.</p>'
                + (f'<label>Adicionar administrador</label><div class="row2"><input name="q" list="ulist" autocomplete="off" placeholder="Escreve o utilizador ou email" required><datalist id="ulist">{cand}</datalist><button class="p">Tornar admin</button></div>'
                    '<p class="m">Escreve parte do nome, utilizador ou email e escolhe da lista.</p>' if cand
                   else '<p class="m">Não há mais contas para promover.</p>') + '</form>')
        return self.apage(u, "/admin/users", addf + f'<p class="m">{len(us)} contas. Clica num nome para editar, mudar o email, repor a palavra-passe ou suspender.</p>'
                          '<input id="uf" placeholder="Procurar na lista..." style="margin-bottom:10px;width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--sf);color:var(--ink);font:inherit" autocomplete="off">'
                          f'<form method="post" action="/admin/users/bulkdelete"><div class="card sc"><table class="tb" id="ut"><tr><th></th><th>Conta</th><th class="l">Email</th><th>Registo</th><th>Último acesso</th><th>Eventos</th><th>Clientes</th><th></th></tr>{tr}</table></div>'
                          '<div class="card"><h2 style="margin-top:0">Apagar contas selecionadas</h2><label class="c"><input type="checkbox" name="confirm">Confirmo: apagar as contas selecionadas e todos os seus dados (é feito um backup antes)</label>'
                          '<p><button class="d">Apagar contas selecionadas</button></p></div></form>'
                          '<script nonce="__NONCE__">document.getElementById("uf").oninput=function(){var q=this.value.toLowerCase();document.querySelectorAll("#ut tr.ur").forEach(function(r){r.style.display=r.textContent.toLowerCase().indexOf(q)<0?"none":""})}</script>', ok)

    def a_user(self, u, tid, ok="", err="", link=""):
        t = one("select * from users where id=?", (tid,))
        if not t: raise ValueError
        ne = one("select count(*) from events where user_id=?", (t["id"],))[0]; nc = one("select count(*) from clients where user_id=?", (t["id"],))[0]
        me = t["id"] == u["id"]; base = f"/admin/user/{t['id']}"
        bdg = ('<span class="bd a">Admin</span> ' if t["is_admin"] else "") + ('<span class="bd s">Suspensa</span>' if t["disabled"] else "")
        btn = lambda act, label, cls="": f'<form method="post" action="{base}/{act}"><button class="{cls}">{label}</button></form>'
        lk = (f'<div class="card"><b>Link de recuperação (válido 1 hora)</b><p class="m">Envia este link à pessoa para ela escolher uma nova palavra-passe.</p>'
              f'<input readonly id="lk" value="{e(link)}" style="width:100%;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></div>') if link else ""
        return self.apage(u, "/admin/users", (
            f'<p><a href="/admin/users" class="m">‹ Todas as contas</a></p>{lk}'
            f'<div class="card"><div class="row2"><span class="av">{e(ini(t["name"] or t["username"]))}</span><div><b>{e(t["name"] or t["username"])}</b> {bdg}'
            f'<div class="m">Registo {e(t["created"])} · último acesso {e(t["last_seen"]) if t["last_seen"] else "nunca"} · {pl(ne, "evento")} · {pl(nc, "cliente")}</div></div></div></div>'
            f'<form class="f card" method="post" action="{base}/save"><h2>Dados da conta</h2>' + fld("Utilizador", "username", val=t["username"], extra="required") + fld("Nome", "name", val=t["name"], extra="required")
            + fld("Email", "email", "email", t["email"], "required") + fld("Telemóvel", "phone", "tel", t["phone"] or "") + '<p><button class="p">Guardar</button></p></form>'
            f'<div class="card"><h2>Acesso</h2><div class="row2">{btn("link", "Gerar link de recuperação")}{btn("ics", "Renovar link do calendário")}</div>'
            f'<form class="f" method="post" action="{base}/password" style="margin-top:14px"><label>Definir nova palavra-passe (mínimo 8)</label><div class="row2"><input name="p" type="text" minlength="8" autocomplete="off" required style="flex:1;min-width:200px"><button>Definir</button></div></form></div>'
            f'<div class="card"><h2>Estado</h2><div class="row2">{btn("admin", "Remover admin" if t["is_admin"] else "Tornar admin")}{btn("disable", "Reativar conta" if t["disabled"] else "Suspender conta", "d")}</div>'
            f'<p class="m">Uma conta suspensa não consegue entrar, mas os dados ficam guardados.</p></div>'
            f'<details><summary>Apagar conta e todos os dados</summary><form class="f" method="post" action="{base}/delete"><p class="m">Apaga a conta e os dados associados: {pl(ne, "evento")} · {pl(nc, "cliente")}. Não dá para desfazer (só com um backup). '
            f'Escreve <b>{e(t["username"])}</b> para confirmar.</p><input name="confirm" autocomplete="off" required><p><button class="d">Apagar definitivamente</button></p></form></details>'), ok, err)

    def a_email(self, u, ok="", err=""):
        c = smtp_conf(); src = {"db": "guardado aqui, no painel", "env": "variáveis do Portainer (SMTP_USER / SMTP_PASSWORD)"}.get(c["src"]) if c else None
        k = {r["k"][5:]: r["v"] for r in rows("select k, v from kv where k like 'smtp.%'")}; g = lambda x, d="": k.get(x) or d
        sec = g("sec", "starttls"); so = lambda v, lab: f'<option value="{v}"{" selected" if sec == v else ""}>{lab}</option>'
        st = (f'<p class="msg ok"><span>A usar:</span> {eh(src)} · <b>{e(c["user"])}</b></p>' if c else '<p class="msg err">O envio de emails está desligado.</p>')
        return self.apage(u, "/admin/email", st + '<form class="f card" method="post" action="/admin/email/save"><h2>Email do sistema</h2>'
            '<p class="m">É o email que o Claquete usa para as boas-vindas, a recuperação de palavra-passe e as respostas do suporte. O que guardares aqui tem prioridade sobre as variáveis do Portainer.</p>'
            '<label>Fornecedor</label><select id="prov"><option value="">Outro</option><option value="gmail">Gmail</option><option value="outlook">Outlook / Hotmail</option><option value="office365">Microsoft 365</option></select>'
            + fld("Servidor SMTP", "host", val=g("host", "smtp.gmail.com"), extra='id="host" required maxlength="120"')
            + '<div class="g2"><div>' + fld("Porta", "port", "number", str(g("port", 587)), 'id="port" required') + f'</div><div><label>Segurança</label><select name="sec" id="sec">{so("starttls", "STARTTLS (587)")}{so("ssl", "SSL/TLS (465)")}</select></div></div>'
            + fld("Utilizador (o email de envio)", "user", val=g("user"), extra='required maxlength="160" autocomplete="off"')
            + f'<label>Palavra-passe</label><input name="password" type="password" autocomplete="new-password" placeholder="{"•••••••• (deixa vazio para manter)" if k.get("pw") else ""}"{"" if k.get("pw") else " required"}>'
            + fld("Endereço do remetente (opcional, por omissão o utilizador)", "from", "email", g("from"), 'placeholder="geral@o-teu-dominio.pt"')
            + '<p class="m">Com um domínio teu, usa o SMTP do fornecedor do domínio (ou do teu serviço de email) e põe aqui o endereço, por exemplo <b>geral@claquete.pt</b>. No Gmail usa uma «palavra-passe de aplicação».</p>'
            '<p><button class="p">Guardar</button></p></form>'
            + ('<div class="card"><h2>Testar</h2><p class="m">Envia um email de teste para o teu email de administrador.</p><form method="post" action="/admin/email/test" style="display:inline"><button>Enviar teste</button></form> '
               + ('<form method="post" action="/admin/email/reset" style="display:inline"><button class="d">Voltar às variáveis do Portainer</button></form>' if k.get("pw") else "") + '</div>' if c else "")
            + '<script nonce="__NONCE__">var P={gmail:["smtp.gmail.com",587,"starttls"],outlook:["smtp-mail.outlook.com",587,"starttls"],office365:["smtp.office365.com",587,"starttls"]};'
              'document.getElementById("prov").onchange=function(){var p=P[this.value];if(!p)return;host.value=p[0];port.value=p[1];sec.value=p[2]}</script>', ok, err)

    def a_site(self, u, ok=""):
        c = cfg(); ck = lambda k: "checked" if c[k] == "1" else ""
        lopts = "".join(f'<option value="{k}"{" selected" if cfg()["lang"] == k else ""}>{v}</option>' for k, v in i18n.LANGS.items())
        presets = [("Azul", "#3b4cdb,#e5484d,#f0a020,#2fa56b"), ("Esmeralda", "#0f766e,#e5484d,#f0a020,#2fa56b"), ("Violeta", "#7c3aed,#e11d48,#f59e0b,#16a34a"),
                   ("Laranja", "#ea580c,#dc2626,#ca8a04,#15803d"), ("Grafite", "#334155,#e5484d,#f0a020,#2fa56b")]
        pb = "".join(f'<button type="button" data-c="{v}">{n}</button>' for n, v in presets)
        cin = lambda k, lab: f'<div><label>{lab}</label><input type="color" id="{k}" name="{k}" value="{c[k]}"></div>'
        lg = logo(c).replace('class="lg"', 'class="lg" id="pvlogo"')
        return self.apage(u, "/admin/site", (
            '<form class="f card" method="post" action="/admin/site/texts"><h2>Nomes e textos</h2>' + fld("Nome do site", "site_name", val=c["site_name"], extra='maxlength="40" required')
            + fld("Título da página de entrada", "hero_title", val=c["hero_title"], extra='maxlength="140"') + f'<label>Texto da página de entrada</label><textarea name="hero_text" rows="3" maxlength="300">{e(c["hero_text"])}</textarea>'
            f'<label>Idioma por defeito</label><select name="lang">{lopts}</select><p class="m">Usado quando o browser do visitante não indica um idioma disponível.</p>'
            f'<label class="c" style="margin-top:16px"><input type="checkbox" name="reg_open" {ck("reg_open")}>Permitir que novas pessoas criem conta</label>'
            + fld("Código de convite (vazio = sem código)", "invite", val=c["invite"], extra='maxlength="60" autocomplete="off"') + '<p><button class="p">Guardar</button></p></form>'
            '<form class="f card" method="post" action="/admin/site/colors"><h2>Cores</h2><p class="m">Mudam em todo o site e no ícone do separador. O modo escuro ajusta-se sozinho.</p>'
            f'<div class="pre">{pb}</div><div class="g4">{cin("c_brand", "Principal")}{cin("c_todo", "Por faturar")}{cin("c_inv", "Faturada")}{cin("c_paid", "Paga")}</div>'
            f'<div id="pv" class="card" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:16px 0 0;--brand:{c["c_brand"]};--todo:{c["c_todo"]};--inv:{c["c_inv"]};--paid:{c["c_paid"]}">{lg}'
            '<button type="button" class="p">Botão</button><span class="chip on f">✓ Faturada</span><span class="chip on p2">✓ Paga</span><b style="color:var(--todo)">Por faturar</b></div>'
            '<p class="row2" style="margin-top:14px"><button class="p">Guardar cores</button><button type="submit" formaction="/admin/site/reset" formnovalidate>Repor cores originais</button></p></form>'
            '<script nonce="__NONCE__">(function(){var ids=["c_brand","c_todo","c_inv","c_paid"],nm=["brand","todo","inv","paid"],pv=document.getElementById("pv"),lr=document.querySelectorAll("#pvlogo rect");'
            'function upd(){ids.forEach(function(k,i){var v=document.getElementById(k).value;pv.style.setProperty("--"+nm[i],v);lr[i].setAttribute("fill",v)})}'
            'ids.forEach(function(k){document.getElementById(k).oninput=upd});document.querySelectorAll("[data-c]").forEach(function(b){b.onclick=function(){var v=b.dataset.c.split(",");ids.forEach(function(k,i){document.getElementById(k).value=v[i]});upd()}});upd()})();</script>'), ok)

    def a_ads(self, u, ok=""):
        c = cfg(); ck = lambda k: "checked" if c[k] == "1" else ""
        prev = ad_html(dict(c, ad_on="1", ad_app="1"), "app") or '<p class="m">Preenche uma imagem ou um texto para ver a pré-visualização.</p>'
        return self.apage(u, "/admin/ads", (
            '<form class="f card" method="post" action="/admin/ads/save"><h2>Banner de publicidade</h2><p class="m">Aparece como um banner com a indicação «Publicidade». Aceita imagem ou texto, com ligação opcional. '
            'Scripts de anúncios (por exemplo AdSense) ficam bloqueados por segurança.</p>'
            f'<label class="c"><input type="checkbox" name="ad_on" {ck("ad_on")}>Mostrar publicidade</label>'
            + fld("URL da imagem (https://...)", "ad_img", "url", c["ad_img"], 'placeholder="https://..."') + fld("Ligação ao clicar (opcional)", "ad_link", "url", c["ad_link"], 'placeholder="https://..."')
            + fld("Texto (usa-se também como descrição da imagem)", "ad_text", val=c["ad_text"], extra='maxlength="120"')
            + f'<label>Onde aparece</label><label class="c"><input type="checkbox" name="ad_app" {ck("ad_app")}>Dentro da aplicação (topo de cada página)</label>'
            f'<label class="c"><input type="checkbox" name="ad_auth" {ck("ad_auth")}>Páginas de entrada e registo</label><p><button class="p">Guardar</button></p></form>'
            f'<h2>Pré-visualização</h2><div style="max-width:720px">{prev}</div>'), ok)

    def a_db(self, u, ok="", t="", q="", res=None, err=""):
        tabs = [r["name"] for r in rows("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        cnt = {x: one('select count(*) from "' + x + '"')[0] for x in tabs}
        chips = "".join(f'<a href="/admin/db?t={x}#sql">{x} ({cnt[x]})</a>' for x in tabs)
        if res is None and t in tabs:
            q = f'select * from "{t}" limit 100'; res = sql_run(q, False)
        cols, data, info = res if res else (None, None, "")
        bks = "".join(f'<div class="bk"><span><b>{fn[9:13]}-{fn[13:15]}-{fn[15:17]} {fn[18:20]}:{fn[20:22]}</b> <span class="m">· {fn.rsplit("-", 1)[1][:-3]} · {fsize(sz)}</span></span><a class="btn" href="/admin/backups/{fn}">Descarregar</a></div>' for fn, sz in list_backups()[:15]) \
            or '<p class="m">Ainda não há backups guardados no servidor.</p>'
        return self.apage(u, "/admin/db", (
            f'<div class="card"><h2>Backups</h2><p class="m">Há um backup automático por dia (guarda os últimos 14). Ficam na pasta de dados do servidor, por isso descarrega de vez em quando uma cópia para outro sítio.</p>'
            f'<div class="row2"><a class="btn p" href="/admin/backup.db">Criar e descarregar backup agora</a><form method="post" action="/admin/db/snapshot"><button>Criar backup no servidor</button></form></div><div style="margin-top:12px">{bks}</div></div>'
            '<form class="f card" id="rf"><h2>Restaurar um backup</h2><p class="m">Substitui <b>toda</b> a base de dados atual pelo ficheiro escolhido (um .db descarregado daqui). É criado um backup do estado atual antes. Depois tens de entrar de novo.</p>'
            '<input type="file" id="rfile" accept=".db,.sqlite,application/octet-stream" required><p><button class="d" id="rb">Restaurar</button></p></form>'
            f'<div class="card" id="sql"><h2>Ver e editar dados</h2><p class="m">Tabelas (clica para ver as primeiras 100 linhas):</p><div class="chips">{chips}</div>'
            f'<form class="f" method="post" action="/admin/db/sql#sql"><textarea name="q" rows="4" class="mono" spellcheck="false">{e(q or "select id, username, email from users")}</textarea>'
            '<label class="c" style="margin-top:10px"><input type="checkbox" name="confirm">Confirmo que esta instrução pode alterar dados (é criado um backup antes)</label>'
            '<p class="m">Exemplos: <code>' + e("update users set email='novo@exemplo.pt' where id=2") + '</code> · <code>' + e("update events set user_id=3 where id=10") + '</code></p><p><button class="p">Executar</button></p></form>'
            + (f'<p class="msg {"err" if info.startswith(("Erro", "Esta")) else "ok"}">{e(info)}</p>' if info else "") + sql_table(cols, data or []) + '</div>'
            '<script nonce="__NONCE__">document.getElementById("rf").onsubmit=function(ev){ev.preventDefault();var f=document.getElementById("rfile").files[0],b=document.getElementById("rb");if(!f)return;'
            'if(!confirm("' + tx("Isto substitui TODA a base de dados atual pela do ficheiro. Continuar?") + '"))return;b.disabled=true;b.textContent="' + tx("A restaurar...") + '";'
            'fetch("/admin/db/restore",{method:"POST",body:f,headers:{"Content-Type":"application/octet-stream"}}).then(function(r){return r.text().then(function(t){if(r.ok){location.href="/login"}else{alert(t);b.disabled=false;b.textContent="' + tx("Restaurar") + '"}})})'
            '.catch(function(){alert("' + tx("Falhou o envio do ficheiro.") + '");b.disabled=false;b.textContent="' + tx("Restaurar") + '"})};</script>'), ok, err)

    def admin_post(self, u, p, parts, f):
        if not u["is_admin"]: return self.out(page("Não encontrado", "<h1>Página não encontrada</h1>", "", u), 404)
        yes = lambda k: "1" if f.get(k) else "0"
        if p.startswith("/admin/email/"):
            sec_ = one("select v from kv where k='secret'")["v"]; kvset = lambda k, v: run("insert into kv values(?,?) on conflict(k) do update set v=excluded.v", ("smtp." + k, v))
            if p == "/admin/email/reset": run("delete from kv where k like 'smtp.%'"); return self.go("/admin/email?ok=mailreset")
            if p == "/admin/email/test":
                try:
                    if not smtp_ready(): raise ValueError("O envio de emails está desligado.")
                    send_mail(u["email"], f"{SN()}: teste de email", "Se estás a ler isto, o email do sistema está a funcionar.", strict=True); return self.go("/admin/email?ok=mailtest")
                except Exception as ex: return self.out(self.a_email(u, err=f"Não foi possível enviar: {ex}"))
            if p == "/admin/email/save":
                host = f.get("host", "").strip().lower()[:120]; user = f.get("user", "").strip()[:160]; frm = f.get("from", "").strip()[:160]
                try: port = int(f.get("port") or 587)
                except ValueError: port = 0
                old = {r["k"][5:]: r["v"] for r in rows("select k, v from kv where k like 'smtp.%'")}
                if not re.match(r"^[a-z0-9.-]{3,120}$", host) or not 1 <= port <= 65535 or not user: return self.out(self.a_email(u, err="Preenche o servidor, a porta e o utilizador."))
                if frm and not mailer.EMAIL_RE.match(frm): return self.out(self.a_email(u, err="O email de envio não é válido."))
                pw = f.get("password", "")
                if pw: pw_enc = mailer.enc(sec_, pw[:200])
                elif old.get("pw"): pw_enc = old["pw"]
                else: return self.out(self.a_email(u, err="Indica a palavra-passe."))
                for k_, v_ in (("host", host), ("port", str(port)), ("sec", f.get("sec") if f.get("sec") in ("ssl", "none") and (f.get("sec") == "ssl" or mailer.DEV) else "starttls"), ("user", user), ("from", frm), ("pw", pw_enc)): kvset(k_, v_)
                return self.go("/admin/email?ok=mailsaved")
        if p == "/admin/site/texts":
            set_cfg({"site_name": f.get("site_name", "").strip()[:40] or DEFAULTS["site_name"], "hero_title": f.get("hero_title", "").strip()[:140] or DEFAULTS["hero_title"],
                     "hero_text": f.get("hero_text", "").strip()[:300] or DEFAULTS["hero_text"], "reg_open": yes("reg_open"), "invite": f.get("invite", "").strip()[:60], "lang": f.get("lang") if f.get("lang") in i18n.LANGS else "pt"})
            return self.go("/admin/site?ok=texts")
        if p == "/admin/site/colors":
            if not all(HEX.match(f.get(k, "")) for k in COLOR_KEYS): return self.out(self.apage(u, "/admin/site", "", err="Cor inválida."), 400)
            set_cfg({k: f[k].lower() for k in COLOR_KEYS}); return self.go("/admin/site?ok=colors")
        if p == "/admin/site/reset": set_cfg({k: DEFAULTS[k] for k in COLOR_KEYS}); return self.go("/admin/site?ok=reset")
        if p == "/admin/ads/save":
            img, link = f.get("ad_img", "").strip(), f.get("ad_link", "").strip()
            set_cfg({"ad_on": yes("ad_on"), "ad_img": img if img.startswith("https://") else "", "ad_link": link if re.match(r"^https?://", link) else "",
                     "ad_text": f.get("ad_text", "").strip()[:120], "ad_app": yes("ad_app"), "ad_auth": yes("ad_auth")})
            return self.go("/admin/ads?ok=ads")
        if p == "/admin/users/promote":
            q = f.get("q", "").strip()[:120].lower()
            ts = [r for r in rows("select * from users where disabled=0 and is_admin=0") if q and (q in r["username"].lower() or q in (r["email"] or "").lower() or q in (r["name"] or "").lower())]
            ex = [r for r in ts if q in (r["username"].lower(), (r["email"] or "").lower())]
            t = ex[0] if ex else (ts[0] if len(ts) == 1 else None)
            if t: run("update users set is_admin=1 where id=?", (t["id"],)); return self.go("/admin/users?ok=newadmin")
            return self.go("/admin/users?ok=nouser")
        if p == "/admin/news/publish":
            title, body = f.get("title", "").strip()[:120], f.get("body", "").strip()[:3000]
            if not title or not body: return self.out(self.a_news(u, err="Escreve o título e a mensagem."), 400)
            tr = {l: {"t": f.get("t_" + l, "").strip()[:120], "b": f.get("b_" + l, "").strip()[:3000]} for l in i18n.LANGS if l != "pt"}
            tr = {l: v for l, v in tr.items() if v["t"] or v["b"]}
            nid = run("insert into notifs(title,body,tr,created,author) values(?,?,?,?,?)", (title, body, json.dumps(tr, ensure_ascii=False), now_str(), u["id"]))
            ws.hub.push(ws.hub.online_ids(), {"e": "notif", "id": nid}); return self.go("/admin/news?ok=newspub")
        if len(parts) == 4 and parts[1] == "news" and parts[3] == "delete" and parts[2].isdigit():
            run("delete from notif_seen where notif_id=?", (parts[2],)); run("delete from notifs where id=?", (parts[2],)); push_sync(*ws.hub.online_ids()); return self.go("/admin/news?ok=newsdel")
        if p == "/admin/users/bulkdelete":
            ids = [int(x) for x in self.fl.get("ids", []) if x.isdigit() and int(x) != u["id"]]
            if not ids or not f.get("confirm"): return self.go("/admin/users?ok=nosel")
            make_backup("predelete")
            for x in ids: purge_user(x)
            return self.go("/admin/users?ok=bulkdel")
        if len(parts) == 4 and parts[1] == "support":
            t = one("select * from tickets where id=?", (parts[2],))
            if not t: return self.go("/admin/support")
            act, base = parts[3], f"/admin/support/{t['id']}"
            if act == "reply":
                body = f.get("body", "").strip()[:3000]
                if not body: return self.out(self.a_ticket(u, t["id"], err="Escreve a resposta."), 400)
                now = now_str(); run("insert into tmsgs(ticket_id,from_admin,body,created) values(?,?,?,?)", (t["id"], 1, body, now))
                run("update tickets set updated=?, unread_user=1, unread_admin=0 where id=?", (now, t["id"]))
                if smtp_ready() and BASE_URL:
                    mail_async(t["email"], i18n.mail("reply_s", t["lang"], site=SN()), i18n.mail("reply_b", t["lang"], name=t["name"], subject=t["subject"], reply=body, url=f"{BASE_URL}/support/t/{t['token']}"))
                return self.go(base + "?ok=reply")
            if act == "close":
                run("update tickets set status=? where id=?", ("open" if t["status"] == "closed" else "closed", t["id"]))
                return self.go(("/admin/support" if t["status"] != "closed" else base) + ("?ok=closed" if t["status"] != "closed" else "?ok=reopened"))
            if act == "delete": run("delete from tickets where id=?", (t["id"],)); return self.go("/admin/support?ok=deleted")
        if p == "/admin/db/snapshot": make_backup("manual"); return self.go("/admin/db?ok=snap")
        if p == "/admin/db/sql":
            q = f.get("q", "").strip()
            if not q: return self.go("/admin/db")
            res = sql_run(q, bool(f.get("confirm")))
            return self.out(self.a_db(u, q=q, res=res))
        if len(parts) == 4 and parts[1] == "user":
            t = one("select * from users where id=?", (parts[2],))
            if not t: return self.go("/admin/users")
            tid, act = t["id"], parts[3]; me = tid == u["id"]; back = f"/admin/user/{tid}"
            bad = lambda m: self.out(self.a_user(u, tid, err=m), 400)
            if act == "save":
                un, name, em, ph = f.get("username", "").strip(), f.get("name", "").strip()[:60], f.get("email", "").strip(), f.get("phone", "").strip()[:30]
                if not re.match(r"^[\w.\-]{3,30}$", un) or not name or not re.match(EMAIL_RE, em): return bad("Utilizador (3 a 30 caracteres), nome e email têm de ser válidos.")
                try: run("update users set username=?, name=?, email=?, phone=? where id=?", (un, name, em, ph, tid))
                except sqlite3.IntegrityError: return bad("Esse utilizador ou email já existe noutra conta.")
                return self.go(back + "?ok=user")
            if act == "admin":
                if t["is_admin"] and (me or one("select count(*) from users where is_admin=1")[0] <= 1): return bad("Não podes remover o último administrador, nem a ti próprio.")
                run("update users set is_admin=? where id=?", (0 if t["is_admin"] else 1, tid)); return self.go(back + "?ok=state")
            if act == "disable":
                if me: return bad("Não te podes suspender a ti próprio.")
                run("update users set disabled=? where id=?", (0 if t["disabled"] else 1, tid)); return self.go(back + "?ok=state")
            if act == "password":
                if len(f.get("p", "")) < 8: return bad("A palavra-passe tem de ter pelo menos 8 caracteres.")
                run("update users set pw=? where id=?", (hash_pw(f["p"]), tid)); run("delete from resets where user_id=?", (tid,))
                return self.go(back + "?ok=pw", [session_cookie(one("select * from users where id=?", (tid,)), self.https())] if me else [])
            if act == "link":
                tok = secrets.token_urlsafe(32); run("delete from resets where user_id=? or exp<?", (tid, time.time()))
                run("insert into resets values(?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), tid, int(time.time()) + 3600))
                host = BASE_URL or ("https://" if self.https() else "http://") + str(self.headers.get("Host"))
                return self.out(self.a_user(u, tid, link=f"{host}/reset?t={tok}"))
            if act == "ics": run("update users set ics=? where id=?", (secrets.token_hex(20), tid)); return self.go(back + "?ok=ics")
            if act == "delete":
                if me: return bad("Não podes apagar a tua própria conta aqui.")
                if f.get("confirm", "").strip().lower() != t["username"].lower(): return bad("Para apagar, escreve exatamente o nome de utilizador.")
                make_backup("predelete")
                purge_user(tid)
                return self.go("/admin/users")
        self.go("/admin")

    def restore(self):
        u = self.user()
        if not (u and u["is_admin"]): return self.out("Não autorizado", 403, "text/plain")
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0 or n > 100_000_000: return self.out("Ficheiro inválido ou demasiado grande (máximo 100 MB).", 400, "text/plain")
        os.makedirs(BACKUP_DIR, exist_ok=True); tmp = os.path.join(BACKUP_DIR, "upload.tmp")
        try:
            left = n
            with open(tmp, "wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk: break
                    fh.write(chunk); left -= len(chunk)
            with open(tmp, "rb") as fh: magic = fh.read(16)
            if magic != b"SQLite format 3\x00": return self.out("Isto não é um ficheiro de base de dados SQLite.", 400, "text/plain")
            s = sqlite3.connect(tmp)
            try:
                if s.execute("pragma integrity_check").fetchone()[0] != "ok": return self.out("O ficheiro está danificado.", 400, "text/plain")
                if not {"users", "events", "clients", "kv"} <= {r[0] for r in s.execute("select name from sqlite_master where type='table'")}:
                    return self.out("Este ficheiro não parece ser uma base de dados da Claquete.", 400, "text/plain")
                make_backup("prerestore"); d = db()
                try: s.backup(d)
                finally: d.close()
            finally: s.close()
            init(); self.out("ok", 200, "text/plain")
        except sqlite3.Error as ex: self.out(f"Erro: {ex}", 400, "text/plain")
        finally:
            if os.path.exists(tmp): os.remove(tmp)

    # ---- início
    def home(self, u, m):
        first, prev, nxt = month_nav(m); ym = first.strftime("%Y-%m"); i = u["id"]; mn = MES[first.month - 1]
        td = today().isoformat()
        a = rows(EV + "where e.user_id=? and e.invoice_date is null and e.end_date<=? order by e.start_date", (i, td))
        b = rows(EV + "where e.user_id=? and e.invoice_date is not null and e.paid=0 order by e.invoice_date", (i,))
        up = rows(EV + "where e.user_id=? and e.end_date>? order by e.start_date limit 5", (i, td))
        fm = one("select coalesce(sum(amount),0) s from events where user_id=? and substr(invoice_date,1,7)=?", (i,ym))["s"]
        rm = one("select coalesce(sum(amount),0) s from events where user_id=? and paid=1 and substr(invoice_date,1,7)=?", (i,ym))["s"]
        rm = one(f"select coalesce(sum({CASHSQL}),0) s from events where user_id=? and paid=1 and substr(invoice_date,1,7)=?", (i, ym))["s"]
        s = lambda l: sum(x["amount"] or 0 for x in l)
        sc = lambda l: sum(tax_of(x)[2] for x in l)
        tile = lambda c, lab, val, sub: f'<div class="st" style="--c:{c}"><span>{lab}</span><b>{eur(val)}</b><span>{sub}</span></div>'
        tip = ""
        if not u["guide_seen"] and not one("select 1 from events where user_id=?", (i,)):
            tip = '<div class="tip"><a href="/guide">👋 Novo por aqui? Vê em 2 minutos como funciona. <b>›</b></a><form method="post" action="/guide/dismiss"><button class="ib" aria-label="Fechar" title="Fechar">✕</button></form></div>'
        return page("Início", tip + f'<div class="bar-h"><div><h1>Olá, {e(u["name"] or u["username"])}</h1><p class="sub" style="margin:0">O ponto da situação.</p></div><a class="btn p" href="/event/new">Novo evento</a></div>'
            f'<div class="mn"><a class="btn" href="/?m={prev}">‹</a><b>{mn} {first.year}</b><a class="btn" href="/?m={nxt}">›</a><span class="m">aplica-se a Faturado e Recebido</span></div>'
            '<div class="strip">' + tile("var(--todo)", "Por faturar", s(a), pl(len(a), "evento")) + tile("var(--inv)", "Faturado, por receber", sc(b), pl(len(b), "evento"))
            + tile("var(--brand)", f"Faturado em {mn}", fm, "pela data da fatura") + tile("var(--paid)", f"Recebido de {mn}", rm, "já pago") + '</div>'
            + "<h2>Por faturar</h2>" + lst(a, "/", "Nada por faturar. 🎬") + "<h2>Por receber</h2>" + lst(b, "/", "Nada por receber.") + '<div class="bar-h"><h2>Por realizar</h2><a href="/events?f=agendados">Ver todos ›</a></div>' + lst(up, "/", "Sem eventos por realizar."), "/", u)

    # ---- eventos
    def events(self, u, f):
        td = today().isoformat(); order = "e.start_date desc"
        w = {"faturar": f"and e.invoice_date is null and e.end_date<='{td}'", "agendados": f"and e.end_date>'{td}'", "receber": "and e.invoice_date is not null and e.paid=0", "pagos": "and e.paid=1"}.get(f, "")
        if f == "agendados": order = "e.start_date asc"
        r = rows(EV + f"where e.user_id=? {w} order by {order}", (u["id"],))
        chips = "".join(f'<a class="{"on" if f == k else ""}" href="/events?f={k}">{n}</a>' for k, n in [("todos", "Todos"), ("agendados", "Por realizar"), ("faturar", "Por faturar"), ("receber", "Por receber"), ("pagos", "Pagos")])
        return page("Eventos", f'<div class="bar-h"><h1>Eventos</h1><a class="btn p" href="/event/new">Novo evento</a></div><div class="chips">{chips}</div>' + lst(r, f"/events?f={f}", "Sem eventos." + ('<br><a href="/guide/2">Vê como agendar o primeiro</a>' if not one("select 1 from events where user_id=?", (u["id"],)) else "")), "/events", u)

    def event_form(self, u, i, date=""):
        v = None
        if i != "new":
            v = one("select * from events where id=? and user_id=?", (i, u["id"]))
            if not v: raise ValueError
        its = [(x["label"], x["amount"]) for x in rows("select * from items where event_id=? order by id", (i,))] if v else []
        sd = v["start_date"] if v else (okdate(date) or today().isoformat()); ed = v["end_date"] if v else sd
        cl = "".join(f'<option value="{c["id"]}" data-i="{e(" · ".join(x for x in (c["rate"], c["terms"]) if x))}" {"selected" if v and c["id"] == v["client_id"] else ""}>{e(c["name"])}</option>' for c in rows("select * from clients where user_id=? order by name", (u["id"],)))
        rowsh = "".join(f'<div class="it"><input name="label" list="sug" value="{e(l)}" placeholder="Descrição"><input name="amt" inputmode="decimal" value="{f"{a:g}".replace(".", dsep())}" placeholder="0{dsep()}00"></div>' for l, a in (its or [(tx("Diária"), 0)]))
        dele = f'<details><summary>Apagar evento</summary><form method="post" action="/event/{v["id"]}/delete"><p class="m">Esta ação não pode ser desfeita.</p><button class="d">Confirmar: apagar</button></form></details>' if v else ""
        ck = lambda x: "checked" if x else ""
        return page("Evento", f'<h1>{"Editar" if v else "Novo"} evento</h1><form class="f card" method="post" action="/event/save"><input type="hidden" name="id" value="{v["id"] if v else ""}">'
            + fld("Título", "title", val=v["title"] if v else "", extra="required" + ("" if v else " autofocus"))
            + f'<div class="g2"><div><label>Data de início</label><input type="date" id="sd" name="start" value="{sd}" required></div><div><label>Data de fim</label><input type="date" id="ed" name="end" value="{ed}" required></div></div>'
            f'<label>Cliente</label><select id="cs" name="client_id"><option value="">— sem cliente —</option>{cl}</select><div class="info" id="ci" hidden></div>'
            f'<label>Valores</label><div id="items">{rowsh}</div><button type="button" id="add">+ Adicionar linha</button><div class="sum">Valor sem IVA<span id="tot">0{dsep()}00 €</span></div>'
            f'<div class="g2"><div><label>IVA</label>{vat_select(u["vat_country"] or "PT", vat_code(v["vat_mode"], v["vat_rate"]) if v else u["vat_def"] or "none")}</div><div><label>Retenção na fonte (IRS)</label>{wh_select((v["wh_rate"] if v else u["wh_def"]) or 0)}</div></div>'
            f'<div class="tx" id="tx" data-iva="{eh(tx("IVA"))}" data-ret="{eh(tx("Retenção"))}" data-tot="{eh(tx("Total a receber"))}" data-rc="{eh(tx("IVA liquidado pelo cliente (autoliquidação)"))}"></div>'
            '<datalist id="sug">' + "".join(f'<option value="{eh(tx(x))}">' for x in ("Diária", "Meia diária", "Hora extra", "Aluguer de equipamento", "Deslocação", "Edição")) + '</datalist>'
            + f'<div class="g2"><div><label>Data da fatura (vazio = por faturar)</label><input type="date" name="invoice_date" value="{e(v["invoice_date"] if v else "")}"></div><div><label>N.º da fatura</label><input name="invoice_no" value="{e(v["invoice_no"] if v else "")}"></div></div>'
            f'<label class="c" style="margin-top:14px"><input type="checkbox" name="paid" {ck(v and v["paid"])}>Fatura paga (já recebi)</label><label>Notas</label><textarea name="notes" rows="3">{e(v["notes"] if v else "")}</textarea>'
            '<p><button class="p">Guardar</button> <a class="btn" href="/events">Cancelar</a></p></form>' + (self.mail_card(u, v) if v else "") + (f'<div class="card"><b>Exportar este evento</b><p class="m" style="margin:4px 0 10px">Resumo informativo (não é uma fatura).</p><a class="btn" href="/export/run?scope=event&id={v["id"]}&fmt=pdf">PDF</a> <a class="btn" href="/export/run?scope=event&id={v["id"]}&fmt=xlsx">Excel</a></div>' if v else "") + dele
            + CUJS + '<script nonce="__NONCE__">(function(){var L=document.getElementById("items"),T=document.getElementById("tot");function tot(){var s=0;L.querySelectorAll("[name=amt]").forEach(function(i){s+=parseFloat(i.value.replace(",","."))||0});T.textContent=s.toFixed(2).replace(".","' + dsep() + '")+" €";if(window.TX)window.TX(s)}'
            'L.addEventListener("input",tot);tot();document.getElementById("add").onclick=function(){var d=document.createElement("div");d.className="it";d.innerHTML=\'<input name="label" list="sug" placeholder="' + tx("Descrição") + '"><input name="amt" inputmode="decimal" placeholder="0' + dsep() + '00">\';L.appendChild(d);d.firstChild.focus()};'
            'var S=document.getElementById("cs"),I=document.getElementById("ci");function inf(){var o=S.options[S.selectedIndex];I.textContent=o.dataset.i||"";I.hidden=!o.dataset.i}S.onchange=inf;inf();'
            'var a=document.getElementById("sd"),b=document.getElementById("ed");a.onchange=function(){if(!b.value||b.value<a.value)b.value=a.value}})();</script>'
            + '<script nonce="__NONCE__">(function(){var X=document.getElementById("tx"),V=document.querySelector("[name=vat]"),W=document.querySelector("[name=wh]"),VC=document.querySelector("[name=vatc]"),WC=document.querySelector("[name=whc]"),DS="' + dsep() + '";'
            'function n(x){return parseFloat(String(x).replace(",","."))||0}function f(x){return x.toFixed(2).replace(".",DS)+" €"}function p(x){return String(x).replace(".",DS)}'
            'window.TX=function(b){if(b===undefined){b=0;document.querySelectorAll("[name=amt]").forEach(function(i){b+=n(i.value)})}'
            'var vr=V.value=="custom"?n(VC.value):(V.value=="none"||V.value=="rc")?0:n(V.value),wr=W.value=="custom"?n(WC.value):n(W.value),v=b*vr/100,w=b*wr/100,h="";'
            'if(vr>0)h+="<div><span>"+X.dataset.iva+" "+p(vr)+"%</span><span>+"+f(v)+"</span></div>";else if(V.value=="rc")h+="<div><span>"+X.dataset.rc+"</span><span>"+f(0)+"</span></div>";'
            'if(wr>0)h+="<div><span>"+X.dataset.ret+" "+p(wr)+"%</span><span>\u2212"+f(w)+"</span></div>";'
            'if(vr>0||wr>0)h+="<div class=tt><span>"+X.dataset.tot+"</span><span>"+f(b+v-w)+"</span></div>";X.innerHTML=h};'
            '[V,W,VC,WC].forEach(function(e){e.addEventListener("input",function(){TX()});e.addEventListener("change",function(){TX()})});TX()})();</script>', "/events", u)

    def save_event(self, u, f):
        vm, vr = parse_vat(f.get("vat", "none"), f.get("vatc", "")); wr = parse_wh(f.get("wh", "0"), f.get("whc", ""))
        i = u["id"]; ex = one("select * from events where id=? and user_id=?", (f.get("id") or 0, i))
        sd = okdate(f.get("start", "")) or today().isoformat(); ed = okdate(f.get("end", "")) or sd; ed = sd if ed < sd else ed
        cid = f.get("client_id") if one("select 1 from clients where id=? and user_id=?", (f.get("client_id") or 0, i)) else None
        its = [(l.strip()[:80], num(a)) for l, a in zip(self.fl.get("label", []), self.fl.get("amt", [])) if l.strip() or a.strip()]
        inv = okdate(f.get("invoice_date", "")); paid = 1 if f.get("paid") else 0; t = today().isoformat()
        if paid and not inv: inv = t
        if not inv: paid = 0
        pd = (ex["paid_date"] if ex and ex["paid_date"] else t) if paid else None
        v = (f.get("title", "").strip()[:150] or "Evento", sd, ed, cid, sum(a for _, a in its), inv, f.get("invoice_no", "").strip()[:40], paid, pd, f.get("notes", "")[:2000], vm, vr, wr)
        c = db()
        try:
          if ex: c.execute("update events set title=?,start_date=?,end_date=?,client_id=?,amount=?,invoice_date=?,invoice_no=?,paid=?,paid_date=?,notes=?,vat_mode=?,vat_rate=?,wh_rate=? where id=?", v + (ex["id"],)); eid = ex["id"]
          else: eid = c.execute("insert into events(title,start_date,end_date,client_id,amount,invoice_date,invoice_no,paid,paid_date,notes,vat_mode,vat_rate,wh_rate,user_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", v + (i,)).lastrowid
          c.execute("delete from items where event_id=?", (eid,)); c.executemany("insert into items(event_id,label,amount) values(?,?,?)", [(eid, l, a) for l, a in its]); c.commit()
        finally: c.close()
        self.go("/events")

    # ---- clientes
    def clients(self, u):
        r = rows("select c.*, (select count(*) from events where client_id=c.id) n, (select coalesce(sum(amount),0) from events where client_id=c.id and paid=0 and invoice_date is not null) due from clients c where user_id=? order by name", (u["id"],))
        l = "".join(f'<div class="er"><a class="eh" href="/client/{c["id"]}">{avatar(c["name"], c["logo"])}<div><b>{e(c["name"])}</b><small>{e(c["rate"]) if c["rate"] else "sem valores definidos"} · {pl(c["n"], "evento")}</small></div></a><span class="amt">{eur(c["due"]) if c["due"] else ""}</span></div>' for c in r)
        return page("Clientes", f'<div class="bar-h"><h1>Clientes</h1><a class="btn p" href="/client/new">Novo cliente</a></div><div class="list">{l or "<div class=empty>Ainda sem clientes. <a href=/guide/1>Vê como começar</a></div>"}</div>', "/clients", u)

    def client_form(self, u, i):
        v = None
        if i != "new":
            v = one("select * from clients where id=? and user_id=?", (i, u["id"]))
            if not v: raise ValueError
        g = lambda k: v[k] if v else ""
        ta = lambda k, lab: f'<label>{lab}</label><textarea name="{k}" rows="3">{e(g(k))}</textarea>'
        hist = ("<h2>Eventos deste cliente</h2>" + lst(rows(EV + "where e.user_id=? and e.client_id=? order by e.start_date desc", (u["id"], i)), f"/client/{i}", "Sem eventos.")) if v else ""
        dele = f'<details><summary>Apagar cliente</summary><form method="post" action="/client/{v["id"]}/delete"><p class="m">Os eventos ficam, mas sem cliente.</p><button class="d">Confirmar: apagar</button></form></details>' if v else ""
        exp = (f'<div class="card"><b>Exportar todos os eventos deste cliente</b><p class="m" style="margin:4px 0 10px">Para um período ou estado específico usa <a href="/export?client={v["id"]}">Exportar</a>.</p><a class="btn" href="/export/run?client={v["id"]}&fmt=pdf">PDF</a> <a class="btn" href="/export/run?client={v["id"]}&fmt=xlsx">Excel</a></div>') if v else ""
        return page("Cliente", exp + f'<div class="bar-h"><h1>{"Editar" if v else "Novo"} cliente</h1>{avatar(g("name") or "?", g("logo")) if v else ""}</div><form class="f card" method="post" action="/client/save"><input type="hidden" name="id" value="{g("id")}">'
            + fld("Nome", "name", val=g("name"), extra="required") + fld("URL do logo (opcional)", "logo", "url", g("logo"), 'placeholder="https://..."') + fld("NIF", "nif", val=g("nif")) + fld("Contacto", "contact", val=g("contact"))
            + fld("Email(s) para envio de faturas (separados por vírgula)", "email", val=g("email"), extra='maxlength="300"')
            + fld("Valores acordados (ex.: 250 €/dia)", "rate", val=g("rate")) + ta("terms", "Condições de pagamento") + ta("notes", "Notas") + '<p><button class="p">Guardar</button> <a class="btn" href="/clients">Cancelar</a></p></form>' + hist + dele, "/clients", u)

    # ---- calendário
    def cal(self, u, m):
        first, prev, nxt = month_nav(m); i = u["id"]; weeks = calendar.Calendar(0).monthdatescalendar(first.year, first.month)
        lo, hi = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        evs = rows(EV + "where e.user_id=? and e.start_date<=? and e.end_date>=? order by e.start_date, e.end_date desc", (i, hi, lo)); out = ""
        for wk in weeks:
            w0, w1 = wk[0].isoformat(), wk[6].isoformat(); lanes = []; bars = ""
            for r in [r for r in evs if r["start_date"] <= w1 and r["end_date"] >= w0]:
                s = max(0, (D(r["start_date"]) - wk[0]).days); en = min(6, (D(r["end_date"]) - wk[0]).days)
                for li, last in enumerate(lanes):
                    if s > last: lanes[li] = en; lane = li; break
                else: lanes.append(en); lane = len(lanes) - 1
                cls = state(r) + (" cs" if r["start_date"] >= w0 else "") + (" ce" if r["end_date"] <= w1 else "")
                bars += f'<a class="bar {cls}" style="grid-column:{s + 1}/{en + 2};grid-row:{lane + 2}" href="/event/{r["id"]}" title="{e(r["title"])} · {e(r["cn"] or "")} · {eur(r["amount"])}">{e(r["title"])}</a>'
            L = len(lanes)
            cells = "".join(f'<a class="cell{" c0" if k == 0 else ""}{" out" if d.month != first.month else ""}{" we" if k > 4 else ""}{" now" if d == today() else ""}" style="grid-column:{k + 1};grid-row:1/span {L + 2}" href="/event/new?date={d.isoformat()}"><span>{d.day}</span></a>' for k, d in enumerate(wk))
            out += f'<div class="wk" style="grid-template-rows:30px repeat({L},var(--lh)) minmax(8px,1fr)">{cells}{bars}</div>'
        fm, lm = first.isoformat(), ((first + dt.timedelta(32)).replace(day=1) - dt.timedelta(1)).isoformat()
        month_ev = rows(EV + "where e.user_id=? and e.start_date<=? and e.end_date>=? order by e.start_date", (i, lm, fm))
        return page("Calendário", f'<div class="bar-h"><div class="mn" style="margin:0"><a class="btn" href="/calendar?m={prev}">‹</a><b style="font-size:1.3rem">{MES[first.month - 1]} {first.year}</b><a class="btn" href="/calendar?m={nxt}">›</a><a class="btn" href="/calendar">Hoje</a></div><a class="btn p" href="/event/new">Novo evento</a></div>'
            '<div class="cal"><div class="dh">' + "".join(f"<div>{d}</div>" for d in ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")) + f'</div>{out}</div>'
            '<div class="lgd m"><span style="--c:var(--todo)">por faturar</span><span style="--c:var(--inv)">faturada</span><span style="--c:var(--paid)">paga</span><span>toca num dia para criar um evento</span></div>'
            + "<h2>Neste mês</h2>" + lst(month_ev, f"/calendar?m={first:%Y-%m}", "Sem eventos neste mês."), "/calendar", u)

    def ics(self, k):
        u = one("select * from users where ics=?", (k,)) if k else None
        if not u: return self.out("Não autorizado", 403, "text/plain")
        esc = lambda s: str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Claquete//PT", f"X-WR-CALNAME:{SN()}"]
        for r in rows(EV + "where e.user_id=? order by e.start_date", (u["id"],)):
            st = "paga" if r["paid"] else "faturada" if r["invoice_date"] else "por faturar"
            L += ["BEGIN:VEVENT", f"UID:ev{r['id']}@claquete", f"DTSTAMP:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}", f"DTSTART;VALUE=DATE:{r['start_date'].replace('-', '')}",
                  f"DTEND;VALUE=DATE:{(D(r['end_date']) + dt.timedelta(1)):%Y%m%d}", f"SUMMARY:{esc(r['title'])}", f"DESCRIPTION:{esc((r['cn'] or '') + ' | ' + eur(r['amount']) + ' | ' + st)}", "END:VEVENT"]
        self.out("\r\n".join(L + ["END:VCALENDAR"]) + "\r\n", 200, "text/calendar; charset=utf-8")

    # ---- estatísticas
    def stats(self, u, y, g=lambda k, d="": d):
        i = u["id"]; cur = today().year
        years = sorted({int(r["y"]) for r in rows("select distinct substr(invoice_date,1,4) y from events where user_id=? and invoice_date is not null", (i,))} | {cur}, reverse=True)
        try: y = int(y)
        except ValueError: y = cur
        fat, rec, cnt = [0.0] * 12, [0.0] * 12, [0] * 12
        for r in rows("select cast(substr(invoice_date,6,2) as int) mo, sum(amount) f, sum(case when paid=1 then amount else 0 end) p, count(*) n from events where user_id=? and substr(invoice_date,1,4)=? group by mo", (i, str(y))):
            fat[r["mo"] - 1], rec[r["mo"] - 1], cnt[r["mo"] - 1] = r["f"] or 0, r["p"] or 0, r["n"]
        cl = rows("select coalesce(c.name,'Sem cliente') name, c.logo, count(*) n, sum(e.amount) v, sum(julianday(e.end_date)-julianday(e.start_date)+1) d from events e left join clients c on c.id=e.client_id where e.user_id=? and substr(e.invoice_date,1,4)=? group by e.client_id order by v desc", (i, str(y)))
        tf, tr, td = sum(fat), sum(rec), sum(c["d"] for c in cl); act = [k for k in range(12) if fat[k] > 0]
        best = max(act, key=lambda k: fat[k]) if act else None; worst = min(act, key=lambda k: fat[k]) if len(act) > 1 else None
        chips = "".join(f'<a class="{"on" if x == y else ""}" href="/stats?y={x}">{x}</a>' for x in years)
        Q = {k: {"b": 0.0, "v": 0.0, "w": 0.0} for k in (1, 2, 3, 4)}
        for r in rows(f"select (cast(substr(invoice_date,6,2) as int)+2)/3 q, sum(amount) b, sum({VATSQL}) v, sum({WHSQL}) w from events where user_id=? and substr(invoice_date,1,4)=? group by q", (i, str(y))):
            Q[r["q"]] = {"b": r["b"] or 0, "v": r["v"] or 0, "w": r["w"] or 0}
        tq = lambda key: sum(Q[k][key] for k in Q)
        qt = "".join(f'<tr><td>Trimestre {k}</td><td>{eur(Q[k]["b"])}</td><td>{eur(Q[k]["v"])}</td><td>{eur(Q[k]["w"])}</td><td>{eur(Q[k]["b"] + Q[k]["v"] - Q[k]["w"])}</td></tr>' for k in Q)
        tax = (f'<h2>Impostos por trimestre</h2><div class="card sc"><table class="tb"><tr><th>Trimestre</th><th>Faturado (sem IVA)</th><th>IVA</th><th>Retenção IRS</th><th>Total a receber</th></tr>{qt}'
               f'<tr><td><b>Total</b></td><td><b>{eur(tq("b"))}</b></td><td><b>{eur(tq("v"))}</b></td><td><b>{eur(tq("w"))}</b></td><td><b>{eur(tq("b") + tq("v") - tq("w"))}</b></td></tr></table></div>'
               '<p class="m">O IVA é do Estado (não é rendimento teu) e a retenção é imposto que o cliente já entregou por ti. Contam as faturas do ano pela data da fatura.</p>')
        if u["ss_on"]:
            rt, cf = (u["ss_rate"] if u["ss_rate"] is not None else 21.4), (u["ss_coef"] if u["ss_coef"] is not None else 70)
            pay = {1: (5, 7), 2: (8, 10), 3: (11, 1), 4: (2, 4)}
            def rr(k):
                a, b2 = pay[k]; return f"{MES[a - 1][:3]}–{MES[b2 - 1][:3]}"
            sr = "".join(f'<tr><td>Trimestre {k}</td><td>{eur(Q[k]["b"])}</td><td>{eur(Q[k]["b"] * cf / 100)}</td><td>{eur(Q[k]["b"] * cf / 100 * rt / 100)}</td><td>{eur(Q[k]["b"] * cf / 100 * rt / 100 / 3)}</td><td>{rr(k)}</td></tr>' for k in Q)
            tax += (f'<h2>Segurança Social (estimativa)</h2><div class="card sc"><table class="tb"><tr><th>Trimestre</th><th>Faturado (sem IVA)</th><th>Rendimento relevante</th><th>Contribuição</th><th>Por mês</th><th>A pagar em</th></tr>{sr}'
                    f'<tr><td><b>Total</b></td><td><b>{eur(tq("b"))}</b></td><td><b>{eur(tq("b") * cf / 100)}</b></td><td><b>{eur(tq("b") * cf / 100 * rt / 100)}</b></td><td></td><td></td></tr></table></div>'
                    f'<p class="m">{pct(rt)}% × {pct(cf)}% do faturado em cada trimestre, repartido por 3 meses. Estimativa sem limites mínimo e máximo, sem a isenção do primeiro ano e sem ajustes. Confirma sempre na Segurança Social Direta.</p>')
        else:
            tax += '<p class="m">Queres ver a estimativa da Segurança Social? Ativa-a em <a href="/settings">Conta</a>.</p>'
        tile = lambda c, lab, val, sub="": f'<div class="st" style="--c:{c}"><span>{lab}</span><b>{val}</b><span>{sub}</span></div>'
        strip = '<div class="strip">' + tile("var(--brand)", "Faturado", eur(tf), f"média {eur(tf / len(act)) if act else '—'}/mês") + tile("var(--paid)", "Recebido", eur(tr), f"por receber {eur(tf - tr)}") \
            + tile("var(--inv)", "Dias trabalhados", f"{td:g}", pl(sum(cnt), "evento")) + tile("var(--todo)", "Melhor mês", MES[best].capitalize() if best is not None else "—", eur(fat[best]) if best is not None else "") + '</div>'
        mt = "".join(f'<tr class="{"best" if k == best else "worst" if k == worst else ""}"><td>{MES[k].capitalize()}</td><td>{cnt[k]}</td><td>{eur(fat[k])}</td><td>{eur(rec[k])}</td><td>{eur(fat[k] - rec[k])}</td></tr>' for k in range(12))
        mx = max([c["v"] or 0 for c in cl] + [1]); mxd = max([c["d"] or 0 for c in cl] + [1])
        hb = lambda key, mxv, fmt: "".join(f'<div class="hb"><span>{e(c["name"])}</span><div class="t"><i style="width:{max(2, 100 * (c[key] or 0) / mxv):.0f}%"></i></div><b>{fmt(c[key])}</b></div>' for c in cl[:8]) or '<p class="m">Sem dados neste ano.</p>'
        ct = "".join(f'<tr><td>{e(c["name"])}</td><td>{c["n"]}</td><td>{c["d"]:g}</td><td>{eur(c["v"])}</td><td>{eur(c["v"] / c["d"]) if c["d"] else "—"}</td><td>{100 * c["v"] / tf:.0f}%</td></tr>' for c in cl) if tf else ""
        return page("Estatísticas", f'<div class="bar-h"><div><h1>Estatísticas</h1><p class="sub" style="margin:0">Contam os eventos já faturados, no mês e ano da data da fatura. <a href="/export">Exportar relatório ›</a></p></div></div><div class="chips">{chips}</div>{strip}' +
            self.chart_block(u, y, g) +
            f'<div class="card sc"><table class="tb"><tr><th>Mês</th><th>Eventos</th><th>Faturado</th><th>Recebido</th><th>Por receber</th></tr>{mt}<tr><td><b>Total</b></td><td><b>{sum(cnt)}</b></td><td><b>{eur(tf)}</b></td><td><b>{eur(tr)}</b></td><td><b>{eur(tf - tr)}</b></td></tr></table></div>'
            f'<h2>Clientes</h2><div class="g2"><div class="card"><b>Quem dá mais volume</b><div style="margin-top:8px">{hb("v", mx, eur)}</div></div><div class="card"><b>Dias trabalhados</b><div style="margin-top:8px">{hb("d", mxd, lambda v: f"{v:g} dias")}</div></div></div>'
            f'<div class="card sc"><table class="tb"><tr><th>Cliente</th><th>Eventos</th><th>Dias</th><th>Faturado</th><th>€/dia</th><th>Peso</th></tr>{ct}</table></div>' + tax, "/stats", u)

    PAL = ("#4c6ef5", "#f59f00", "#12b886", "#e8590c", "#ae3ec9", "#15aabf", "#e64980", "#82c91e")

    def chart_block(self, u, y, g):
        i = u["id"]; view = g("g") if g("g") in ("fr", "cl") else "fr"; met = g("m") if g("m") in ("v", "t", "d", "n") else "v"
        st = g("s") if g("s") in ("all", "paid", "open") else "all"; cid = g("c") if (g("c") or "").isdigit() else ""
        clients = rows("select id, name from clients where user_id=? order by lower(name)", (i,))
        data = rows("select e.*, coalesce(c.name,'') cn, julianday(e.end_date)-julianday(e.start_date)+1 dd from events e left join clients c on c.id=e.client_id where e.user_id=? and substr(e.invoice_date,1,4)=?", (i, str(y)))
        val = lambda r: {"v": r["amount"] or 0, "t": tax_of(r)[2], "d": r["dd"] or 0, "n": 1}[met]
        data = [r for r in data if (not cid or str(r["client_id"] or "") == cid) and (st == "all" or (st == "paid") == bool(r["paid"]))]
        mo = lambda r: int(r["invoice_date"][5:7]) - 1
        money = met in ("v", "t"); fmt = eur if money else (lambda v: f"{v:g}")
        if view == "fr":
            a, b = [0.0] * 12, [0.0] * 12
            for r in data:
                a[mo(r)] += val(r); b[mo(r)] += val(r) if r["paid"] else 0
            ser = [(tx("faturado"), "var(--brand)", a), (tx("recebido"), "var(--paid)", b)]; mode = "group"; extra = ""
        else:
            tot = {}
            for r in data: tot[r["client_id"]] = tot.get(r["client_id"], 0) + val(r)
            order = sorted(tot, key=lambda k: -tot[k]); top = order[:7]; names = {r["client_id"]: r["cn"] for r in data}
            ser = []
            for n_, k in enumerate(top):
                arr = [0.0] * 12
                for r in data:
                    if r["client_id"] == k: arr[mo(r)] += val(r)
                ser.append((names[k] or tx("Sem cliente"), self.PAL[n_], arr))
            if len(order) > 7:
                arr = [0.0] * 12
                for r in data:
                    if r["client_id"] not in top: arr[mo(r)] += val(r)
                ser.append((tx("Outros"), "#8a95a3", arr, False))
            mode = "stack"
            tm = [sum(x[2][k] for x in ser) for k in range(12)]
            lead = ""
            for k in range(12):
                if tm[k] > 0:
                    w = max(ser, key=lambda x: x[2][k]); lead += f'<span class="ld" style="--c:{w[1]}"><b>{MES[k][:3].capitalize()}</b> {e(w[0])} {100 * w[2][k] / tm[k]:.0f}%</span>'
            extra = (f'<h3 class="m" style="margin:14px 0 6px">Cliente com mais peso em cada mês</h3><div class="lds">{lead}</div>' if lead else "")
        lg = "".join(f'<span style="--c:{c_}">{e(n_) if view == "cl" else n_}{" · " + fmt(sum(a_)) if view == "cl" else ""}</span>' for n_, c_, a_ in ser)
        o = lambda v, lab, cur: f'<option value="{v}"{" selected" if cur == v else ""}>{lab}</option>'
        sel = lambda name, lab, opts: f'<div><label>{lab}</label><select name="{name}">{opts}</select></div>'
        form = (f'<form class="f fl" id="cf" method="get" action="/stats#chart"><input type="hidden" name="y" value="{y}">'
                + sel("g", "Gráfico", o("fr", "Faturado e recebido", view) + o("cl", "Peso de cada cliente", view))
                + sel("m", "Medir", o("v", "Valor sem IVA", met) + o("t", "Total a receber", met) + o("d", "Dias trabalhados", met) + o("n", "Nº de eventos", met))
                + sel("c", "Cliente", '<option value="">Todos os clientes</option>' + "".join(f'<option value="{c_["id"]}"{" selected" if cid == str(c_["id"]) else ""}>{e(c_["name"])}</option>' for c_ in clients))
                + sel("s", "Estado", o("all", "Todos", st) + o("paid", "Só pagos", st) + o("open", "Por receber", st))
                + '<div><button class="p">Aplicar</button></div></form>'
                '<script nonce="__NONCE__">document.querySelectorAll("#cf select").forEach(function(s){s.onchange=function(){s.form.submit()}});document.querySelector("#cf button").parentNode.hidden=true</script>')
        return (f'<h2 id="chart">Gráfico</h2><div class="card">{form}'
                + (self.chart2(ser, mode, money) if any(sum(x[2]) for x in ser) else '<p class="m">Sem dados com estes filtros.</p>')
                + f'<div class="lgd m">{lg}</div>{extra}</div>')

    def chart2(self, ser, mode, money):
        W, H, L, B, T = 720, 250, 46, 26, 10; pw, ph = W - L - 6, H - B - T
        mv = max([sum(x[2][k] for x in ser) for k in range(12)] if mode == "stack" else [max(x[2]) for x in ser] + [0])
        mag = 10 ** math.floor(math.log10(mv)) if mv > 0 else 1; mx = next((m * mag for m in (1, 2, 2.5, 5, 10) if mv <= m * mag), 10 * mag) if mv > 0 else 100
        fm = eur if money else (lambda v: f"{v:g}")
        o = f'<svg class="ch" viewBox="0 0 {W} {H}" role="img" aria-label="Gráfico">'
        for k in range(5): y = T + ph - ph * k / 4; o += f'<line class="gl" x1="{L}" x2="{W - 6}" y1="{y:.1f}" y2="{y:.1f}"/><text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{short(mx * k / 4) if money or mx >= 1000 else f"{mx * k / 4:g}"}</text>'
        sl = pw / 12
        for k in range(12):
            if mode == "group":
                for j, (n_, c_, arr) in enumerate(ser):
                    h = ph * arr[k] / mx; bw = sl * .32
                    o += f'<rect style="fill:{c_}" x="{L + k * sl + sl * .17 + j * (bw + 2):.1f}" y="{T + ph - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3"><title>{MES[k]}: {fm(arr[k])}</title></rect>'
            else:
                acc = 0.0; bw = sl * .6
                for n_, c_, arr in ser:
                    if arr[k] <= 0: continue
                    h = ph * arr[k] / mx; acc += h
                    o += f'<rect style="fill:{c_}" x="{L + k * sl + sl * .2:.1f}" y="{T + ph - acc:.1f}" width="{bw:.1f}" height="{max(h, 1):.1f}" rx="2"><title>{MES[k]} · {e(n_)}: {fm(arr[k])}</title></rect>'
            o += f'<text x="{L + k * sl + sl / 2:.1f}" y="{H - 7}" text-anchor="middle">{MES[k][:3]}</text>'
        return o + "</svg>"

    def chart(self, fat, rec):
        W, H, L, B, T = 720, 250, 46, 26, 10; pw, ph = W - L - 6, H - B - T; mv = max(fat + rec + [0])
        mag = 10 ** math.floor(math.log10(mv)) if mv > 0 else 1; mx = next((m * mag for m in (1, 2, 2.5, 5, 10) if mv <= m * mag), 10 * mag) if mv > 0 else 100
        o = f'<svg class="ch" viewBox="0 0 {W} {H}" role="img" aria-label="Faturado e recebido por mês">'
        for k in range(5): y = T + ph - ph * k / 4; o += f'<line class="gl" x1="{L}" x2="{W - 6}" y1="{y:.1f}" y2="{y:.1f}"/><text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{short(mx * k / 4)}</text>'
        sl = pw / 12
        for k in range(12):
            for j, (arr, c) in enumerate(((fat, "b1"), (rec, "b2"))):
                h = ph * arr[k] / mx; bw = sl * .32
                o += f'<rect class="{c}" x="{L + k * sl + sl * .17 + j * (bw + 2):.1f}" y="{T + ph - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3"><title>{MES[k]}: {eur(arr[k])}</title></rect>'
            o += f'<text x="{L + k * sl + sl / 2:.1f}" y="{H - 7}" text-anchor="middle">{MES[k][:3]}</text>'
        return o + "</svg>"

    # ---- tempo real
    def websocket(self, u):
        if not u: return self.out("", 401, "text/plain")
        key, org = self.headers.get("Sec-WebSocket-Key"), self.headers.get("Origin")
        hosts = (self.headers.get("Host"), self.headers.get("X-Forwarded-Host"))
        if not key or "websocket" not in (self.headers.get("Upgrade") or "").lower() or (org and urlparse(org).netloc not in hosts): return self.out("pedido inválido", 400, "text/plain")
        uid = u["id"]; sock = self.connection
        self.wfile.write(ws.handshake(key)); self.wfile.flush(); self.close_connection = True
        sock.settimeout(25); c = ws.Conn(sock, uid); rd = ws.Reader(sock)
        if ws.hub.add(uid, c): presence(uid, True)
        try:
            while True:
                try: op, data = rd.message()
                except socket.timeout: c.send(ws.frame(b"", 9)); continue
                if op == 8: break
                if op == 9: c.send(ws.frame(data, 10)); continue
                if op == 1: self.ws_msg(u, data)
        except (EOFError, OSError, ValueError): pass
        finally:
            if ws.hub.remove(uid, c): presence(uid, False)

    def ws_msg(self, u, data):
        try: d = json.loads(data.decode())
        except ValueError: return
        if isinstance(d, dict) and d.get("t") == "typing" and isinstance(d.get("c"), int) and chat_member(d["c"], u["id"]):
            ws.hub.push([x for x in member_ids(d["c"]) if x != u["id"]], {"e": "typing", "c": d["c"], "u": u["id"], "n": uname(u)})

    def avatar(self, uid):
        r = one("select mime, data from avatars where user_id=?", (uid,))
        if not r: raise ValueError
        self.out(base64.b64decode(r["data"]), 200, r["mime"], (("Cache-Control", "private, max-age=604800"),))

    def save_avatar(self, u, f):
        m = re.match(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$", f.get("img", ""))
        try: raw = base64.b64decode(m.group(2), validate=True) if m else b""
        except ValueError: raw = b""
        ok = len(raw) <= 140000 and ((m and m.group(1) == "jpeg" and raw[:3] == b"\xff\xd8\xff") or (m and m.group(1) == "png" and raw[:8] == b"\x89PNG\r\n\x1a\n")
                                     or (m and m.group(1) == "webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"))
        if not ok: return self.out(self.settings(u, err="Imagem inválida. Usa JPG, PNG ou WebP."), 400)
        run("insert into avatars(user_id,mime,data) values(?,?,?) on conflict(user_id) do update set mime=excluded.mime, data=excluded.data", (u["id"], "image/" + m.group(1), m.group(2)))
        run("update users set av_v=? where id=?", (int(time.time()), u["id"]))
        self.go("/settings?ok=avatar")

    # ---- novidades (notificações do admin)
    def notifications(self, u):
        me = u["id"]; cr = u["created"] or ""
        ns = rows("select n.*, (select 1 from notif_seen where user_id=? and notif_id=n.id) seen from notifs n where substr(n.created,1,10) >= ? order by n.id desc limit 100", (me, cr))
        run("insert or ignore into notif_seen(user_id,notif_id) select ?, id from notifs where substr(created,1,10) >= ?", (me, cr)); push_sync(me)
        nw = ' <span class="bd s">Novo</span>'
        cards = "".join(f'<div class="card nt"><h2>{e(notif_text(n)[0])}{"" if n["seen"] else nw}</h2><div class="m">{e(n["created"])}</div><p>{e(notif_text(n)[1])}</p></div>' for n in ns)
        return page("Novidades", f'<h1>Novidades</h1><p class="sub">O que mudou e o que há de novo.</p>{cards or "<div class=card>Ainda não há novidades.</div>"}', "/notifications", u)

    def notif_latest(self, u):
        n = one("select * from notifs n where substr(n.created,1,10) >= ? and n.id not in (select notif_id from notif_seen where user_id=?) order by n.id desc limit 1", (u["created"] or "", u["id"]))
        t, b = notif_text(n) if n else ("", "")
        self.out(json.dumps({"t": t, "b": b[:140]}), 200, "application/json", (("Cache-Control", "no-store"),))

    def a_news(self, u, ok="", err=""):
        ns = rows("select n.*, (select count(*) from notif_seen where notif_id=n.id) seen from notifs n order by id desc limit 50")
        total = one("select count(*) from users where disabled=0")[0]
        trf = "".join(f'<div class="card" style="margin:10px 0"><b>{v}</b>{fld("Título", "t_" + k, extra="maxlength=120")}<label>Mensagem</label><textarea name="b_{k}" rows="4" maxlength="3000"></textarea></div>' for k, v in i18n.LANGS.items() if k != "pt")
        lst = "".join(f'<div class="card nt"><div class="row2"><div style="flex:1"><h2>{e(n["title"])}</h2><div class="m">{e(n["created"])} · Lida por {n["seen"]}/{total}</div></div>'
                      f'<form method="post" action="/admin/news/{n["id"]}/delete"><button class="d">Apagar</button></form></div><p>{e(n["body"])}</p></div>' for n in ns)
        return self.apage(u, "/admin/news", (
            '<form class="f card" method="post" action="/admin/news/publish"><h2>Publicar novidade</h2><p class="m">Isto envia uma notificação a todas as contas. Escreve o texto principal e, se quiseres, traduções.</p>'
            + fld("Título", "title", extra='maxlength="120" required placeholder="UPDATE 3.0"') + '<label>Mensagem</label><textarea name="body" rows="6" maxlength="3000" required></textarea>'
            f'<details><summary>Traduções (opcional)</summary><p class="m">Se deixares vazio, usa-se o texto principal.</p>{trf}</details><p><button class="p">Publicar para todos</button></p></form>' + lst), ok, err)

    # ---- chat
    CHM = {"sent": "Pedido de amizade enviado.", "already": "Já são amigos.", "pend": "Já enviaste um pedido a esta pessoa.", "accepted": "Agora são amigos.",
           "nouser": "Não encontrámos ninguém com esse utilizador ou email.", "self": "Não podes adicionar-te a ti próprio.", "limit": "Demasiados pedidos. Tenta mais tarde.",
           "reqgone": "Pedido removido.", "fgone": "Amigo removido.", "gnew": "Grupo criado.", "noname": "Dá um nome ao grupo.", "madd": "Membro adicionado.",
           "left": "Saíste do grupo.", "gdel": "Grupo apagado.", "kick": "Membro removido."}
    CHERR = ("nouser", "self", "limit", "noname")

    def chat_shell(self, u, right, tab="c", ok="", open_=False, cur=0):
        pn = chat_panels(u, cur)
        fl = f'<p class="msg {"err" if ok in self.CHERR else "ok"}">{eh(self.CHM[ok])}</p>' if ok in self.CHM and not open_ else ""
        nb = lambda n: f'<i class="nb"{"" if n else " hidden"}>{n}</i>'
        left = (f'<aside class="cl" id="cl" data-tab="{tab}"><div class="ch"><b>Chat</b><button type="button" id="bn" class="ib" title="Ativar notificações no browser">🔔</button></div>{fl}'
                '<input id="cq" type="search" placeholder="Pesquisar..." autocomplete="off">'
                f'<div class="tabs" id="tb"><button type="button" data-t="c">Conversas{nb(pn["bc"])}</button><button type="button" data-t="f">Contactos{nb(pn["bf"])}</button><button type="button" data-t="g">Grupos</button></div>'
                f'<div class="pn" id="p-c">{pn["c"]}</div><div class="pn" id="p-f" hidden>{pn["f"]}</div><div class="pn" id="p-g" hidden>{pn["g"]}</div></aside>')
        return page("Chat", f'<div class="cw{" open" if open_ else ""}">{left}<section class="crm">{right}</section></div>', "/chat", u)

    def chat_get(self, u, p, parts, g):
        me = u["id"]
        if p == "/chat": return self.out(self.chat_shell(u, '<div class="ro"><div><div class="big">💬</div><p>Seleciona uma conversa para começar.</p></div></div>', g("t", "c"), g("ok")))
        if p == "/chat/state": return self.out(json.dumps({"chat": chat_badge(me), "notif": notif_unread(u)}), 200, "application/json", (("Cache-Control", "no-store"),))
        if p == "/chat/panels":
            pn = chat_panels(u, int(g("cid", "0") or 0))
            return self.out(f'<div data-bc="{pn["bc"]}" data-bf="{pn["bf"]}"></div><div data-p="c">{pn["c"]}</div><div data-p="f">{pn["f"]}</div><div data-p="g">{pn["g"]}</div>')
        if p == "/chat/new":
            fr = friends_of(me)
            form = ('<div class="gnew"><p><a class="back" href="/chat?t=g">‹ Chat</a></p><h2>Novo grupo</h2>' + ('<form class="f" method="post" action="/chat/group/new">' + fld("Nome do grupo", "name", extra='maxlength="40" required')
                    + '<label>Escolhe os amigos para o grupo:</label><input id="gq" placeholder="Pesquisar..." autocomplete="off"><div class="gf">'
                    + "".join(f'<label class="c"><input type="checkbox" name="m" value="{r["id"]}" style="width:auto">{e(uname(r))} <span class="m">@{e(r["username"])}</span></label>' for r in fr)
                    + '</div><p><button class="p">Criar grupo</button></p></form>'
                    '<script nonce="__NONCE__">document.getElementById("gq").oninput=function(){var q=this.value.toLowerCase();document.querySelectorAll(".gf label").forEach(function(l){l.style.display=l.textContent.toLowerCase().indexOf(q)<0?"none":""})}</script>'
                    if fr else '<p class="m">Precisas de amigos para criar um grupo.</p>') + '</div>')
            return self.out(self.chat_shell(u, form, "g", open_=True))
        if len(parts) == 3 and parts[1] == "img":
            r = one("select * from chat_imgs where id=?", (int(parts[2]),))
            if not r or not chat_member(r["chat_id"], me): raise ValueError
            return self.out(base64.b64decode(r["data"]), 200, r["mime"], (("Cache-Control", "private, max-age=86400"),))
        cid = int(parts[1]); m = chat_member(cid, me)
        if not m: raise ValueError
        if len(parts) == 3 and parts[2] == "poll":
            bef = int(g("before", "0") or 0); aft = int(g("after", "0") or 0)
            if bef:
                ms = rows("select m.*, u.name, u.username, u.av_v, exists(select 1 from chat_imgs i where i.id=m.img) ie from chat_msgs m join users u on u.id=m.user_id where m.chat_id=? and m.id<? order by m.id desc limit 50", (cid, bef))[::-1]
                more = bool(ms) and bool(one("select 1 from chat_msgs where chat_id=? and id<?", (cid, ms[0]["id"])))
            else:
                ms = rows("select m.*, u.name, u.username, u.av_v, exists(select 1 from chat_imgs i where i.id=m.img) ie from chat_msgs m join users u on u.id=m.user_id where m.chat_id=? and m.id>? order by m.id limit 100", (cid, aft)); more = False
                self.mark_read(cid, me)
            return self.out(json.dumps({"more": more, "m": [{"id": x["id"], "me": x["user_id"] == me, "n": uname(x), "t": x["created"], "b": x["body"], "u": x["user_id"], "a": x["av_v"], "img": x["img"] if x["ie"] else 0, "gone": 1 if x["img"] and not x["ie"] else 0} for x in ms]}), 200, "application/json", (("Cache-Control", "no-store"),))
        return self.out(self.chat_room(u, cid, g("ok")))

    def mark_read(self, cid, me):
        mx = one("select coalesce(max(id),0) from chat_msgs where chat_id=?", (cid,))[0]
        cur = one("select last_read from chat_members where chat_id=? and user_id=?", (cid, me))["last_read"] or 0
        if mx > cur:
            run("update chat_members set last_read=? where chat_id=? and user_id=?", (mx, cid, me))
            ws.hub.push([x for x in member_ids(cid) if x != me], {"e": "read", "c": cid, "u": me, "upto": mx}); push_sync(me)

    def chat_room(self, u, cid, k=""):
        me = u["id"]; c = one("select * from chats where id=?", (cid,)); grp = c["kind"] == "group"; owner = c["owner"] == me
        mem = rows("select u.* from chat_members m join users u on u.id=m.user_id where m.chat_id=? order by lower(coalesce(nullif(u.name,''),u.username))", (cid,))
        ms = rows("select m.*, u.name, u.username, u.av_v, exists(select 1 from chat_imgs i where i.id=m.img) ie from chat_msgs m join users u on u.id=m.user_id where m.chat_id=? order by m.id desc limit 60", (cid,))[::-1]
        more = bool(ms) and bool(one("select 1 from chat_msgs where chat_id=? and id<?", (cid, ms[0]["id"])))
        peer = None if grp else next((x for x in mem if x["id"] != me), None); plr = (chat_member(cid, peer["id"])["last_read"] or 0) if peer else 0
        out, day = [], ""
        for x in ms:
            if x["created"][:10] != day: day = x["created"][:10]; out.append(f'<div class="ds">{day_label(day)}</div>')
            out.append(msg_html(x, me, not grp, plr))
        self.mark_read(cid, me)
        fl = f'<p class="msg {"err" if k in self.CHERR else "ok"}" style="margin:8px 12px 0">{eh(self.CHM[k])}</p>' if k in self.CHM else ""
        base = f"/chat/{cid}"
        if grp:
            title = e(c["name"]); av = f'<span class="av u g">{e(ini(c["name"]))}</span>'; sub = f'<small id="rs">{pl(len(mem), "membro")}</small>'
            inids = {x["id"] for x in mem}; cand = [x for x in friends_of(me) if x["id"] not in inids]
            rows_m = "".join(f'<div class="mb">{uav(x)}<span>{e(uname(x))}{" (Dono)" if x["id"] == c["owner"] else ""}</span>'
                             + (f'<form method="post" action="{base}/kick/{x["id"]}"><button class="d">✕</button></form>' if owner and x["id"] != me else "") + "</div>" for x in mem)
            addf = (f'<form method="post" action="{base}/add"><select name="uid" required><option value="">— escolhe um amigo —</option>' + "".join(f'<option value="{x["id"]}">{e(uname(x))}</option>' for x in cand)
                    + '</select><button>Adicionar</button></form>') if owner and cand else ("<p class=m>Todos os teus amigos já estão neste grupo.</p>" if owner else "")
            menu = (f'<div class="gp"><b>Informação do grupo</b>{rows_m}{addf}<div class="row2" style="margin-top:10px"><form method="post" action="{base}/leave"><button>Sair do grupo</button></form>'
                    + (f'<form method="post" action="{base}/delete"><button class="d">Apagar grupo</button></form>' if owner else "") + "</div></div>")
        else:
            title = e(uname(peer)); av = f'<span class="avw">{uav(peer)}<i class="dot" data-pres="{peer["id"]}"{"" if is_online(peer["id"]) else " hidden"}></i></span>'
            sub = f'<small id="rs" data-ps="{peer["id"]}">{pres_text(peer)}</small>'
            f_ = one("select id from friends where status='ok' and ((a=? and b=?) or (a=? and b=?))", (me, peer["id"], peer["id"], me))
            menu = f'<div class="gp"><div class="mb">{uav(peer)}<span><b>{title}</b><br><span class="m">@{e(peer["username"])}</span></span></div><form method="post" action="/chat/friend/remove/{f_["id"] if f_ else 0}"><button class="d">Remover amigo</button></form></div>'
        right = (f'<header class="rh"><a class="back" href="/chat">‹</a>{av}<div class="rt"><b>{title}</b>{sub}</div><details class="gi"><summary>⋮</summary>{menu}</details></header>{fl}'
                 f'<div class="rm" id="msgs" data-cid="{cid}" data-dm="{0 if grp else 1}" data-last="{ms[-1]["id"] if ms else 0}" data-first="{ms[0]["id"] if ms else 0}" data-day="{ms[-1]["created"][:10] if ms else ""}">'
                 f'{"<button type=button id=more>Carregar mensagens anteriores</button>" if more else ""}{"".join(out)}</div>'
                 f'<form class="rc" id="sf" method="post" action="{base}/send"><div class="ep" id="ep" hidden></div><button type="button" class="ib" id="eb" title="Emojis" aria-label="Emojis">😊</button><button type="button" class="ib" id="ib" title="Enviar imagem (apagada ao fim de 5 dias)" aria-label="Enviar imagem">📷</button><input type="file" id="if" accept="image/*" hidden><input name="body" maxlength="1000" autocomplete="off" placeholder="Escreve uma mensagem..."><button class="p">Enviar</button></form>')
        return self.chat_shell(u, right, "g" if grp else "c", open_=True, cur=cid)

    def chat_post(self, u, p, parts, f):
        me = u["id"]; go = lambda k="", to="/chat": self.go(to + (f"?ok={k}" if k else ""))
        if p == "/chat/friend/add":
            ip = "fr" + str(me); n, t0 = self.fails.get(ip, (0, 0))
            if n >= 20 and time.time() - t0 < 3600: return go("limit")
            self.fails[ip] = (n + 1 if time.time() - t0 < 3600 else 1, time.time())
            q = f.get("q", "").strip()[:120]; t = one("select * from users where (lower(username)=lower(?) or lower(email)=lower(?)) and disabled=0", (q, q)) if q else None
            if not t: return go("nouser", "/chat?t=f")
            if t["id"] == me: return go("self", "/chat?t=f")
            ex = one("select * from friends where (a=? and b=?) or (a=? and b=?)", (me, t["id"], t["id"], me))
            if ex:
                if ex["status"] == "ok": return go("already", "/chat?t=f")
                if ex["a"] == me: return go("pend", "/chat?t=f")
                accept_friend(ex); return go("accepted", "/chat?t=f")
            run("insert into friends(a,b,status,created) values(?,?,'pending',?)", (me, t["id"], now_str())); push_sync(t["id"]); return go("sent", "/chat?t=f")
        if len(parts) == 4 and parts[1] == "friend" and parts[3].isdigit():
            r = one("select * from friends where id=? and (a=? or b=?)", (parts[3], me, me))
            if not r: return go()
            other = r["a"] if r["b"] == me else r["b"]
            if parts[2] == "accept" and r["b"] == me and r["status"] == "pending":
                accept_friend(r); return go("accepted", "/chat?t=f")
            if parts[2] == "remove":
                run("delete from friends where id=?", (r["id"],))
                if r["status"] == "ok": run("delete from chats where kind='dm' and id=?", (dm_chat(r["a"], r["b"]),))
                push_sync(me, other); return go("fgone" if r["status"] == "ok" else "reqgone", "/chat?t=f")
            return go()
        if len(parts) == 3 and parts[1] == "dm" and parts[2].isdigit():
            if not any(x["id"] == int(parts[2]) for x in friends_of(me)): return go()
            return self.go(f"/chat/{dm_chat(me, int(parts[2]))}")
        if p == "/chat/group/new":
            name = f.get("name", "").strip()[:40]
            if not name: return go("noname", "/chat?t=g")
            fids = {x["id"] for x in friends_of(me)}; sel = [int(x) for x in self.fl.get("m", []) if x.isdigit() and int(x) in fids][:49]
            cid = run("insert into chats(kind,name,owner,created) values('group',?,?,?)", (name, me, now_str()))
            for x in [me] + sel: run("insert into chat_members(chat_id,user_id) values(?,?)", (cid, x))
            push_sync(*sel); return self.go(f"/chat/{cid}?ok=gnew")
        if len(parts) >= 3 and parts[1].isdigit():
            cid = int(parts[1]); c = one("select * from chats where id=?", (cid,)); act = parts[2]
            if not c or not chat_member(cid, me): raise ValueError
            room = f"/chat/{cid}"
            if act == "read": self.mark_read(cid, me); return self.out("ok", 200, "text/plain")
            if act == "send":
                ip = "c" + str(me); n, t0 = self.fails.get(ip, (0, 0)); body = f.get("body", "").strip()[:1000]
                self.fails[ip] = (n + 1 if time.time() - t0 < 60 else 1, time.time())
                im = re.match(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$", f.get("img", "")[:560000]) if f.get("img") else None
                raw = b""
                if im:
                    try: raw = base64.b64decode(im.group(2), validate=True)
                    except ValueError: raw = b""
                    if len(raw) > 420000 or not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")): raw = b""
                if (body or raw) and not (n >= 40 and time.time() - t0 < 60):
                    now = now_str(); iid = 0
                    if raw: iid = run("insert into chat_imgs(chat_id,mime,data,created) values(?,?,?,?)", (cid, "image/" + im.group(1), im.group(2), now))
                    mid = run("insert into chat_msgs(chat_id,user_id,body,created,img) values(?,?,?,?,?)", (cid, me, body, now, iid))
                    run("update chat_members set last_read=? where chat_id=? and user_id=?", (mid, cid, me))
                    ws.hub.push(member_ids(cid), {"e": "msg", "c": cid, "id": mid, "u": me, "n": uname(u), "a": u["av_v"], "b": body, "t": now, "img": iid})
                return self.out("ok", 200, "text/plain") if f.get("ajax") else self.go(room)
            if c["kind"] != "group": return self.go(room)
            mem = member_ids(cid)
            if act == "leave":
                run("delete from chat_members where chat_id=? and user_id=?", (cid, me))
                nx = one("select user_id from chat_members where chat_id=? order by rowid limit 1", (cid,))
                if not nx: run("delete from chats where id=?", (cid,))
                elif c["owner"] == me: run("update chats set owner=? where id=?", (nx["user_id"], cid))
                push_sync(*mem); return go("left", "/chat?t=g")
            if c["owner"] != me: return self.go(room)
            if act == "delete": run("delete from chats where id=?", (cid,)); push_sync(*mem); return go("gdel", "/chat?t=g")
            if act == "add" and f.get("uid", "").isdigit() and int(f["uid"]) in {x["id"] for x in friends_of(me)}:
                run("insert or ignore into chat_members(chat_id,user_id) values(?,?)", (cid, int(f["uid"]))); push_sync(*mem, int(f["uid"])); return self.go(room + "?ok=madd")
            if act == "kick" and len(parts) == 4 and parts[3].isdigit() and int(parts[3]) != me:
                run("delete from chat_members where chat_id=? and user_id=?", (cid, int(parts[3]))); push_sync(*mem); return self.go(room + "?ok=kick")
            return self.go(room)
        self.go("/chat")

    # ---- sobre e suporte (público)
    def guide_page(self, u, p):
        G = guide; n = len(G.TOPICS); parts = p.strip("/").split("/")
        if len(parts) == 1:
            cards = "".join(f'<a class="card gc" href="/guide/{i + 1}"><span class="gn">{i + 1}</span><span class="gi2">{t[0]}</span><span class="ct"><b>{eh(t[1][0])}</b><small>{eh(t[2][0])}</small></span><span class="m">›</span></a>' for i, t in enumerate(G.TOPICS))
            go = '<a class="btn p" href="/">' + eh(G.UI["home"][0]) + '</a>' if u else '<a class="btn p" href="/login">' + eh(G.UI["login"][0]) + '</a>'
            return shell(G.UI["title"][0], f'<h1>{eh(G.UI["title"][0])}</h1><p class="sub">{eh(G.UI["sub"][0])}</p><div class="card ab"><p style="margin:0">{eh(G.UI["intro"][0])}</p></div>{cards}'
                         f'<p style="margin:18px 0">{go}</p><div class="card"><p style="margin:0 0 12px">{eh(G.UI["help"][0])}</p><a class="btn" href="/support">{eh("Falar com o suporte")}</a></div>', u, "/guide")
        i = int(parts[1]) - 1
        if len(parts) != 2 or not 0 <= i < n: raise ValueError
        ico, t, _s, body = G.TOPICS[i]; out, ul = [], []
        for k, tx_ in body:
            if k == "li": ul.append(f"<li>{eh(tx_[0])}</li>"); continue
            if ul: out.append("<ul>" + "".join(ul) + "</ul>"); ul = []
            out.append(f"<p>{eh(tx_[0])}</p>")
        if ul: out.append("<ul>" + "".join(ul) + "</ul>")
        nav = (f'<a class="btn" href="/guide/{i}">‹ {eh(G.UI["prev"][0])}</a>' if i else "") + f'<a class="btn" href="/guide">{eh(G.UI["index"][0])}</a>' + (f'<a class="btn p" href="/guide/{i + 2}">{eh(G.UI["next"][0])} ›</a>' if i + 1 < n else "")
        return shell(t[0], f'<p class="m"><a href="/guide">‹ {eh(G.UI["title"][0])}</a> · {i + 1}/{n}</p><h1><span class="gi2">{ico}</span> {eh(t[0])}</h1>{guide_art.SCENES[i]()}<div class="card ab gt">{"".join(out)}</div><div class="row2" style="justify-content:space-between">{nav}</div>', u, "/guide")

    def about(self, u):
        c = cfg(); sn = e(c["site_name"])
        li = "".join(f"<li>{eh(x)}</li>" for x in ("Organizar eventos, incluindo trabalhos de vários dias e com vários valores.", "Guardar clientes com logótipo, valores acordados e condições de pagamento.",
                     "Saber de relance o que falta faturar, o que falta receber e o que já recebeste, mês a mês.", "Ver estatísticas e gráficos do teu ano.", "Ligar o calendário ao Google Calendar."))
        return shell("Sobre", f'<h1>Sobre {sn}</h1><p class="sub">Este site é um organizador pessoal para freelancers de audiovisual: guarda num só sítio os teus eventos, os teus clientes e o estado de cada fatura.</p>'
            f'<div class="card ab"><h2 style="margin-top:0">O que podes fazer</h2><ul>{li}</ul></div>'
            '<div class="card ab"><h2 style="margin-top:0">Importante</h2><p style="margin:0">Este site não emite faturas: a emissão continua a ser feita por ti, no teu programa de faturação. Aqui só acompanhas o estado de cada uma: por faturar, faturada ou paga.</p></div>'
            '<div class="card ab"><h2 style="margin-top:0">Privacidade</h2><p style="margin:0">Cada conta vê apenas os seus próprios eventos e clientes. Os dados ficam no servidor onde este site está instalado.</p></div>'
            f'<div class="card"><div class="cr"><b>Feito por Daniel Nunes</b><span class="m">·</span><b>Made in Portugal</b>{FLAG}</div></div>'
            f'<div class="card"><p style="margin:0 0 12px">Precisas de ajuda ou tens uma sugestão?</p><a class="btn p" href="/support">Falar com o suporte</a></div>', u, "/about")

    def support_get(self, u, p, g):
        parts = p.strip("/").split("/")
        if p == "/support": return self.support_page(u, ok=g("ok"))
        if len(parts) == 3 and parts[1] == "t": return self.ticket_page(u, parts[2], g("ok"))
        raise ValueError

    def support_page(self, u, ok="", err="", v=None):
        v = v or {}; fl = f'<p class="msg err">{eh(err)}</p>' if err else ""
        if u:
            ident = f'<p class="m">A escrever como <b>{e(u["name"] or u["username"])}</b> ({e(u["email"])}). As respostas aparecem aqui e também são enviadas para o teu email.</p>'
        else:
            ident = ('<p class="m">Ainda não tens conta ou não consegues entrar? Podes escrever na mesma: indica o teu email para podermos responder.</p>'
                     + fld("O teu nome", "name", val=v.get("name", ""), extra='maxlength="60" required autocomplete="name"')
                     + fld("O teu email (obrigatório, para podermos responder)", "email", "email", v.get("email", ""), 'maxlength="120" required autocomplete="email"'))
        form = ('<form class="f card" method="post" action="/support">' + ident + fld("Assunto", "subject", val=v.get("subject", ""), extra='maxlength="120" required')
                + f'<label>Mensagem</label><textarea name="body" rows="6" maxlength="3000" required>{e(v.get("body", ""))}</textarea>'
                '<input type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0">'
                '<p><button class="p">Enviar mensagem</button></p></form>')
        mine = ""
        if u:
            ts = rows("select * from tickets where user_id=? order by updated desc limit 30", (u["id"],))
            items = "".join(f'<div class="er {"todo" if t["unread_user"] else ""}"><a class="eh" href="/support/t/{t["token"]}"><div><b>{e(t["subject"])}</b>'
                            f'<small>{e(t["updated"])} · {"Fechada" if t["status"] == "closed" else "Aberta"}{" · <b>Nova resposta</b>" if t["unread_user"] else ""}</small></div></a></div>' for t in ts)
            mine = f'<h2>As tuas mensagens</h2><div class="list">{items or "<div class=empty>Ainda não enviaste nenhuma mensagem.</div>"}</div>'
        return shell("Suporte", f'<h1>Suporte</h1><p class="sub">Tens uma dúvida, um problema ou uma sugestão? Escreve-nos e respondemos o mais depressa possível.</p>{fl}{form}{mine}', u, "/support")

    def ticket_page(self, u, tok, ok=""):
        t = one("select * from tickets where token=?", (tok,))
        if not t: raise ValueError
        if t["unread_user"]: run("update tickets set unread_user=0 where id=?", (t["id"],))
        ms = rows("select * from tmsgs where ticket_id=? order by id", (t["id"],))
        bub = "".join(f'<div class="mg{" a" if m["from_admin"] else ""}"><small>{"Suporte" if m["from_admin"] else "Tu"} · {e(m["created"])}</small>{e(m["body"])}</div>' for m in ms)
        fl = f'<p class="msg ok">{eh("Mensagem enviada. A resposta aparece nesta página e é enviada para o teu email. Guarda este endereço para voltares cá." if ok == "sent" else "Resposta enviada.")}</p>' if ok in ("sent", "reply") else ""
        note = '<p class="m">Esta conversa está fechada. Se responderes, volta a abrir.</p>' if t["status"] == "closed" else ""
        return (shell("Suporte", f'<p><a class="m" href="/support">‹ Suporte</a></p><h1>{e(t["subject"])}</h1><p class="sub">Conversa com o suporte</p>{fl}<div class="msgs">{bub}</div>{note}'
            f'<form class="f card" method="post" action="/support/t/{e(tok)}/reply"><label>Responder</label><textarea name="body" rows="4" maxlength="3000" required></textarea>'
            '<p><button class="p">Enviar resposta</button></p></form>', u, "/support"))

    def support_post(self, u, p, f):
        parts = p.strip("/").split("/"); ip = "s" + self.client_address[0]; n, t0 = self.fails.get(ip, (0, 0)); lim = n >= 8 and time.time() - t0 < 3600
        host = BASE_URL or ("https://" if self.https() else "http://") + str(self.headers.get("Host"))
        if p == "/support":
            if f.get("website"): return self.go("/support")
            if lim: return self.out(self.support_page(u, err="Demasiadas mensagens. Tenta mais tarde.", v=f), 429)
            subj, body = f.get("subject", "").strip()[:120], f.get("body", "").strip()[:3000]
            name, em, uid = ((u["name"] or u["username"]), u["email"], u["id"]) if u else (f.get("name", "").strip()[:60], f.get("email", "").strip()[:120], None)
            if not subj or len(body) < 3 or not name or not re.match(EMAIL_RE, em): return self.out(self.support_page(u, err="Preenche o nome, um email válido, o assunto e a mensagem.", v=f), 400)
            self.fails[ip] = (n + 1 if time.time() - t0 < 3600 else 1, time.time()); tok = secrets.token_urlsafe(18); now = now_str()
            tid = run("insert into tickets(token,user_id,name,email,subject,lang,created,updated) values(?,?,?,?,?,?,?,?)", (tok, uid, name, em, subj, i18n.lang(), now, now))
            run("insert into tmsgs(ticket_id,from_admin,body,created) values(?,?,?,?)", (tid, 0, body, now))
            notify_admins(f"{SN()} · Nova mensagem de suporte", f"{name} <{em}>\nAssunto: {subj}\n\n{body}\n\n" + (f"Responder: {BASE_URL}/admin/support/{tid}\n" if BASE_URL else ""))
            if BASE_URL: mail_async(em, i18n.mail("ack_s", site=SN()), i18n.mail("ack_b", name=name, subject=subj, url=f"{BASE_URL}/support/t/{tok}"))
            return self.go(f"/support/t/{tok}?ok=sent")
        if len(parts) == 4 and parts[1] == "t" and parts[3] == "reply":
            t = one("select * from tickets where token=?", (parts[2],))
            if not t: raise ValueError
            body = f.get("body", "").strip()[:3000]
            if len(body) < 1 or lim: return self.go(f"/support/t/{parts[2]}")
            self.fails[ip] = (n + 1 if time.time() - t0 < 3600 else 1, time.time()); now = now_str()
            run("insert into tmsgs(ticket_id,from_admin,body,created) values(?,?,?,?)", (t["id"], 0, body, now))
            run("update tickets set status='open', updated=?, unread_admin=1 where id=?", (now, t["id"]))
            notify_admins(f"{SN()} · Nova mensagem de suporte", f"{t['name']} <{t['email']}>\nAssunto: {t['subject']}\n\n{body}\n\n" + (f"Responder: {BASE_URL}/admin/support/{t['id']}\n" if BASE_URL else ""))
            return self.go(f"/support/t/{parts[2]}?ok=reply")
        raise ValueError

    # ---- admin: suporte
    def a_support(self, u, flt="open", ok=""):
        flt = flt if flt in ("open", "closed", "all") else "open"
        cond = {"open": "status='open'", "closed": "status='closed'", "all": "1=1"}[flt]
        ts = rows(f"select t.*, (select body from tmsgs where ticket_id=t.id order by id desc limit 1) last, (select from_admin from tmsgs where ticket_id=t.id order by id desc limit 1) la "
                  f"from tickets t where {cond} order by unread_admin desc, updated desc limit 200")
        chips = "".join(f'<a class="{"on" if k == flt else ""}" href="/admin/support?f={k}">{n}</a>' for k, n in (("open", "Abertas"), ("closed", "Fechadas"), ("all", "Todos")))
        def row(t):
            bd = (' <span class="bd s">Nova</span>' if t["unread_admin"] else "") + (' <span class="bd a">Conta</span>' if t["user_id"] else ' <span class="bd">Visitante</span>') + (' <span class="bd">Fechada</span>' if t["status"] == "closed" else "")
            return (f'<div class="er {"todo" if t["unread_admin"] else ""}"><a class="eh" href="/admin/support/{t["id"]}"><span class="av">{e(ini(t["name"]))}</span><div><b>{e(t["subject"])}</b>{bd}'
                    f'<small>{e(t["name"])} · {e(t["email"])} · {e(t["updated"])}</small><small>{e((t["last"] or "")[:110])}</small></div></a></div>')
        return self.apage(u, "/admin/support", f'<h2 style="margin-top:0">Mensagens de suporte</h2><div class="chips">{chips}</div><div class="list">{"".join(row(t) for t in ts) or "<div class=empty>Sem mensagens.</div>"}</div>', ok)

    def a_ticket(self, u, tid, ok="", err=""):
        t = one("select * from tickets where id=?", (tid,))
        if not t: raise ValueError
        run("update tickets set unread_admin=0 where id=?", (t["id"],))
        ms = rows("select * from tmsgs where ticket_id=? order by id", (t["id"],)); base = f"/admin/support/{t['id']}"
        host = BASE_URL or ("https://" if self.https() else "http://") + str(self.headers.get("Host"))
        bub = "".join(f'<div class="mg{" a" if m["from_admin"] else ""}"><small>{"Suporte" if m["from_admin"] else e(t["name"])} · {e(m["created"])}</small>{e(m["body"])}</div>' for m in ms)
        who = ('<span class="bd a">Conta</span> ' if t["user_id"] else '<span class="bd">Visitante</span> ') + ('<span class="bd">Fechada</span>' if t["status"] == "closed" else "")
        btn = lambda act, label, cls="": f'<form method="post" action="{base}/{act}"><button class="{cls}">{label}</button></form>'
        return self.apage(u, "/admin/support", (
            f'<p><a href="/admin/support" class="m">‹ Todas as mensagens</a></p><div class="card"><b>{e(t["subject"])}</b> {who}<div class="m">{e(t["name"])} · <a href="mailto:{e(t["email"])}">{e(t["email"])}</a> · {e(t["created"])} · {e(i18n.LANGS.get(t["lang"], ""))}</div></div>'
            f'<div class="msgs">{bub}</div><form class="f card" method="post" action="{base}/reply"><label>Resposta</label><textarea name="body" rows="5" maxlength="3000" required></textarea>'
            f'<p class="m">A resposta aparece na página da conversa e é enviada por email para {e(t["email"])} (se o envio de emails estiver ativo).</p><p><button class="p">Enviar resposta</button></p></form>'
            f'<div class="card"><b>Link da conversa (para enviares manualmente, se precisares)</b><input readonly value="{e(host + "/support/t/" + t["token"])}" style="width:100%;margin-top:8px;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></div>'
            f'<div class="row2">{btn("close", "Reabrir conversa" if t["status"] == "closed" else "Fechar conversa")}{btn("delete", "Apagar conversa", "d")}</div>'), ok, err)

    # ---- definições
    # ---- envio de faturas por email
    MAIL_DEF = ("Fatura {n_fatura} – {evento} | {meu_nome}", "Olá {cliente},\n\nObrigado pela confiança e pela excelente colaboração em {evento} ({datas}). Foi um gosto trabalhar convosco!\n\nSegue em anexo a fatura {n_fatura}, no valor de {valor}. Em baixo encontram os meus dados de contacto e de pagamento.\n\nSe precisarem de qualquer esclarecimento, estou sempre disponível.\n\nMais uma vez, muito obrigado e até à próxima!", "Com os melhores cumprimentos,\n{meu_nome}")

    def mcfg(self, uid): return one("select * from mailcfg where user_id=?", (uid,))
    def mready(self, c): return bool(c and c["host"] and c["pw_enc"] and c["from_email"])

    def mvals(self, u, r):
        clean = lambda t: t.replace("\u202f", " ").replace("\xa0", " "); dd = lambda x: f"{x[8:10]}/{x[5:7]}/{x[:4]}" if x else ""
        v, w, tot = tax_of(r)
        return {"cliente": r["cn"] or "", "evento": r["title"], "datas": dd(r["start_date"]) + ("" if r["start_date"] == r["end_date"] else " – " + dd(r["end_date"])), "n_fatura": r["invoice_no"] or "",
                "valor": clean(eur(tot)), "valor_base": clean(eur(r["amount"] or 0)), "data_fatura": dd(r["invoice_date"]), "meu_nome": u["name"] or u["username"]}

    def mail_card(self, u, v):
        ev = v["id"]; fl = one("select name, size from invoice_files where event_id=?", (ev,)); last = one("select to_addr, created from mail_log where event_id=? and user_id=? and status='ok' order by id desc limit 1", (ev, u["id"]))
        inv = (f'<p>📎 <a href="/event/{ev}/invoice">{e(fl["name"])}</a> <span class="m">({fl["size"] // 1024} KB)</span></p>'
               f'<form method="post" action="/event/{ev}/invoice/delete" style="display:inline"><button class="d">Remover fatura</button></form> ' if fl else '<p class="m">Ainda não anexaste a fatura (PDF).</p>')
        up = (f'<p><label class="btn" style="cursor:pointer">{"Substituir fatura (PDF)" if fl else "Anexar fatura (PDF)"}<input type="file" id="invf" accept="application/pdf" hidden></label> <span id="invm" class="m"></span></p>'
              f'<script nonce="__NONCE__">document.getElementById("invf").onchange=function(){{var f=this.files[0];if(!f)return;var m=document.getElementById("invm");if(f.size>5242880){{m.textContent="Max 5 MB";return}}m.textContent="…";'
              f'fetch("/event/{ev}/invoice/upload",{{method:"POST",headers:{{"X-Filename":encodeURIComponent(f.name),"Content-Type":"application/pdf"}},body:f}}).then(function(r){{return r.text().then(function(t){{if(r.ok)location.reload();else m.textContent=t}})}}).catch(function(){{m.textContent="⚠"}})}}</script>')
        lg = f'<p class="m"><span>Último envio:</span> {e(last["to_addr"])} · {e(last["created"][:10])}</p>' if last else ""
        return (f'<div class="card"><b>Enviar fatura ao cliente</b><p class="m" style="margin:4px 0 10px">Anexa a fatura que emitiste e envia-a por email ao cliente.</p>{inv}{up}{lg}'
                f'<p><a class="btn p" href="/event/{ev}/mail">Enviar por email</a></p></div>')

    def invoice_get(self, u, eid):
        r = one("select f.* from invoice_files f join events e on e.id=f.event_id where f.event_id=? and e.user_id=?", (eid, u["id"]))
        if not r: raise ValueError
        self.out(bytes(r["data"]), 200, "application/pdf", (("Content-Disposition", f'attachment; filename="{r["name"]}"'), ("Cache-Control", "no-store")))

    def invoice_upload(self):
        u = self.user()
        if not u: return self.out("Não autorizado", 401, "text/plain")
        eid = int(urlparse(self.path).path.split("/")[2]); n = int(self.headers.get("Content-Length", 0) or 0)
        if not one("select 1 from events where id=? and user_id=?", (eid, u["id"])): return self.out(tx("Evento inválido."), 404, "text/plain")
        if n <= 0 or n > 5 * 1024 * 1024: return self.out(tx("Ficheiro demasiado grande (máximo 5 MB)."), 413, "text/plain")
        data = self.rfile.read(n)
        if not data.startswith(b"%PDF-"): return self.out(tx("Só são aceites ficheiros PDF."), 400, "text/plain")
        nm = re.sub(r"[^\w.\- ]", "_", unquote(self.headers.get("X-Filename", "fatura.pdf")))[:80] or "fatura.pdf"
        nm = nm if nm.lower().endswith(".pdf") else nm + ".pdf"
        run("insert into invoice_files(event_id,name,size,data,created) values(?,?,?,?,?) on conflict(event_id) do update set name=excluded.name,size=excluded.size,data=excluded.data,created=excluded.created", (eid, nm, len(data), data, now_str()))
        self.out("ok", 200, "text/plain")

    def mail_settings(self, u, ok="", err=""):
        c = self.mcfg(u["id"]); g = lambda k, d="": (c[k] if c and c[k] is not None else d)
        msg = {"saved": "Configuração guardada.", "test": "Email de teste enviado para o teu email da conta."}.get(ok)
        flash = (f'<p class="msg ok">{msg}</p>' if msg else "") + (f'<p class="msg err">{e(err)}</p>' if err else "")
        d = self.MAIL_DEF; sub, body, sig = g("subject", tx(d[0])), g("body", tx(d[1])), g("signature", tx(d[2]))
        sec = g("sec", "starttls"); so = lambda v, lab: f'<option value="{v}"{" selected" if sec == v else ""}>{lab}</option>'
        chips = "".join(f'<button type="button" class="chip" data-v="{x}">{{{x}}}</button> ' for x in mailer.VARS)
        return page("Envio de email", f'<p><a class="back" href="/settings">‹ Conta</a></p><h1>Envio de faturas por email</h1>{flash}'
            '<p class="sub">O email sai da tua própria conta, em teu nome. O Claquete guarda a palavra-passe cifrada e só a usa para enviar o que tu confirmares.</p>'
            '<form class="f" method="post" action="/settings/mail" id="mf"><div class="card"><h2>O meu email</h2>'
            '<label>Fornecedor</label><select id="prov"><option value="">Outro</option><option value="gmail">Gmail</option><option value="outlook">Outlook / Hotmail</option><option value="office365">Microsoft 365</option></select>'
            + fld("Servidor SMTP", "host", val=g("host"), extra='id="host" placeholder="smtp.exemplo.com" required maxlength="120"')
            + '<div class="g2"><div>' + fld("Porta", "port", "number", str(g("port", 587)), 'id="port" required') + f'</div><div><label>Segurança</label><select name="sec" id="sec">{so("starttls", "STARTTLS (587)")}{so("ssl", "SSL/TLS (465)")}</select></div></div>'
            + fld("Utilizador (normalmente o teu email)", "username", val=g("username"), extra="required maxlength='160' autocomplete='off'")
            + f'<label>Palavra-passe</label><input name="password" type="password" autocomplete="new-password" placeholder="{"•••••••• (deixa vazio para manter)" if self.mready(c) else ""}"{"" if self.mready(c) else " required"}>'
            '<p class="m"><b>Gmail:</b> ativa a verificação em duas etapas e cria uma «palavra-passe de aplicação» em myaccount.google.com/apppasswords. Usa essa palavra-passe aqui, não a tua normal.</p>'
            + fld("Nome que aparece no email", "from_name", val=g("from_name", u["name"] or ""), extra='maxlength="80"') + fld("Email de envio", "from_email", "email", g("from_email", u["email"]), "required")
            + fld("Responder para (opcional)", "reply_to", "email", g("reply_to")) + '</div>'
            '<div class="card"><h2>Mensagem</h2><p class="m">Estas são as mensagens por omissão. Antes de cada envio podes alterar o texto. Variáveis: ' + chips + '</p>'
            + fld("Assunto", "subject", val=sub, extra='id="subject" maxlength="200"') + f'<label>Texto</label><textarea name="body" id="body" rows="8" maxlength="3000">{e(body)}</textarea>'
            + f'<label>Assinatura</label><textarea name="signature" rows="3" maxlength="500">{e(sig)}</textarea>'
            f'<label class="c" style="margin-top:12px"><input type="checkbox" name="send_pdf"{" checked" if g("send_pdf", 0) else ""}>Anexar também o resumo em PDF do Claquete</label>'
            f'<label class="c"><input type="checkbox" name="footer"{" checked" if g("footer", 1) else ""}>Mostrar o cartão do Claquete e «Enviado com Claquete» no fim do email</label>'
            '<label class="c"><input type="checkbox" name="reset_text">Repor o texto sugerido (assunto, mensagem e assinatura)</label></div>'
            '<p><button class="p">Guardar</button></p></form>'
            + ('<form class="f card" method="post" action="/settings/mail/test"><b>Testar</b><p class="m">Envia um email de teste para o teu email da conta, com a configuração guardada.</p><button>Enviar teste</button></form>' if self.mready(c) else "")
            + '<script nonce="__NONCE__">var P={gmail:["smtp.gmail.com",587,"starttls"],outlook:["smtp-mail.outlook.com",587,"starttls"],office365:["smtp.office365.com",587,"starttls"]};'
              'document.getElementById("prov").onchange=function(){var p=P[this.value];if(!p)return;host.value=p[0];port.value=p[1];sec.value=p[2]};'
              'var last=document.getElementById("body");document.querySelectorAll("#mf .chip").forEach(function(b){b.onclick=function(){var t=document.activeElement;if(!t||(t.id!="body"&&t.id!="subject"&&t.name!="signature"))t=last;'
              'var i=t.selectionStart||t.value.length;t.value=t.value.slice(0,i)+b.dataset.v+t.value.slice(i);t.focus()}});document.querySelectorAll("#mf textarea,#subject").forEach(function(x){x.onfocus=function(){last=x}})</script>', "/settings", u)

    def mail_settings_post(self, u, p, f):
        i = u["id"]; c = self.mcfg(i); sec_ = one("select v from kv where k='secret'")["v"]
        if p == "/settings/mail/test":
            if not self.mready(c): return self.go("/settings/mail")
            try:
                dd = dict(zip(mailer.VARS, ("Cliente Exemplo", "Evento de exemplo", "01/01/2027", "FT 2027/1", "1 230,00 €", "1 000,00 €", "02/01/2027", u["name"] or u["username"])))
                msg = self.mail_build(u, c, [u["email"]], mailer.fill(c["subject"], dd), mailer.fill(c["body"], dd), mailer.fill(c["signature"], dd), [], vals=dd)
                mailer.send(self.mail_conn(c, sec_), msg, [u["email"]]); return self.out(self.mail_settings(u, ok="test"))
            except Exception as ex: print("ERRO teste email:", ex, flush=True); return self.out(self.mail_settings(u, err=tx(mailer.friendly(ex))))
        try:
            host = f.get("host", "").strip().lower()[:120]; port = int(f.get("port") or 587); sec = f.get("sec") if f.get("sec") in ("starttls", "ssl") + (("none",) if mailer.DEV else ()) else "starttls"
            if not mailer.DEV and port not in mailer.PORTS: raise ValueError("Porta não permitida (usa 587 ou 465).")
            if not re.match(r"^[a-z0-9.-]{3,120}$", host): raise ValueError("Servidor SMTP inválido.")
            un = f.get("username", "").strip()[:160]; fe = f.get("from_email", "").strip()
            if not un or not mailer.EMAIL_RE.match(fe): raise ValueError("Preenche o utilizador e um email de envio válido.")
            pw = f.get("password", "")
            if pw: pw_enc = mailer.enc(sec_, pw[:200])
            elif c and c["pw_enc"]: pw_enc = c["pw_enc"]
            else: raise ValueError("Indica a palavra-passe.")
            rt = f.get("reply_to", "").strip(); rt = rt if mailer.EMAIL_RE.match(rt) else ""
            dfl = [tx(x) for x in self.MAIL_DEF]
            v = (host, port, sec, un, pw_enc, f.get("from_name", "").strip()[:80], fe, rt, dfl[0] if f.get("reset_text") else f.get("subject", "").strip()[:200], dfl[1] if f.get("reset_text") else f.get("body", "").strip()[:3000], dfl[2] if f.get("reset_text") else f.get("signature", "").strip()[:500], 1 if f.get("send_pdf") else 0, 1 if f.get("footer") else 0)
        except ValueError as ex: return self.out(self.mail_settings(u, err=tx(str(ex))))
        run("insert into mailcfg(host,port,sec,username,pw_enc,from_name,from_email,reply_to,subject,body,signature,send_pdf,footer,user_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(user_id) do update set "
            "host=excluded.host,port=excluded.port,sec=excluded.sec,username=excluded.username,pw_enc=excluded.pw_enc,from_name=excluded.from_name,from_email=excluded.from_email,reply_to=excluded.reply_to,"
            "subject=excluded.subject,body=excluded.body,signature=excluded.signature,send_pdf=excluded.send_pdf,footer=excluded.footer", v + (i,))
        return self.go("/settings/mail?ok=saved")

    def mail_conn(self, c, sec_):
        return {"from_email": c["from_email"], "host": c["host"], "port": c["port"], "sec": c["sec"], "username": c["username"], "password": mailer.dec(sec_, c["pw_enc"]) or ""}

    def mail_build(self, u, c, to, subject, body, sig, atts, r=None, vals=None, iban_on=True):
        cf = cfg(); v = vals or {}; site_url = BASE_URL or ""; dd = lambda k: v.get(k, "")
        name = u["name"] or u["username"]; reach = c["reply_to"] or c["from_email"]
        card = [(tx("Evento"), dd("evento")), (tx("Datas"), dd("datas")), (tx("Fatura n.º"), dd("n_fatura")), (tx("Data da fatura"), dd("data_fatura"))]
        card = [x for x in card if x[1]]
        contact = [(tx("Email"), reach, "mailto:" + reach)] + ([(tx("Telemóvel"), u["phone"], "tel:" + re.sub(r"[^\d+]", "", u["phone"]))] if u["phone"] else [])
        ib = re.sub(r"\s", "", u["iban"] or ""); ibn = (" ".join(ib[i:i + 4] for i in range(0, len(ib), 4)), name) if ib and iban_on else None
        promo = ({"title": tx("Também és freelancer de audiovisual?"), "text": tx("O Claquete organiza os teus eventos, clientes e o estado das faturas num só sítio: calendário, estatísticas, exportação em PDF e Excel, e uma rede para falares com outros profissionais. Gratuito e feito por um freelancer português."),
                  "button": tx("Conhecer o Claquete"), "url": site_url or "https://claquete.pt"} if c["footer"] else None)
        ctx = {"brand": cf["c_brand"], "site": cf["site_name"], "logo": png_icon(96, tuple(cf[k] for k in COLOR_KEYS)) if promo else None, "header_name": tx("Fatura de") + " " + name,
               "header_sub": (tx("Fatura n.º") + " " + dd("n_fatura")) if dd("n_fatura") else tx("Fatura"), "preheader": tx("Fatura em anexo") + (" · " + dd("evento") if dd("evento") else "") + " · " + name,
               "card": card, "total": (tx("Total a pagar"), dd("valor")) if dd("valor") else None, "contact_title": tx("Contacto"), "contact": contact,
               "pay_title": tx("Dados para pagamento"), "iban": (tx("IBAN"), ibn[0], ibn[1]) if ibn else None, "promo": promo,
               "footer": (tx("Enviado com Claquete") + (" · " + site_url.replace("https://", "").replace("http://", "") if site_url else "")) if c["footer"] else ""}
        return mailer.build({"from_name": c["from_name"], "from_email": c["from_email"], "reply_to": c["reply_to"]}, to, subject, body, sig, atts, ctx)

    def mail_compose(self, u, eid, ok=""):
        r = one(EV + "where e.id=? and e.user_id=?", (eid, u["id"]))
        if not r: raise ValueError
        c = self.mcfg(u["id"]); back = f'<p><a class="back" href="/event/{eid}">‹ {e(r["title"])}</a></p><h1>Enviar fatura por email</h1>'
        cl = one("select * from clients where id=? and user_id=?", (r["client_id"], u["id"])) if r["client_id"] else None; to = mailer.emails_of(cl["email"]) if cl and cl["email"] else []
        if not self.mready(c): return page("Enviar", back + '<p class="msg err">Ainda não ligaste o teu email.</p><p><a class="btn p" href="/settings/mail">Configurar envio de email</a></p>', "/events", u)
        if not to: return page("Enviar", back + '<p class="msg err">Este evento não tem cliente com email guardado.</p>' + (f'<p><a class="btn p" href="/client/{cl["id"]}">Adicionar email ao cliente</a></p>' if cl else f'<p><a class="btn p" href="/event/{eid}">Escolher cliente no evento</a></p>'), "/events", u)
        fl = one("select name from invoice_files where event_id=?", (eid,)); vals = self.mvals(u, r)
        sub = mailer.fill(c["subject"] or tx(self.MAIL_DEF[0]), vals); sub = sub if vals["meu_nome"] in sub else f"{sub} | {vals['meu_nome']}"; body = mailer.fill(c["body"] or tx(self.MAIL_DEF[1]), vals); sig = mailer.fill(c["signature"] or "", vals)
        hist = rows("select to_addr, status, error, created from mail_log where event_id=? and user_id=? order by id desc limit 5", (eid, u["id"]))
        hl = "".join(f'<li>{e(h["created"][:16])} · {e(h["to_addr"])} · {eh("enviado") if h["status"] == "ok" else eh("falhou")}</li>' for h in hist)
        msg = f'<p class="msg ok">{eh("Email enviado.")}</p>' if ok == "sent" else ""
        rc = "".join(f'<label class="c"><input type="checkbox" name="to" value="{e(x)}" checked>{e(x)}</label>' for x in to)
        return page("Enviar", back + msg + '<form class="f card" method="post" action="/event/' + str(eid) + '/mail/send"><label>Para</label>' + rc
            + fld("Assunto", "subject", val=sub, extra='maxlength="200" required') + f'<label>Mensagem</label><textarea name="body" rows="10" maxlength="3000" required>{e(body)}</textarea><p class="m">{eh("A assinatura, os teus contactos e o IBAN são adicionados ao email automaticamente.")}</p>'
            + (f'<label class="c"><input type="checkbox" name="iban_on" checked>{eh("Incluir o meu IBAN no email")}</label>' if u["iban"] else f'<p class="m">{eh("Dica: guarda o teu IBAN em Definições para ele aparecer no email.")} <a href="/settings">{eh("Abrir definições")}</a></p>')
            + '<label>Anexos</label>'
            + (f'<label class="c"><input type="checkbox" name="att_inv" checked>{eh("Fatura")}: {e(fl["name"])}</label>' if fl else f'<p class="m">{eh("Não anexaste a fatura a este evento.")} <a href="/event/{eid}">{eh("Anexar")}</a></p>')
            + f'<label class="c"><input type="checkbox" name="att_pdf"{" checked" if c["send_pdf"] else ""}>{eh("Resumo em PDF do Claquete")}</label>'
            + '<p class="m">Vais enviar este email em teu nome. Confirma o destinatário e os anexos.</p><p><button class="p">Enviar email</button> <a class="btn" href="/event/' + str(eid) + '">Cancelar</a></p></form>'
            + (f'<h2>Envios deste evento</h2><ul class="m">{hl}</ul>' if hl else ""), "/events", u)

    def mail_event_post(self, u, p, f):
        i = u["id"]; eid = int(p.split("/")[2]); r = one(EV + "where e.id=? and e.user_id=?", (eid, i))
        if not r: return self.go("/events")
        if p.endswith("/invoice/delete"): run("delete from invoice_files where event_id=?", (eid,)); return self.go(f"/event/{eid}")
        c = self.mcfg(i); cl = one("select * from clients where id=? and user_id=?", (r["client_id"], i)) if r["client_id"] else None
        allowed = mailer.emails_of(cl["email"]) if cl and cl["email"] else []; to = [x for x in self.fl.get("to", []) if x in allowed]
        def fail(m): return self.out(page("Enviar", f'<p><a class="back" href="/event/{eid}/mail">‹ Voltar</a></p><p class="msg err">{e(tx(m))}</p>', "/events", u))
        if not self.mready(c) or not to: return fail("Escolhe pelo menos um destinatário do cliente.")
        if one("select count(*) from mail_log where user_id=? and status='ok' and created>?", (i, (dt.datetime.now() - dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))[0] >= 30: return fail("Atingiste o limite de envios por hora. Tenta mais tarde.")
        atts = []; fl = one("select name, data from invoice_files where event_id=?", (eid,))
        if f.get("att_inv") and fl: atts.append((fl["name"], bytes(fl["data"])))
        if f.get("att_pdf"):
            try: atts.append((f"claquete-resumo-{eid}.pdf", export.pdf_event(self.export_doc(u, {"scope": "event", "id": eid}))))
            except Exception as ex: print("ERRO PDF resumo:", ex, flush=True)
        if not atts: return fail("Anexa a fatura ao evento ou escolhe o resumo em PDF.")
        sub, body = f.get("subject", "").strip()[:200], f.get("body", "").strip()[:3000]
        if not sub or not body: return fail("Preenche o assunto e a mensagem.")
        try:
            msg = self.mail_build(u, c, to, sub, body, mailer.fill(c["signature"] or "", self.mvals(u, r)), atts, vals=self.mvals(u, r), iban_on=bool(f.get("iban_on"))); mailer.send(self.mail_conn(c, one("select v from kv where k='secret'")["v"]), msg, to)
            st, er = "ok", ""
        except Exception as ex: print("ERRO envio fatura:", ex, flush=True); st, er = "erro", mailer.friendly(ex)
        run("insert into mail_log(user_id,event_id,to_addr,subject,status,error,created) values(?,?,?,?,?,?,?)", (i, eid, ", ".join(to), sub, st, er, dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if st != "ok": return fail(er)
        return self.go(f"/event/{eid}/mail?ok=sent")

    # ---- rede de freelancers AV
    def pro_of(self, uid): return one("select * from pro where user_id=?", (uid,))

    def chips(self, items, cls=""): return '<div class="tgs">' + "".join(f'<span class="{cls}">{e(x)}</span>' for x in items) + '</div>' if items else ""

    def role_names(self, p):
        li = ("pt", "en", "es", "fr", "it").index(i18n.lang()) if i18n.lang() in ("pt", "en", "es", "fr", "it") else 0
        return [people.ROLES[k][1][li] for k in (p["roles"] or "").split(",") if k in people.ROLES]

    def people_get(self, u, p, g):
        me = u["id"]; pro = self.pro_of(me)
        msg = {"saved": "Perfil guardado.", "sent": "Pedido enviado.", "asked": "Pedido de contacto enviado.", "answered": "Resposta guardada.", "limit": "Tentaste muitas vezes. Volta a tentar mais tarde.",
               "pend": "Já enviaste um pedido a esta pessoa.", "none": "Escolhe pelo menos o que queres partilhar (email ou telemóvel).", "gone": "Feito."}.get(g("ok"))
        flash = f'<p class="msg ok">{msg}</p>' if msg else ""
        if p == "/people/me":
            pro = pro or {k: "" for k in ("headline", "city", "roles", "roles_other", "software", "gear", "career", "companies", "projects")} | {"visible": 0, "travel": "no"}
            sel = set((pro["roles"] or "").split(","))
            rg = "".join('<div class="rg"><h3>' + eh(gp[0][0]) + '</h3><div class="ck">' + "".join(
                f'<label class="c"><input type="checkbox" name="role" value="{r[0]}"{" checked" if r[0] in sel else ""}>{eh(r[1])}</label>' for r in gp[1]) + '</div></div>' for gp in people.GROUPS)
            sug = lambda tid, items: '<div class="sg">' + "".join(f'<button type="button" data-t="{tid}" data-v="{e(x)}">{e(x)}</button>' for x in items) + '</div>'
            tv = "".join(f'<option value="{t[0]}"{" selected" if (pro["travel"] or "no") == t[0] else ""}>{eh(t[1])}</option>' for t in people.TRAVEL)
            body = (f'<p><a class="back" href="/people">‹ AV Freelancers</a></p><h1>O meu perfil profissional</h1>{flash}'
                    '<form class="f" method="post" action="/people/me">'
                    f'<div class="card"><label class="c"><input type="checkbox" name="visible"{" checked" if pro["visible"] else ""}><b>Tornar o meu perfil visível a outros freelancers</b></label>'
                    '<p class="m">Se estiver desligado, ninguém te encontra na pesquisa. O teu email e telemóvel nunca aparecem: só os partilhas com quem tu autorizares.</p></div>'
                    '<div class="card"><h2>Quem sou</h2>' + fld("Título (ex.: Técnico de luz e operador de grandMA3)", "headline", val=pro["headline"], extra='maxlength="100"')
                    + fld("Cidade ou zona onde trabalhas", "city", val=pro["city"], extra='maxlength="80"') + f'<label>Disponibilidade para viajar</label><select name="travel">{tv}</select></div>'
                    f'<div class="card"><h2>Funções</h2>{rg}' + fld("Outras funções (separadas por vírgula)", "roles_other", val=pro["roles_other"], extra='maxlength="200"') + '</div>'
                    '<div class="card"><h2>Software e equipamento</h2>' + fld("Software que dominas (separado por vírgula)", "software", val=pro["software"], extra='id="f_software" maxlength="400"') + sug("f_software", people.SOFT)
                    + fld("Equipamento que operas (separado por vírgula)", "gear", val=pro["gear"], extra='id="f_gear" maxlength="400"') + sug("f_gear", people.GEAR) + '</div>'
                    '<div class="card"><h2>Carreira</h2><label>A tua história profissional</label><textarea name="career" rows="6" maxlength="2000">' + e(pro["career"]) + '</textarea>'
                    '<label>Empresas para as quais costumas trabalhar</label><textarea name="companies" rows="3" maxlength="800">' + e(pro["companies"]) + '</textarea>'
                    '<label>Projetos e eventos em que participaste</label><textarea name="projects" rows="4" maxlength="1500">' + e(pro["projects"]) + '</textarea></div>'
                    '<p><button class="p">Guardar perfil</button></p></form>'
                    '<script nonce="__NONCE__">document.querySelectorAll(".sg button").forEach(function(b){b.onclick=function(){var i=document.getElementById(b.dataset.t),v=b.dataset.v,a=i.value.split(",").map(function(x){return x.trim()}).filter(Boolean);if(a.indexOf(v)<0)a.push(v);i.value=a.join(", ")}})</script>')
            return page("O meu perfil profissional", body, "/people", u)
        if p == "/people/requests":
            inc = rows("select c.id cid, c.status, c.s_email, c.s_phone, u.* from contact_req c join users u on u.id=c.a where c.b=? order by c.id desc", (me,))
            out_ = rows("select c.id cid, c.status, u.* from contact_req c join users u on u.id=c.b where c.a=? order by c.id desc", (me,))
            btn = lambda url, cid, label, cls="": f'<form method="post" action="{url}"><input type="hidden" name="id" value="{cid}"><button class="{cls}">{label}</button></form>'
            pend = ""
            for r in inc:
                who = f'<a href="/people/p?id={r["id"]}"><b>{e(uname(r))}</b></a> <span class="m">@{e(r["username"])}</span>'
                if r["status"] == "pending":
                    pend += (f'<form class="f card" method="post" action="/people/answer"><input type="hidden" name="id" value="{r["cid"]}"><p>{who} {eh("quer o teu contacto.")}</p>'
                             '<label class="c"><input type="checkbox" name="s_email" checked>Partilhar o meu email</label>'
                             + ('<label class="c"><input type="checkbox" name="s_phone">Partilhar o meu telemóvel</label>' if u["phone"] else "")
                             + '<p><button class="p" name="act" value="ok">Autorizar</button> <button name="act" value="no">Recusar</button></p></form>')
            ok_ = "".join(f'<div class="card"><p>{"<a href=" + chr(34) + "/people/p?id=" + str(r["id"]) + chr(34) + "><b>" + e(uname(r)) + "</b></a>"} · {eh("partilhas")}: {eh("email") if r["s_email"] else ""} {eh("telemóvel") if r["s_phone"] else ""}</p>'
                          + btn("/people/revoke", r["cid"], "Retirar autorização") + '</div>' for r in inc if r["status"] == "ok")
            mine = "".join(f'<div class="card"><p><a href="/people/p?id={r["id"]}"><b>{e(uname(r))}</b></a> · {eh({"pending": "à espera de resposta", "ok": "autorizado", "no": "recusado"}[r["status"]])}</p>'
                           + (btn("/people/revoke", r["cid"], "Cancelar pedido") if r["status"] == "pending" else "") + '</div>' for r in out_)
            body = (f'<p><a class="back" href="/people">‹ AV Freelancers</a></p><h1>Pedidos de contacto</h1>{flash}<p class="sub">Só partilhas o teu email ou telemóvel com quem tu autorizares.</p>'
                    + (pend or '<p class="m">Não tens pedidos pendentes.</p>') + ('<h2>Autorizados por ti</h2>' + ok_ if ok_ else "") + ('<h2>Pedidos que fizeste</h2>' + mine if mine else ""))
            return page("Pedidos de contacto", body, "/people", u)
        if p == "/people/p":
            t = one("select * from users where id=? and disabled=0", (g("id") or 0,)); pr = self.pro_of(t["id"]) if t else None
            if not t or not pr or (not pr["visible"] and t["id"] != me): return page("AV Freelancers", '<p class="m">Este perfil não está disponível.</p><p><a class="btn" href="/people">‹ AV Freelancers</a></p>', "/people", u)
            roles = self.role_names(pr) + people.csv(pr["roles_other"], 10)
            sec = lambda title, txt: f'<div class="card"><h2>{title}</h2><p class="pv">{e(txt)}</p></div>' if (txt or "").strip() else ""
            tvl = eh(people.TRAVEL_D.get(pr["travel"] or "no", "Só na minha zona"))
            top = (f'<p><a class="back" href="/people">‹ AV Freelancers</a></p><div class="pp">{uav(t)}<div><h1>{e(uname(t))}</h1><div class="m">{e(pr["headline"] or "")}</div>'
                   f'<div class="m">{"📍 " + e(pr["city"]) + " · " if pr["city"] else ""}✈ {tvl}</div></div></div>')
            act = ""
            if t["id"] == me:
                act = '<p><a class="btn p" href="/people/me">Editar o meu perfil</a>' + ("" if pr["visible"] else ' <span class="m">· Não estás visível na pesquisa.</span>') + '</p>'
            else:
                fr = one("select * from friends where (a=? and b=?) or (a=? and b=?)", (me, t["id"], t["id"], me))
                if fr and fr["status"] == "ok": act = f'<form method="post" action="/people/msg"><input type="hidden" name="id" value="{t["id"]}"><button class="p">Abrir conversa</button></form>'
                elif fr and fr["a"] == me: act = '<p class="m">Mensagem enviada. Aguarda que a pessoa aceite.</p>'
                else: act = (f'<form class="f" method="post" action="/people/msg"><input type="hidden" name="id" value="{t["id"]}"><label>Primeira mensagem (apresenta-te)</label>'
                             '<textarea name="text" rows="3" maxlength="300" required></textarea><p><button class="p">Enviar mensagem</button></p></form>')
                cr = one("select * from contact_req where a=? and b=?", (me, t["id"]))
                if cr and cr["status"] == "ok":
                    ct = ([f'{eh("Email")}: <b>{e(t["email"])}</b>'] if cr["s_email"] else []) + ([f'{eh("Telemóvel")}: <b>{e(t["phone"])}</b>'] if cr["s_phone"] and t["phone"] else [])
                    act += '<div class="card"><h2>Contacto autorizado</h2><p>' + "<br>".join(ct) + '</p></div>'
                elif cr and cr["status"] == "pending": act += '<p class="m">Pedido de contacto enviado. Aguarda a autorização.</p>'
                elif cr: act += '<p class="m">A pessoa preferiu não partilhar o contacto.</p>'
                else: act += f'<form method="post" action="/people/ask"><input type="hidden" name="id" value="{t["id"]}"><button>Pedir email / telemóvel</button><p class="m">A pessoa escolhe se autoriza e o que partilha.</p></form>'
            body = (top + flash + act + '<div class="card"><h2>Funções</h2>' + (self.chips(roles) or '<span class="m">—</span>') + '</div>'
                    + ('<div class="card"><h2>Software</h2>' + self.chips(people.csv(pr["software"]), "n") + '</div>' if (pr["software"] or "").strip() else "")
                    + ('<div class="card"><h2>Equipamento</h2>' + self.chips(people.csv(pr["gear"]), "n") + '</div>' if (pr["gear"] or "").strip() else "")
                    + sec("Carreira", pr["career"]) + sec("Empresas para as quais trabalha", pr["companies"]) + sec("Projetos e eventos", pr["projects"]))
            return page(uname(t), body, "/people", u)
        # diretório
        q, role, city, trav = g("q").strip()[:80], g("role"), g("city").strip()[:60], g("trav")
        rs = rows("select u.id, u.name, u.username, u.av_v, u.last_seen, pr.* from pro pr join users u on u.id=pr.user_id where pr.visible=1 and u.disabled=0 and u.id!=?", (me,))
        out = []
        for r in rs:
            if role in people.ROLES and role not in (r["roles"] or "").split(","): continue
            if city and people.norm(city) not in people.norm(r["city"]): continue
            if trav and (r["travel"] or "no") == "no": continue
            if q and not people.match(r, q): continue
            out.append(r)
        out.sort(key=lambda r: (not is_online(r["id"]), uname(r).lower())); total = len(out); out = out[:60]
        cards = ""
        for r in out:
            rn = self.role_names(r) + people.csv(r["roles_other"], 3); more = len(rn) - 3
            tg = "".join(f"<i>{e(x)}</i>" for x in rn[:3]) + (f"<i>+{more}</i>" if more > 0 else "")
            cards += (f'<a class="pc" href="/people/p?id={r["id"]}"><span class="avw">{uav(r)}<i class="dot" data-pres="{r["id"]}"{"" if is_online(r["id"]) else " hidden"}></i></span><span><b>{e(uname(r))}</b>'
                      f'<small>{e(r["headline"] or "")}</small><small>{"📍 " + e(r["city"]) if r["city"] else ""}{" · ✈" if (r["travel"] or "no") != "no" else ""}</small><div class="tg2">{tg}</div></span></a>')
        ropt = '<option value="">Todas as funções</option>' + "".join('<optgroup label="' + e(tx(gp[0][0])) + '">' + "".join(f'<option value="{r_[0]}"{" selected" if role == r_[0] else ""}>{e(r_[1])}</option>' for r_ in gp[1]) + '</optgroup>' for gp in people.GROUPS)
        pq = one("select count(*) from contact_req where b=? and status='pending'", (me,))[0]
        top = ('<div class="bar-h"><div><h1>AV Freelancers</h1><p class="sub" style="margin:0">Encontra colegas do audiovisual, partilha conhecimento, contactos e trabalhos.</p></div>'
               '<a class="btn p" href="/people/me">O meu perfil</a></div>' + flash
               + (f'<p class="msg ok"><a href="/people/requests">{pq} {eh("pedido(s) de contacto à espera de resposta")} ›</a></p>' if pq else "")
               + ('' if pro and pro["visible"] else '<p class="msg err">O teu perfil ainda não está visível para outros. <a href="/people/me">Preencher e ativar</a></p>'))
        flt = ('<form class="f fl" method="get" action="/people"><div><label>Pesquisar (ex.: grandMA3, Resolume, Sony FX6)</label><input name="q" value="' + e(q) + '" maxlength="80"></div>'
               f'<div><label>Função</label><select name="role">{ropt}</select></div><div><label>Cidade</label><input name="city" value="{e(city)}" maxlength="60"></div>'
               f'<div><label class="c"><input type="checkbox" name="trav" value="1"{" checked" if trav else ""}>Disponível a viajar</label></div><div><button class="p">Procurar</button></div></form>')
        res = (f'<p class="m">{total} {eh("resultado(s)")}</p><div class="pf">{cards}</div>' if out else '<p class="m">Ainda não há perfis com estes filtros.</p>')
        return page("AV Freelancers", top + flt + res + '<p class="m"><a href="/people/requests">Pedidos de contacto</a></p>', "/people", u)

    def people_post(self, u, p, f):
        me = u["id"]; go = lambda k, to="/people": self.go(to + ("&" if "?" in to else "?") + "ok=" + k)
        if p == "/people/me":
            roles = ",".join(k for k in self.fl.get("role", []) if k in people.ROLES)
            tv = f.get("travel") if f.get("travel") in people.TRAVEL_D else "no"; cl = lambda k, n: f.get(k, "").strip()[:n]
            v = (1 if f.get("visible") else 0, cl("headline", 100), cl("city", 80), tv, roles, cl("roles_other", 200), cl("software", 400), cl("gear", 400), cl("career", 2000), cl("companies", 800), cl("projects", 1500), now_str())
            run("insert into pro(visible,headline,city,travel,roles,roles_other,software,gear,career,companies,projects,updated,user_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "on conflict(user_id) do update set visible=excluded.visible,headline=excluded.headline,city=excluded.city,travel=excluded.travel,roles=excluded.roles,roles_other=excluded.roles_other,"
                "software=excluded.software,gear=excluded.gear,career=excluded.career,companies=excluded.companies,projects=excluded.projects,updated=excluded.updated", v + (me,))
            return go("saved", "/people/me")
        if p in ("/people/msg", "/people/ask"):
            tid = int(f.get("id") or 0); t = one("select * from users where id=? and disabled=0", (tid,)); pr = self.pro_of(tid) if t else None
            if not t or tid == me or not pr or not pr["visible"]: return self.go("/people")
            back = f"/people/p?id={tid}"
            ip = "pm" + str(me); n, t0 = self.fails.get(ip, (0, 0))
            if n >= 20 and time.time() - t0 < 3600: return go("limit", back)
            self.fails[ip] = (n + 1 if time.time() - t0 < 3600 else 1, time.time())
            if p == "/people/ask":
                run("insert or ignore into contact_req(a,b,status,created) values(?,?,'pending',?)", (me, tid, now_str())); push_sync(tid); return go("asked", back)
            ex = one("select * from friends where (a=? and b=?) or (a=? and b=?)", (me, tid, tid, me))
            if ex and ex["status"] == "ok": return self.go(f"/chat/{dm_chat(me, tid)}")
            if ex and ex["a"] == me: return go("pend", back)
            intro = f.get("text", "").strip()[:300]
            if ex: accept_friend(ex); return self.go(f"/chat/{dm_chat(me, tid)}")
            run("insert into friends(a,b,status,created,intro) values(?,?,'pending',?,?)", (me, tid, now_str(), intro)); push_sync(tid); return go("sent", back)
        if p in ("/people/answer", "/people/revoke"):
            r = one("select * from contact_req where id=? and (a=? or b=?)", (f.get("id") or 0, me, me))
            if not r: return self.go("/people/requests")
            if p == "/people/revoke":
                if r["a"] == me: run("delete from contact_req where id=?", (r["id"],))
                else: run("update contact_req set status='no', s_email=0, s_phone=0 where id=?", (r["id"],))
                push_sync(r["a"], r["b"]); return go("gone", "/people/requests")
            if r["b"] != me: return self.go("/people/requests")
            if f.get("act") == "ok":
                se, sp = (1 if f.get("s_email") else 0), (1 if f.get("s_phone") and u["phone"] else 0)
                if not (se or sp): return go("none", "/people/requests")
                run("update contact_req set status='ok', s_email=?, s_phone=? where id=?", (se, sp, r["id"]))
            else: run("update contact_req set status='no' where id=?", (r["id"],))
            push_sync(r["a"], me); return go("answered", "/people/requests")
        return self.go("/people")

    # ---- exportação (PDF / Excel)
    XL = {"page": "Página", "generated": "Gerado em", "inv_date": "Data fatura", "event": "Evento", "client": "Cliente", "inv_no": "N.º fatura", "base": "Base (sem IVA)", "vat": "IVA", "wh": "Retenção",
          "total": "Total a receber", "status": "Estado", "totals": "Totais", "start": "Início", "end": "Fim", "none": "Sem eventos neste filtro.", "s_base": "Valor sem IVA", "s_vat": "IVA", "s_wh": "Retenção IRS",
          "s_total": "Total a receber", "s_paid": "Já recebido", "s_due": "Por receber", "st_todo": "Por faturar", "st_plan": "Por realizar", "st_inv": "Faturada", "st_paid": "Paga", "name": "Nome", "nif": "NIF", "contact": "Contacto",
          "invoice": "Fatura", "desc": "Descrição", "amount": "Valor", "notes": "Notas", "dates": "Datas", "sheet": "Eventos", "sheet_event": "Evento"}

    def export_doc(self, u, f):
        c = cfg(); T = {k: tx(v) for k, v in self.XL.items()}; lang = i18n.lang(); i = u["id"]
        clean = lambda s: s.replace("\u202f", " ").replace("\xa0", " ")
        eurx = lambda v: clean(eur(v)); dd = lambda s: f"{s[8:10]}/{s[5:7]}/{s[:4]}" if s else ""
        cols = tuple(c[k] for k in COLOR_KEYS)
        issuer_kv = [(tx("Emitido por"), u["name"] or u["username"]), (tx("Utilizador"), u["username"]), (tx("Email"), u["email"])] + ([(tx("Telemóvel"), u["phone"])] if u["phone"] else []) + ([(tx("IBAN"), u["iban"])] if u["iban"] else [])
        issuer = [u["name"] or u["username"], f'@{u["username"]}  |  {u["email"]}'] + ([u["phone"]] if u["phone"] else [])
        doc = {"T": T, "eur": eurx, "d": dd, "cols": cols, "site": c["site_name"], "issuer": issuer, "issuer_kv": issuer_kv, "generated": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
               "disclaimer": tx("Documento informativo gerado pelo Claquete. Não é uma fatura nem um documento fiscal."), "png": png_icon(96, cols)}
        def mk(r):
            v, w, t_ = tax_of(r); return {"id": r["id"], "title": r["title"], "start": r["start_date"], "end": r["end_date"], "client": r["cn"] or "", "invoice_date": r["invoice_date"] or "", "invoice_no": r["invoice_no"] or "",
                                          "base": r["amount"] or 0, "vat": v, "wh": w, "total": t_, "state": state(r), "notes": r["notes"] or "", "paid_date": r["paid_date"] or ""}
        if f.get("scope") == "event":
            r = one(EV + "where e.id=? and e.user_id=?", (f.get("id") or 0, i))
            if not r: raise ValueError
            x = mk(r); cl = one("select * from clients where id=?", (r["client_id"],)) if r["client_id"] else None
            doc["kind"] = "event"; doc["title"] = tx("Resumo do evento"); doc["rows"] = [x]
            doc["client"] = [(T["name"], cl["name"])] + ([(T["nif"], cl["nif"])] if cl["nif"] else []) + ([(T["contact"], cl["contact"])] if cl["contact"] else []) if cl else None
            doc["invoice"] = [(T["inv_no"], x["invoice_no"] or "—"), (T["inv_date"], dd(x["invoice_date"]) or "—"), (T["status"], T["st_" + x["state"]])] + ([(tx("Pago em"), dd(x["paid_date"]))] if x["paid_date"] else [])
            doc["lines"] = [(l["label"], l["amount"]) for l in rows("select * from items where event_id=? order by id", (r["id"],))] or [(r["title"], x["base"])]
            doc["vat_text"] = f'{tx("IVA")} {pct(r["vat_rate"])}%' if r["vat_mode"] == "rate" else (tx("IVA liquidado pelo cliente (autoliquidação)") if r["vat_mode"] == "rc" else "")
            doc["wh_text"] = f'{tx("Retenção")} {pct(r["wh_rate"])}%' if r["wh_rate"] else ""
            doc["vat_rate"] = r["vat_rate"] if r["vat_mode"] == "rate" else 0; doc["wh_rate"] = r["wh_rate"] or 0
            doc["dates"] = dd(x["start"]) + ("" if x["start"] == x["end"] else " – " + dd(x["end"]))
            doc["totals"] = {"base": x["base"], "vat": x["vat"], "wh": x["wh"], "total": x["total"]}; doc["name"] = "evento-" + re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:30]
            return doc
        where, args = ["e.user_id=?"], [i]; by = "e.invoice_date" if f.get("by", "invoice") == "invoice" else "e.start_date"; a = b = ""
        mo = f.get("month", "")
        if re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mo): y_, m_ = int(mo[:4]), int(mo[5:]); a = f"{mo}-01"; b = f"{mo}-{calendar.monthrange(y_, m_)[1]:02d}"
        else: a, b = okdate(f.get("from", "")) or "", okdate(f.get("to", "")) or ""
        if a: where.append(f"{by}>=?"); args.append(a)
        if b: where.append(f"{by}<=?"); args.append(b)
        cl = None
        if f.get("client") and f["client"].isdigit():
            cl = one("select * from clients where id=? and user_id=?", (f["client"], i))
            if cl: where.append("e.client_id=?"); args.append(cl["id"])
        stt = f.get("status", "all"); tds = today().isoformat(); where.append({"todo": f"e.invoice_date is null and e.end_date<='{tds}'", "plan": f"e.invoice_date is null and e.end_date>'{tds}'", "inv": "e.invoice_date is not null and e.paid=0", "paid": "e.paid=1"}.get(stt, "1=1"))
        rs = [mk(r) for r in rows(EV + "where " + " and ".join(where) + " order by coalesce(e.invoice_date, e.start_date), e.start_date", args)]
        tot = {k: sum(x[k] for x in rs) for k in ("base", "vat", "wh", "total")}; tot["paid"] = sum(x["total"] for x in rs if x["state"] == "paid"); tot["due"] = sum(x["total"] for x in rs if x["state"] == "inv")
        per = f"{dd(a)} – {dd(b)}" if a and b else (f"{tx('desde')} {dd(a)}" if a else (f"{tx('até')} {dd(b)}" if b else tx("Todo o período")))
        doc["kind"] = "list"; doc["title"] = tx("Relatório de eventos"); doc["rows"] = rs; doc["totals"] = tot
        doc["filters"] = [(tx("Período"), per), (tx("Contar por"), tx("Data da fatura") if f.get("by", "invoice") == "invoice" else tx("Data do evento")), (T["status"], {"todo": T["st_todo"], "plan": T["st_plan"], "inv": T["st_inv"], "paid": T["st_paid"]}.get(stt, tx("Todos")))]
        doc["client"] = [(T["name"], cl["name"])] + [(k, cl[x]) for k, x in ((T["nif"], "nif"), (T["contact"], "contact"), (tx("Tarifa"), "rate"), (tx("Condições"), "terms")) if cl[x]] if cl else None
        if cl and doc["client"]: doc["filters"] = [(T["client"], cl["name"])] + doc["filters"]
        doc["name"] = "relatorio" + (f"-{mo}" if mo and a else (f"-{a}-{b}" if a and b else "")) + ("-" + re.sub(r"[^a-z0-9]+", "-", cl["name"].lower()).strip("-")[:20] if cl else "")
        return doc

    def export_run(self, u, g):
        f = {k: g(k) for k in ("scope", "id", "client", "month", "from", "to", "by", "status")}; fmt = g("fmt", "pdf")
        doc = self.export_doc(u, f); ev = doc["kind"] == "event"
        if fmt == "xlsx": body = export.xlsx_event(doc) if ev else export.xlsx_list(doc); ct, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        else: body = export.pdf_event(doc) if ev else export.pdf_list(doc); ct, ext = "application/pdf", "pdf"
        self.out(body, 200, ct, (("Content-Disposition", f'attachment; filename="claquete-{doc["name"]}.{ext}"'), ("Cache-Control", "no-store")))

    def export_page(self, u, g):
        cl = "".join(f'<option value="{c["id"]}"{" selected" if g("client") == str(c["id"]) else ""}>{e(c["name"])}</option>' for c in rows("select * from clients where user_id=? order by name", (u["id"],)))
        return page("Exportar", '<h1>Exportar</h1><p class="sub">Descarrega um relatório em PDF ou Excel dos teus eventos e faturas.</p>'
            '<form class="f card" method="get" action="/export/run"><label>Cliente</label><select name="client"><option value="">Todos os clientes</option>' + cl + '</select>'
            '<div class="g2"><div><label>Mês</label><input type="month" name="month"></div><div></div></div><p class="m" style="margin:6px 0 0">Escolhe um mês ou um intervalo de datas. Se deixares vazio, exporta tudo.</p>'
            '<div class="g2"><div><label>De</label><input type="date" name="from"></div><div><label>Até</label><input type="date" name="to"></div></div>'
            '<div class="g2"><div><label>Contar por</label><select name="by"><option value="invoice">Data da fatura</option><option value="event">Data do evento</option></select></div>'
            '<div><label>Estado</label><select name="status"><option value="all">Todos</option><option value="plan">Por realizar</option><option value="todo">Por faturar</option><option value="inv">Faturadas (por receber)</option><option value="paid">Pagas</option></select></div></div>'
            '<p style="margin-top:18px"><button class="p" name="fmt" value="pdf">Descarregar PDF</button> <button name="fmt" value="xlsx">Descarregar Excel</button></p>'
            '<p class="m">Isto não é uma fatura: é um resumo informativo para teu controlo.</p></form>', "/stats", u)

    def theme_card(self, u):
        cur = u["theme"] or "auto"
        b = lambda v, ico, lab: f'<form method="post" action="/settings/theme"><input type="hidden" name="t" value="{v}"><button class="chip{" on p2" if cur == v else ""}">{ico} {lab}</button></form>'
        return ('<div class="card"><h2>Aspeto</h2><p class="m">Escolhe o tema do site: claro (dia), escuro (noite) ou automático, que segue o teu telemóvel.</p><div class="tg" style="flex-wrap:wrap">'
                + b("auto", "🌓", "Automático") + b("light", "☀️", "Claro (dia)") + b("dark", "🌙", "Escuro (noite)") + '</div></div>')

    def tax_card(self, u):
        co = "".join(f'<option value="{k}"{" selected" if k == (u["vat_country"] or "PT") else ""}>{v[0]}</option>' for k, v in COUNTRIES.items())
        rt = json.dumps({k: [f"{x:g}" for x in v[1]] for k, v in COUNTRIES.items()})
        lab = json.dumps({"none": tx("Sem IVA (isento)"), "rc": tx("IVA liquidado pelo cliente (autoliquidação)"), "custom": tx("Outra taxa..."), "iva": tx("IVA")})
        return ('<form class="f card" method="post" action="/settings/tax"><h2>Faturação e impostos</h2><p class="m">Valores predefinidos: aparecem logo em cada novo evento e podes mudá-los em cada fatura.</p>'
                f'<label>País / regime de IVA</label><select name="country" id="tc">{co}</select>'
                f'<label>IVA predefinido</label><div id="tv" data-r="{e(rt)}" data-l="{e(lab)}">{vat_select(u["vat_country"] or "PT", u["vat_def"] or "none", "vat", "vatc")}</div>'
                f'<label>Retenção na fonte predefinida (IRS)</label><div>{wh_select(u["wh_def"] or 0)}</div>'
                f'<label class="c" style="margin-top:16px"><input type="checkbox" name="ss_on" {"checked" if u["ss_on"] else ""}>Calcular a Segurança Social (estimativa trimestral)</label>'
                f'<div class="g2"><div><label>Taxa contributiva (%)</label><input name="ss_rate" inputmode="decimal" value="{pct(u["ss_rate"] if u["ss_rate"] is not None else 21.4)}"></div>'
                f'<div><label>% do rendimento considerada</label><input name="ss_coef" inputmode="decimal" value="{pct(u["ss_coef"] if u["ss_coef"] is not None else 70)}"></div></div>'
                '<p class="m">Valores indicativos para Portugal: IVA 23% (continente), retenção na fonte de IRS 23%, 16,5% ou 11,5% conforme a atividade, e Segurança Social de 21,4% sobre 70% do rendimento dos serviços. Confirma com o teu contabilista.</p>'
                '<p><button class="p">Guardar</button></p></form>' + CUJS +
                '<script nonce="__NONCE__">(function(){var c=document.getElementById("tc"),b=document.getElementById("tv"),R=JSON.parse(b.dataset.r),L=JSON.parse(b.dataset.l);c.onchange=function(){var s=b.querySelector("select"),k=s.value,o=[["none",L.none]];(R[c.value]||[]).forEach(function(x){o.push([x,L.iva+" "+x.replace(".","' + dsep() + '")+"%"])});o.push(["rc",L.rc],["custom",L.custom]);'
                's.innerHTML="";o.forEach(function(x){var e=document.createElement("option");e.value=x[0];e.textContent=x[1];if(x[0]==k)e.selected=true;s.appendChild(e)})}})();</script>')

    def settings(self, u, ok="", err=""):
        proto = "https" if self.https() else "http"; url = f'{BASE_URL or proto + "://" + str(self.headers.get("Host"))}/calendar.ics?k={u["ics"]}'
        msg = {"profile": "Dados guardados.", "password": "Palavra-passe alterada.", "ics": "Link novo gerado. O antigo deixou de funcionar.", "avatar": "Foto guardada.", "avatar_rm": "Foto removida.", "tax": "Preferências de faturação guardadas.", "theme": "Tema guardado."}.get(ok); m = f'<p class="msg ok">{msg}</p>' if msg else (f'<p class="msg err">{err}</p>' if err else "")
        return page("Conta", f'<h1>Conta</h1><p class="sub">Os teus dados e a tua segurança.</p>{m}<form class="f card" method="post" action="/settings/profile"><h2>Dados pessoais</h2>'
            + fld("Nome", "name", val=u["name"], extra="required") + fld("Email", "email", "email", u["email"], "required") + fld("Telemóvel", "phone", "tel", u["phone"] or "")
            + fld("IBAN (opcional, aparece nos emails de fatura)", "iban", val=" ".join((u["iban"] or "")[i:i + 4] for i in range(0, len(u["iban"] or ""), 4)), extra='maxlength="42" autocomplete="off" placeholder="PT50 0000 0000 0000 0000 0000 0"')
            + f'<p class="m">Utilizador: <b>{e(u["username"])}</b></p><p><button class="p">Guardar dados</button></p></form>'
            + '<div class="card"><h2>Perfil profissional</h2><p class="m">Aparece na rede AV Freelancers para outros colegas te encontrarem. Só fica visível se tu quiseres.</p><p><a class="btn" href="/people/me">Editar perfil profissional</a></p></div>'
            + '<div class="card"><h2>Envio de faturas por email</h2><p class="m">Liga o teu email e envia a fatura ao cliente diretamente a partir do evento, com uma mensagem tua.</p><p><a class="btn" href="/settings/mail">Configurar envio de email</a></p></div>'
            + self.theme_card(u) + self.tax_card(u) +
            '<div class="card" id="pwa"><h2>Instalar como aplicação</h2><p class="m">Usa o site como uma app no telemóvel: ícone no ecrã principal, ecrã inteiro e avisos.</p>'
            '<p><button type="button" class="p" id="pwab" hidden>Instalar app</button></p>'
            '<p class="m"><b>Android (Chrome):</b> menu ⋮ → «Instalar app» ou «Adicionar ao ecrã principal».<br><b>iPhone/iPad (Safari):</b> botão Partilhar → «Adicionar ao ecrã principal».</p></div>'
            f'<div class="card"><h2>Foto de perfil</h2><div class="avset">{uav(u)}<div><form id="avf" method="post" action="/settings/avatar"><input type="file" id="avfile" accept="image/*"><input type="hidden" name="img" id="avdata">'
            '<p style="margin:10px 0 0"><img id="avpv" class="av u" alt="" hidden> <button class="p" id="avsave" hidden>Guardar</button></p></form>'
            + (f'<form method="post" action="/settings/avatar/remove" style="margin-top:8px"><button>Remover foto</button></form>' if u["av_v"] else "") + '</div></div>'
            '<p class="m" style="margin-bottom:0">A imagem é reduzida e guardada na base de dados.</p></div>'
            '<form class="f card" method="post" action="/settings/password"><h2>Alterar palavra-passe</h2>' + fld("Palavra-passe atual", "old", "password", extra='autocomplete="current-password" required')
            + fld("Nova palavra-passe (mínimo 8)", "p", "password", extra='autocomplete="new-password" minlength="8" required') + fld("Repetir nova palavra-passe", "p2", "password", extra='autocomplete="new-password" minlength="8" required') + '<p><button class="p">Alterar palavra-passe</button></p></form>'
            f'<div class="card"><h2>Google Calendar</h2><p class="m">Em Google Calendar → Outras agendas → A partir do URL, cola este link (só leitura). O Google precisa de conseguir aceder ao endereço, por isso só funciona se o site estiver acessível pela internet em HTTPS. Não partilhes este link.</p><input readonly value="{e(url)}" style="width:100%;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)" id="icsurl"><form method="post" action="/settings/ics" style="margin-top:12px"><button>Gerar novo link</button> <span class="m">O link antigo deixa de funcionar.</span></form></div>'
            f'<div class="card"><h2>Idioma</h2><p class="m">Escolhe o idioma do site.</p>{langbar(True)}</div>'
            '<form method="post" action="/logout"><button>Terminar sessão</button></form><script nonce="__NONCE__">document.getElementById("icsurl").onclick=function(){this.select()}</script>', "/settings", u)

    def save_profile(self, u, f):
        name, em, ph = f.get("name", "").strip()[:60], f.get("email", "").strip(), f.get("phone", "").strip()[:30]
        if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", em): return self.out(self.settings(u, err="Nome e email válidos são obrigatórios."), 400)
        ib = re.sub(r"\s", "", f.get("iban", "")).upper()
        if ib and not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$", ib): return self.out(self.settings(u, err="O IBAN não parece válido."), 400)
        try: run("update users set name=?, email=?, phone=?, iban=? where id=?", (name, em, ph, ib, u["id"]))
        except sqlite3.IntegrityError: return self.out(self.settings(u, err="Esse email já está a ser usado por outra conta."), 400)
        self.go("/settings?ok=profile")

    def save_password(self, u, f):
        if not check_pw(f.get("old", ""), u["pw"]): return self.out(self.settings(u, err="A palavra-passe atual está incorreta."), 400)
        if len(f.get("p", "")) < 8 or f.get("p") != f.get("p2"): return self.out(self.settings(u, err="A nova palavra-passe tem de ter 8+ caracteres e coincidir nos dois campos."), 400)
        run("update users set pw=? where id=?", (hash_pw(f["p"]), u["id"])); nu = one("select * from users where id=?", (u["id"],))
        self.go("/settings?ok=password", [session_cookie(nu, self.https())])

if __name__ == "__main__":
    init(); threading.Thread(target=backup_loop, daemon=True).start(); threading.Thread(target=img_loop, daemon=True).start(); print("Claquete a escutar na porta 8000 | email:", "ativo" if smtp_ready() else "desligado", "| BASE_URL:", BASE_URL or "(vazio)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
