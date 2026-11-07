"""Envio de faturas por email com o SMTP de cada utilizador (só biblioteca padrão)."""
import base64, hashlib, hmac, html, ipaddress, os, re, secrets, smtplib, socket, ssl
from email.message import EmailMessage
from email.utils import formataddr

DEV = bool(os.environ.get("CLAQUETE_DEV_SMTP"))  # só para testes locais
PORTS = (465, 587, 2525)
PRESETS = {"gmail": ("smtp.gmail.com", 587, "starttls"), "outlook": ("smtp-mail.outlook.com", 587, "starttls"), "office365": ("smtp.office365.com", 587, "starttls")}
VARS = ("cliente", "evento", "datas", "n_fatura", "valor", "valor_base", "data_fatura", "meu_nome")
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

# ---- cifra da palavra-passe (HMAC-SHA256 em modo contador + etiqueta; encrypt-then-MAC)
def _keys(secret):
    k = hashlib.sha256(("claquete-mail|" + secret).encode()).digest()
    return hmac.new(k, b"enc", hashlib.sha256).digest(), hmac.new(k, b"mac", hashlib.sha256).digest()

def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest(); i += 1
    return out[:n]

def enc(secret, text):
    ke, km = _keys(secret); nonce = secrets.token_bytes(16); b = text.encode()
    ct = bytes(x ^ y for x, y in zip(b, _stream(ke, nonce, len(b))))
    return base64.urlsafe_b64encode(nonce + ct + hmac.new(km, nonce + ct, hashlib.sha256).digest()).decode()

def dec(secret, token):
    try:
        raw = base64.urlsafe_b64decode(token.encode()); nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
        ke, km = _keys(secret)
        if not hmac.compare_digest(tag, hmac.new(km, nonce + ct, hashlib.sha256).digest()): return None
        return bytes(x ^ y for x, y in zip(ct, _stream(ke, nonce, len(ct)))).decode()
    except Exception: return None

# ---- validações
def emails_of(s):
    return [x.strip() for x in re.split(r"[,;\s]+", s or "") if EMAIL_RE.match(x.strip())]

def safe_host(host, port):
    """Evita que o servidor seja usado para tentar ligações à rede interna."""
    if not host or not re.match(r"^[A-Za-z0-9.-]{1,253}$", host): raise ValueError("Servidor SMTP inválido.")
    if not DEV and int(port) not in PORTS: raise ValueError("Porta não permitida (usa 587 ou 465).")
    infos = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
    for fam, _, _, _, addr in infos:
        ip = ipaddress.ip_address(addr[0])
        if not DEV and not ip.is_global: raise ValueError("Este servidor SMTP não é público.")
    return infos[0][4][0]

def fill(tpl, vals):
    return re.sub(r"\{(" + "|".join(VARS) + r")\}", lambda m: str(vals.get(m.group(1), "")), tpl or "")

# ---- construção e envio
def _mix(h, k):
    """mistura a cor h com branco (k=0..1 de cor) ou preto (k<0)"""
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    t = 255 if k >= 0 else 0; k = abs(k)
    return "#" + "".join(f"{round(x * k + t * (1 - k)):02x}" for x in c)

def _esc(x): return html.escape(x or "")

def _para(text):
    out = ""
    for p in re.split(r"\n\s*\n", (text or "").strip()):
        if p.strip(): out += f'<p style="margin:0 0 16px;font-size:16px;line-height:1.65;color:#1f2433">{_esc(p.strip()).replace(chr(10), "<br>")}</p>'
    return out

def build(cfg, to, subject, body, signature, attachments, ctx):
    """cfg: from_name, from_email, reply_to. ctx: ver app.mail_build."""
    m = EmailMessage(); m["From"] = formataddr((cfg["from_name"] or "", cfg["from_email"])); m["To"] = ", ".join(to); m["Subject"] = subject.replace("\n", " ")[:200]
    if cfg.get("reply_to"): m["Reply-To"] = cfg["reply_to"]
    brand = ctx["brand"]; dark = _mix(brand, -.78); tint = _mix(brand, .09); line = _mix(brand, .2)
    # texto simples
    t = body.strip()
    if signature.strip(): t += "\n\n" + signature.strip()
    if ctx.get("card"): t += "\n\n" + "\n".join(f"{k}: {v}" for k, v in ctx["card"] + ([ctx["total"]] if ctx.get("total") else []))
    if ctx.get("contact"): t += "\n\n" + ctx["contact_title"] + ":\n" + "\n".join(f"{k}: {v}" for k, v, _ in ctx["contact"])
    if ctx.get("iban"): t += "\n\n" + ctx["pay_title"] + ":\nIBAN: " + ctx["iban"][1] + ("\n" + ctx["iban"][2] if ctx["iban"][2] else "")
    if ctx.get("promo"): t += "\n\n--\n" + ctx["promo"]["title"] + " " + ctx["promo"]["text"] + " " + ctx["promo"]["url"]
    m.set_content(t)
    # html
    F = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    lab = "font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7385;font-weight:600"
    h = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light only">'
         '<style>@media only screen and (max-width:620px){.w{width:100%!important}.px{padding-left:22px!important;padding-right:22px!important}.col{display:block!important;width:100%!important;box-sizing:border-box;margin-bottom:12px}.gap{display:none!important}.tot{font-size:28px!important}.hn{font-size:22px!important}}a{color:' + brand + '}</style></head>'
         f'<body style="margin:0;padding:0;background:#eef0f6;{F}"><div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{_esc(ctx.get("preheader", ""))}</div>'
         '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef0f6"><tr><td align="center" style="padding:28px 12px">'
         '<table role="presentation" class="w" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px">']
    # cabeçalho
    h.append(f'<tr><td class="px" style="background:{brand};background-image:linear-gradient(135deg,{brand},{dark});border-radius:16px 16px 0 0;padding:30px 36px 28px;{F}">'
             f'<div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:{_mix(brand, .72)};font-weight:700">{_esc(ctx.get("header_sub", ""))}</div>'
             f'<div class="hn" style="font-size:26px;line-height:1.25;font-weight:800;color:#ffffff;margin-top:8px">{_esc(ctx.get("header_name", ""))}</div></td></tr>')
    # corpo
    inner = _para(body)
    if ctx.get("card"):
        rws = "".join(f'<tr><td style="padding:9px 0;border-bottom:1px solid {line};{lab}">{_esc(k)}</td><td align="right" style="padding:9px 0;border-bottom:1px solid {line};font-size:15px;color:#1f2433;font-weight:600">{_esc(v)}</td></tr>' for k, v in ctx["card"])
        tot = (f'<tr><td style="padding:16px 0 4px;{lab}">{_esc(ctx["total"][0])}</td><td align="right" class="tot" style="padding:12px 0 4px;font-size:32px;font-weight:800;color:{brand};letter-spacing:-.5px">{_esc(ctx["total"][1])}</td></tr>' if ctx.get("total") else "")
        inner += (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{tint};border:1px solid {line};border-radius:12px;margin:8px 0 22px"><tr><td style="padding:8px 22px 14px">'
                  f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rws}{tot}</table></td></tr></table>')
    if signature.strip(): inner += f'<p style="margin:0 0 4px;font-size:16px;line-height:1.5;color:#1f2433;font-weight:700">{_esc(signature.strip()).replace(chr(10), "<br>")}</p>'
    h.append(f'<tr><td class="px" style="background:#ffffff;padding:34px 36px 8px;{F}">{inner}</td></tr>')
    # contactos e pagamento
    cols = []
    if ctx.get("contact"):
        ln = "".join(f'<div style="font-size:15px;line-height:1.6;color:#1f2433"><span style="color:#6b7385">{_esc(k)}:</span> ' + (f'<a href="{_esc(href)}" style="color:#1f2433;text-decoration:none;font-weight:600">{_esc(v)}</a>' if href else f'<b>{_esc(v)}</b>') + '</div>' for k, v, href in ctx["contact"])
        cols.append(f'<div style="{lab};margin-bottom:8px">{_esc(ctx["contact_title"])}</div>{ln}')
    if ctx.get("iban"):
        cols.append(f'<div style="{lab};margin-bottom:8px">{_esc(ctx["pay_title"])}</div><div style="font-size:12px;color:#6b7385">IBAN</div>'
                    f'<div style="font-family:Consolas,Menlo,monospace;font-size:14px;font-weight:700;color:#1f2433;letter-spacing:.02em">{_esc(ctx["iban"][1])}</div>'
                    + (f'<div style="font-size:13px;color:#6b7385;margin-top:4px">{_esc(ctx["iban"][2])}</div>' if ctx["iban"][2] else ""))
    if cols:
        w = "100%" if len(cols) == 1 else "50%"
        cells = f'<td class="col" width="{w}" valign="top" style="background:{tint};border:1px solid {line};border-radius:12px;padding:18px 20px">{cols[0]}</td>'
        if len(cols) == 2: cells += f'<td class="gap" width="14" style="font-size:0">&nbsp;</td><td class="col" width="50%" valign="top" style="background:{tint};border:1px solid {line};border-radius:12px;padding:18px 20px">{cols[1]}</td>'
        h.append(f'<tr><td class="px" style="background:#ffffff;padding:18px 36px 34px;{F}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table></td></tr>')
    else: h.append('<tr><td style="background:#ffffff;height:26px;font-size:0">&nbsp;</td></tr>')
    # publicidade Claquete
    pr = ctx.get("promo"); radius = "0 0 16px 16px" if not pr else "0"
    if pr:
        logo = '<img src="cid:claquetelogo" width="44" height="44" alt="" style="display:block;border-radius:11px;border:0">' if ctx.get("logo") else ""
        h.append(f'<tr><td class="px" style="background:{dark};padding:30px 36px;border-radius:0 0 16px 16px;{F}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                 f'<td width="56" valign="top" style="padding-right:14px">{logo}</td><td valign="top"><div style="font-size:18px;font-weight:800;color:#ffffff;line-height:1.3">{_esc(pr["title"])}</div>'
                 f'<div style="font-size:14px;line-height:1.6;color:{_mix(brand, .9)};margin:8px 0 18px">{_esc(pr["text"])}</div>'
                 f'<a href="{_esc(pr["url"])}" style="display:inline-block;background:#ffffff;color:{dark};text-decoration:none;font-weight:700;font-size:14px;padding:11px 22px;border-radius:99px">{_esc(pr["button"])} &rarr;</a></td></tr></table></td></tr>')
    if ctx.get("footer"): h.append(f'<tr><td align="center" style="padding:18px 12px 4px;font-size:12px;line-height:1.5;color:#7a8099;{F}">{_esc(ctx["footer"])}</td></tr>')
    h.append("</table></td></tr></table></body></html>")
    m.add_alternative("".join(h), subtype="html")
    if ctx.get("logo"): m.get_body(("html",)).add_related(ctx["logo"], "image", "png", cid="<claquetelogo>")
    for name, data in attachments: m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return m

def send(cfg, msg, to):
    """cfg: host, port, sec ('starttls'|'ssl'|'none' só em DEV), username, password"""
    ip = safe_host(cfg["host"], cfg["port"]); ctx = ssl.create_default_context(); port = int(cfg["port"])
    s = smtplib.SMTP_SSL(timeout=25, context=ctx) if cfg["sec"] == "ssl" else smtplib.SMTP(timeout=25)
    s._host = cfg["host"]  # nome para validar o certificado, ligando-se ao IP já verificado
    try:
        s.connect(ip, port)
        if cfg["sec"] == "starttls": s.starttls(context=ctx); s.ehlo()
        elif cfg["sec"] == "none" and not DEV: raise ValueError("Ligação sem cifra não permitida.")
        if cfg.get("username"): s.login(cfg["username"], cfg["password"])
        s.send_message(msg, from_addr=cfg["from_email"], to_addrs=to)
    finally:
        try: s.quit()
        except Exception: pass

def friendly(ex):
    if isinstance(ex, smtplib.SMTPAuthenticationError): return "Utilizador ou palavra-passe recusados pelo servidor de email. No Gmail usa uma palavra-passe de aplicação."
    if isinstance(ex, smtplib.SMTPRecipientsRefused): return "O servidor recusou o destinatário."
    if isinstance(ex, (socket.timeout, TimeoutError)): return "O servidor não respondeu a tempo."
    if isinstance(ex, (socket.gaierror, ConnectionError, OSError)): return "Não foi possível ligar ao servidor de email (verifica o endereço, a porta e se o teu servidor permite ligações de saída)."
    if isinstance(ex, ssl.SSLError): return "Falha na ligação segura ao servidor de email."
    if isinstance(ex, ValueError): return str(ex)
    return "Não foi possível enviar o email."
