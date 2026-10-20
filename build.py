"""Prepara el material del boletín mensual de turismo de Marbella.

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
import re
import sys
import time
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
    "vut_viviendas":    ("VTE3889",  "Viviendas de uso turístico"),
}

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
        lambda v, _: f"{v / 1000:.0f} mil".replace(".", ",") if v >= 1000 else f"{v:.0f}"))


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


def noticias(dias=35, por_consulta=12, maximo=40):
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
    return out[:maximo]


# ---------------------------------------------------------------- plantilla
def num(v, dec=0):
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def kpi(etiqueta, valor, var, sufijo_var="%", invertir=False):
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


def render_plantilla(d):
    t, e = d["turismo_marbella"], d["economia_marbella"]
    tarjetas = []
    if "pernoct_hotel" in t:
        x = t["pernoct_hotel"]
        tarjetas.append(kpi("Pernoctaciones hoteleras", num(x["valor"]), x.get("variacion_interanual_pct")))
    if "ocupacion_plazas" in t:
        x = t["ocupacion_plazas"]
        dif = round(x["valor"] - x["anio_anterior"], 1) if "anio_anterior" in x else None
        tarjetas.append(kpi("Ocupación hotelera (plazas)", num(x["valor"], 1) + " %", dif, " p.p."))
    if "adr" in t:
        x = t["adr"]
        tarjetas.append(kpi("Tarifa media diaria (ADR)", num(x["valor"]) + " €", x.get("variacion_interanual_pct")))
    if e.get("paro_registrado"):
        x = e["paro_registrado"]
        tarjetas.append(kpi(f'Paro registrado ({x["mes"].split(" ")[0]})', num(x["valor"]),
                            x.get("variacion_interanual_pct"), invertir=True))

    tabla = ""
    p = d.get("mercados_internacionales")
    if p:
        filas = "".join(
            f'<tr><td style="padding:7px 0;border-bottom:1px solid #eef0f3;font-size:14px">{i + 1}. {x["pais"]}</td>'
            f'<td align="right" style="padding:7px 0;border-bottom:1px solid #eef0f3;font-size:14px;font-weight:600">{num(x["pernoctaciones"])}</td></tr>'
            for i, x in enumerate(p["top_pernoctaciones_hotel"]))
        tabla = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:10px 0 4px">'
                 f'<tr><td style="font-size:11px;color:#9ca3af;padding-bottom:4px">Pernoctaciones hoteleras por país · {p["mes"]}</td>'
                 f'<td align="right" style="font-size:11px;color:#9ca3af">Fuente: Turismo Costa del Sol</td></tr>{filas}</table>')

    g = {x["clave"]: x["url"] for x in d["graficas"]}
    rep = {
        "[[EDICION]]": d["edicion_texto"].capitalize(),
        "[[FOTO_URL]]": d["foto"]["url"],
        "[[FOTO_ENLACE]]": d["foto"]["enlace"],
        "[[FOTO_CREDITO]]": html.escape(d["foto"]["credito"]),
        "[[KPIS]]": "".join(tarjetas),
        "[[GRAF1]]": g.get("pernoct_hotel", ""),
        "[[GRAF2]]": g.get("adr", ""),
        "[[TABLA_PAISES]]": tabla,
        "[[FUENTES]]": d["fuentes"],
        "[[WEB]]": d["enlaces"]["web"],
    }
    s = (RAIZ / "plantilla" / "boletin.html").read_text(encoding="utf-8")
    for k, v in rep.items():
        s = s.replace(k, v)
    return s


# ---------------------------------------------------------------- main
def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    series = {k: serie_ine(cod) for k, (cod, _) in SERIES.items()}
    ref = series["pernoct_hotel"][-1]["t"]          # mes de referencia del boletín

    turismo = {}
    for k, (cod, desc) in SERIES.items():
        r = resumen(series[k], 2 if k in ("ocupacion_plazas", "estancia_media", "adr", "revpar") else 0)
        if r:
            r["indicador"] = desc
            r["serie_ine"] = cod
            turismo[k] = r
    ext, esp = turismo.get("viajeros_ext"), turismo.get("viajeros_esp")
    if ext and esp:
        turismo["cuota_extranjeros_pct"] = round(ext["valor"] / (ext["valor"] + esp["valor"]) * 100, 1)

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
                     key=lambda x: -x[1])[:6]
        paises = {"periodo": mes, "mes": nombre_mes(mes), "fuente": p["meta"]["fuente"],
                  "top_pernoctaciones_hotel": [{"pais": a, "pernoctaciones": round(b)} for a, b in top]}
    except Exception as e:
        print("paises:", e, file=sys.stderr)

    # Observatorio económico
    economia = {}
    try:
        paro = json.loads(get(f"{ECO}/paro_mensual.json"))["serie"]
        economia["paro_registrado"] = resumen([{"t": x["t"], "v": x["total"]} for x in paro])
        afi = json.loads(get(f"{ECO}/afiliacion.json"))["marbella"]["total"]
        economia["afiliados_seguridad_social"] = resumen(afi)
        con = json.loads(get(f"{ECO}/contratos_mensual.json"))["serie"]
        economia["contratos"] = resumen([{"t": x["t"], "v": x["total"]} for x in con])
        u = con[-1]
        economia["contratos"]["pct_indefinidos"] = round(u["indefinidos"] / u["total"] * 100, 1)
    except Exception as e:
        print("economia:", e, file=sys.stderr)

    # Gráficas (nombre con el periodo para que el correo no muestre otra versión en caché)
    graficas = []
    for clave, titulo, fn in (
        ("pernoct_hotel", "Pernoctaciones hoteleras en Marbella", grafica_interanual),
        ("adr", "Tarifa media diaria de los hoteles (€)", grafica_linea),
    ):
        nombre = f"graf-{ref}-{clave}.png"
        fn(series[clave], titulo, nombre)
        graficas.append({"clave": clave, "url": f"{WEB}/boletin/{nombre}", "titulo": titulo})

    # Foto del mes: rota sobre las fotos libres
    fotos = json.loads((RAIZ / "docs" / "img" / "fotos" / "creditos.json").read_text(encoding="utf-8"))
    a, m = map(int, ref.split("-"))
    foto = fotos[(a * 12 + m) % len(fotos)]
    foto = {"url": f'{WEB}/img/fotos/{foto["file"]}',
            "credito": f'Foto: {foto["autor"]} · {foto["licencia"]} · Wikimedia Commons', "enlace": foto["url"]}

    datos = {
        "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "edicion": ref,
        "edicion_texto": nombre_mes(ref),
        "turismo_marbella": turismo,
        "acumulado_anual": acumulados,
        "mercados_internacionales": paises,
        "economia_marbella": economia,
        "noticias_candidatas": noticias(),
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
    (SALIDA / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    (SALIDA / "plantilla.html").write_text(render_plantilla(datos), encoding="utf-8")

    # Borrar gráficas de ediciones antiguas (se conservan las 3 últimas)
    eds = sorted({p.name[5:12] for p in SALIDA.glob("graf-*.png")})
    for viejo in eds[:-3]:
        for p in SALIDA.glob(f"graf-{viejo}-*.png"):
            p.unlink()
    print(f"Edición {ref}: {len(datos['noticias_candidatas'])} noticias candidatas")


if __name__ == "__main__":
    main()
