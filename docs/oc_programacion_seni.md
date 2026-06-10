# Fuente: Programación del SENI (OC) — feed diario/semanal

Flujo de alimentación para los **programas de despacho** que el OC publica en:

> https://www.oc.do/Informes/Operación-del-SENI/Programación-del-SENI

A diferencia del caso MODOM (que trae la **red**), esta fuente trae el **programa
operativo vigente**: cómo se va a despachar (diario/semanal), con los **CVP
declarados** y combustibles oficiales. Es la fuente que mantiene la plataforma
**actualizada al día**.

> **Para el agente (Grace):** cuando el usuario lo indique —o cuando haya un
> programa nuevo publicado— descarga los archivos de las subcarpetas, guárdalos en
> `data/external/programacion_seni/<subcarpeta>/` respetando el nombre del OC, y
> corre el extractor correspondiente (tabla de abajo). No inventes valores; si un
> archivo no está, deja el paso pendiente y avísalo.

## Estructura de la página (4 subcarpetas)

| Subcarpeta del OC | Cadencia | Qué trae | Archivos típicos |
|---|---|---|---|
| **1. PROGRAMACION SEMANAL** (PSD) | Semanal | Despacho semanal por mérito, **niveles de embalse** (hidro), factores de nodo, reservas, curtailment | `PSD_<dd-mm>_<dd-mm-aaaa>.xlsx`, `OC-GO-10-RPSO*.pdf`, `OC-GO-10-ASPPSO*.pdf` |
| **2. PROGRAMACION DIARIA** (PDD) | Diaria | Despacho diario por generador, demanda SENI, **Q de generadores**, factores de nodo, reservas, `Analisis_Electrico` | `PDD <dd-mm-aa>.xlsx`, `OC-GO-10-RPDO<aaaammdd>-V0.pdf` |
| **3. VEROPE** (verificación de operación) | Semanal | **CVP declarado** por unidad + **combustible oficial** + existencia de combustible | `VERIFICACION CVP_<dd-mm>_<dd-mm-aa>.xlsx` |
| **4. MISCELANEOS** | — | Documentos varios | (revisar caso a caso) |

## Dónde guardarlos

```
data/external/programacion_seni/
  semanal/   <- PSD + reportes (PROGRAMACION SEMANAL)
  diaria/    <- PDD + reporte (PROGRAMACION DIARIA)
  verope/    <- VERIFICACION CVP (VEROPE)
  misc/      <- MISCELANEOS
```

(Hasta ahora se subieron casos sueltos como `data/external/PDD 11-06-26/` y
`data/external/PSD_06-06_12-06-2026/`; el destino canónico es el de arriba.)

## Qué alimenta cada uno y cómo incorporarlo

| Dato | Hoja / archivo | Alimenta | Extractor | Estado |
|---|---|---|---|---|
| **CVP declarado + combustible oficial** | VEROPE → `COSTO VARIABLE DE PRODUCCIÓN` (col `CENTRAL`=generator_id, `COMBUSTIBLE`, `COSTO VARIABLE`) | reemplaza `effective_cvp` y la clasificación de combustible (hoy heurística del unifilar) → fidelidad de costos/precios/mezcla | `scripts/build_declared_cvp.py` (a crear) | **Recomendado primero** (fácil, alto valor, semanal). Cruza ~54/140 térmicos que declaran. |
| **Caso operativo diario** (despacho, demanda, Q gen, factores de nodo, reservas) | PDD → `DESPACHO EN OM`, `DEMANDA SENI`, `Gen_Pot_Reactiva`, `Factores de Nodo`, `Despacho de Reserva *` | caso vigente para el despacho + **validación diaria** (nuestro despacho vs el oficial) + latido del refresco de la plataforma | `scripts/build_pdd_case.py` (a crear) | Planeado |
| **Niveles de embalse (hidro)** | PSD → `Niveles de Embalse` (caudales afluentes por día + nivel inicial por central) | hidro como `StorageUnit` con presupuesto de energía (fidelidad de despacho, Fase 1) | (a crear) | Planeado |
| **Reservas / inercia / curtailment** | PDD/PSD → `Despacho de Reserva RPF/RSF-AGC`, `S_INERCIA`, `Curtailment` | co-optimización de reservas (Fase 2) | (a crear) | Futuro |

## Salvedad importante

Esta fuente **NO trae la red** (topología, impedancias, datos reactivos). Eso sigue
viniendo del MODOM (núcleo) y de DIgSILENT (reactivo). Por tanto **no desbloquea el
flujo AC de 24h** — para eso hace falta el export completo de DIgSILENT (ver
[`docs/`] y la memoria del proyecto). Sí mejora **costos, combustible, caso vigente,
validación y la actualización continua**.

## Llaves de cruce

- Generadores: `generator_id` (`G3…`) en la columna `CENTRAL`/`CÓDIGO`.
- Barras: códigos `W…` (las hojas de factores de nodo usan `BARRA`=código W).
- Eje temporal: 48 periodos (2 días) en los programas; usar los primeros 24 (día 1),
  igual que el resto del pipeline.
