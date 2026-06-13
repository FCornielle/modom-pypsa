# Spec de extracción DIgSILENT/PowerFactory para la capa AC

Qué exportar del modelo PowerFactory del SENI (PDD) para construir la capa AC en
pandapower y **unirla por código exacto** a nuestro modelo MODOM. Pensado para
entregárselo a quien tenga PowerFactory (idealmente vía la API `powerfactory` en
Python o un script DPL).

## 3 reglas de oro

1. **`for_name` (Foreign Key) en TODOS los elementos.** Es el código del MODOM
   (barras = `W…`, generadores = `G3…`). Es la llave de cruce. *(El export anterior
   lo omitió → por eso solo cruzó 22%.)* Sin esto, nada machea limpio.
2. **Elemento ≠ tipo.** Cada elemento (`Elm*`) referencia su tipo (`Typ*`) por
   `typ_id`. **Exportar ambas tablas** e incluir `typ_id` en el elemento para poder
   unirlas. Los parámetros eléctricos por-km / de placa están en el **tipo**.
3. **Endpoints por `for_name`.** Para cada rama/elemento, exportar el **`for_name`
   de la(s) terminal(es) conectada(s)** (vía cubicle → terminal), no solo el nombre
   local. Así las conexiones quedan en códigos `W…` directamente.

Además: incluir **unidades** (ohm, %, MVA, kV, µS/km, Mvar), el flag **`outserv`**
(fuera de servicio) en todo, y anotar **a qué caso/escenario** (hora del PDD)
corresponden los valores operativos.

---

## Por elemento (ELEMENTO `Elm*` + TIPO `Typ*`)

### 1. Barras / nodos — `ElmTerm` *(sin tipo relevante)*
- `loc_name`, **`for_name`** (→ barra `W…`), `uknom` (kV nominal), `outserv`,
  `cpSubstat` (subestación), `cpArea`, `cpZone`, `iUsage` (barra/nodo interno),
  `GPSlat`, `GPSlon` (coordenadas — bonus para el mapa).

### 2. Líneas — `ElmLne` + tipo `TypLne`
- **Elemento `ElmLne`**: `loc_name`, **`for_name`**, `typ_id`, `for_name` de
  **terminal i y j**, `dline` (longitud km), `nlnum` (# paralelas), `outserv`,
  `Inom`, y los **calculados** `R1, X1, B1, R0, X0, B0, G1` (ohm/µS totales — sirven
  directo).
- **Tipo `TypLne`**: `loc_name`, `rline` (R1 ohm/km), `xline` (X1 ohm/km),
  `bline` (B1 µS/km), `cline` (C1 µF/km), `gline`, `rline0, xline0, bline0` (sec.
  cero), `sline`/`Inom` (kA), `uline` (kV), conductor/sección, `aohl_` (aérea/cable).

### 3. Transformadores 2 dev. — `ElmTr2` + tipo `TypTr2`
- **Elemento `ElmTr2`**: `loc_name`, **`for_name`**, `typ_id`, `for_name` de
  **terminal AT y BT**, `nntap` (posición de tap actual), `ntnum` (# paralelos),
  `i_cont` (tap automático on/off), `usetp` (consigna de tensión OLTC, pu),
  `c_ptapc`/nodo controlado, `outserv`.
- **Tipo `TypTr2`**: `strn` (Sn MVA), `utrn_h`/`utrn_l` (kV AT/BT), **`uktr` (Ucc/vk %)**,
  `uktrr` (vkr %), `pcutr` (pérdidas cobre kW), `pfe` (pérdidas hierro kW),
  `curmg` (i0 %), `vecgrp`/`tr2cn_h`/`tr2cn_l` (grupo vectorial), `tap_side`,
  `dutap` (paso de tap %), `phitr` (desfase), `nntap0` (tap neutro),
  `ntpmn`/`ntpmx` (tap mín/máx).

### 4. Transformadores 3 dev. — `ElmTr3` + tipo `TypTr3` *(si hay)*
- **Elemento**: `for_name`, `typ_id`, `for_name` de terminal AT/MT/BT, taps por
  devanado, `outserv`.
- **Tipo**: `strn3_h/m/l` (MVA), `utrn3_h/m/l` (kV), `uktr3_*` (vk% por par
  AT-MT/AT-BT/MT-BT), `uktrr3_*`, grupos vectoriales, taps.

### 5. Generadores síncronos — `ElmSym` + tipo `TypSym`
- **Elemento `ElmSym`**: `loc_name`, **`for_name`** (→ `G3…`), `typ_id`,
  `for_name` de terminal, `ngnum` (# unidades), `pgini` (P despachada MW),
  `qgini` (Q Mvar), `usetp` (consigna V pu), `av_mode` (modo: constv/constq…),
  **`q_min`/`q_max`** (límites de reactiva Mvar), `P_max`, `Pmax_uc`/`Pmin_uc`,
  `ip_ctrl` (¿máquina de referencia/slack?), `outserv`, `cCategory`.
- **Tipo `TypSym`**: `sgn` (Sn MVA), `ugn` (kV), `cosn` (fp), `Q_max`/`Q_min` o
  curva de capabilidad si está en el tipo. *(Las reactancias xd/xq… son para
  dinámica, no hacen falta para flujo.)*

### 6. Generadores estáticos (solar/eólico/BESS) — `ElmGenstat` *(tipo opcional `TypStat`)*
- `loc_name`, **`for_name`**, `for_name` de terminal, `sgn` (MVA), `cosn`,
  `pgini`, `qgini`, `usetp`, `av_mode`, **`q_min`/`q_max`**, `P_max`, `outserv`,
  `cCategory` (tecnología: PV/eólico/almacenamiento).

### 7. Shunts / filtros — `ElmShnt` *(sin tipo)*
- `loc_name`, **`for_name`**, `for_name` de terminal, `shtype` (tipo: C, R-L, R-L-C…),
  `qtotn` (Mvar nominal), `ushnm` (kV), `ncapx` (# pasos máx), `ncapa` (paso actual),
  `ccap` (capacitancia), `rlrea` (reactancia/inductancia), `systp`, `outserv`,
  `c_pctrl`/`usetp` (si controla tensión).

### 8. Cargas — `ElmLod` + tipo `TypLod`
- **Elemento `ElmLod`**: `loc_name`, **`for_name`**, `typ_id`, `for_name` de terminal,
  `plini` (P MW), `qlini` (Q Mvar), `coslini` (fp), `scale0` (escalado), `outserv`.
- **Tipo `TypLod`**: coeficientes ZIP / dependencia de tensión (`aP,bP,cP,aQ,bQ,cQ`,
  `kpu,kqu`) — secundario para flujo, incluir si está.

### 9. Acoples / interruptores — `ElmCoup` (+ `StaSwitch` en cubicles)
*(Para conectividad/islas y para reducir el modelo de 4992 terminales.)*
- `ElmCoup`: `loc_name`, **`for_name`**, `for_name` de terminal i/j, `on_off`
  (cerrado/abierto), `aUsage` (interruptor/seccionador), `outserv`.
- `StaSwitch`: `on_off` por cubicle (estado de conexión de cada elemento a su barra).

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
- Un **CSV por clase** (como el export `salida_PDD_*`), pero **agregando `for_name`**
  en todos y el `for_name` de las terminales conectadas; más las tablas `Typ*`.
- O un solo `.xlsx` con una hoja por clase (formato `digsilent 2023.xlsx`).
- Indicar **unidades** en los encabezados y el **caso/hora** del PDD exportado.

## Por qué así
Con `for_name` (cruce exacto al MODOM) + `Elm*`/`Typ*` unidos por `typ_id`, se
reconstruye la red AC completa (R/X/B reales, Ucc%/taps, shunts, límites Q,
conectividad) y se **inyecta nuestro despacho MODOM por código** — sin matching
fuzzy. Es lo que destraba la convergencia del flujo AC de 24 h.
