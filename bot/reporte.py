"""Informe para el dueño del proyecto (español simple): informe.html en la carpeta del proyecto, con el estado actual arriba y el
informe de cada día debajo (el más reciente primero). Cada día queda guardado en reportes/diario/AAAA-MM-DD.json
(y .md) para reconstruir el informe y para que Claude lo lea."""
import bisect
import datetime as dt
import html
import json
import os
import statistics

from bot import config as C
from bot import principal as P

E = P.E


def usd(x):
    return "$" + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, signo=True):
    return (f"{x:+.1%}" if signo else f"{x:.1%}").replace(".", ",")


def num(x, dec=2):
    return f"{x:.{dec}f}".replace(".", ",")


def fecha_larga(f):
    meses = "ene feb mar abr may jun jul ago sep oct nov dic".split()
    d = dt.date.fromisoformat(f)
    return f"{d.day} {meses[d.month - 1]} {d.year}"


# ---------------------------------------------------------------------------------------------- cálculos
def _historia_contado():
    """Lo que estudio.cargar() arma, solo con el contado (lo único que usa la simulación de la tendencia). Así el bot
    no necesita los archivos del perpetuo de Binance, el MVRV ni el miedo/codicia del estudio."""
    D = {}
    for a in E.ACTIVOS:
        filas = sorted((int(r[0]), float(r[4])) for r in E._csv(f"velas_spot_{a}USDT_1d.csv"))
        D[f"fechas_{a}"] = [E._dia(ms) for ms, _c in filas]
        c = [x for _ms, x in filas]
        D[f"precio_{a}"] = c
        D[f"r_spot_{a}"] = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    if D["fechas_BTC"] != D["fechas_ETH"]:
        raise RuntimeError("Las fechas de BTC y ETH no coinciden en la historia del contado.")
    D["fechas"] = D["fechas_BTC"]
    D["n"] = len(D["fechas"])
    return D


def rango_historico(dias):
    """Rendimientos de la estrategia en ventanas de `dias` días desde 2018 (el estudio), y su peor caída."""
    D = _historia_contado()
    sen = {a: E.senales_tendencia(D[f"precio_{a}"])["promedio_8"] for a in E.ACTIVOS}
    curva, _ops, _ex = E.simular(D, lambda i: {f"spot_{a}": (sen[a][i] or 0) / 2 for a in E.ACTIVOS})
    i0 = bisect.bisect_left(D["fechas"], "2018-03-06")
    v = curva[i0:]
    dias = max(1, dias)
    r = sorted(v[k + dias] / v[k] - 1 for k in range(len(v) - dias))
    pico, peor = v[0], 0.0
    for x in v:
        pico = max(pico, x)
        peor = min(peor, x / pico - 1)
    return {"p10": r[len(r) // 10], "p50": r[len(r) // 2], "p90": r[9 * len(r) // 10], "peor_caida": peor}


def calcular(st, V, S):
    hoy_cot = P.ahora_cot().date()
    inicio = dt.date.fromisoformat(C.INICIO)
    dia_n = (hoy_cot - inicio).days + 1
    diario, ops = P.leer(P.DIARIO), P.leer(P.OPERACIONES)
    ult = diario[-1] if diario else None
    R = {"dia_n": dia_n, "hoy": hoy_cot.isoformat(), "ult": ult, "diario": diario, "st": st}

    # Libros
    libros = {}
    for k in C.LIBROS:
        serie = [float(r[f"valor_{k}"]) for r in diario]
        actual = serie[-1] if serie else C.CAPITAL
        pico = max(serie) if serie else C.CAPITAL
        libros[k] = {"valor": actual, "desde_inicio": actual / C.CAPITAL - 1,
                     "ayer": (actual / serie[-2] - 1) if len(serie) > 1 else 0.0,
                     "caida": actual / pico - 1, "pesos": json.loads(ult[f"pesos_{k}"]) if ult else {},
                     "ajustes": st["libros"][k]["ajustes"], "ajustes_ideal": st["ideal"][k]["ajustes"],
                     "dif_ideal": ((float(ult[f"valor_cierre_{k}"]) - float(ult[f"ideal_{k}"])) / C.CAPITAL) if ult else 0.0,
                     "ops_hoy": [o for o in ops if ult and o["hora"] == ult["hora"] and o["libro"] == k]}
    R["libros"] = libros

    # Salud del bot
    contables = diario[1:]  # el primer día es el arranque: no cuenta para la puntualidad
    a_tiempo = sum(float(r["atraso_h"]) <= C.ATRASO_MAX_H for r in contables)
    sin_revision = sum(int(r["dias_sin_revision"]) for r in diario)
    errores = []
    if os.path.exists(P.ERRORES):
        with open(P.ERRORES, encoding="utf-8") as f:
            bloques = f.read().split("--- ")[1:]
        errores = [b for b in bloques if b[:10] >= (hoy_cot - dt.timedelta(days=7)).isoformat()]
    esperado = (P.ahora_utc().date() - dt.timedelta(days=1)).isoformat()
    R["salud"] = {"a_tiempo": a_tiempo, "contables": len(contables), "sin_revision": sin_revision,
                  "errores_7d": len(errores), "ultimo_error": errores[-1].strip().splitlines()[-1] if errores else "",
                  "problemas": st.get("problemas", []), "al_dia": bool(ult) and ult["fecha_cierre"] >= esperado,
                  "ultima_corrida": st.get("ultima_corrida", "")}

    # Mercado
    mercado = {}
    for a in C.ACTIVOS:
        f, c, m = V[a]["fechas"], V[a]["cierre"], V[a]["maximo"]
        k = max(range(len(m)), key=m.__getitem__)
        mercado[a] = {"precio": c[-1], "fecha": f[-1], "dia": c[-1] / c[-2] - 1, "maximo": m[k], "fecha_maximo": f[k],
                      "senal": S[a][f[-1]] or 0.0}
    R["mercado"] = mercado

    # ¿Va como esperábamos?
    dias = len(diario)
    R["historia"] = rango_historico(dias)

    # Compuerta B y cuenta regresiva
    minima = inicio + dt.timedelta(days=C.DIAS_MINIMOS)
    tope = inicio + dt.timedelta(days=C.DIAS_MAXIMOS)
    aj = libros["tendencia"]["ajustes"]
    faltan_aj = max(0, C.AJUSTES_MINIMOS - aj)
    estimada = max(minima, hoy_cot + dt.timedelta(days=7 * faltan_aj)) if faltan_aj else minima
    estimada = min(estimada, tope)
    pct_tiempo = a_tiempo / len(contables) if contables else 1.0
    peor_dif = max((abs(v["dif_ideal"]) for v in libros.values()), default=0)
    R["cuenta"] = {"minima": minima.isoformat(), "tope": tope.isoformat(), "faltan_dias": (minima - hoy_cot).days,
                   "faltan_tope": (tope - hoy_cot).days, "ajustes": aj, "estimada": estimada.isoformat()}
    R["compuerta"] = [
        (hoy_cot >= minima, f"Mínimo 4 semanas de práctica: van {max(0, dia_n)} de {C.DIAS_MINIMOS} días."),
        (aj >= C.AJUSTES_MINIMOS or hoy_cot >= tope,
         f"Al menos {C.AJUSTES_MINIMOS} ajustes de la estrategia (o llegar al tope del {fecha_larga(tope.isoformat())}): van {aj}."),
        (peor_dif * 100 <= C.TOLERANCIA_PP,
         f"La práctica se parece a la simulación: diferencia de {num(abs(peor_dif) * 100)} puntos (máximo {num(C.TOLERANCIA_PP, 1)})."),
        (pct_tiempo >= C.A_TIEMPO_MIN, (f"Revisiones a tiempo: {a_tiempo} de {len(contables)} (mínimo {C.A_TIEMPO_MIN:.0%})."
                                         if contables else "Revisiones a tiempo: se empiezan a contar desde el día 2.")),
        (not errores, f"Sin errores en los últimos 7 días: {len(errores)} errores."),
    ]
    R["listo"] = all(ok for ok, _t in R["compuerta"])

    # Avisos importantes
    avisos = list(R["salud"]["problemas"])
    if not R["salud"]["al_dia"]:
        avisos.append("El bot no ha revisado el último cierre. ¿Falló la revisión programada de las 7:10 pm?")
    if ult and int(ult["dias_sin_revision"]):
        avisos.append(f"Hubo {ult['dias_sin_revision']} día(s) sin revisión antes de hoy (la revisión no corrió o falló).")
    if ult and float(ult["atraso_h"]) > C.ATRASO_MAX_H and len(diario) > 1:
        avisos.append(f"La revisión de hoy se hizo {float(ult['atraso_h']):.1f} h tarde.")
    if peor_dif * 100 > C.TOLERANCIA_PP:
        avisos.append("La práctica se está alejando de la simulación más de lo aceptado. Hay que revisarlo con Claude.")
    if libros["tendencia"]["caida"] < -0.20:
        avisos.append(f"La estrategia está {pct(libros['tendencia']['caida'])} bajo su máximo de la práctica "
                      f"(en la historia la peor caída fue {pct(R['historia']['peor_caida'])}).")
    for k, v in libros.items():
        if any(o["nota"] for o in v["ops_hoy"]):
            avisos.append(f"{C.LIBROS[k]}: una orden quedó por debajo del mínimo de $5 y no se hizo.")
    if errores:
        avisos.append(f"Error reciente del bot: {R['salud']['ultimo_error']}")
    R["avisos"] = avisos
    R["estado"] = "Todo en orden" if not avisos else "Hay algo para revisar"

    # Tercer libro (solo observación): no entra en la compuerta B ni en los avisos de arriba.
    try:
        from bot import adaptativa
        R["adaptativa"] = adaptativa.resumen()
    except Exception:
        R["adaptativa"] = None
    return R


def lineas_adaptativa(R):
    """Textos del libro adaptativa (todos empiezan con "Adaptativa" para distinguirlos). {} si aún no hay datos."""
    X = R.get("adaptativa")
    if not X:
        return {}
    nombre = C.ADAPTATIVA["nombre"]
    if X.get("valor") is None:
        return {"como": [f"Adaptativa: el tercer libro ({nombre}) aún no empieza. "
                         + " ".join(X.get("problemas") or [])], "hoy": [], "esperado": [], "veredicto": X["veredicto"]}
    largo = " · ".join(f"{a} {pct(w, False)}" for a, w in X["pesos"].items())
    v = X["valor"]
    cortos = X["cortos"]
    nominal = sum(k["nocional"] for k in cortos.values())
    efectivo = 1 - sum(X["pesos"].values())
    bajas = (" · apuestas a la baja: " + ", ".join(f"{a} {pct(k['nocional'] / v, False)}" for a, k in cortos.items())
             if cortos else " · sin apuestas a la baja")
    como = [f"Adaptativa (alza + baja, desde el {fecha_larga(X['inicio'])}): {usd(v)} ({pct(X['desde_inicio'])} desde su "
            f"inicio, {pct(X['ayer'])} desde la revisión anterior). Compras: {largo}{bajas}."]
    for a, k in cortos.items():
        res = k["resultado_precio"] + k["financiacion"] - k["comisiones"]
        fin = k["financiacion"]
        como.append(f"Adaptativa · apuesta a la baja en {a} abierta: {f"{k['cantidad']:.8f}".rstrip('0').replace('.', ',')} {a} "
                    f"(≈ {usd(k['nocional'])}, {pct(k['nocional'] / v, False)} del libro), desde el "
                    f"{fecha_larga(k['desde'])} a {usd(k['precio_entrada'])}. Resultado hasta hoy "
                    f"{'+' if res >= 0 else '−'}{usd(abs(res))} (financiación {'cobrada' if fin >= 0 else 'pagada'} "
                    f"{usd(abs(fin))}; comisiones {usd(k['comisiones'])}). Se cierra si "
                    f"{a} cierra sobre el máximo de sus 10 cierres anteriores, vuelve a 3 de 8 señales"
                    + (f" o cierra sobre {usd(k['stop'])}." if k.get("stop") else "."))
    if not cortos:
        como.append("Adaptativa · no hay apuestas a la baja abiertas (se abren solo si BTC está bajo su media de 200 "
                    "días, el activo tiene 0 o 1 de 8 señales y cierra bajo el mínimo de sus 20 cierres anteriores).")
    como.append("Adaptativa · " + X["veredicto"])
    hechas = [o for o in X["ops_hoy"] if not o["nota"].startswith("omitida")]
    if hechas:
        verbo = {"compra": "compró", "venta": "vendió", "abre corto": "abrió apuesta a la baja de",
                 "cierra corto": "cerró la apuesta a la baja de"}
        det = "; ".join(f"{verbo.get(o['lado'], o['lado'])} {f'{float(o['cantidad']):.8f}'.rstrip('0').replace('.', ',')} {o['activo']} "
                        f"a {usd(float(o['precio']))} ({usd(float(o['monto']))})" for o in hechas)
        hoy = [f"Adaptativa: {det}."]
    else:
        hoy = ["Adaptativa: sin cambios."]
    if R.get("ult") and X["ult"]["fecha_cierre"] != R["ult"]["fecha_cierre"]:
        hoy = [f"Adaptativa: no revisó el cierre del {fecha_larga(R['ult']['fecha_cierre'])} (última revisión: cierre del "
               f"{fecha_larga(X['ult']['fecha_cierre'])}); lo hace en la próxima."]
    hoy += [f"Adaptativa: no se hizo una orden ({o['activo']}, {o['lado']}): {o['nota']}." for o in X["ops_hoy"]
            if o["nota"].startswith("omitida")]
    esperado = [f"Adaptativa: diferencia con su simulación (mismas reglas, precios de cierre): {num(X['dif_ideal'] * 100)} "
                "puntos (solo informativo: este libro no cuenta para la fecha del dinero real)."]
    if X.get("problemas"):
        esperado.append("Adaptativa: " + " ".join(X["problemas"]))
    return {"como": como, "hoy": hoy, "esperado": esperado, "veredicto": X["veredicto"]}


# ---------------------------------------------------------------------------------------------- textos
def textos(R):
    """Bloques de texto (titulo, [(seccion, [lineas])]) que usan la página y el archivo del día."""
    L, m, cu, h = R["libros"], R["mercado"], R["cuenta"], R["historia"]
    t = L["tendencia"]
    s = []
    lineas = []
    for k, v in L.items():
        pos = " · ".join(f"{a} {pct(w, False)}" for a, w in v["pesos"].items())
        efectivo = 1 - sum(v["pesos"].values()) if v["pesos"] else 1
        lineas.append(f"{C.LIBROS[k]}: {usd(v['valor'])} ({pct(v['desde_inicio'])} desde el inicio, "
                      f"{pct(v['ayer'])} desde la revisión anterior). Posición: {pos} · efectivo {pct(efectivo, False)}.")
    dif = t["valor"] - L["mantener"]["valor"]
    lineas.append(f"La estrategia va {usd(abs(dif))} {'por encima' if dif >= 0 else 'por debajo'} de mantener quieto.")
    ad = lineas_adaptativa(R)
    lineas += ad.get("como", [])
    como = ("Cómo vamos", lineas)

    hoy = []
    for k, v in L.items():
        hechas = [o for o in v["ops_hoy"] if not o["nota"]]
        if hechas:
            det = "; ".join(f"{'compró' if o['lado'] == 'compra' else 'vendió'} {str(float(o['cantidad'])).replace('.', ',')} {o['activo']} "
                            f"a {usd(float(o['precio']))} ({usd(float(o['monto']))})" for o in hechas)
            hoy.append(f"{C.LIBROS[k]}: {det}.")
        else:
            hoy.append(f"{C.LIBROS[k]}: sin cambios (la diferencia con su objetivo no alcanza el 10%).")
    for a, x in m.items():
        n8 = round(x["senal"] * 8)
        hoy.append(f"{a}: {usd(x['precio'])} al cierre del {fecha_larga(x['fecha'])} ({pct(x['dia'])} en el día), "
                   f"{pct(x['precio'] / x['maximo'] - 1)} bajo su máximo histórico ({usd(x['maximo'])}, "
                   f"{fecha_larga(x['fecha_maximo'])}). Señales al alza: {n8} de 8 → la estrategia quiere "
                   f"{pct(x['senal'] / len(C.ACTIVOS), False)} del libro en {a}.")
    hoy += ad.get("hoy", [])
    s += [("Qué pasó hoy", hoy), como]

    esperado = [f"Diferencia con la simulación (mismas reglas, precios de cierre): {num(t['dif_ideal'] * 100)} puntos "
                f"(aceptable hasta ±{num(C.TOLERANCIA_PP, 1)}). Ajustes: práctica {t['ajustes']}, simulación {t['ajustes_ideal']}.",
                f"En la historia, en periodos de {len(R['diario'])} día(s) la estrategia quedó entre {pct(h['p10'])} y "
                f"{pct(h['p90'])} en 8 de cada 10 casos (mediana {pct(h['p50'])}). Ahora va {pct(t['desde_inicio'])}: "
                + ("dentro de lo normal." if h["p10"] <= t["desde_inicio"] <= h["p90"] else "fuera de lo habitual, sin ser imposible."),
                f"Caída desde su máximo en la práctica: {pct(t['caida'] + 0.0, False)}. La peor caída de la historia fue {pct(h['peor_caida'], False)}."]
    esperado += ad.get("esperado", [])
    s.append(("¿Va como esperábamos?", esperado))

    sa = R["salud"]
    salud = [f"Última revisión: {sa['ultima_corrida']} (hora de Colombia). "
             + ("Al día con el último cierre." if sa["al_dia"] else "NO está al día con el último cierre."),
             (f"Revisiones a tiempo: {sa['a_tiempo']} de {sa['contables']}. " if sa["contables"] else "Revisiones a tiempo: se cuentan desde el día 2. ")
             + f"Días sin revisión: {sa['sin_revision']}.",
             f"Errores en los últimos 7 días: {sa['errores_7d']}."
             + (f" Último: {sa['ultimo_error']}" if sa["ultimo_error"] else ""),
             "Datos: " + ("sin problemas." if not sa["problemas"] else " ".join(sa["problemas"]))]
    s.append(("¿El bot está funcionando?", salud))

    s.append(("Importante", R["avisos"] or ["Nada fuera de lo normal hoy."]))
    titulo = f"Trading cripto · etapa {C.ETAPA} · día {R['dia_n']} de la práctica · {R['estado']}"
    return titulo, s


