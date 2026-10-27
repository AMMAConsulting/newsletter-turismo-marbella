"""Prepara el material del boletín SEMANAL de turismo de Marbella.

Cada semana rota el tema central (hoteles, alojamiento extrahotelero, mercados,
empleo) para que el contenido y las gráficas cambien aunque las fuentes
oficiales sean mensuales. Las noticias son siempre las de los últimos días.

Reúne lo último de:
  - INE Tempus3 (EOH hoteles, EOAP apartamentos, VUT) para Marbella
  - Observatorio Económico de Marbella (paro, afiliación, contratos)
  - Noticias turísticas recientes (Google News RSS)

y deja en docs/boletin/:
  - datos.json      -> lo que lee Make para que GPT redacte el boletín
  - graf-*.png      -> gráficas que se incrustan en el correo
  - plantilla.html  -> plantilla del correo (se copia desde plantilla/)

Solo usa la librería estándar + matplotlib.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import logging
import matplotlib
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
matplotlib.use("Agg")
plt_rc = {"font.family": "sans-serif", "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"]}
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
plt.rcParams.update(plt_rc)

RAIZ = Path(__file__).parent
SALIDA = RAIZ / "docs" / "boletin"
WEB = "https://ammaconsulting.github.io/newsletter-turismo-marbella"
ECO = "https://josehino.github.io/observatorio-economico-marbella/data"
UA = {"User-Agent": "boletin-turismo-marbella/1.0"}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Series INE de Marbella (ver memoria ine-indicadores-marbella)
SERIES = {
    "viajeros_hotel":   ("EOT42428", "Viajeros en hoteles"),
    "pernoct_hotel":    ("EOT42534", "Pernoctaciones en hoteles"),
    "viajeros_esp":     ("EOT2759",  "Viajeros residentes en España"),
    "viajeros_ext":     ("EOT2760",  "Viajeros extranjeros"),
    "ocupacion_plazas": ("EOT3152",  "Ocupación hotelera por plazas (%)"),
    "estancia_media":   ("EOT2936",  "Estancia media (días)"),
    "adr":              ("EOT43542", "Tarifa media diaria ADR (€)"),
    "revpar":           ("EOT43946", "Ingreso por habitación disponible RevPAR (€)"),
    "pernoct_apart":    ("EOT41394", "Pernoctaciones en apartamentos turísticos"),
    "ocup_apart":       ("EOT9851",  "Ocupación de apartamentos turísticos (%)"),
    "pernoct_apart_esp": ("EOT9425", "Pernoctaciones en apartamentos de residentes en España"),
    "pernoct_apart_ext": ("EOT9426", "Pernoctaciones en apartamentos de residentes en el extranjero"),
    "vut_viviendas":    ("VTE3889",  "Viviendas de uso turístico"),
    "vut_plazas":       ("VTE15629", "Plazas en viviendas de uso turístico"),
}
TASAS = ("ocupacion_plazas", "ocup_apart")

TEMAS = [
    {"id": "hoteles", "etiqueta": "TEMA DE LA SEMANA · HOTELES",
     "foco": "Hoteles: viajeros, pernoctaciones, ocupación, estancia media, tarifa media (ADR) y RevPAR."},
    {"id": "extrahotelero", "etiqueta": "TEMA DE LA SEMANA · APARTAMENTOS Y VIVIENDAS TURÍSTICAS",
     "foco": "Alojamiento extrahotelero: apartamentos turísticos (pernoctaciones, ocupación, origen) y viviendas de uso turístico (número y plazas)."},
    {"id": "mercados", "etiqueta": "TEMA DE LA SEMANA · MERCADOS INTERNACIONALES",
     "foco": "Mercados: de qué países llegan los visitantes, peso del turista extranjero frente al nacional y su evolución."},
    {"id": "empleo", "etiqueta": "TEMA DE LA SEMANA · EMPLEO Y ECONOMÍA",
     "foco": "Empleo: paro registrado, afiliación a la Seguridad Social, contratos y estabilidad (indefinidos)."},
]

def hora_madrid(fecha, hh, mm):
    """ISO 8601 con el desfase de Madrid (horario de verano: último domingo de marzo a último de octubre)."""
    def ultimo_domingo(anio, mes):
        d = dt.date(anio, mes, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    verano = ultimo_domingo(fecha.year, 3) <= fecha < ultimo_domingo(fecha.year, 10)
    return f"{fecha.isoformat()}T{hh:02d}:{mm:02d}:00{'+02:00' if verano else '+01:00'}"


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

AZUL, AZUL_CLARO, GRIS = "#0b5cad", "#9cc3ea", "#6b7280"


def get(url, intentos=3):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(5)


def periodo_ine(d):
    # NO usar Fecha (va en hora de Madrid y en UTC cae un mes antes)
    fk = d["FK_Periodo"]
    if 1 <= fk <= 12:
        return f'{d["Anyo"]}-{fk:02d}'
    f = dt.datetime.fromtimestamp(d["Fecha"] / 1000 + 7200, dt.timezone.utc)
    return f"{f.year}-{f.month:02d}"


def serie_ine(cod, n=26):
    js = json.loads(get(f"https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/{cod}?nult={n}"))
    return [{"t": periodo_ine(d), "v": d["Valor"]} for d in js["Data"] if d.get("Valor") is not None]


def nombre_mes(t):
    a, m = t.split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def resumen(serie, decimales=0):
    """Último dato, mismo mes del año anterior y variación."""
    if not serie:
        return None
    ult = serie[-1]
    a, m = ult["t"].split("-")
    previo = next((x for x in serie if x["t"] == f"{int(a) - 1}-{m}"), None)
    r = {"periodo": ult["t"], "mes": nombre_mes(ult["t"]), "valor": round(ult["v"], decimales)}
    if previo and previo["v"]:
        r["anio_anterior"] = round(previo["v"], decimales)
        r["variacion_interanual_pct"] = round((ult["v"] / previo["v"] - 1) * 100, 1)
    return r


def acumulado_anual(serie):
    """Suma enero..último mes del año en curso frente al mismo tramo del año anterior."""
    if not serie:
        return None
    a, m = serie[-1]["t"].split("-")
    act = [x["v"] for x in serie if x["t"].startswith(a + "-") and x["t"] <= f"{a}-{m}"]
    ant = [x["v"] for x in serie if x["t"].startswith(f"{int(a) - 1}-") and x["t"][5:] <= m]
    if len(act) != int(m) or len(ant) != int(m):
        return None
    return {"desde": f"{a}-01", "hasta": f"{a}-{m}", "total": round(sum(act)),
            "anio_anterior": round(sum(ant)), "variacion_pct": round((sum(act) / sum(ant) - 1) * 100, 1)}


# ---------------------------------------------------------------- gráficas
def estilo(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#d1d5db")
    ax.tick_params(colors=GRIS, labelsize=9, length=0)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: (f"{v / 1000:.0f} mil" if v >= 10000 else f"{v / 1000:.1f} mil").replace(".", ",")
        if v >= 1000 else f"{v:.0f}"))


def grafica_interanual(serie, titulo, fichero):
    """Barras: últimos 12 meses frente a los mismos meses del año anterior."""
    ult = serie[-12:]
    idx = {x["t"]: x["v"] for x in serie}
    prev = [idx.get(f'{int(x["t"][:4]) - 1}{x["t"][4:]}') for x in ult]
    etiquetas = [MESES[int(x["t"][5:]) - 1][:3] for x in ult]
    fig, ax = plt.subplots(figsize=(6.4, 2.9), dpi=150)
    xs = range(len(ult))
    ax.bar([x - 0.2 for x in xs], [p or 0 for p in prev], 0.4, color=AZUL_CLARO, label="Año anterior")
    ax.bar([x + 0.2 for x in xs], [x["v"] for x in ult], 0.4, color=AZUL, label="Últimos 12 meses")
    ax.set_xticks(list(xs), etiquetas)
    estilo(ax)
    ax.set_title(titulo, loc="left", fontsize=11, color="#111827", fontweight="bold", pad=12)
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncols=2, bbox_to_anchor=(0, 1.02), labelcolor=GRIS)
    fig.tight_layout()
    fig.savefig(SALIDA / fichero, facecolor="white")
    plt.close(fig)


def grafica_barras_h(pares, titulo, fichero):
    """Ranking horizontal (p. ej. países)."""
    pares = list(reversed(pares))
    fig, ax = plt.subplots(figsize=(6.4, 3.1), dpi=150)
    ax.barh([a for a, _ in pares], [b for _, b in pares], color=AZUL, height=0.6)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color("#d1d5db")
    ax.tick_params(colors=GRIS, labelsize=9, length=0)
    ax.xaxis.set_visible(False)
    for i, (_, b) in enumerate(pares):
        ax.text(b, i, " " + f"{b:,.0f}".replace(",", "."), va="center", fontsize=8.5, color="#374151")
    ax.set_title(titulo, loc="left", fontsize=11, color="#111827", fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(SALIDA / fichero, facecolor="white")
    plt.close(fig)


def grafica_columnas(serie, titulo, fichero):
    """Columnas simples para series cortas o semestrales."""
    fig, ax = plt.subplots(figsize=(6.4, 2.9), dpi=150)
    ax.bar(range(len(serie)), [x["v"] for x in serie], 0.55, color=AZUL)
    ax.set_xticks(range(len(serie)), [f'{MESES[int(x["t"][5:]) - 1][:3]} {x["t"][2:4]}' for x in serie])
    estilo(ax)
    ax.set_title(titulo, loc="left", fontsize=11, color="#111827", fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(SALIDA / fichero, facecolor="white")
    plt.close(fig)


def grafica_linea(serie, titulo, fichero, n=24):
    s = serie[-n:]
    fig, ax = plt.subplots(figsize=(6.4, 2.9), dpi=150)
    ax.plot(range(len(s)), [x["v"] for x in s], color=AZUL, linewidth=2.2)
    ax.fill_between(range(len(s)), [x["v"] for x in s], color=AZUL, alpha=0.08)
    ticks = list(range(0, len(s), 3))
    ax.set_xticks(ticks, [f'{MESES[int(s[i]["t"][5:]) - 1][:3]} {s[i]["t"][2:4]}' for i in ticks])
    estilo(ax)
    lo = min(x["v"] for x in s)
    ax.set_ylim(lo * 0.9, None)
    ax.set_title(titulo, loc="left", fontsize=11, color="#111827", fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(SALIDA / fichero, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- noticias
CONSULTAS = ["turismo Marbella", "hoteles Marbella", "Costa del Sol turismo", "Marbella turistas"]
DESCARTE = re.compile(r"accidente|detenid|apuñal|tiroteo|muert|fallec|incendio|robo|ladr|narco|polic[ií]a|muere|despide|luto", re.I)


def noticias(dias=8, por_consulta=12, maximo=40):
    vistas, out = set(), []
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=dias)
    for q in CONSULTAS:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{q} when:{dias}d", "hl": "es", "gl": "ES", "ceid": "ES:es"})
        try:
            xml = get(url).decode("utf-8", "replace")
        except Exception as e:
            print("noticias:", q, e, file=sys.stderr)
            continue
        n = 0
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            if n >= por_consulta:
                break
            tit = html.unescape(re.search(r"<title>(.*?)</title>", item, re.S).group(1))
            link = re.search(r"<link>(.*?)</link>", item, re.S).group(1).strip()
            fecha = email.utils.parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", item).group(1))
            fuente = re.search(r"<source[^>]*>(.*?)</source>", item, re.S)
            fuente = html.unescape(fuente.group(1)) if fuente else ""
            titular = re.sub(r"\s+-\s+[^-]+$", "", tit).strip()
            clave = re.sub(r"\W+", "", titular.lower())[:60]
            if fecha < limite or clave in vistas or DESCARTE.search(titular):
                continue
            vistas.add(clave)
            n += 1
            out.append({"titular": titular, "fuente": fuente, "fecha": fecha.strftime("%Y-%m-%d"), "enlace": link})
    out.sort(key=lambda x: x["fecha"], reverse=True)
    out = agrupar(out)[:maximo]
    for i, x in enumerate(out, 1):
        x["id"] = i
    return out


# Varios medios cuentan el mismo hecho con titulares distintos: se agrupan por palabras
# significativas compartidas y se deja una sola noticia por hecho, con el número de medios
# que lo cubren (sirve a la IA como pista de importancia).
COMUNES = set("""marbella marbelli turismo turistico turistica turisticos turisticas turistas costa malaga
andalucia andaluces espana sector destino nuevo nueva nuevos nuevas sobre entre desde hasta para tras
como este esta estos estas millones euros anos semana gran grandes primer primera lujo hotel hoteles
hotelera hotelero hoteleros alojamientos internacional internacionales ciudad ayuntamiento alcaldesa
junta diputacion gobierno""".split())


def _palabras(t):
    """(palabras significativas, nombres propios): un nombre propio compartido (St. Regis,
    DUCO, Marriott...) basta para tratarlas como el mismo hecho; si no, hacen falta dos palabras."""
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    ws = re.findall(r"[A-Za-z0-9]{4,}", t)
    todas = {w.lower() for w in ws} - COMUNES
    propios = {w.lower() for w in ws[1:] if w[0].isupper()} - COMUNES
    return todas, propios


def _mismo_hecho(p, q):
    return len(p[0] & q[0]) >= 2 or bool(p[1] & q[1])


def agrupar(lista):
    grupos = []
    for x in lista:
        p = _palabras(x["titular"])
        g = next((g for g in grupos if any(_mismo_hecho(p, q) for q in g["palabras"])), None)
        if g:
            g["items"].append(x)
            g["palabras"].append(p)
        else:
            grupos.append({"palabras": [p], "items": [x]})
    out = []
    for g in grupos:
        x = dict(g["items"][0])   # la más reciente
        x["medios"] = len({y["fuente"] for y in g["items"]})
        x["otros_titulares"] = [y["titular"] for y in g["items"][1:4]]
        out.append(x)
    return out


# Las noticias de Google News llegan con un enlace intermedio (news.google.com/rss/articles/...).
# Se traduce al del periódico con el mismo método que usa la web de Google News, y de ahí
# se saca la foto de portada (og:image). Si algo falla, la noticia se queda con el enlace
# de Google y sin foto propia (luego se le pone la foto de la semana).
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def leer(url, datos=None, cabeceras=None, limite=1_500_000):
    req = urllib.request.Request(url, data=datos, headers={**NAVEGADOR, **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limite), r.headers.get_content_charset() or "utf-8"


def enlace_real(enlace):
    if "news.google.com" not in enlace:
        return enlace
    aid = urllib.parse.urlparse(enlace).path.rstrip("/").split("/")[-1]
    pg = leer(f"https://news.google.com/rss/articles/{aid}")[0].decode("utf-8", "replace")
    sg = re.search(r'data-n-a-sg="([^"]+)"', pg).group(1)
    ts = re.search(r'data-n-a-ts="([^"]+)"', pg).group(1)
    peticion = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                                           None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                           aid, int(ts), sg])
    cuerpo = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", peticion]]])}).encode()
    txt = leer("https://news.google.com/_/DotsSplashUi/data/batchexecute", cuerpo,
               {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})[0].decode("utf-8", "replace")
    return json.loads(json.loads(txt.split("\n\n")[1])[0][2])[1]


def foto_portada(url):
    datos, cs = leer(url)
    pg = datos.decode(cs, "replace")
    for patron in (r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]*content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)'):
        m = re.search(patron, pg, re.I)
        if m:
            return urllib.parse.urljoin(url, html.unescape(m.group(1)))
    return None


def miniatura(url, destino, ancho=280, alto=187):
    """Recorta la foto a 3:2 y la guarda pequeña (280 px = 140 px en pantallas retina)."""
    from io import BytesIO
    from PIL import Image
    datos, _ = leer(url, limite=15_000_000)
    im = Image.open(BytesIO(datos)).convert("RGB")
    w, h = im.size
    if w < 200 or h < 120:
        raise ValueError(f"foto demasiado pequeña ({w}x{h})")
    if w / h > ancho / alto:
        nw = round(h * ancho / alto)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = round(w * alto / ancho)
        im = im.crop((0, (h - nh) // 3, w, (h - nh) // 3 + nh))
    im.resize((ancho, alto), Image.LANCZOS).save(destino, "JPEG", quality=82, optimize=True, progressive=True)


def fotos_noticias(lista, edicion):
    for p in SALIDA.glob(f"not-{edicion}-*.jpg"):   # al reejecutar la semana los id cambian
        p.unlink()
    con = 0
    for x in lista:
        x["imagen"] = ""
        try:
            x["enlace"] = enlace_real(x["enlace"])
            img = foto_portada(x["enlace"])
            if img:
                nombre = f"not-{edicion}-{x['id']:02d}.jpg"
                miniatura(img, SALIDA / nombre)
                x["imagen"] = f"{WEB}/boletin/{nombre}"
                con += 1
        except Exception as e:
            print("foto noticia:", x["id"], x["fuente"], repr(e)[:150], file=sys.stderr)
        time.sleep(0.5)
    print(f"Fotos de noticias: {con} de {len(lista)}")




# ---------------------------------------------------------------- foto de la semana
def elegir_foto(edicion):
    """Una foto distinta por edición: la primera del banco que no se haya usado nunca.

    El banco (docs/img/fotos/banco.json) son fotos libres de Wikimedia Commons revisadas
    a mano; las usadas quedan en docs/boletin/fotos_usadas.json. Si se reejecuta la misma
    semana se repite su foto. Si el banco se agota, se reutiliza la que lleve más tiempo
    sin salir y se avisa para ampliarlo.
    """
    banco = json.loads((RAIZ / "docs" / "img" / "fotos" / "banco.json").read_text(encoding="utf-8"))
    ruta = SALIDA / "fotos_usadas.json"
    usadas = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    ya = next((u["file"] for u in usadas if u["edicion"] == edicion), None)
    vistas = {u["file"] for u in usadas}
    if ya:
        f = next((x for x in banco if x["file"] == ya), None)
    else:
        f = next((x for x in banco if x["file"] not in vistas), None)
        if f is None:
            print("AVISO: banco de fotos agotado; se reutiliza la más antigua. Conviene ampliarlo.", file=sys.stderr)
            orden = [u["file"] for u in usadas]
            f = min(banco, key=lambda x: max((i for i, n in enumerate(orden) if n == x["file"]), default=-1))
        usadas.append({"edicion": edicion, "file": f["file"]})
        ruta.write_text(json.dumps(usadas, ensure_ascii=False, indent=1), encoding="utf-8")
    if f is None:                               # foto antigua fuera del banco: la primera del banco
        f = banco[0]
    restantes = len([x for x in banco if x["file"] not in {u["file"] for u in usadas}])
    print(f"Foto {f['file']} · quedan {restantes} sin usar en el banco")
    return {"url": f'{WEB}/img/fotos/{f["file"]}',
            "credito": f'Foto: {f["autor"] or "Wikimedia Commons"} · {f["licencia"]} · Wikimedia Commons',
            "enlace": f["url"]}


# ---------------------------------------------------------------- plantilla
def num(v, dec=0):
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def kpi(etiqueta, valor, var, sufijo_var=" %", invertir=False):
    """Tarjeta KPI. `invertir` = bajar es bueno (paro)."""
    if var is None:
        flecha = ""
    else:
        bueno = (var < 0) if invertir else (var >= 0)
        color = "#047857" if bueno else "#b91c1c"
        signo = "+" if var > 0 else ""
        flecha = f'<div style="font-size:13px;font-weight:600;color:{color};margin-top:2px">{signo}{num(var, 1)}{sufijo_var}</div>'
    return (f'<td class="kpi" width="25%" valign="top" style="padding:6px">'
            f'<div style="background:#f3f7fb;border-radius:10px;padding:14px 12px">'
            f'<div style="font-size:11px;line-height:15px;color:#6b7280;min-height:30px">{etiqueta}</div>'
            f'<div style="font-family:Montserrat,Arial,sans-serif;font-size:21px;font-weight:700;color:#0f172a;margin-top:4px">{valor}</div>'
            f'{flecha}</div></td>')


def mes_corto(r):
    return r["mes"].split(" ")[0]


def tarjetas_tema(tema, d):
    t, e = d["turismo_marbella"], d["economia_marbella"]
    out = []

    def tarjeta(k, etiqueta, dec=0, suf="", inv=False, src=t):
        x = src.get(k)
        if x:
            var = x.get("variacion_puntos", x.get("variacion_interanual_pct"))
            out.append(kpi(f"{etiqueta} ({mes_corto(x)})", num(x["valor"], dec) + suf, var,
                           " p.p." if "variacion_puntos" in x else " %", inv))

    if tema == "hoteles":
        tarjeta("pernoct_hotel", "Pernoctaciones hoteleras")
        tarjeta("ocupacion_plazas", "Ocupación por plazas", 1, " %")
        tarjeta("adr", "Tarifa media (ADR)", 0, " €")
        tarjeta("revpar", "RevPAR", 0, " €")
    elif tema == "extrahotelero":
        tarjeta("pernoct_apart", "Pernoct. en apartamentos")
        tarjeta("ocup_apart", "Ocupación de apartamentos", 1, " %")
        tarjeta("vut_viviendas", "Viviendas turísticas")
        tarjeta("vut_plazas", "Plazas en viviendas turísticas")
    elif tema == "mercados":
        tarjeta("viajeros_ext", "Viajeros extranjeros")
        tarjeta("viajeros_esp", "Viajeros nacionales")
        tarjeta("cuota_extranjeros", "Cuota de extranjeros", 1, " %")
        p = d.get("mercados_internacionales")
        if p:
            a = p["top_pernoctaciones_hotel"][0]
            out.append(kpi(f'Primer mercado ({p["mes"].split(" ")[0]})', a["pais"], None))
    else:
        tarjeta("paro_registrado", "Paro registrado", inv=True, src=e)
        tarjeta("afiliados_seguridad_social", "Afiliados S. Social", src=e)
        tarjeta("contratos", "Contratos firmados", src=e)
        x = e.get("contratos")
        if x and "pct_indefinidos" in x:
            out.append(kpi(f'Contratos indefinidos ({mes_corto(x)})', num(x["pct_indefinidos"], 1) + " %", None))
    return "".join(out)


def tabla_paises(p):
    filas = "".join(
        f'<tr><td style="padding:7px 0;border-bottom:1px solid #eef0f3;font-size:14px">{i + 1}. {x["pais"]}</td>'
        f'<td align="right" style="padding:7px 0;border-bottom:1px solid #eef0f3;font-size:14px;font-weight:600">{num(x["pernoctaciones"])}</td></tr>'
        for i, x in enumerate(p["top_pernoctaciones_hotel"]))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 4px">'
            f'<tr><td style="font-size:11px;color:#9ca3af;padding-bottom:4px">Pernoctaciones hoteleras por país · {p["mes"]}</td>'
            f'<td align="right" style="font-size:11px;color:#9ca3af">Fuente: Turismo Costa del Sol</td></tr>{filas}</table>')


def render_plantilla(d):
    tema = d["tema"]["id"]
    p = d.get("mercados_internacionales")
    img = '<img src="{}" width="536" alt="{}" style="display:block;width:100%;height:auto;border:0;margin:6px 0 16px">'
    rep = {
        "[[EDICION]]": d["edicion_texto"],
        "[[FOTO_URL]]": d["foto"]["url"],
        "[[FOTO_ENLACE]]": d["foto"]["enlace"],
        "[[FOTO_CREDITO]]": html.escape(d["foto"]["credito"]),
        "[[KPIS]]": tarjetas_tema(tema, d),
        "[[TEMA_ETIQUETA]]": d["tema"]["etiqueta"],
        "[[GRAFICAS]]": "".join(img.format(x["url"], html.escape(x["titulo"])) for x in d["graficas"]),
        # La tabla solo si no hay gráfica de países (no repetir el ranking)
        "[[TABLA_PAISES]]": tabla_paises(p) if (tema == "mercados" and p and
                                                not any(x["clave"] == "paises" for x in d["graficas"])) else "",
        "[[FUENTES]]": d["fuentes"],
        "[[WEB]]": d["enlaces"]["web"],
    }
    s = (RAIZ / "plantilla" / "boletin.html").read_text(encoding="utf-8")
    for k, v in rep.items():
        s = s.replace(k, v)
    return s


# ---------------------------------------------------------------- main
def novedades(previo, actual):
    """Indicadores cuyo último periodo ha cambiado desde la edición anterior."""
    out = []
    for bloque in ("turismo_marbella", "economia_marbella"):
        for k, x in actual.get(bloque, {}).items():
            if not isinstance(x, dict) or "periodo" not in x:
                continue
            antes = (previo.get(bloque) or {}).get(k) or {}
            if antes.get("periodo") and antes["periodo"] != x["periodo"]:
                out.append(f'{x.get("indicador", k)} ({x["mes"]})')
    p, q = actual.get("mercados_internacionales"), previo.get("mercados_internacionales")
    if p and q and p["periodo"] != q["periodo"]:
        out.append(f'mercados por país ({p["mes"]})')
    return out


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    # BOLETIN_FECHA=AAAA-MM-DD permite simular otra semana (pruebas)
    hoy = dt.date.fromisoformat(os.environ["BOLETIN_FECHA"]) if os.environ.get("BOLETIN_FECHA") else dt.date.today()
    lunes = hoy - dt.timedelta(days=hoy.weekday())
    anio, semana, _ = lunes.isocalendar()
    edicion = f"{anio}-S{semana:02d}"
    martes = lunes + dt.timedelta(days=1)
    tema = TEMAS[semana % len(TEMAS)]
    previo = {}
    if (SALIDA / "datos.json").exists():
        previo = json.loads((SALIDA / "datos.json").read_text(encoding="utf-8"))
        if previo.get("edicion") == edicion:          # reejecución de la misma semana
            previo = previo.get("_previo") or {}

    series = {k: serie_ine(cod) for k, (cod, _) in SERIES.items()}

    turismo = {}
    for k, (cod, desc) in SERIES.items():
        r = resumen(series[k], 2 if k in TASAS + ("estancia_media", "adr", "revpar") else 0)
        if r:
            if k in TASAS and "anio_anterior" in r:
                # Una tasa se compara en puntos, no en % de variación
                r["variacion_puntos"] = round(r["valor"] - r["anio_anterior"], 1)
                del r["variacion_interanual_pct"]
            r["indicador"] = desc
            r["serie_ine"] = cod
            turismo[k] = r
    # Cuota de viajeros extranjeros en hoteles (serie propia, para la gráfica de mercados)
    esp = {x["t"]: x["v"] for x in series["viajeros_esp"]}
    cuota = [{"t": x["t"], "v": round(x["v"] / (x["v"] + esp[x["t"]]) * 100, 1)}
             for x in series["viajeros_ext"] if esp.get(x["t"])]
    c = resumen(cuota, 1)
    if c:
        if "anio_anterior" in c:
            c["variacion_puntos"] = round(c["valor"] - c["anio_anterior"], 1)
            del c["variacion_interanual_pct"]
        c["indicador"] = "Cuota de viajeros extranjeros en hoteles (%)"
        turismo["cuota_extranjeros"] = c

    acumulados = {k: acumulado_anual(series[k]) for k in ("viajeros_hotel", "pernoct_hotel")}

    # Países (Turismo Costa del Sol Big Data, en el observatorio turístico)
    paises = None
    try:
        p = json.loads(get("https://josehino.github.io/observatorio-turistico-marbella/data/paises_marbella.json"))
        mes = p["meses"][-1]
        i = len(p["meses"]) - 1
        pern = p["datos"]["Hoteles"]["Pernoctaciones"]
        top = sorted(((pais, v[i]) for pais, v in pern.items()
                      if v[i] and pais not in ("España", "Extranjero", "Total") and not pais.startswith("Resto")),
                     key=lambda x: -x[1])[:8]
        paises = {"periodo": mes, "mes": nombre_mes(mes), "fuente": p["meta"]["fuente"],
                  "top_pernoctaciones_hotel": [{"pais": a, "pernoctaciones": round(b)} for a, b in top]}
    except Exception as e:
        print("paises:", e, file=sys.stderr)

    # Observatorio económico
    economia, paro_s, afi_s = {}, [], []
    try:
        paro = json.loads(get(f"{ECO}/paro_mensual.json"))["serie"]
        paro_s = [{"t": x["t"], "v": x["total"]} for x in paro]
        economia["paro_registrado"] = dict(resumen(paro_s), indicador="Paro registrado")
        afi_s = json.loads(get(f"{ECO}/afiliacion.json"))["marbella"]["total"]
        economia["afiliados_seguridad_social"] = dict(resumen(afi_s), indicador="Afiliados a la Seguridad Social")
        con = json.loads(get(f"{ECO}/contratos_mensual.json"))["serie"]
        economia["contratos"] = dict(resumen([{"t": x["t"], "v": x["total"]} for x in con]), indicador="Contratos")
        u = con[-1]
        economia["contratos"]["pct_indefinidos"] = round(u["indefinidos"] / u["total"] * 100, 1)
    except Exception as e:
        print("economia:", e, file=sys.stderr)

    # Gráficas del tema (nombre con la edición para que el correo no muestre otra versión en caché)
    planes = {
        "hoteles": [("pernoct_hotel", "Pernoctaciones hoteleras en Marbella", grafica_interanual, series["pernoct_hotel"]),
                    ("adr", "Tarifa media diaria de los hoteles (€)", grafica_linea, series["adr"])],
        "extrahotelero": [("pernoct_apart", "Pernoctaciones en apartamentos turísticos", grafica_interanual, series["pernoct_apart"]),
                          ("vut_viviendas", "Viviendas de uso turístico registradas", grafica_columnas, series["vut_viviendas"][-8:])],
        "mercados": [("cuota_ext", "Peso de los viajeros extranjeros en hoteles (%)", grafica_linea, cuota)],
        "empleo": [("paro", "Paro registrado en Marbella", grafica_linea, paro_s),
                   ("afiliacion", "Afiliados a la Seguridad Social (residentes)", grafica_linea, afi_s)],
    }[tema["id"]]
    graficas = []
    if tema["id"] == "mercados" and paises:
        nombre = f"graf-{edicion}-paises.png"
        grafica_barras_h([(x["pais"], x["pernoctaciones"]) for x in paises["top_pernoctaciones_hotel"]],
                         f'Pernoctaciones hoteleras por país · {paises["mes"]}', nombre)
        graficas.append({"clave": "paises", "url": f"{WEB}/boletin/{nombre}", "titulo": "Pernoctaciones por país"})
    for clave, titulo, fn, serie in planes:
        if not serie:
            continue
        nombre = f"graf-{edicion}-{clave}.png"
        fn(serie, titulo, nombre)
        graficas.append({"clave": clave, "url": f"{WEB}/boletin/{nombre}", "titulo": titulo})

    foto = elegir_foto(edicion)
    candidatas = noticias()
    fotos_noticias(candidatas, edicion)
    for x in candidatas:
        x["imagen"] = x["imagen"] or foto["url"]

    datos = {
        "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "edicion": edicion,
        "edicion_texto": f"Semana del {lunes.day} de {MESES[lunes.month - 1]} de {lunes.year}",
        "envio": hora_madrid(martes, 13, 30),
        "envio_texto": f"martes {martes.day} de {MESES[martes.month - 1]} a las 13:30",
        "tema": tema,
        "novedades": [],
        "turismo_marbella": turismo,
        "acumulado_anual": acumulados,
        "mercados_internacionales": paises,
        "economia_marbella": economia,
        "noticias_candidatas": candidatas,
        "graficas": graficas,
        "foto": foto,
        "enlaces": {
            "observatorio_turistico": "https://josehino.github.io/observatorio-turistico-marbella/",
            "observatorio_economico": "https://josehino.github.io/observatorio-economico-marbella/",
            "web": WEB + "/",
            "baja": WEB + "/baja.html",
        },
        "fuentes": "INE (Encuesta de Ocupación Hotelera, Apartamentos Turísticos y Viviendas Turísticas), "
                   "Turismo Costa del Sol Big Data, SEPE, Seguridad Social (IECA).",
    }
    datos["novedades"] = novedades(previo, datos)
    # Lo mínimo de la edición anterior, para poder reejecutar la misma semana sin perder las novedades
    datos["_previo"] = {k: previo.get(k) for k in ("turismo_marbella", "economia_marbella", "mercados_internacionales")}
    (SALIDA / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    (SALIDA / "plantilla.html").write_text(render_plantilla(datos), encoding="utf-8")

    # Borrar gráficas de ediciones antiguas (se conservan las 6 últimas)
    eds = sorted({m.group(1) for p in SALIDA.glob("graf-*.png")
                  if (m := re.match(r"graf-(\d{4}-(?:S\d\d|\d\d))-", p.name))})
    for viejo in eds[:-6]:
        for p in SALIDA.glob(f"graf-{viejo}-*.png"):
            p.unlink()
    # Y lo mismo con las fotos de las noticias
    eds = sorted({m.group(1) for p in SALIDA.glob("not-*.jpg")
                  if (m := re.match(r"not-(\d{4}-S\d\d)-", p.name))})
    for viejo in eds[:-6]:
        for p in SALIDA.glob(f"not-{viejo}-*.jpg"):
            p.unlink()
    print(f"Edición {edicion} · tema {tema['id']} · {len(datos['noticias_candidatas'])} noticias · novedades: {datos['novedades']}")


if __name__ == "__main__":
    main()
