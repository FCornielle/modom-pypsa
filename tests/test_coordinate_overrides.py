from pathlib import Path

from modom_pypsa.smc_coordinates import apply_coordinate_overrides


def test_apply_coordinate_overrides_updates_matching_bus(tmp_path: Path) -> None:
    override_csv = tmp_path / "coordinate_overrides.csv"
    override_csv.write_text(
        "\n".join(
            [
                "bus_id_modom,lat,lon,coord_source,based_on_bus_id,rationale",
                "WBUS1,18.5,-69.9,manual_override,WBUS2,test reason",
            ]
        ),
        encoding="utf-8",
    )
    rows = [
        {"bus_id_modom": "WBUS1", "lat": "", "lon": "", "coord_source": ""},
        {"bus_id_modom": "WBUS2", "lat": "19.0", "lon": "-70.0", "coord_source": "smc_match"},
    ]

    summary = apply_coordinate_overrides(rows, override_csv)

    assert summary["applied_count"] == 1
    assert rows[0]["lat"] == 18.5
    assert rows[0]["lon"] == -69.9
    assert rows[0]["coord_source"] == "manual_override"


def test_apply_coordinate_overrides_ignores_unknown_bus(tmp_path: Path) -> None:
    override_csv = tmp_path / "coordinate_overrides.csv"
    override_csv.write_text(
        "\n".join(
            [
                "bus_id_modom,lat,lon,coord_source",
                "WUNKNOWN,18.5,-69.9,manual_override",
            ]
        ),
        encoding="utf-8",
    )
    rows = [{"bus_id_modom": "WBUS1", "lat": "", "lon": "", "coord_source": ""}]

    summary = apply_coordinate_overrides(rows, override_csv)

    assert summary["applied_count"] == 0
    assert rows[0]["lat"] == ""
