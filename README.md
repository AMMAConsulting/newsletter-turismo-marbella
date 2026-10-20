# Marbella en Datos — boletín de turismo

Boletín SEMANAL automático (sale los martes a las 13:30) con datos del Observatorio Turístico y del Observatorio Económico de Marbella, más noticias del sector.

## Cómo funciona

1. **GitHub Actions** (`.github/workflows/boletin.yml`): el **lunes** `build.py` genera `docs/boletin/datos.json`, las gráficas del tema de la semana (rotan: hoteles, apartamentos/VUT, mercados, empleo) y `plantilla.html`, y pide el borrador a Make. El **martes a las 13:30** pide el envío.
2. **Make, escenario "Boletín"**: GPT redacta los textos a partir de `datos.json`, rellena la plantilla y manda el **borrador al revisor** con un enlace a `revision.html`.
3. El revisor **aprueba** (si es antes del martes 13:30 queda programado; si es después, sale en el momento) o **pide cambios** (GPT rehace el borrador y le llega uno nuevo).
4. **Make, escenario "Suscripciones"**: altas con doble confirmación, confirmaciones y bajas desde la web (`docs/`, GitHub Pages).

## Ficheros

- `build.py`: recogida de datos, gráficas y relleno de la parte fija de la plantilla.
- `plantilla/boletin.html`: diseño del correo. `[[...]]` lo rellena `build.py`; `%%...%%` lo rellena Make (no se usan llaves porque Make las toma por fórmulas).
- `docs/`: la web pública (alta, baja, revisión, privacidad). `docs/config.js` guarda las URL de los webhooks.
- `docs/img/fotos/`: fotos libres de Wikimedia Commons (`creditos.json`); rotan cada mes.

## Secretos del repositorio

- `MAKE_WEBHOOK_BOLETIN`: URL del webhook del escenario "Boletín".
- `MAKE_CLAVE`: clave compartida con Make para que nadie más pueda lanzar o aprobar ediciones.

Lanzar a mano: `gh workflow run boletin.yml -f accion=generar` (o `accion=enviar`). Simular otra semana en local: `BOLETIN_FECHA=2026-11-02 python build.py`.
