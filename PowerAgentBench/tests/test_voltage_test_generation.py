from scripts.generate_voltage_structural_test import selectable_ok, select_test


def row(cid, label, family, spatial="g1", vec=None, fp=None, cond="UNDERVOLTAGE"):
    return {"candidate_id": cid, "structure_class": label, "operating_family_id": family, "spatial_family_id": spatial,
            "physical_fingerprint": fp or cid, "physical_vector": vec or [float(len(cid)) * hash(cid) % 7 + 5.0, 5.0],
            "initial_voltage_condition": cond}


def test_dev_family_fingerprint_and_near_state_are_excluded():
    rows = [row("a", "S1", "dev_family", vec=[1.0, 1.0]), row("b", "S1", "f2", fp="dev_fp", vec=[3.0, 3.0]),
            row("c", "S1", "f3", vec=[1.01, 1.01]), row("d", "S1", "f4", vec=[9.0, 9.0])]
    chosen, rejected = select_test(rows, 2041, 4, ({"dev_family"}, {"dev_fp"}, [[1.0, 1.0]]))
    assert [r["candidate_id"] for r in chosen] == ["d"]
    assert {r["candidate_id"] for r in rejected} == {"a", "b", "c"}


def test_one_per_operating_family_and_feasibility_needs_two_s4_families():
    rows = [row("a", "S4", "same", "g1", [20.0, 1.0]), row("b", "S4", "same", "g2", [40.0, 1.0])]
    chosen, _ = select_test(rows, 2041, 24, (set(), set(), []))
    assert len(chosen) == 1
    full = [row(f"{label}{i}", label, f"{label}{i}", f"g{i % 2}", [5.0 if j == 24 * k + i else 0.0 for j in range(96)])
            for k, label in enumerate(("S1", "S2", "S3", "S4")) for i in range(24)]
    chosen, _ = select_test(full, 2041, 24, (set(), set(), []))
    assert selectable_ok(chosen, 24)
    assert not selectable_ok([r for r in chosen if r["structure_class"] != "S4"], 24)
