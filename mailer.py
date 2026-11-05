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
def build(cfg, to, subject, body, signature, brand, site, footer_text, attachments):
    """cfg: dict com from_name, from_email, reply_to. attachments: [(nome, bytes)]"""
    m = EmailMessage(); m["From"] = formataddr((cfg["from_name"] or "", cfg["from_email"])); m["To"] = ", ".join(to); m["Subject"] = subject.replace("\n", " ")[:200]
    if cfg.get("reply_to"): m["Reply-To"] = cfg["reply_to"]
    sig = signature.strip()
    text = body.strip() + ("\n\n" + sig if sig else "") + ("\n\n--\n" + footer_text if footer_text else "")
    m.set_content(text)
    esc = lambda s: html.escape(s).replace("\n", "<br>")
    h = (f'<div style="background:#f4f5f9;padding:24px 12px;font-family:Arial,Helvetica,sans-serif"><div style="max-width:600px;margin:auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e3e6ef">'
         f'<div style="background:{brand};color:#fff;padding:16px 24px;font-size:18px;font-weight:bold">{html.escape(cfg["from_name"] or site)}</div>'
         f'<div style="padding:24px;color:#1b1f33;font-size:15px;line-height:1.55">{esc(body.strip())}'
         + (f'<p style="margin-top:24px;color:#444">{esc(sig)}</p>' if sig else "") + '</div>'
         + (f'<div style="padding:12px 24px;background:#f4f5f9;color:#7a8099;font-size:12px;text-align:center">{html.escape(footer_text)}</div>' if footer_text else "") + '</div></div>')
    m.add_alternative(h, subtype="html")
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
