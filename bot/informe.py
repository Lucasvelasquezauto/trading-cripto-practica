"""informe.html (en la carpeta del proyecto y publicado en GitHub Pages): el estado actual de la etapa 2 arriba y el
informe de cada día debajo, el más reciente primero. Cada día queda guardado en reportes/diario/AAAA-MM-DD.json (para
reconstruir el informe) y .md (para Claude). Al final, plegada, la etapa 1 (3 oct – 15 nov 2026) tal como quedó: su
resumen final congelado (reportes/diario_etapa1/resumen_final.json) y sus informes diarios."""
import html
import json
import os
import re

from bot import config as C
from bot import principal as P
from bot.reporte import calcular, fecha_larga, lineas_adaptativa, pct, textos, usd

INFORME = os.path.join(C.RAIZ, "informe.html")
DIAS = os.path.join(C.REPORTES, "diario")
DIAS_E1 = C.ETAPA1["reportes"]
RESUMEN_E1 = os.path.join(DIAS_E1, "resumen_final.json")
MARCA_ERROR = "El bot tuvo un error en la última revisión"


def al_dia():
    """¿Ya está escrito el informe de hoy (fecha de Colombia) y sin aviso de error? Si sí y no hay nada nuevo, la
    revisión no reescribe nada (así repetirla el mismo día no cambia ningún archivo)."""
    if not (os.path.exists(INFORME) and os.path.exists(os.path.join(DIAS, f"{P.ahora_cot().date().isoformat()}.json"))):
        return False
    with open(INFORME, encoding="utf-8") as f:
        return MARCA_ERROR not in f.read()


def escribir(st, V, S, guardar=True):
    """Guarda la entrada del día y reconstruye informe.html. Devuelve un resumen de una línea. Con guardar=False solo
    calcula el resumen (no escribe nada)."""
    R = calcular(st, V, S)
    titulo, secciones = textos(R)
    t, mt, ad = R["libros"]["tendencia"], R["libros"]["mantener"], R.get("adaptativa") or {}
    extra = (f" · Adaptativa {usd(ad['valor'])} ({pct(ad['desde_inicio'])})" if ad.get("valor") is not None else "")
    resumen = {"titulo": titulo, "texto": f"Tendencia {usd(t['valor'])} ({pct(t['desde_inicio'])}) · Mantener "
                                          f"{usd(mt['valor'])} ({pct(mt['desde_inicio'])}){extra} · {R['estado']}"}
    if not guardar:
        resumen["texto"] += " · sin cambios desde la revisión anterior"
        return resumen
    os.makedirs(DIAS, exist_ok=True)
    t, mt, cu = R["libros"]["tendencia"], R["libros"]["mantener"], R["cuenta"]
    entrada = {"fecha": R["hoy"], "dia_n": R["dia_n"], "estado": R["estado"], "hora": R["salud"]["ultima_corrida"],
               "tendencia": t["valor"], "mantener": mt["valor"], "faltan_dias": max(0, cu["faltan_dias"]),
               "ajustes": cu["ajustes"], "secciones": secciones}
    ad = R.get("adaptativa") or {}
    if ad.get("valor") is not None:
        entrada["adaptativa"] = ad["valor"]
    with open(os.path.join(DIAS, f"{R['hoy']}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=1)
    md = [f"# {titulo}", ""]
    for nombre, lineas in secciones:
        md += [f"## {nombre}", ""] + [f"- {x}" for x in lineas] + [""]
    with open(os.path.join(DIAS, f"{R['hoy']}.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))
    _guardar(R)
    return resumen


def reconstruir(error=None):
    """Vuelve a armar informe.html sin agregar un día (p. ej. después de un error)."""
    st = P.cargar_estado()
    V = P.velas()
    _guardar(calcular(st, V, P.senales(V)), error)


def entradas_de(carpeta):
    """Los informes diarios guardados (AAAA-MM-DD.json), el más reciente primero."""
    entradas = []
    if os.path.isdir(carpeta):
        for n in sorted(os.listdir(carpeta), reverse=True):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", n):
                with open(os.path.join(carpeta, n), encoding="utf-8") as f:
                    entradas.append(json.load(f))
    return entradas


def _guardar(R, error=None):
    tmp = INFORME + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(pagina(R, entradas_de(DIAS), error))
    os.replace(tmp, INFORME)


def _e(x):
    return html.escape(str(x))


def _linea(x):
    """Una línea de texto; ✓/✗ al inicio se vuelven ícono de estado (el texto sigue en tinta normal)."""
    if x.startswith("✓ "):
        return f"<li class='chk'><span class='ic ok' aria-hidden='true'>✓</span><span>{_e(x[2:])}</span></li>"
    if x.startswith("✗ "):
        return f"<li class='chk'><span class='ic no' aria-hidden='true'>✗</span><span>{_e(x[2:])}</span></li>"
    return f"<li>{_e(x)}</li>"


def _medidor(etiqueta, valor, total, detalle):
    frac = max(0.0, min(1.0, valor / total)) if total else 0
    return (f"<div class='med'><div class='med-top'><span>{_e(etiqueta)}</span><b>{_e(detalle)}</b></div>"
            f"<div class='pista' role='progressbar' aria-label='{_e(etiqueta)}' aria-valuemin='0' aria-valuemax='{total}' "
            f"aria-valuenow='{min(valor, total)}'><div class='relleno' style='width:{frac * 100:.1f}%'></div></div></div>")


def dias_html(entradas):
    """Un bloque plegable por día (el más reciente abierto), igual en las dos etapas."""
    salida = []
    for k, e in enumerate(entradas):
        cuerpo = "".join(f"<h4>{_e(n)}</h4><ul>{''.join(_linea(x) for x in ls)}</ul>" for n, ls in e["secciones"])
        bien = e["estado"] == "Todo en orden"
        salida.append(
            f"<details class='dia'{' open' if k == 0 else ''}><summary><span class='ic {'ok' if bien else 'no'}' "
            f"aria-hidden='true'>{'✓' if bien else '!'}</span><span class='d-tit'>Día {e['dia_n']} · "
            f"{fecha_larga(e['fecha'])}</span><span class='d-num'>Tendencia {usd(e['tendencia'])} · Mantener "
            f"{usd(e['mantener'])}" + (f" · Adaptativa {usd(e['adaptativa'])}" if e.get("adaptativa") is not None else "")
            + "</span></summary><div class='d-cuerpo'>"
            f"<p class='nota'>Revisado {_e(e['hora'])} · "
            f"{_e(e['estado'])} · faltaban {e['faltan_dias']} días · ajustes {e['ajustes']} de {C.AJUSTES_MINIMOS}</p>"
            f"{cuerpo}</div></details>")
    return "".join(salida)


def etapa1_html():
    """La etapa 1 tal como quedó en su último informe (16 nov 2026, 02:27): resumen congelado, gráfica y días."""
    if not os.path.exists(RESUMEN_E1):
        return "", []
    with open(RESUMEN_E1, encoding="utf-8") as f:
        r = json.load(f)
    cuerpo = (f"<details class='etapa' id='etapa1'><summary><span class='e-tit'>{_e(r['titulo'])}</span>"
              "<span class='e-sub'>Historia cerrada · ya no se actualiza</span></summary><div class='e-cuerpo'>"
              f"<p class='etiqueta'>{_e(r['nota'])}</p><p class='nota'>{_e(r['cabecera'])}</p>"
              f"{r['resumen_html']}<h2 style=\"margin-top:28px\">Informe de cada día (etapa 1)</h2>"
              f"{dias_html(entradas_de(DIAS_E1))}</div></details>")
    return cuerpo, r["datos"]


def pagina(R, entradas, error=None):
    t, mt, cu, sa = R["libros"]["tendencia"], R["libros"]["mantener"], R["cuenta"], R["salud"]
    ad = R.get("adaptativa") or {}
    por_fecha = ad.get("por_fecha", {})
    # Etapa 2: los tres libros parten de $100 con el mismo cierre; cada punto es un cierre diario revisado.
    primer = (R.get("st") or {}).get("primer_dia") or C.INICIO_CIERRE
    puntos = [{"f": primer, "t": C.CAPITAL, "m": C.CAPITAL, "a": C.CAPITAL}] if R["diario"] else []
    puntos += [{"f": r["fecha_cierre"], "t": float(r["valor_tendencia"]), "m": float(r["valor_mantener"]),
                "a": por_fecha.get(r["fecha_cierre"])} for r in R["diario"] if r["fecha_cierre"] > primer]
    generado = P.ahora_cot().isoformat(timespec="minutes")
    problemas = ([f"{MARCA_ERROR}: {error}"] if error else []) + R["avisos"]
    if problemas:
        estado = ("<div class='estado mal'><span class='ic no' aria-hidden='true'>!</span><div><b>Hay algo para revisar</b>"
                  f"<ul>{''.join(f'<li>{_e(x)}</li>' for x in problemas)}</ul></div></div>")
    else:
        estado = ("<div class='estado bien'><span class='ic ok' aria-hidden='true'>✓</span><div><b>Todo en orden</b>"
                  "<p>El bot revisó a tiempo, los datos están completos y la práctica se parece a la simulación.</p></div></div>")
    if R["listo"]:
        regresiva = ("<p class='clave'>Se cumplen todas las condiciones. Abre Claude y pregunta: "
                     "«¿ya es momento de pasar a dinero real?»</p>")
    else:
        regresiva = (f"<p class='clave'>Fecha más temprana para dinero real: <b>{fecha_larga(cu['minima'])}</b> "
                     f"(faltan {max(0, cu['faltan_dias'])} días). Si los ajustes llegan al ritmo normal, la fecha "
                     f"estimada es el {fecha_larga(cu['estimada'])}; el tope de la práctica es el {fecha_larga(cu['tope'])}.</p>")
    dias_vistos = min(max(R["dia_n"], 0), C.DIAS_MINIMOS)
    medidores = (_medidor("Días de práctica", dias_vistos, C.DIAS_MINIMOS, f"{dias_vistos} de {C.DIAS_MINIMOS}")
                 + _medidor("Ajustes de la estrategia", cu["ajustes"], C.AJUSTES_MINIMOS, f"{cu['ajustes']} de {C.AJUSTES_MINIMOS}"))
    condiciones = "".join(_linea(("✓ " if ok else "✗ ") + txt) for ok, txt in R["compuerta"])

    etapa1, datos_e1 = etapa1_html()
    tabla = "".join(f"<tr><td>{fecha_larga(p['f'])}</td><td>{usd(p['t'])}</td><td>{usd(p['m'])}</td>"
                    f"<td>{usd(p['a']) if p['a'] is not None else '—'}</td></tr>" for p in reversed(puntos))
    tiles = [(usd(t["valor"]), "Tendencia (la estrategia)", pct(t["desde_inicio"]) + " desde el inicio"),
             (usd(mt["valor"]), "Mantener BTC+ETH", pct(mt["desde_inicio"]) + " desde el inicio"),
             ("Listo" if R["listo"] else f"{max(0, cu['faltan_dias'])} días", "Faltan para la fecha mínima",
              fecha_larga(cu["minima"])),
             (f"{cu['ajustes']} de {C.AJUSTES_MINIMOS}", "Ajustes de la estrategia", f"se necesitan {C.AJUSTES_MINIMOS}")]
    if ad.get("valor") is not None:
        tiles.insert(2, (usd(ad["valor"]), C.ADAPTATIVA["nombre"],
                         f"{pct(ad['desde_inicio'])} desde el {fecha_larga(ad['inicio'])}"))
    la = lineas_adaptativa(R)
    if la:
        tercero = (f"<section class='tarjeta'><h2>Tercer libro: {_e(C.ADAPTATIVA['nombre'])}</h2>"
                   f"<p class='etiqueta'>{_e(la['veredicto'])}</p><ul>"
                   + "".join(_linea(x.replace("Adaptativa · ", "", 1)) for x in la["como"]
                             if not x.startswith("Adaptativa · Prueba"))
                   + "".join(_linea(x.replace("Adaptativa: ", "", 1)) for x in la["esperado"]) + "</ul></section>")
    else:
        tercero = ""
    tiles_html = "".join(f"<div class='tile'><span class='t-et'>{_e(b)}</span><b>{_e(a)}</b>"
                         f"<span class='t-sub'>{_e(c)}</span></div>" for a, b, c in tiles)
    # Reemplazos en un solo paso: ningún texto insertado (p. ej. la etapa 1) se vuelve a revisar como plantilla.
    valores = {"css": CSS, "generado": generado, "inicio": fecha_larga(primer), "ultima": _e(sa["ultima_corrida"]),
               "estado": estado, "tiles": tiles_html, "regresiva": regresiva, "medidores": medidores,
               "condiciones": condiciones, "tabla": tabla, "tercero": tercero,
               "dias": dias_html(entradas) or "<p>Aún no hay días registrados.</p>", "etapa1": etapa1,
               "datos": json.dumps(puntos), "datos_e1": json.dumps(datos_e1), "js": JS}
    return re.sub(r"\{\{(\w+)\}\}", lambda m: valores[m.group(1)], PLANTILLA)


CSS = """
:root{color-scheme:light;--plano:#f9f9f7;--sup:#fcfcfb;--tinta:#0b0b0b;--tinta2:#52514e;--tenue:#898781;
--rejilla:#e1e0d9;--eje:#c3c2b7;--borde:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--bien:#0ca30c;--mal:#d03b3b;
--lavado-bien:rgba(12,163,12,.08);--lavado-mal:rgba(208,59,59,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--plano:#0d0d0d;--sup:#1a1a19;
--tinta:#fff;--tinta2:#c3c2b7;--tenue:#898781;--rejilla:#2c2c2a;--eje:#383835;--borde:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--lavado-bien:rgba(12,163,12,.12);--lavado-mal:rgba(208,59,59,.14)}}
:root[data-theme="dark"]{color-scheme:dark;--plano:#0d0d0d;--sup:#1a1a19;--tinta:#fff;--tinta2:#c3c2b7;--tenue:#898781;
--rejilla:#2c2c2a;--eje:#383835;--borde:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--lavado-bien:rgba(12,163,12,.12);--lavado-mal:rgba(208,59,59,.14)}
*{box-sizing:border-box}
body{margin:0;background:var(--plano);color:var(--tinta);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:820px;margin:0 auto;padding:28px 16px 64px}
header h1{font-size:1.6rem;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}
header p{margin:0;color:var(--tinta2)}
h2{font-size:1.05rem;margin:0 0 12px}h4{font-size:.95rem;margin:16px 0 6px}
.tarjeta{background:var(--sup);border:1px solid var(--borde);border-radius:14px;padding:18px 20px;margin:16px 0}
.viejo{display:none;background:var(--lavado-mal);border:1px solid var(--mal);border-radius:14px;padding:14px 18px;margin:16px 0}
.estado{display:flex;gap:12px;align-items:flex-start;border-radius:14px;padding:14px 18px;margin:16px 0;border:1px solid var(--borde)}
.estado.bien{background:var(--lavado-bien)}.estado.mal{background:var(--lavado-mal)}
.estado p,.estado ul{margin:2px 0 0;color:var(--tinta2)}.estado ul{padding-left:18px}
.ic{flex:none;display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;color:#fff;font-size:.8rem;font-weight:700}
.ic.ok{background:var(--bien)}.ic.no{background:var(--mal)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--sup);border:1px solid var(--borde);border-radius:14px;padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.tile b{font-size:1.55rem;line-height:1.2}.t-et{color:var(--tinta2);font-size:.85rem}.t-sub{color:var(--tenue);font-size:.8rem}
.clave{margin:0 0 14px}
.med{margin:10px 0}.med-top{display:flex;justify-content:space-between;font-size:.9rem;color:var(--tinta2);margin-bottom:4px}
.med-top b{color:var(--tinta);font-weight:600}
.pista{height:8px;border-radius:4px;background:var(--rejilla);overflow:hidden}.relleno{height:100%;border-radius:4px;background:var(--s1)}
ul{margin:0;padding-left:20px}li{margin:5px 0}
li.chk{list-style:none;display:flex;gap:10px;align-items:flex-start;margin-left:-20px}
li.chk .ic{width:18px;height:18px;font-size:.7rem;margin-top:3px}
.leyenda{display:flex;gap:18px;flex-wrap:wrap;font-size:.88rem;color:var(--tinta2);margin:0 0 6px}
.leyenda span{display:inline-flex;align-items:center;gap:6px}.leyenda i{display:inline-block;width:16px;height:2px;border-radius:1px}
#grafica{position:relative}#grafica svg{display:block;width:100%;height:auto;overflow:visible}
.tip{position:absolute;pointer-events:none;background:var(--sup);border:1px solid var(--borde);border-radius:10px;
padding:8px 10px;font-size:.82rem;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;white-space:nowrap}
.tip .f{color:var(--tinta2);margin-bottom:2px}.tip div{display:flex;align-items:center;gap:6px}
.tip i{width:12px;height:2px;display:inline-block}.tip span{color:var(--tinta2)}
details.tabla{margin-top:10px}details.tabla summary{cursor:pointer;color:var(--tinta2);font-size:.9rem}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums;margin-top:8px}
th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--rejilla)}th:first-child,td:first-child{text-align:left}
th{color:var(--tinta2);font-weight:600}
details.dia{background:var(--sup);border:1px solid var(--borde);border-radius:14px;margin:10px 0}
details.dia summary{cursor:pointer;list-style:none;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;padding:14px 18px}
details.dia summary::-webkit-details-marker{display:none}
.d-tit{font-weight:600}.d-num{color:var(--tinta2);font-size:.9rem;margin-left:auto}
.d-cuerpo{padding:0 20px 16px;border-top:1px solid var(--rejilla)}.nota{color:var(--tenue);font-size:.85rem;margin:12px 0 0}
.etiqueta{display:inline-block;margin:0 0 10px;padding:4px 10px;border-radius:8px;border:1px solid var(--borde);
background:var(--plano);color:var(--tinta2);font-size:.88rem}
.intro{margin:14px 0 0;padding:10px 14px;border-left:3px solid var(--s1);background:var(--sup);border-radius:0 10px 10px 0;
color:var(--tinta2)}
details.etapa{background:var(--plano);border:1px dashed var(--eje);border-radius:14px;margin:28px 0 10px}
details.etapa>summary{cursor:pointer;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;padding:14px 18px}
.e-tit{font-weight:600}.e-sub{color:var(--tenue);font-size:.88rem}
.e-cuerpo{padding:0 16px 12px;border-top:1px dashed var(--eje)}.e-cuerpo>.etiqueta{margin-top:14px}
footer{color:var(--tenue);font-size:.88rem;margin-top:28px}
@media (max-width:520px){.d-num{margin-left:34px;width:100%}}
"""

PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe de trading cripto</title><style>{{css}}</style></head>
<body data-generado="{{generado}}"><main>
<header><h1>Informe de la práctica sin dinero</h1>
<p>Trading cripto · bitcoin y ether · etapa 2, desde el cierre del {{inicio}} · última revisión {{ultima}} (hora de Colombia)</p>
<p class="intro">El 15 de noviembre de 2026 los tres libros volvieron a empezar con $100 cada uno, en el mismo momento y
con los mismos precios, para compararlos en igualdad de condiciones. Lo anterior está guardado al final, en la sección
plegada «Etapa 1».</p></header>
<div class="viejo" id="viejo"></div>
{{estado}}
<div class="tiles">{{tiles}}</div>
<section class="tarjeta"><h2>Cuenta regresiva para el dinero real</h2>{{regresiva}}{{medidores}}
<ul style="margin-top:14px">{{condiciones}}</ul></section>
<section class="tarjeta"><h2>Cómo van los libros (valor en dólares)</h2>
<div class="leyenda"><span><i style="background:var(--s1)"></i>Tendencia (la estrategia)</span>
<span><i style="background:var(--s2)"></i>Mantener BTC+ETH</span>
<span><i style="background:var(--s3)"></i>Adaptativa (alza + baja)</span>
<span><i style="background:var(--eje)"></i>$100 iniciales</span></div>
<div id="grafica"></div>
<details class="tabla"><summary>Ver los datos</summary><table><thead><tr><th>Día</th><th>Tendencia</th><th>Mantener</th><th>Adaptativa</th></tr></thead>
<tbody>{{tabla}}</tbody></table></details></section>
{{tercero}}
<h2 style="margin-top:28px">Informe de cada día</h2>
{{dias}}
{{etapa1}}
<footer>¿Algo raro? Abre Claude en la carpeta trading-cripto y escribe «revisa el trading». Esta página se actualiza
sola cada noche hacia las 7:10 pm (hora de Colombia) desde GitHub; no depende de que el PC esté prendido.</footer>
</main>
<script>const DATOS = {{datos}}; const DATOS_E1 = {{datos_e1}};</script>
<script>{{js}}</script>
</body></html>
"""

JS = r"""
(function(){
  // Aviso si el informe está viejo (el bot no corre o falló sin poder escribir).
  var gen = new Date(document.body.dataset.generado);
  var horas = (Date.now() - gen.getTime()) / 36e5;
  if (horas > 26) {
    var v = document.getElementById('viejo');
    v.textContent = 'Este informe no se actualiza desde hace ' + Math.floor(horas / 24) + ' día(s). Puede que el bot no ' +
      'esté corriendo en GitHub: abre Claude y escribe «revisa el trading».';
    v.style.display = 'block';
  }
  dibujar(document.getElementById('grafica'), DATOS);
  var e1 = document.getElementById('grafica-e1');
  if (e1) dibujar(e1, DATOS_E1);
})();

// Gráfica de líneas: los libros + referencia en $100, con cruz y recuadro al pasar el puntero.
function dibujar(caja, DATOS){
  if (!caja) return;
  if (!DATOS.length) { caja.textContent = 'La gráfica aparece desde el primer día.'; return; }
  var NS = 'http://www.w3.org/2000/svg';
  var W = 760, H = 280, m = {l: 54, r: 130, t: 12, b: 30};
  var fechas = DATOS.map(function(p){ return new Date(p.f + 'T12:00:00'); });
  var x0 = fechas[0].getTime(), x1 = fechas[fechas.length - 1].getTime();
  var vals = [100]; DATOS.forEach(function(p){ vals.push(p.t, p.m); if (p.a != null) vals.push(p.a); });
  var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  var pad = Math.max((hi - lo) * 0.15, 1); lo -= pad; hi += pad;
  function X(i){ return x1 === x0 ? m.l + (W - m.l - m.r) / 2 : m.l + (fechas[i].getTime() - x0) / (x1 - x0) * (W - m.l - m.r); }
  function Y(v){ return m.t + (hi - v) / (hi - lo) * (H - m.t - m.b); }
  function el(n, a){ var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); svg.appendChild(e); return e; }
  function dinero(v){ return '$' + v.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
  var meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  function corta(d){ return d.getDate() + ' ' + meses[d.getMonth()]; }
  var svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Valor diario de los libros simulados frente a los 100 dólares iniciales');
  caja.appendChild(svg);
  // Rejilla y eje Y con marcas redondas
  var paso = Math.pow(10, Math.floor(Math.log10((hi - lo) / 4))), mult = [1, 2, 2.5, 5, 10];
  for (var j = 0; j < mult.length; j++) if ((hi - lo) / (paso * mult[j]) <= 5) { paso *= mult[j]; break; }
  for (var v = Math.ceil(lo / paso) * paso; v <= hi + 1e-9; v += paso) {
    el('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: 'var(--rejilla)', 'stroke-width': 1});
    var tx = el('text', {x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 12, fill: 'var(--tenue)'});
    tx.textContent = '$' + (Math.round(v * 100) / 100).toString().replace('.', ',');
  }
  el('line', {x1: m.l, x2: W - m.r, y1: Y(100), y2: Y(100), stroke: 'var(--eje)', 'stroke-width': 1.5});
  // Eje X: primera, última y algunas intermedias
  var n = DATOS.length, cada = Math.max(1, Math.ceil(n / 6));
  function etiquetaX(i){ var t = el('text', {x: X(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 12, fill: 'var(--tenue)'}); t.textContent = corta(fechas[i]); }
  for (var i = 0; i < n; i += cada) etiquetaX(i);
  if ((n - 1) % cada) etiquetaX(n - 1);
  // Líneas, punto final y etiqueta directa con el valor
  var series = [{k: 't', c: 'var(--s1)', n: 'Tendencia'}, {k: 'm', c: 'var(--s2)', n: 'Mantener'},
                {k: 'a', c: 'var(--s3)', n: 'Adaptativa'}], finales = [];
  series.forEach(function(s){
    // Solo los días con valor (la adaptativa empieza el 15 nov): la línea se corta donde no hay dato.
    var d = '', ult = -1, previo = false;
    DATOS.forEach(function(p, i){
      if (p[s.k] == null) { previo = false; return; }
      d += (previo ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(p[s.k]).toFixed(1) + ' '; previo = true; ult = i;
    });
    if (ult < 0) return;
    if (d.indexOf('L') >= 0) el('path', {d: d, fill: 'none', stroke: s.c, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
    var u = DATOS[ult][s.k];
    el('circle', {cx: X(ult), cy: Y(u), r: 4, fill: s.c, stroke: 'var(--sup)', 'stroke-width': 2});
    finales.push({y: Y(u), texto: s.n + ' ' + dinero(u)});
  });
  finales.sort(function(a, b){ return a.y - b.y; });
  for (var q = 1; q < finales.length; q++) if (finales[q].y - finales[q - 1].y < 16) finales[q].y = finales[q - 1].y + 16;
  var sobra = finales.length ? finales[finales.length - 1].y - (H - m.b) : 0;
  if (sobra > 0) finales.forEach(function(f){ f.y -= sobra; });
  finales.forEach(function(f){ var t = el('text', {x: X(n - 1) + 10, y: f.y + 4, 'font-size': 12, fill: 'var(--tinta2)'}); t.textContent = f.texto; });
  // Cruz y recuadro al pasar el puntero
  var cruz = el('line', {y1: m.t, y2: H - m.b, stroke: 'var(--eje)', 'stroke-width': 1, visibility: 'hidden'});
  var tip = document.createElement('div'); tip.className = 'tip'; caja.appendChild(tip);
  var zona = el('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent'});
  function mostrar(ev){
    var r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W, mejor = 0;
    for (var i = 1; i < n; i++) if (Math.abs(X(i) - px) < Math.abs(X(mejor) - px)) mejor = i;
    cruz.setAttribute('x1', X(mejor)); cruz.setAttribute('x2', X(mejor)); cruz.setAttribute('visibility', 'visible');
    tip.replaceChildren();
    var f = document.createElement('div'); f.className = 'f'; f.textContent = corta(fechas[mejor]); tip.appendChild(f);
    series.forEach(function(s){
      if (DATOS[mejor][s.k] == null) return;
      var d = document.createElement('div'), k = document.createElement('i'), b = document.createElement('b'), sp = document.createElement('span');
      k.style.background = s.c; b.textContent = dinero(DATOS[mejor][s.k]); sp.textContent = s.n;
      d.appendChild(k); d.appendChild(b); d.appendChild(sp); tip.appendChild(d);
    });
    tip.style.display = 'block';
    var izq = X(mejor) / W * r.width + 12; if (izq + tip.offsetWidth > r.width) izq -= tip.offsetWidth + 24;
    tip.style.left = izq + 'px'; tip.style.top = '8px';
  }
  zona.addEventListener('pointermove', mostrar);
  zona.addEventListener('pointerleave', function(){ cruz.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; });
}
"""
