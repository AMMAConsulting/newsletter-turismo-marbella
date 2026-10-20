# Marbella en Datos — boletín de turismo

Boletín mensual automático con datos del Observatorio Turístico y del Observatorio Económico de Marbella, más noticias del sector.

## Cómo funciona

1. **GitHub Actions** (`.github/workflows/boletin.yml`) se ejecuta cada día. Cuando el INE publica un mes nuevo de la Encuesta de Ocupación Hotelera, `build.py` genera `docs/boletin/datos.json`, las gráficas y `plantilla.html`, y avisa al webhook de Make.
2. **Make, escenario "Boletín"**: GPT redacta los textos a partir de `datos.json`, rellena la plantilla y manda el **borrador al revisor** con un enlace a `revision.html`.
3. El revisor **aprueba** (se envía a todos los suscriptores activos) o **pide cambios** (GPT rehace el borrador y le llega uno nuevo).
4. **Make, escenario "Suscripciones"**: altas con doble confirmación, confirmaciones y bajas desde la web (`docs/`, GitHub Pages).

## Ficheros

- `build.py`: recogida de datos, gráficas y relleno de la parte fija de la plantilla.
- `plantilla/boletin.html`: diseño del correo. `[[...]]` lo rellena `build.py`; `%%...%%` lo rellena Make (no se usan llaves porque Make las toma por fórmulas).
- `docs/`: la web pública (alta, baja, revisión, privacidad). `docs/config.js` guarda las URL de los webhooks.
- `docs/img/fotos/`: fotos libres de Wikimedia Commons (`creditos.json`); rotan cada mes.

## Secretos del repositorio

- `MAKE_WEBHOOK_BOLETIN`: URL del webhook del escenario "Boletín".
- `MAKE_CLAVE`: clave compartida con Make para que nadie más pueda lanzar o aprobar ediciones.

Lanzar a mano: `gh workflow run boletin.yml -f forzar=true`.
