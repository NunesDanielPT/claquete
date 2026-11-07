"""Exportacao para PDF e Excel (xlsx) sem dependencias: PDF e XLSX escritos 'a mao'."""
import io, struct, unicodedata, zipfile, zlib
import datetime as dt
from xml.sax.saxutils import escape

# ---------------------------------------------------------------- PDF
_HW = {32: 278, 33: 278, 34: 355, 35: 556, 36: 556, 37: 889, 38: 667, 39: 191, 40: 333, 41: 333, 42: 389, 43: 584, 44: 278, 45: 333, 46: 278, 47: 278, 58: 278, 59: 278, 60: 584, 61: 584, 62: 584, 63: 556, 64: 1015,
       65: 667, 66: 667, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778, 72: 722, 73: 278, 74: 500, 75: 667, 76: 556, 77: 833, 78: 722, 79: 778, 80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722, 86: 667, 87: 944, 88: 667, 89: 667, 90: 611,
       91: 278, 92: 278, 93: 278, 94: 469, 95: 556, 96: 333, 97: 556, 98: 556, 99: 500, 100: 556, 101: 556, 102: 278, 103: 556, 104: 556, 105: 222, 106: 222, 107: 500, 108: 222, 109: 833, 110: 556, 111: 556, 112: 556, 113: 556, 114: 333,
       115: 500, 116: 278, 117: 556, 118: 500, 119: 722, 120: 500, 121: 500, 122: 500, 123: 334, 124: 260, 125: 334, 126: 584}
_BW = dict(_HW); _BW.update({33: 333, 34: 474, 38: 722, 39: 238, 58: 333, 59: 333, 63: 611, 64: 975, 74: 556, 75: 722, 76: 611, 98: 611, 99: 556, 100: 611, 102: 333, 103: 611, 104: 611, 105: 278, 106: 278, 107: 556, 108: 278, 109: 889, 110: 611,
       111: 611, 112: 611, 113: 611, 114: 389, 115: 556, 116: 333, 117: 611, 118: 556, 119: 778, 120: 556, 121: 556, 122: 500, 124: 280, 91: 333, 92: 278, 93: 333, 123: 389, 125: 389, 94: 584})
for _k in range(48, 58): _HW[_k] = _BW[_k] = 556

def _cw(ch, bold):
    t = _BW if bold else _HW; o = ord(ch)
    if o in t: return t[o]
    if ch in "€–": return 556
    if ch == "…": return 1000
    if ch in "•·": return 350
    b = unicodedata.normalize("NFD", ch)[0]
    return t.get(ord(b), 556)

def text_w(s, size, bold=False): return sum(_cw(c, bold) for c in s) * size / 1000

def fit(s, size, maxw, bold=False):
    s = str(s)
    if text_w(s, size, bold) <= maxw: return s
    while s and text_w(s + "…", size, bold) > maxw: s = s[:-1]
    return s.rstrip() + "…"

def wrap(s, size, maxw, bold=False, maxlines=3):
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(t, size, bold) <= maxw: cur = t
        else:
            if cur: lines.append(cur)
            cur = w if text_w(w, size, bold) <= maxw else fit(w, size, maxw, bold)
    if cur: lines.append(cur)
    if len(lines) > maxlines: lines = lines[:maxlines]; lines[-1] = fit(lines[-1] + "…", size, maxw, bold)
    return lines or [""]

def _rgb(h):
    h = h.lstrip("#"); return " ".join(f"{int(h[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))

class PDF:
    def __init__(self, landscape=False, title="", footer=None):
        self.W, self.H = (842, 595) if landscape else (595, 842); self.pages = []; self.ops = None; self.title = title; self.footer = footer
        self.new_page()

    def new_page(self): self.ops = []; self.pages.append(self.ops)

    def _y(self, y, h=0): return self.H - y - h

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=.6):
        o = []
        if fill: o.append(f"{_rgb(fill)} rg")
        if stroke: o.append(f"{_rgb(stroke)} RG {lw} w")
        op = "B" if fill and stroke else "f" if fill else "S"
        self.ops.append(" ".join(o) + f" {x:.2f} {self._y(y, h):.2f} {w:.2f} {h:.2f} re {op}")

    def rrect(self, x, y, w, h, r, fill):
        Y = self._y(y, h); k = .5523 * r; X = x
        p = (f"{X + r:.2f} {Y:.2f} m {X + w - r:.2f} {Y:.2f} l {X + w - r + k:.2f} {Y:.2f} {X + w:.2f} {Y + r - k:.2f} {X + w:.2f} {Y + r:.2f} c {X + w:.2f} {Y + h - r:.2f} l "
             f"{X + w:.2f} {Y + h - r + k:.2f} {X + w - r + k:.2f} {Y + h:.2f} {X + w - r:.2f} {Y + h:.2f} c {X + r:.2f} {Y + h:.2f} l {X + r - k:.2f} {Y + h:.2f} {X:.2f} {Y + h - r + k:.2f} {X:.2f} {Y + h - r:.2f} c "
             f"{X:.2f} {Y + r:.2f} l {X:.2f} {Y + r - k:.2f} {X + r - k:.2f} {Y:.2f} {X + r:.2f} {Y:.2f} c h")
        self.ops.append(f"{_rgb(fill)} rg {p} f")

    def line(self, x1, y1, x2, y2, color="#e2e6eb", lw=.6):
        self.ops.append(f"{_rgb(color)} RG {lw} w {x1:.2f} {self._y(y1):.2f} m {x2:.2f} {self._y(y2):.2f} l S")

    def text(self, x, y, s, size=10, bold=False, color="#12161c", align="l"):
        s = str(s)
        if align != "l":
            w = text_w(s, size, bold); x = x - w if align == "r" else x - w / 2
        b = s.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        self.ops.append(f"BT {_rgb(color)} rg /{'F2' if bold else 'F1'} {size} Tf {x:.2f} {self._y(y):.2f} Td (".encode() + b + b") Tj ET")

    def logo(self, x, y, size, cols):
        """cols = (brand, todo, inv, paid) em hex; desenha o logotipo da Claquete em vetor"""
        s = size / 28.0
        self.rrect(x, y, size, size, 8 * s, cols[0])
        for bx, by, bw, bh, c in ((6, 7, 16, 3.6, cols[1]), (6, 12.2, 11, 3.6, cols[2]), (9, 17.4, 13, 3.6, cols[3])):
            self.rrect(x + bx * s, y + by * s, bw * s, bh * s, 1.8 * s, c)

    def save(self):
        n = len(self.pages)
        if self.footer:
            for i, ops in enumerate(self.pages): self.ops = ops; self.footer(self, i + 1, n)
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        for ops in self.pages:
            data = zlib.compress(b"\n".join(o if isinstance(o, bytes) else o.encode("latin-1", "replace") for o in ops))
            objs.append(b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"); ci = len(objs)
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W} {self.H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {ci} 0 R >>".encode()); kids.append(len(objs))
        objs[1] = f"<< /Type /Pages /Count {n} /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>".encode()
        t = self.title.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        objs.append(b"<< /Title (" + t + b") /Producer (Claquete) >>")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offs = []
        for i, o in enumerate(objs): offs.append(len(out)); out += f"{i + 1} 0 obj\n".encode() + o + b"\nendobj\n"
        x = len(out); out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for o in offs: out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{x}\n%%EOF".encode()
        return bytes(out)

# ---------------------------------------------------------------- XLSX
def col_letter(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s

def xl_date(d): return (dt.date.fromisoformat(d) - dt.date(1899, 12, 30)).days

class Sheet:
    def __init__(self, name): self.name = name[:31]; self.cells = {}; self.widths = {}; self.merges = []; self.heights = {}; self.image = None; self.freeze = None
    def set(self, r, c, v, st="text"): self.cells[(r, c)] = (v, st)

STYLES = ["default", "title", "header", "text", "money", "date", "boldtext", "boldmoney", "note", "label", "wrap", "center", "sub", "formulamoney"]
_SI = {n: i for i, n in enumerate(STYLES)}

def _styles_xml(brand):
    b = brand.lstrip("#").upper()
    fonts = (f'<font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="20"/><color rgb="FF{b}"/><name val="Calibri"/></font>'
             '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><i/><sz val="9"/><color rgb="FF67717E"/><name val="Calibri"/></font><font><sz val="12"/><color rgb="FF67717E"/><name val="Calibri"/></font>')
    fills = f'<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF{b}"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF1F3F6"/></patternFill></fill>'
    bd = '<border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFE2E6EB"/></left><right style="thin"><color rgb="FFE2E6EB"/></right><top style="thin"><color rgb="FFE2E6EB"/></top><bottom style="thin"><color rgb="FFE2E6EB"/></bottom><diagonal/></border>'
    # (numFmt, font, fill, border, align)
    xf = {"default": (0, 0, 0, 0, ""), "title": (0, 2, 0, 0, '<alignment vertical="center"/>'), "header": (0, 3, 2, 1, '<alignment horizontal="center" vertical="center" wrapText="1"/>'),
          "text": (0, 0, 0, 1, '<alignment vertical="center"/>'), "money": (164, 0, 0, 1, '<alignment vertical="center"/>'), "date": (165, 0, 0, 1, '<alignment horizontal="center" vertical="center"/>'),
          "boldtext": (0, 1, 3, 1, '<alignment vertical="center"/>'), "boldmoney": (164, 1, 3, 1, '<alignment vertical="center"/>'), "note": (0, 4, 0, 0, '<alignment wrapText="1" vertical="top"/>'),
          "label": (0, 1, 0, 0, ""), "wrap": (0, 0, 0, 1, '<alignment wrapText="1" vertical="center"/>'), "center": (0, 0, 0, 1, '<alignment horizontal="center" vertical="center"/>'),
          "sub": (0, 5, 0, 0, '<alignment vertical="center"/>'), "formulamoney": (164, 1, 3, 1, '<alignment vertical="center"/>')}
    cx = "".join(f'<xf numFmtId="{n}" fontId="{f}" fillId="{fi}" borderId="{b_}" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">{al}</xf>' for n, f, fi, b_, al in (xf[k] for k in STYLES))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00\\ &quot;€&quot;"/><numFmt numFmtId="165" formatCode="dd/mm/yyyy"/></numFmts>'
            f'<fonts count="6">{fonts}</fonts><fills count="4">{fills}</fills><borders count="2">{bd}</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(STYLES)}">{cx}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

def _sheet_xml(sh, has_img):
    rows = {}
    for (r, c), v in sh.cells.items(): rows.setdefault(r, {})[c] = v
    mr = max(rows) if rows else 1; mc = max((c for r in rows.values() for c in r), default=1)
    o = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
         '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>', f'<dimension ref="A1:{col_letter(mc)}{mr}"/>']
    pane = f'<pane ySplit="{sh.freeze}" topLeftCell="A{sh.freeze + 1}" activePane="bottomLeft" state="frozen"/>' if sh.freeze else ""
    o.append(f'<sheetViews><sheetView showGridLines="0" workbookViewId="0">{pane}</sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/>')
    if sh.widths: o.append("<cols>" + "".join(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>' for c, w in sorted(sh.widths.items())) + "</cols>")
    o.append("<sheetData>")
    for r in sorted(rows):
        ht = f' ht="{sh.heights[r]}" customHeight="1"' if r in sh.heights else ""
        o.append(f'<row r="{r}"{ht}>')
        for c in sorted(rows[r]):
            v, st = rows[r][c]; ref = f"{col_letter(c)}{r}"; s = _SI[st]
            if v is None or v == "": o.append(f'<c r="{ref}" s="{s}"/>')
            elif isinstance(v, tuple):  # ("f", formula, cached)
                o.append(f'<c r="{ref}" s="{s}"><f>{escape(v[1])}</f><v>{v[2]}</v></c>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool): o.append(f'<c r="{ref}" s="{s}"><v>{v}</v></c>')
            else: o.append(f'<c r="{ref}" s="{s}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        o.append("</row>")
    o.append("</sheetData>")
    if sh.merges: o.append(f'<mergeCells count="{len(sh.merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in sh.merges) + "</mergeCells>")
    o.append('<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>')
    if has_img: o.append('<drawing r:id="rId1"/>')
    o.append("</worksheet>"); return "".join(o)

def xlsx(sheets, brand="#3b4cdb", logo_png=None):
    z = io.BytesIO(); zf = zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED)
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    for i, sh in enumerate(sheets, 1):
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        if sh.image and logo_png: ct.append(f'<Override PartName="/xl/drawings/drawing{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
    zf.writestr("[Content_Types].xml", "".join(ct) + "</Types>")
    zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{escape(sh.name)}" sheetId="{i}" r:id="rId{i}"/>' for i, sh in enumerate(sheets, 1)) + "</sheets></workbook>")
    zf.writestr("xl/workbook.xml", wb)
    zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    zf.writestr("xl/styles.xml", _styles_xml(brand))
    for i, sh in enumerate(sheets, 1):
        img = bool(sh.image and logo_png)
        zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sh, img))
        if img:
            zf.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing{i}.xml"/></Relationships>')
            zf.writestr(f"xl/drawings/drawing{i}.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>95250</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>95250</xdr:rowOff></xdr:from><xdr:ext cx="571500" cy="571500"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Logo"/><xdr:cNvPicPr/></xdr:nvPicPr>'
                        '<xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="571500" cy="571500"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>')
            zf.writestr(f"xl/drawings/_rels/drawing{i}.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/></Relationships>')
    if logo_png and any(sh.image for sh in sheets): zf.writestr("xl/media/logo.png", logo_png)
    zf.close(); return z.getvalue()


# ---------------------------------------------------------------- documentos
GREY, LIGHT, INK, MUT = "#e2e6eb", "#f1f3f6", "#12161c", "#67717e"
ST_COL = {"plan": "#5f6b8a", "todo": "#d1343a", "inv": "#b9770e", "paid": "#1f8a58"}

def _footer(doc):
    def f(p, i, n):
        p.line(36, p.H - 40, p.W - 36, p.H - 40, GREY)
        p.text(36, p.H - 27, doc["disclaimer"], 7.5, False, MUT)
        p.text(36, p.H - 16, doc["site"] + " · " + doc["T"]["generated"] + " " + doc["generated"], 7.5, False, MUT)
        p.text(p.W - 36, p.H - 27, f'{doc["T"]["page"]} {i}/{n}', 8, True, MUT, "r")
    return f

def _header(p, doc):
    cols = doc["cols"]; W = p.W; M = 36
    p.rect(0, 0, W, 6, fill=cols[0]); p.logo(M, 22, 44, cols)
    p.text(M + 56, 44, doc["site"], 20, True); p.text(M + 56, 62, doc["title"], 11, False, MUT)
    y = 32
    for i, ln in enumerate(doc["issuer"]):
        p.text(W - M, y, ln, 9.5 if i == 0 else 8.5, i == 0, INK if i == 0 else MUT, "r"); y += 12
    p.line(M, 86, W - M, 86, cols[0], 1.2)

def _kv_lines(p, x, y, pairs, size=8.5, lab_w=70):
    for k, v in pairs:
        p.text(x, y, k, size, True, MUT); p.text(x + lab_w, y, fit(v, size, 300), size); y += 12
    return y

def pdf_list(doc):
    T, eur, d, cols = doc["T"], doc["eur"], doc["d"], doc["cols"]
    p = PDF(True, doc["title"], _footer(doc)); M = 36; W = p.W; _header(p, doc); y = 102
    if doc["filters"]: y = _kv_lines(p, M, y, doc["filters"], 8.5, 62) + 2
    if doc.get("client"):
        p.rrect(M, y, W - 2 * M, 12 + 12 * ((len(doc["client"]) + 1) // 2), 8, LIGHT); yy = y + 16
        for i, (k, v) in enumerate(doc["client"]):
            x = M + 12 + (i % 2) * 380
            p.text(x, yy, k, 8.5, True, MUT); p.text(x + 70, yy, fit(v, 8.5, 290), 8.5)
            if i % 2: yy += 12
        y += 18 + 12 * ((len(doc["client"]) + 1) // 2)
    tot = doc["totals"]
    boxes = [(T["s_base"], tot["base"]), (T["s_vat"], tot["vat"]), (T["s_wh"], tot["wh"]), (T["s_total"], tot["total"]), (T["s_paid"], tot["paid"]), (T["s_due"], tot["due"])]
    bw = (W - 2 * M - 5 * 8) / 6; y += 6
    for i, (k, v) in enumerate(boxes):
        x = M + i * (bw + 8); p.rrect(x, y, bw, 42, 8, LIGHT); p.text(x + 10, y + 16, fit(k, 7.5, bw - 16), 7.5, False, MUT); p.text(x + 10, y + 33, eur(v), 12.5, True, cols[0] if i == 3 else INK)
    y += 58
    C = [("inv_date", 62, "l"), ("event", 196, "l"), ("client", 124, "l"), ("inv_no", 62, "l"), ("base", 68, "r"), ("vat", 58, "r"), ("wh", 62, "r"), ("total", 74, "r"), ("status", 64, "l")]
    def thead(y):
        p.rect(M, y, W - 2 * M, 20, fill=cols[0]); x = M
        for k, w, al in C:
            p.text(x + (w - 6 if al == "r" else 6), y + 13.5, fit(T[k], 8, w - 10, True), 8, True, "#ffffff", al); x += w
        return y + 20
    y = thead(y); n = 0
    for r in doc["rows"]:
        if y + 26 > p.H - 52:
            p.new_page(); _header(p, doc); y = thead(102)
        if n % 2: p.rect(M, y, W - 2 * M, 26, fill="#f7f8fa")
        x = M; vals = [d(r["invoice_date"]) if r["invoice_date"] else "—", None, r["client"] or "—", r["invoice_no"] or "—", eur(r["base"]), eur(r["vat"]) if r["vat"] else "—", eur(r["wh"]) if r["wh"] else "—", eur(r["total"]), None]
        for j, (k, w, al) in enumerate(C):
            if k == "event":
                p.text(x + 6, y + 11, fit(r["title"], 8.5, w - 10, True), 8.5, True); p.text(x + 6, y + 21, d(r["start"]) + ("" if r["start"] == r["end"] else " – " + d(r["end"])), 7, False, MUT)
            elif k == "status": p.text(x + 6, y + 16, T["st_" + r["state"]], 8, True, ST_COL[r["state"]])
            else: p.text(x + (w - 6 if al == "r" else 6), y + 16, fit(vals[j], 8.5, w - 10, k == "total"), 8.5, k == "total", INK, al)
            x += w
        p.line(M, y + 26, W - M, y + 26, GREY, .4); y += 26; n += 1
    if not doc["rows"]: p.text(M + 6, y + 18, T["none"], 9, False, MUT); y += 26
    if y + 28 > p.H - 52: p.new_page(); _header(p, doc); y = 102
    p.rect(M, y + 4, W - 2 * M, 24, fill=LIGHT); x = M
    for k, w, al in C:
        if k == "event": p.text(x + 6, y + 20, T["totals"] + f' ({len(doc["rows"])})', 9, True)
        elif k in ("base", "vat", "wh", "total"): p.text(x + w - 6, y + 20, eur(tot[k]), 9, True, INK, "r")
        x += w
    return p.save()

def pdf_event(doc):
    T, eur, d, cols = doc["T"], doc["eur"], doc["d"], doc["cols"]; r = doc["rows"][0]
    p = PDF(False, doc["title"], _footer(doc)); M = 36; W = p.W; _header(p, doc)
    p.text(M, 118, fit(r["title"], 20, W - 2 * M - 110, True), 20, True)
    p.text(W - M, 118, T["st_" + r["state"]].upper(), 10, True, ST_COL[r["state"]], "r")
    p.text(M, 134, d(r["start"]) + ("" if r["start"] == r["end"] else " – " + d(r["end"])), 10, False, MUT)
    cw = (W - 2 * M - 12) / 2; y = 150
    for i, (head, pairs) in enumerate(((T["client"], doc["client"] or [(T["name"], "—")]), (T["invoice"], doc["invoice"]))):
        x = M + i * (cw + 12); p.rrect(x, y, cw, 20 + 14 * max(len(doc["client"] or [1]), len(doc["invoice"])) + 8, 8, LIGHT)
        p.text(x + 12, y + 17, head.upper(), 8, True, cols[0]); yy = y + 33
        for k, v in pairs: p.text(x + 12, yy, k, 8.5, True, MUT); p.text(x + 78, yy, fit(v, 9, cw - 90), 9); yy += 14
    y += 20 + 14 * max(len(doc["client"] or [1]), len(doc["invoice"])) + 24
    p.rect(M, y, W - 2 * M, 22, fill=cols[0]); p.text(M + 8, y + 15, T["desc"], 9, True, "#ffffff"); p.text(W - M - 8, y + 15, T["amount"], 9, True, "#ffffff", "r"); y += 22
    for i, (lab, amt) in enumerate(doc["lines"]):
        if i % 2: p.rect(M, y, W - 2 * M, 22, fill="#f7f8fa")
        p.text(M + 8, y + 15, fit(lab or "—", 9.5, W - 2 * M - 140), 9.5); p.text(W - M - 8, y + 15, eur(amt), 9.5, False, INK, "r"); p.line(M, y + 22, W - M, y + 22, GREY, .4); y += 22
    y += 14; bx = W - M - 250; tot = doc["totals"]
    rowsx = [(T["s_base"], tot["base"], False)]
    if doc["vat_text"]: rowsx.append((doc["vat_text"], tot["vat"], False))
    if doc["wh_text"]: rowsx.append((doc["wh_text"], -tot["wh"], False))
    for lab, v, b in rowsx:
        p.text(bx, y + 12, lab, 9.5, b, MUT); p.text(W - M - 8, y + 12, eur(v), 9.5, b, INK, "r"); y += 18
    p.rrect(bx - 8, y + 2, 258, 34, 8, cols[0]); p.text(bx + 4, y + 24, T["s_total"], 11, True, "#ffffff"); p.text(W - M - 8, y + 25, eur(tot["total"]), 14, True, "#ffffff", "r"); y += 52
    if r.get("notes"):
        p.text(M, y, T["notes"].upper(), 8, True, cols[0]); y += 14
        for ln in wrap(r["notes"], 9, W - 2 * M, False, 8): p.text(M, y, ln, 9); y += 12
    return p.save()

def _top(sh, doc, ncols):
    T = doc["T"]; sh.image = True; sh.heights[1] = 26; sh.heights[2] = 22
    sh.set(1, 2, doc["site"], "title"); sh.set(2, 2, doc["title"], "sub"); r = 4
    for k, v in doc["issuer_kv"] + doc["filters"]:
        sh.set(r, 1, k, "label"); sh.set(r, 2, v, "text"); sh.merges.append(f"B{r}:{col_letter(min(ncols, 4))}{r}"); r += 1
    if doc.get("client"):
        r += 1
        for k, v in doc["client"]: sh.set(r, 1, k, "label"); sh.set(r, 2, v, "text"); sh.merges.append(f"B{r}:{col_letter(min(ncols, 4))}{r}"); r += 1
    return r + 1

def xlsx_list(doc):
    T = doc["T"]; sh = Sheet(T["sheet"]); heads = ["inv_date", "event", "start", "end", "client", "inv_no", "base", "vat", "wh", "total", "status"]; widths = [15, 34, 12, 12, 26, 14, 14, 13, 13, 16, 14]
    for i, w in enumerate(widths, 1): sh.widths[i] = w
    r = _top(sh, doc, len(heads)); sh.heights[r] = 30
    for c, k in enumerate(heads, 1): sh.set(r, c, T[k], "header")
    sh.freeze = r; first = r + 1
    for x in doc["rows"]:
        r += 1
        sh.set(r, 1, xl_date(x["invoice_date"]) if x["invoice_date"] else "—", "date" if x["invoice_date"] else "center"); sh.set(r, 2, x["title"], "wrap")
        sh.set(r, 3, xl_date(x["start"]), "date"); sh.set(r, 4, xl_date(x["end"]), "date"); sh.set(r, 5, x["client"] or "—", "text"); sh.set(r, 6, x["invoice_no"] or "—", "center")
        sh.set(r, 7, round(x["base"], 2), "money"); sh.set(r, 8, round(x["vat"], 2), "money"); sh.set(r, 9, round(x["wh"], 2), "money")
        sh.set(r, 10, ("f", f"G{r}+H{r}-I{r}", round(x["total"], 2)), "money"); sh.set(r, 11, T["st_" + x["state"]], "center")
    last = r
    r += 1; sh.set(r, 1, T["totals"], "boldtext")
    for c in range(2, 12): sh.set(r, c, "", "boldtext")
    tot = doc["totals"]
    for c, k in ((7, "base"), (8, "vat"), (9, "wh"), (10, "total")):
        L = col_letter(c); sh.set(r, c, ("f", f"SUM({L}{first}:{L}{last})", round(tot[k], 2)), "formulamoney")
    r += 2
    sh.set(r, 9, T["s_paid"], "label"); sh.set(r, 10, ("f", f'SUMIF(K{first}:K{last},"{T["st_paid"]}",J{first}:J{last})', round(tot["paid"], 2)), "formulamoney")
    sh.set(r + 1, 9, T["s_due"], "label"); sh.set(r + 1, 10, ("f", f"J{r - 2}-J{r}", round(tot["due"], 2)), "formulamoney")
    sh.set(r + 3, 1, doc["disclaimer"], "note"); sh.merges.append(f"A{r + 3}:K{r + 3}"); sh.heights[r + 3] = 28
    return xlsx([sh], doc["cols"][0], doc.get("png"))

def xlsx_event(doc):
    T = doc["T"]; sh = Sheet(T["sheet_event"]); r0 = doc["rows"][0]
    sh.widths.update({1: 26, 2: 40, 3: 18})
    sh.image = True; sh.heights[1] = 26; sh.heights[2] = 22; sh.set(1, 2, doc["site"], "title"); sh.set(2, 2, doc["title"], "sub"); r = 4
    for k, v in doc["issuer_kv"]: sh.set(r, 1, k, "label"); sh.set(r, 2, v, "text"); r += 1
    r += 1; sh.set(r, 1, r0["title"], "title"); sh.heights[r] = 24; r += 1
    for k, v in [(T["dates"], doc["dates"]), (T["status"], T["st_" + r0["state"]])] + doc["client"] + doc["invoice"]:
        sh.set(r, 1, k, "label"); sh.set(r, 2, v, "text"); r += 1
    r += 1; sh.set(r, 1, T["desc"], "header"); sh.set(r, 2, "", "header"); sh.set(r, 3, T["amount"], "header"); sh.merges.append(f"A{r}:B{r}"); r += 1; first = r
    for lab, amt in doc["lines"]: sh.set(r, 1, lab or "—", "text"); sh.set(r, 2, "", "text"); sh.merges.append(f"A{r}:B{r}"); sh.set(r, 3, round(amt, 2), "money"); r += 1
    last = r - 1; tot = doc["totals"]; b = r
    sh.set(r, 1, T["s_base"], "boldtext"); sh.set(r, 2, "", "boldtext"); sh.set(r, 3, ("f", f"SUM(C{first}:C{last})", round(tot["base"], 2)), "formulamoney"); r += 1
    if doc["vat_text"]: sh.set(r, 1, doc["vat_text"], "text"); sh.set(r, 2, "", "text"); sh.set(r, 3, ("f", f"C{b}*{doc['vat_rate']}/100", round(tot["vat"], 2)), "money"); r += 1
    if doc["wh_text"]: sh.set(r, 1, doc["wh_text"], "text"); sh.set(r, 2, "", "text"); sh.set(r, 3, ("f", f"-C{b}*{doc['wh_rate']}/100", round(-tot["wh"], 2)), "money"); r += 1
    sh.set(r, 1, T["s_total"], "boldtext"); sh.set(r, 2, "", "boldtext"); sh.set(r, 3, ("f", f"SUM(C{b}:C{r - 1})", round(tot["total"], 2)), "formulamoney"); r += 2
    if r0.get("notes"): sh.set(r, 1, T["notes"], "label"); sh.set(r, 2, r0["notes"], "wrap"); sh.merges.append(f"B{r}:C{r}"); sh.heights[r] = 48; r += 2
    sh.set(r, 1, doc["disclaimer"], "note"); sh.merges.append(f"A{r}:C{r}"); sh.heights[r] = 28
    return xlsx([sh], doc["cols"][0], doc.get("png"))
