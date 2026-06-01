from __future__ import annotations

from pathlib import Path

from modom_pypsa.smc_coordinates import (
    join_coordinates,
    normalize,
    to_float,
    token_set,
)


def test_normalize_and_tokens() -> None:
    assert normalize("Parque Eólico  Los Cocos") == "PARQUE EOLICO LOS COCOS"
    # stopwords y sufijos de unidad (T01) se descartan en el set de tokens
    assert token_set("PARQUE EOLICO LOS COCOS T01") == frozenset({"COCOS"})


def test_to_float_strips_suffix() -> None:
    assert to_float("18.272838S") == 18.272838
    assert to_float("-71.5") == -71.5
    assert to_float("") is None


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def test_join_coordinates(tmp_path: Path) -> None:
    data = tmp_path / "processed"
    _write(
        data / "buses" / "buses.csv",
        "bus_id_modom,bus_name,bus_name_legacy,v_nom_kv,bus_role",
        ["WPNORE,PLANTA NORTE,,138.0,network", "WCSURF,CIUDAD SUR,,69.0,network"],
    )
    _write(
        data / "generators" / "generators.csv",
        "generator_id,generator_name,bus_id",
        ["G1,PLANTA NORTE UNIDAD,WPNORE"],
    )
    _write(
        data / "loads_time_series" / "smc_load_registry.csv",
        "load_id_raw,resolved_bus_id,load_name_examples",
        ["ZCSURF-D1,WCSURF,['CIUDAD SUR']"],
    )
    oc = tmp_path / "oc_smc_points.csv"
    _write(
        oc,
        "lat,lon,punto,tipo,tension,agente",
        [
            "19.0,-70.0,PLANTA NORTE,CENTRAL,138 KV,EGEHID",       # exacto -> WPNORE
            "19.2,-70.2,PARQUE PLANTA NORTE T1,CENTRAL,138 KV,X",  # fuzzy  -> WPNORE
            "18.0,-71.0,CIUDAD SUR,RETIRO,69 KV,EDESUR",           # exacto -> WCSURF
            "17.5,-68.5,LUGAR DESCONOCIDO,RETIRO,138 KV,Z",        # sin match
        ],
    )

    payload = join_coordinates(data_dir=data, oc_csv=oc)
    summary = payload["summary"]
    assert summary["oc_points_total"] == 4
    assert summary["oc_points_unmatched"] == 1
    assert summary["buses_with_coordinates"] == 2

    by_bus = {r["bus_id_modom"]: r for r in payload["bus_rows"]}
    # WPNORE recibe dos puntos OC -> coords promediadas (19.1, -70.1)
    assert by_bus["WPNORE"]["oc_point_count"] == 2
    assert by_bus["WPNORE"]["lat"] == 19.1
    assert by_bus["WPNORE"]["lon"] == -70.1
    assert by_bus["WCSURF"]["lat"] == 18.0
