"""Genera el blueprint del escenario de Make "Boletín · Suscripciones".

Uso: python make/suscripciones.py > make/suscripciones.json
La sal del token se lee de la variable de entorno CLAVE (no se guarda en el repo).
"""
import json
import os

HOOK = 3938649
STORE = 225550
SMTP = 12133954
HOOK_URL = "https://hook.eu1.make.com/4ckbk32a0fxkobuky054q5xljtiwwjn7"
WEB = "https://ammaconsulting.github.io/newsletter-turismo-marbella"
SAL = os.environ["CLAVE"]
REMITENTE = "Marbella en Datos <proyectos1@ammaconsulting.com>"


def token(campo):
    return f'md5(replace("{SAL}:EMAIL"; "EMAIL"; lower(trim({campo}))))'


def responder(i, m):
    return {"id": i, "module": "gateway:WebhookRespond", "version": 1, "mapper": {
        "status": 302, "body": "",
        "headers": [{"key": "Location", "value": f"{WEB}/gracias.html?m={m}"}]}}


def filtro(nombre, *conds):
    return {"name": nombre, "conditions": [list(conds)]}


IGNORAR = [{"id": 90, "module": "builtin:Ignore", "version": 1}]

correo_confirmacion = (
    '<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1f2937;line-height:1.6">'
    '<p style="font-weight:700;color:#0b5cad;letter-spacing:.5px;margin:0 0 18px">MARBELLA EN DATOS</p>'
    '<h2 style="color:#0f172a;margin:0 0 12px">Confirma tu suscripción</h2>'
    '<p>Hola {{1.nombre}}:</p>'
    '<p>Gracias por apuntarte al boletín mensual de turismo de Marbella. Para empezar a recibirlo, confirma tu dirección:</p>'
    f'<p style="margin:24px 0"><a href="{HOOK_URL}?accion=confirmar&e={{{{encodeURL(lower(trim(1.email)))}}}}&t={{{{{token("1.email")}}}}}" '
    'style="display:inline-block;background:#0b5cad;color:#ffffff;padding:13px 24px;border-radius:8px;text-decoration:none;font-weight:600">Confirmar suscripción</a></p>'
    '<p style="font-size:13px;color:#6b7280">Si no te has suscrito tú, ignora este correo: no recibirás nada.</p>'
    '<p style="font-size:12px;color:#9ca3af;margin-top:28px">Marbella en Datos · AMMA Consulting</p></div>'
)

alta = [
    {"id": 3, "module": "datastore:GetRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "mapper": {"key": "{{lower(trim(1.email))}}", "returnWrapped": False},
     "filter": filtro("Alta válida",
                      {"a": "{{1.accion}}", "o": "text:equal", "b": "alta"},
                      {"a": "{{1.web}}", "o": "notexist"},
                      {"a": "{{1.acepto}}", "o": "text:equal", "b": "si"},
                      {"a": "{{1.email}}", "o": "text:contain", "b": "@"})},
    {"id": 4, "module": "builtin:BasicRouter", "version": 1, "routes": [
        {"flow": [dict(responder(5, "yaactiva"),
                       filter=filtro("Ya activo", {"a": "{{3.estado}}", "o": "text:equal", "b": "activo"}))]},
        {"flow": [
            {"id": 6, "module": "datastore:AddRecord", "version": 1,
             "parameters": {"datastore": STORE},
             "filter": filtro("No activo", {"a": "{{3.estado}}", "o": "text:notequal", "b": "activo"}),
             "mapper": {"key": "{{lower(trim(1.email))}}", "overwrite": True, "data": {
                 "tipo": "suscriptor", "email": "{{lower(trim(1.email))}}",
                 "nombre": "{{trim(1.nombre)}}", "entidad": "{{trim(1.entidad)}}",
                 "estado": "pendiente", "token": "{{" + token("1.email") + "}}", "fecha": "{{now}}"}}},
            {"id": 7, "module": "email:ActionSendEmail", "version": 7,
             "parameters": {"account": SMTP, "saveAfterSent": False},
             "mapper": {"to": ["{{lower(trim(1.email))}}"], "from": REMITENTE,
                        "subject": "Confirma tu suscripción a Marbella en Datos",
                        "contentType": "html", "html": correo_confirmacion}},
            responder(8, "alta"),
        ]},
    ]},
]

confirmar = [
    {"id": 10, "module": "builtin:BasicRouter", "version": 1,
     "filter": filtro("Confirmar", {"a": "{{1.accion}}", "o": "text:equal", "b": "confirmar"}),
     "routes": [
         {"flow": [
             {"id": 11, "module": "datastore:UpdateRecord", "version": 1,
              "parameters": {"datastore": STORE},
              "filter": filtro("Token correcto", {"a": "{{1.t}}", "o": "text:equal", "b": "{{" + token("1.e") + "}}"}),
              "mapper": {"key": "{{lower(trim(1.e))}}", "data": {"estado": "activo"},
                         "upsert": False, "overwriteArrays": False},
              "onerror": IGNORAR},
             responder(12, "confirmada"),
         ]},
         {"flow": [dict(responder(13, "caducado"),
                        filter=filtro("Token incorrecto", {"a": "{{1.t}}", "o": "text:notequal", "b": "{{" + token("1.e") + "}}"}))]},
     ]},
]

baja = [
    {"id": 14, "module": "datastore:DeleteRecord", "version": 1,
     "parameters": {"datastore": STORE},
     "filter": filtro("Baja", {"a": "{{1.accion}}", "o": "text:equal", "b": "baja"},
                      {"a": "{{1.email}}", "o": "text:contain", "b": "@"}),
     "mapper": {"key": "{{lower(trim(1.email))}}"},
     "onerror": [{"id": 91, "module": "builtin:Ignore", "version": 1}]},
    responder(15, "baja"),
]

blueprint = {
    "name": "Boletín · Suscripciones",
    "metadata": {"version": 1},
    "flow": [
        {"id": 1, "module": "gateway:CustomWebHook", "version": 1,
         "parameters": {"hook": HOOK, "maxResults": 1}, "mapper": {}},
        {"id": 2, "module": "builtin:BasicRouter", "version": 1,
         "routes": [{"flow": alta}, {"flow": confirmar}, {"flow": baja}]},
    ],
}
print(json.dumps(blueprint, ensure_ascii=False))
