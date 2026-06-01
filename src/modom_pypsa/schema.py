"""Definiciones base para la capa canonica del proyecto.

Este modulo no implementa extraccion ni validacion todavia. Su funcion inicial es
dejar claro el contrato conceptual de las tablas que alimentaran a PyPSA.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalTable:
    """Describe una tabla canonica del proyecto.

    Attributes
    ----------
    name:
        Nombre estable de la tabla dentro del proyecto.
    purpose:
        Para que existe la tabla dentro del flujo.
    modom_sources:
        Hojas o artefactos de MODOM que alimentan esta tabla.
    pypsa_target:
        Componente o uso esperado dentro de PyPSA.
    grain:
        Granularidad principal de la tabla, por ejemplo por barra, por unidad o
        por barra-periodo.
    notes:
        Comentario corto para aclarar supuestos o decisiones de modelado.
    """

    name: str
    purpose: str
    modom_sources: tuple[str, ...]
    pypsa_target: str
    grain: str
    notes: str


CANONICAL_TABLES: tuple[CanonicalTable, ...] = (
    CanonicalTable(
        name="buses",
        purpose="Inventario de barras y atributos electricos base.",
        modom_sources=("e_datred", "MAPEO TODAS LAS BARRAS"),
        pypsa_target="network.buses",
        grain="una fila por barra",
        notes=(
            "Debe consolidar identificadores de barra, nombre, nivel de tension "
            "y metadatos necesarios para un mapeo estable."
        ),
    ),
    CanonicalTable(
        name="branches",
        purpose="Lineas y transformadores con impedancias, limites y estado base.",
        modom_sources=("e_datred",),
        pypsa_target="network.lines / network.transformers",
        grain="una fila por activo serie de red",
        notes=(
            "Debe separar lineas y transformadores si MODOM los mezcla en una "
            "misma hoja logica."
        ),
    ),
    CanonicalTable(
        name="generators",
        purpose="Catalogo de unidades de generacion y parametros operativos base.",
        modom_sources=("e_datgen", "MAPEO CENTRALES DE GENERACION"),
        pypsa_target="network.generators / network.storage_units",
        grain="una fila por unidad o bloque generador",
        notes=(
            "Debe conservar el identificador operativo de MODOM y el nodo de "
            "conexion para no perder trazabilidad."
        ),
    ),
    CanonicalTable(
        name="loads_time_series",
        purpose="Demanda por barra y periodo.",
        modom_sources=("e_datdem", "PDemanda"),
        pypsa_target="network.loads_t.p_set",
        grain="una fila por barra-periodo",
        notes=(
            "La demanda debe quedar en formato largo aunque el workbook la traiga "
            "en formato ancho."
        ),
    ),
    CanonicalTable(
        name="generator_availability",
        purpose="Disponibilidad operativa de unidades por periodo.",
        modom_sources=("Reporte de Disponibilidad",),
        pypsa_target="network.generators_t.p_max_pu",
        grain="una fila por unidad-periodo",
        notes=(
            "Debe distinguir disponibilidad tecnica, derates y estados fuera de "
            "servicio cuando existan."
        ),
    ),
    CanonicalTable(
        name="renewable_profiles",
        purpose="Perfiles temporales de generacion renovable pronosticada.",
        modom_sources=("Pronostico Renovable",),
        pypsa_target="network.generators_t.p_max_pu",
        grain="una fila por recurso-periodo",
        notes=(
            "Conviene separar solar, eolica y otras tecnologias si la hoja las "
            "mezcla."
        ),
    ),
    CanonicalTable(
        name="branch_outages",
        purpose="Indisponibilidades y cambios de estado de elementos de red.",
        modom_sources=("e_modred", "Mantenimientos Red Transmision"),
        pypsa_target="aplicacion de estados por snapshot antes del power flow",
        grain="una fila por activo-periodo-evento",
        notes=(
            "Esta tabla modifica el estado base de branches y puede afectar tanto "
            "capacidad como disponibilidad."
        ),
    ),
    CanonicalTable(
        name="hydro_units",
        purpose="Catalogo y parametros base de unidades o sistemas hidraulicos.",
        modom_sources=("e_hidro", "e_datgen"),
        pypsa_target="network.storage_units / network.generators",
        grain="una fila por activo hidraulico",
        notes=(
            "Puede requerir separar centrales hidraulicas, embalses y relaciones "
            "hidrologicas en tablas distintas."
        ),
    ),
    CanonicalTable(
        name="hydro_time_series",
        purpose="Condiciones hidrologicas variables por periodo.",
        modom_sources=("e_hidro",),
        pypsa_target="series para inflows, restricciones energeticas o disponibilidad",
        grain="una fila por activo hidraulico-periodo",
        notes=(
            "Aqui deben quedar inflows, niveles, limites energeticos u otras "
            "variables temporales que apliquen."
        ),
    ),
    CanonicalTable(
        name="snapshots",
        purpose="Definicion del horizonte temporal del caso diario.",
        modom_sources=("e_sets",),
        pypsa_target="network.snapshots",
        grain="una fila por periodo",
        notes=(
            "Debe fijar orden temporal, etiqueta del periodo y cualquier relacion "
            "con bloques horarios del caso."
        ),
    ),
    CanonicalTable(
        name="modom_results_reference",
        purpose="Resultados de referencia de MODOM para validar la replica en PyPSA.",
        modom_sources=("S_FLUJO", "VOLTAJE", "S_FNODO", "CMG"),
        pypsa_target="backtesting y validacion post-construccion",
        grain="varia segun el tipo de resultado",
        notes=(
            "No alimenta directamente la construccion del modelo; sirve para "
            "comparar flujos, tensiones y precios nodales."
        ),
    ),
)
