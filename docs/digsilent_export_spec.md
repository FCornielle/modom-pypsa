# Spec de extracción DIgSILENT/PowerFactory para la capa AC

Qué exportar del modelo PowerFactory del SENI (PDD) para construir la capa AC en
pandapower y **unirla por código exacto** a nuestro modelo MODOM. Pensado para
entregárselo a quien tenga PowerFactory (idealmente vía la API `powerfactory` en
Python o un script DPL).

## 4 reglas de oro

1. **PATH único del terminal (`_id`) en CADA extremo de CADA rama** *(la más
   importante para la conectividad)*. Para toda rama —líneas, **transformadores 2 y 3
   devanados**, interruptores, y la barra de conexión de gen/carga/shunt— exportar el
   **path completo del terminal conectado** (el `ruta` único del `ElmTerm`), igual que
   las líneas ya traen `barra_i_id`/`barra_j_id`. **Este es el único identificador
   ÚNICO y fiable de conexión.**
2. **`for_name` (Foreign Key) en TODOS los elementos.** Es el código del MODOM
   (barras = `W…`, generadores = `G3…`). Es la llave de cruce con nuestro modelo. Útil
   pero **NO sustituye al path**: muchos `for_name` están vacíos (lado HV de trafos) y
   los nombres de terminal son genéricos.
3. **Elemento ≠ tipo.** Cada elemento (`Elm*`) referencia su tipo (`Typ*`) por
   `typ_id`. **Exportar ambas tablas** e incluir `typ_id` en el elemento. Los
   parámetros eléctricos por-km / de placa están en el **tipo**.
4. **Unidades + estado.** Incluir **unidades** (ohm, %, MVA, kV, µS/km, Mvar), el flag
   **`outserv`** en todo, y anotar **a qué caso/hora del PDD** corresponden los valores.

> ⚠️ **Lección del export de dic-2024 (NO repetir):** las **líneas** traían el path
> (`barra_i_id`) y enlazaron al 100%; los **transformadores** trajeron solo
> nombre + `for_name` (SIN path) → con nombres de terminal genéricos ("T2.1") y el lado
> HV sin `for_name`, **0 de 157 trafos pudieron puentear las islas de 69 kV → ~330 MW
> quedaron desconectados**. **Cada rama necesita el path `_id` de sus dos extremos.**
> Para trafos: **`barra(bushv)_id` y `barra(buslv)_id`** son OBLIGATORIOS.

---

## Por elemento (ELEMENTO `Elm*` + TIPO `Typ*`)

### 1. Barras / nodos — `ElmTerm` *(sin tipo relevante)*
- `loc_name`, **`for_name`** (→ barra `W…`), `uknom` (kV nominal), `outserv`,
  `cpSubstat` (subestación), `cpArea`, `cpZone`, `iUsage` (barra/nodo interno),
  `GPSlat`, `GPSlon` (coordenadas — bonus para el mapa).

### 2. Líneas — `ElmLne` + tipo `TypLne`
- **Elemento `ElmLne`**: `loc_name`, **`for_name`**, `typ_id`,
  **`barra_i_id` y `barra_j_id` (PATH único de cada terminal — OBLIGATORIO)** +
  `barra_i_for`/`barra_j_for` (for_name de cada terminal), `dline` (longitud km),
  `nlnum` (# paralelas), `outserv`, `Inom`, y los **calculados**
  `R1, X1, B1, R0, X0, B0, G1` (ohm/µS totales — sirven directo).
- **Tipo `TypLne`**: `loc_name`, `rline` (R1 ohm/km), `xline` (X1 ohm/km),
  `bline` (B1 µS/km), `cline` (C1 µF/km), `gline`, `rline0, xline0, bline0` (sec.
  cero), `sline`/`Inom` (kA), `uline` (kV), conductor/sección, `aohl_` (aérea/cable).

### 3. Transformadores 2 dev. — `ElmTr2` + tipo `TypTr2`
- **Elemento `ElmTr2`**: `loc_name`, **`for_name`**, `typ_id`,
  **🔑 `barra(bushv)_id` y `barra(buslv)_id` (PATH único del terminal AT y BT —
  OBLIGATORIO; lo que FALTÓ en el export de dic-2024)** + `barra(bushv)_for`/
  `barra(buslv)_for` (for_name de cada lado), `nntap` (posición de tap actual),
  `ntnum` (# paralelos), `i_cont` (tap automático on/off), `usetp` (consigna OLTC, pu),
  `c_ptapc`/nodo controlado, `outserv`.
- **Tipo `TypTr2`**: `strn` (Sn MVA), `utrn_h`/`utrn_l` (kV AT/BT), **`uktr` (Ucc/vk %)**,
  `uktrr` (vkr %), `pcutr` (pérdidas cobre kW), `pfe` (pérdidas hierro kW),
  `curmg` (i0 %), `vecgrp`/`tr2cn_h`/`tr2cn_l` (grupo vectorial), `tap_side`,
  `dutap` (paso de tap %), `phitr` (desfase), `nntap0` (tap neutro),
  `ntpmn`/`ntpmx` (tap mín/máx).

### 4. Transformadores 3 dev. — `ElmTr3` + tipo `TypTr3` *(si hay)*
- **Elemento**: `for_name`, `typ_id`,
  **🔑 `barra(bushv)_id`/`barra(busmv)_id`/`barra(buslv)_id` (PATH de terminal
  AT/MT/BT — OBLIGATORIO)** + sus `_for`, taps por devanado, `outserv`.
- **Tipo**: `strn3_h/m/l` (MVA), `utrn3_h/m/l` (kV), `uktr3_*` (vk% por par
  AT-MT/AT-BT/MT-BT), `uktrr3_*`, grupos vectoriales, taps.

### 5. Generadores síncronos — `ElmSym` + tipo `TypSym`
- **Elemento `ElmSym`**: `loc_name`, **`for_name`** (→ `G3…`), `typ_id`,
  **`barra_con_id` (PATH de la barra de conexión) + `barra_con_for`**,
  `ngnum` (# unidades), `pgini` (P despachada MW),
  `qgini` (Q Mvar), `usetp` (consigna V pu), `av_mode` (modo: constv/constq…),
  **`q_min`/`q_max`** (límites de reactiva Mvar), `P_max`, `Pmax_uc`/`Pmin_uc`,
  `ip_ctrl` (¿máquina de referencia/slack?), `outserv`, `cCategory`.
- **Tipo `TypSym`**: `sgn` (Sn MVA), `ugn` (kV), `cosn` (fp), `Q_max`/`Q_min` o
  curva de capabilidad si está en el tipo. *(Las reactancias xd/xq… son para
  dinámica, no hacen falta para flujo.)*

### 6. Generadores estáticos (solar/eólico/BESS) — `ElmGenstat` *(tipo opcional `TypStat`)*
- `loc_name`, **`for_name`**, **`barra_con_id` (PATH) + `barra_con_for`**, `sgn` (MVA), `cosn`,
  `pgini`, `qgini`, `usetp`, `av_mode`, **`q_min`/`q_max`**, `P_max`, `outserv`,
  `cCategory` (tecnología: PV/eólico/almacenamiento).

### 7. Shunts / filtros — `ElmShnt` *(sin tipo)*
- `loc_name`, **`for_name`**, **`barra_con_id` (PATH) + `barra_con_for`**, `shtype` (tipo: C, R-L, R-L-C…),
  `qtotn` (Mvar nominal), `ushnm` (kV), `ncapx` (# pasos máx), `ncapa` (paso actual),
  `ccap` (capacitancia), `rlrea` (reactancia/inductancia), `systp`, `outserv`,
  `c_pctrl`/`usetp` (si controla tensión).

### 8. Cargas — `ElmLod` + tipo `TypLod`
- **Elemento `ElmLod`**: `loc_name`, **`for_name`**, `typ_id`, **`barra_con_id` (PATH) + `barra_con_for`**,
  `plini` (P MW), `qlini` (Q Mvar), `coslini` (fp), `scale0` (escalado), `outserv`.
- **Tipo `TypLod`**: coeficientes ZIP / dependencia de tensión (`aP,bP,cP,aQ,bQ,cQ`,
  `kpu,kqu`) — secundario para flujo, incluir si está.

### 9. Acoples / interruptores — `ElmCoup` (+ `StaSwitch` en cubicles)
*(Para conectividad/islas y para fusionar el modelo de 4992 terminales a nodos.)*
- `ElmCoup`: `loc_name`, **`for_name`**,
  **🔑 `barra_i_id`/`barra_j_id` (PATH de terminal i/j — OBLIGATORIO)** + sus `_for`,
  `on_off` (cerrado/abierto), `aUsage` (interruptor/seccionador), `outserv`.
- `StaSwitch`: `on_off` por cubicle (estado de conexión de cada elemento a su barra),
  con el **path del terminal** y del elemento.

### 10. Red externa / slack — `ElmXnet`
- `loc_name`, **`for_name`**, `for_name` de terminal, `bustp` (SL/PV/PQ),
  `usetp` (V pu), `phiini` (ángulo), `outserv`. **Identificar cuál es el slack.**

### 11. Compensación dinámica — `ElmSvs` (SVC) / condensadores síncronos *(si hay)*
- `loc_name`, **`for_name`**, terminal, rango Q (`qmin`/`qmax`), `usetp`, control.

### 12. Controladores de estación — `ElmStactrl`
*(Quién controla la tensión de qué nodo y a qué consigna — OLTC y gen en V.)*
- `loc_name`, **`for_name`**, nodo controlado (`for_name`), `usetp`, máquinas/trafos
  controlados, `i_ctrl`/modo.

---

## Formato de entrega
- Un **CSV por clase** (como `salida_PDD_*`), con **(a)** el **PATH `_id` de cada
  terminal** en TODAS las ramas (líneas, **trafos 2/3 dev.**, interruptores, y barra
  de conexión de gen/carga/shunt), **(b)** el **`for_name`** en todo, y **(c)** las
  tablas `Typ*` unidas por `typ_id`.
- O un solo `.xlsx` con una hoja por clase (formato `digsilent 2023.xlsx`).
- Indicar **unidades** en los encabezados y el **caso/hora** del PDD exportado.

> ✅ **Checklist mínimo para no repetir el problema:** cada fila de `ElmLne`,
> `ElmTr2`, `ElmTr3`, `ElmCoup`, `ElmSym`, `ElmGenstat`, `ElmLod`, `ElmShnt` debe
> traer el **path `_id` de su(s) terminal(es)**. Si una rama no trae el path de sus
> dos extremos, no se puede ubicar en la red y genera islas.

## Por qué así
La **conectividad** se reconstruye con el **path `_id` de cada terminal** (único y
fiable); el **cruce con el MODOM** con el **`for_name`**; y los **parámetros
eléctricos** uniendo `Elm*`/`Typ*` por `typ_id`. Con los tres, se arma la red AC
completa (R/X/B reales, Ucc%/taps, shunts, límites Q) y se **inyecta nuestro despacho
MODOM por código** — sin matching fuzzy ni islas. Es lo que destraba el flujo AC.
Sin el path de los trafos (export dic-2024), ~330 MW quedaron islados.
