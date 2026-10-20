"""Genera el blueprint del escenario de Make "Boletín · Edición".

Uso: CLAVE=... python make/edicion.py > make/edicion.json
Rutas del webhook:
  - generar (GitHub Actions) / cambios (revisor): GPT redacta -> borrador al revisor
  - aprobar (revisor): envía la edición a los suscriptores activos
"""
import json
import os
import re
from pathlib import Path

HOOK = 3938650
STORE = 225550
SMTP = 12133954
OPENAI = 12135169
MODELO = "gpt-4o"
REVISOR = "josemariahf612@gmail.com"
SUSC_HOOK = "https://hook.eu1.make.com/4ckbk32a0fxkobuky054q5xljtiwwjn7"
WEB = "https://ammaconsulting.github.io/newsletter-turismo-marbella"
RAW = "https://raw.githubusercontent.com/AMMAConsulting/newsletter-turismo-marbella/main/docs/boletin"
CLAVE = os.environ["CLAVE"]
REMITENTE = "Marbella en Datos <proyectos1@ammaconsulting.com>"

texto = (Path(__file__).parent / "prompt-redaccion.md").read_text(encoding="utf-8")
SISTEMA = texto.split("# Prompt del sistema (módulo OpenAI del escenario \"Boletín\")")[1].split("# Prompt para la revisión")[0].strip()
REVISION = texto.split("# Prompt para la revisión (cuando el revisor pide cambios)")[1].strip()


def clave_ok():
    return {"a": "{{1.clave}}", "o": "text:equal", "b": CLAVE}


def responder(i, m, status=302):
    return {"id": i, "module": "gateway:WebhookRespond", "version": 1, "mapper": {
        "status": status, "body": "" if status == 302 else "ok",
        "headers": [{"key": "Location", "value": f"{WEB}/gracias.html?m={m}"}]}}


def http_get(i, url):
    return {"id": i, "module": "http:ActionSendData", "version": 3,
            "parameters": {"handleErrors": True},
            "mapper": {"url": url, "method": "get", "parseResponse": False, "serializeUrl": False,
                       "shareCookies": False, "rejectUnauthorized": True, "followRedirect": True,
                       "followAllRedirects": False, "useQuerystring": False, "gzip": True, "useMtls": False}}


# --- composición del HTML: un replace() anidado por marcador
CAMPOS = {
    "ASUNTO": "7.asunto", "TITULAR": "7.titular", "ENTRADILLA": "7.entradilla",
    "ENTRADILLA_CORTA": "7.entradilla_corta", "TITULO_TEMA": "7.titulo_tema",
    "TEXTO_TEMA": "7.texto_tema", "TEXTO_RESUMEN": "7.texto_resumen",
}
for n in (1, 2, 3):
    CAMPOS[f"N{n}_TITULAR"] = f'get(7.noticias; "{n}.titular")'
    CAMPOS[f"N{n}_RESUMEN"] = f'get(7.noticias; "{n}.resumen")'
    CAMPOS[f"N{n}_FUENTE"] = f'get(7.noticias; "{n}.fuente")'
    CAMPOS[f"N{n}_ENLACE"] = f'first(map(9.noticias_candidatas; "enlace"; "id"; get(7.noticias; "{n}.id")))'

expr = "toString(5.data)"
for marca, valor in CAMPOS.items():
    expr = f'replace({expr}; "%%{marca}%%"; {valor})'
HTML = "{{" + expr + "}}"

AVISO = (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff7e6;border-bottom:2px solid #f59e0b">'
    '<tr><td align="center" style="padding:16px 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#78350f">'
    '<strong>BORRADOR PARA REVISIÓN</strong> · Edición @@ED@@ · Todavía no se ha enviado a nadie.<br>'
    'Si lo apruebas antes del martes a las 13:30 saldrá a esa hora; si lo apruebas después, saldrá en el momento.<br>'
    f'<a href="{WEB}/revision.html?ed=@@ED@@&k={CLAVE}" '
    'style="display:inline-block;margin-top:10px;background:#0b5cad;color:#ffffff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:bold">'
    'Aprobar o pedir cambios</a></td></tr></table>'
)

redactar = [
    {"id": 3, "module": "datastore:GetRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "mapper": {"key": "borrador", "returnWrapped": False},
     "filter": {"name": "Generar o cambios (con clave)", "conditions": [
         [clave_ok(), {"a": "{{1.accion}}", "o": "text:equal", "b": "generar"}],
         [clave_ok(), {"a": "{{1.accion}}", "o": "text:equal", "b": "cambios"}]]}},
    # Se responde ya: GPT tarda y el revisor no tiene que esperar
    {"id": 13, "module": "gateway:WebhookRespond", "version": 1, "mapper": {
        "status": "{{if(1.accion = \"cambios\"; 302; 200)}}", "body": "ok",
        "headers": [{"key": "Location", "value": f"{WEB}/gracias.html?m=cambios"}]}},
    http_get(4, f"{RAW}/datos.json"),
    http_get(5, f"{RAW}/plantilla.html"),
    {"id": 6, "module": "openai-gpt-3:CreateCompletion", "version": 1,
     "parameters": {"__IMTCONN__": OPENAI},
     "mapper": {"select": "chat", "model": MODELO, "max_tokens": 4000, "temperature": 0.7,
                "response_format": "json_object", "parseJSONResponse": False,
                "messages": [
                    {"role": "system", "content": SISTEMA},
                    {"role": "user", "content": "DATOS DE LA SEMANA (JSON):\n{{toString(4.data)}}"},
                    {"role": "user", "content":
                        "{{if(1.accion = \"cambios\"; \"MODO REVISIÓN. " + REVISION.replace('"', "'") +
                        "\"; \"MODO NUEVA EDICIÓN: redacta desde cero con los datos de esta semana. El borrador anterior que aparece abajo es el de la semana pasada: no repitas su titular, su asunto ni su enfoque.\")}}"
                        "\n\nBORRADOR ANTERIOR (JSON):\n{{3.contenido}}"
                        "\n\nCAMBIOS QUE PIDE EL REVISOR:\n{{1.texto}}"},
                ]}},
    {"id": 7, "module": "json:ParseJSON", "version": 1, "parameters": {}, "mapper": {"json": "{{6.result}}"}},
    {"id": 9, "module": "json:ParseJSON", "version": 1, "parameters": {}, "mapper": {"json": "{{toString(4.data)}}"}},
    {"id": 8, "module": "util:SetVariable2", "version": 1, "parameters": {},
     "mapper": {"name": "html", "value": HTML}},
    {"id": 10, "module": "datastore:AddRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "mapper": {"key": "borrador", "overwrite": True, "data": {
         "tipo": "borrador", "estado": "borrador", "edicion": "{{1.edicion}}",
         "asunto": "{{7.asunto}}", "contenido": "{{6.result}}", "html": "{{8.html}}", "fecha": "{{now}}",
         "envio": "{{ifempty(1.envio; 3.envio)}}"}}},
    {"id": 11, "module": "email:ActionSendEmail", "version": 7,
     "parameters": {"account": SMTP, "saveAfterSent": False},
     "mapper": {"to": [REVISOR], "from": REMITENTE,
                "subject": "[Revisión] {{7.asunto}}", "contentType": "html",
                "html": '{{replace(replace(replace(8.html; "%%AVISO_REVISION%%"; "' + AVISO.replace('"', "'") + '"); "@@ED@@"; 1.edicion); "%%BAJA%%"; "#")}}'}},
]

baja_url = f'{WEB}/baja.html?e=@@E@@&t=@@T@@'
# La búsqueda del data store solo garantiza la clave (= email); el token se recalcula
TOKEN24 = f'md5(replace("{CLAVE}:EMAIL"; "EMAIL"; lower(trim(24.key))))'

def cond(a, o, b=None):
    c = {"a": a, "o": o}
    if b is not None:
        c["b"] = b
    return c


BORRADOR_OK = [cond("{{20.estado}}", "text:equal", "borrador"), cond("{{20.edicion}}", "text:equal", "{{1.edicion}}")]
ES_APROBAR = cond("{{1.accion}}", "text:equal", "aprobar")

enviar = [
    {"id": 22, "module": "datastore:UpdateRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "filter": {"name": "Enviar ahora", "conditions": [
         # aprobado después de la hora de envío...
         [ES_APROBAR, *BORRADOR_OK, cond("{{now}}", "date:greaterorequal", "{{20.envio}}")],
         # ...o llega la hora (GitHub, martes 13:30) y ya estaba aprobado
         [cond("{{1.accion}}", "text:equal", "enviar"), cond("{{20.estado}}", "text:equal", "aprobado"),
          cond("{{20.edicion}}", "text:equal", "{{1.edicion}}")]]},
     "mapper": {"key": "borrador", "data": {"estado": "enviado", "fecha": "{{now}}"},
                "upsert": False, "overwriteArrays": False}},
    responder(23, "aprobado"),
    {"id": 24, "module": "datastore:SearchRecord", "version": 1,
     "parameters": {"datastore": STORE, "continueWhenNoRes": False, "limit": 900},
     "mapper": {"filter": [[
         {"a": "tipo", "o": "text:equal", "b": "suscriptor"},
         {"a": "estado", "o": "text:equal", "b": "activo"}]]}},
    {"id": 25, "module": "email:ActionSendEmail", "version": 7,
     "parameters": {"account": SMTP, "saveAfterSent": False},
     "mapper": {"to": ["{{24.key}}"], "from": REMITENTE, "subject": "{{20.asunto}}",
                "contentType": "html",
                "html": '{{replace(replace(replace(replace(20.html; "%%AVISO_REVISION%%"; ""); "%%BAJA%%"; "' + baja_url + '"); "@@E@@"; encodeURL(24.key)); "@@T@@"; ' + TOKEN24 + ')}}'}},
]

aprobar = [
    {"id": 20, "module": "datastore:GetRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "mapper": {"key": "borrador", "returnWrapped": False},
     "filter": {"name": "Aprobar o enviar (con clave)", "conditions": [
         [clave_ok(), ES_APROBAR],
         [clave_ok(), cond("{{1.accion}}", "text:equal", "enviar")]]}},
    {"id": 21, "module": "builtin:BasicRouter", "version": 1, "routes": [
        {"flow": [
            {"id": 27, "module": "datastore:UpdateRecord", "version": 1,
             "parameters": {"datastore": STORE},
             "filter": {"name": "Aprobado antes de la hora: se programa", "conditions": [
                 [ES_APROBAR, *BORRADOR_OK, cond("{{now}}", "date:less", "{{20.envio}}")]]},
             "mapper": {"key": "borrador", "data": {"estado": "aprobado"},
                        "upsert": False, "overwriteArrays": False}},
            responder(28, "programado"),
        ]},
        {"flow": enviar},
        {"flow": [dict(responder(26, "caducado"), filter={"name": "Ya aprobado/enviado o edición distinta", "conditions": [
            [ES_APROBAR, cond("{{20.estado}}", "text:notequal", "borrador")],
            [ES_APROBAR, cond("{{20.edicion}}", "text:notequal", "{{1.edicion}}")]]})]},
    ]},
]

blueprint = {
    "name": "Boletín · Edición",
    "metadata": {"version": 1},
    "flow": [
        {"id": 1, "module": "gateway:CustomWebHook", "version": 1,
         "parameters": {"hook": HOOK, "maxResults": 1}, "mapper": {}},
        {"id": 2, "module": "builtin:BasicRouter", "version": 1,
         "routes": [{"flow": redactar}, {"flow": aprobar}]},
    ],
}
s = json.dumps(blueprint, ensure_ascii=False)
assert "{{{" not in s.replace("{{{{", ""), "llaves triples"
print(s)
