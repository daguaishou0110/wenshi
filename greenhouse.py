"""Multi-greenhouse farm simulation + disease-driven linked climate control.

Demo model
----------
A protected-cultivation site with several houses. Each house has its own climate
state. A leaf scan is attributed to one active house; the policy engine then:

1. builds a primary plan for the scanned house;
2. emits linked spillover plans for neighbours (quarantine / preventive dry-down);
3. optionally applies all plans together (soft-PLC, in-memory).

Swap apply sinks later for MQTT / Modbus / vendor greenhouse controllers.
"""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Farm topology (simulation scene)
# ---------------------------------------------------------------------------

_HOUSE_DEFAULTS: dict[str, dict[str, Any]] = {
    "H1": {
        "house_id": "H1",
        "name": "House 1 — North",
        "crop": "Tomato (cluster A)",
        "zone": "north",
        "neighbours": ["H2"],
        "temp_c": 24.0,
        "rh_pct": 78.0,
        "vent_pct": 28.0,
        "fan_pct": 30.0,
        "fogger_on": False,
        "drip_mode": "normal",
        "shade_pct": 15.0,
        "heating_set_c": 17.5,
        "mode": "auto_assist",
        "quarantine": False,
        "alert": "nominal",
        "last_scan_class": None,
        "last_risk": "low",
    },
    "H2": {
        "house_id": "H2",
        "name": "House 2 — Centre",
        "crop": "Tomato (cluster B)",
        "zone": "centre",
        "neighbours": ["H1", "H3"],
        "temp_c": 25.2,
        "rh_pct": 84.0,
        "vent_pct": 22.0,
        "fan_pct": 25.0,
        "fogger_on": True,
        "drip_mode": "normal",
        "shade_pct": 25.0,
        "heating_set_c": 18.0,
        "mode": "auto_assist",
        "quarantine": False,
        "alert": "humid",
        "last_scan_class": None,
        "last_risk": "low",
    },
    "H3": {
        "house_id": "H3",
        "name": "House 3 — South",
        "crop": "Tomato (cluster C)",
        "zone": "south",
        "neighbours": ["H2", "H4"],
        "temp_c": 23.6,
        "rh_pct": 72.0,
        "vent_pct": 40.0,
        "fan_pct": 45.0,
        "fogger_on": False,
        "drip_mode": "normal",
        "shade_pct": 20.0,
        "heating_set_c": 17.0,
        "mode": "auto_assist",
        "quarantine": False,
        "alert": "nominal",
        "last_scan_class": None,
        "last_risk": "low",
    },
    "H4": {
        "house_id": "H4",
        "name": "House 4 — East bay",
        "crop": "Tomato (nursery)",
        "zone": "east",
        "neighbours": ["H3"],
        "temp_c": 22.8,
        "rh_pct": 68.0,
        "vent_pct": 35.0,
        "fan_pct": 40.0,
        "fogger_on": False,
        "drip_mode": "reduced",
        "shade_pct": 30.0,
        "heating_set_c": 18.5,
        "mode": "auto_assist",
        "quarantine": False,
        "alert": "nominal",
        "last_scan_class": None,
        "last_risk": "low",
    },
}

_HOUSES: dict[str, dict[str, Any]] = {
    k: copy.deepcopy(v) for k, v in _HOUSE_DEFAULTS.items()
}
_ACTIVE = "H2"
_AUDIT: list[dict[str, Any]] = []
_LAST_LINKED_PLAN: dict[str, Any] | None = None

_POLICIES: dict[str, dict[str, Any]] = {
    "Tomato___Late_blight": {
        "risk": "critical",
        "title": "Late blight — dry canopy + neighbour barrier",
        "rh_delta": -12,
        "vent_delta": +35,
        "fan_delta": +40,
        "fogger_on": False,
        "drip_mode": "reduced",
        "heating_set_delta": +1.5,
        "contagious": True,
        "notes": ["Cut leaf wetness", "Open vents / ramp fans", "Barrier-link neighbours"],
    },
    "Tomato___Leaf_Mold": {
        "risk": "high",
        "title": "Leaf mold — dehumidify + airflow",
        "rh_delta": -10,
        "vent_delta": +25,
        "fan_delta": +30,
        "fogger_on": False,
        "drip_mode": "reduced",
        "heating_set_delta": +1.0,
        "contagious": True,
        "notes": ["Overnight RH control", "Link humid neighbours preventively"],
    },
    "Tomato___Bacterial_spot": {
        "risk": "high",
        "title": "Bacterial spot — keep foliage dry",
        "rh_delta": -8,
        "vent_delta": +20,
        "fan_delta": +20,
        "fogger_on": False,
        "drip_mode": "reduced",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Drip only", "Tool hygiene between houses"],
    },
    "Tomato___Early_blight": {
        "risk": "medium",
        "title": "Early blight — moderate dry-down",
        "rh_delta": -6,
        "vent_delta": +15,
        "fan_delta": +15,
        "fogger_on": False,
        "drip_mode": "normal",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Improve basal airflow"],
    },
    "Tomato___Septoria_leaf_spot": {
        "risk": "medium",
        "title": "Septoria — airflow + sanitation",
        "rh_delta": -5,
        "vent_delta": +15,
        "fan_delta": +15,
        "fogger_on": False,
        "drip_mode": "normal",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Keep drip off foliage"],
    },
    "Tomato___Target_Spot": {
        "risk": "medium",
        "title": "Target spot — shorten wetness",
        "rh_delta": -6,
        "vent_delta": +18,
        "fan_delta": +18,
        "fogger_on": False,
        "drip_mode": "reduced",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Vent after irrigation"],
    },
    "Tomato__Spider_Mites": {
        "risk": "high",
        "title": "Spider mites — avoid over-drying",
        "rh_delta": +6,
        "vent_delta": +5,
        "fan_delta": +5,
        "fogger_on": False,
        "drip_mode": "normal",
        "heating_set_delta": -0.5,
        "temp_delta": -1.0,
        "contagious": False,
        "notes": ["Hot dry canopies favour mites", "Do not force late-blight dry-down"],
    },
    "Tomato_Yellow_Leaf_Curl_Virus": {
        "risk": "high",
        "title": "YLCV — biosecurity first",
        "rh_delta": -2,
        "vent_delta": +10,
        "fan_delta": +10,
        "fogger_on": False,
        "drip_mode": "normal",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Rogue plants", "Vector screen on linked houses"],
    },
    "Tomato_mosaic_virus": {
        "risk": "high",
        "title": "Mosaic virus — hygiene protocol",
        "rh_delta": 0,
        "vent_delta": +5,
        "fan_delta": +5,
        "fogger_on": False,
        "drip_mode": "normal",
        "heating_set_delta": 0.0,
        "contagious": True,
        "notes": ["Tool / hand sanitation across houses"],
    },
    "healthy_leaf": {
        "risk": "low",
        "title": "Healthy scan — hold setpoints",
        "rh_delta": 0,
        "vent_delta": 0,
        "fan_delta": 0,
        "fogger_on": None,
        "drip_mode": None,
        "heating_set_delta": 0.0,
        "contagious": False,
        "notes": ["Maintain current recipe"],
    },
}

_RISK_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _estimate_vpd(temp_c: float, rh_pct: float) -> float:
    es = 0.6108 * (2.71828 ** ((17.27 * temp_c) / (temp_c + 237.3)))
    return round(es * (1.0 - rh_pct / 100.0), 2)


def _enrich(house: dict[str, Any]) -> dict[str, Any]:
    h = copy.deepcopy(house)
    h["vpd_kpa"] = _estimate_vpd(float(h["temp_c"]), float(h["rh_pct"]))
    return h


def list_houses() -> list[dict[str, Any]]:
    order = ["H1", "H2", "H3", "H4"]
    return [_enrich(_HOUSES[i]) for i in order]


def get_farm() -> dict[str, Any]:
    houses = list_houses()
    risks = [_RISK_RANK.get(h.get("last_risk", "low"), 1) for h in houses]
    farm_risk = "low"
    for label, rank in (("critical", 4), ("high", 3), ("medium", 2)):
        if max(risks) >= rank:
            farm_risk = label
            break
    return {
        "site": "Canopy Farm — Multi-house simulation",
        "active_house_id": _ACTIVE,
        "farm_risk": farm_risk,
        "houses": houses,
        "links": [
            {"from": "H1", "to": "H2"},
            {"from": "H2", "to": "H3"},
            {"from": "H3", "to": "H4"},
        ],
        "last_linked_plan": _LAST_LINKED_PLAN,
        "audit": get_audit(12),
    }


def get_house(house_id: str) -> dict[str, Any]:
    if house_id not in _HOUSES:
        raise KeyError(house_id)
    return _enrich(_HOUSES[house_id])


def set_active(house_id: str) -> dict[str, Any]:
    global _ACTIVE
    if house_id not in _HOUSES:
        raise KeyError(house_id)
    _ACTIVE = house_id
    return get_farm()


def reset_farm() -> dict[str, Any]:
    global _HOUSES, _ACTIVE, _LAST_LINKED_PLAN
    _HOUSES = {k: copy.deepcopy(v) for k, v in _HOUSE_DEFAULTS.items()}
    _ACTIVE = "H2"
    _LAST_LINKED_PLAN = None
    return get_farm()


def get_audit(limit: int = 20) -> list[dict[str, Any]]:
    return list(reversed(_AUDIT[-limit:]))


def _snapshot(house: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "house_id",
        "name",
        "temp_c",
        "rh_pct",
        "vpd_kpa",
        "vent_pct",
        "fan_pct",
        "fogger_on",
        "drip_mode",
        "shade_pct",
        "heating_set_c",
        "mode",
        "quarantine",
        "alert",
        "last_risk",
    ]
    h = _enrich(house)
    return {k: h.get(k) for k in keys}


def _targets_from_policy(cur: dict[str, Any], policy: dict[str, Any], scale: float = 1.0) -> dict[str, Any]:
    targets = {
        "temp_c": round(
            _clip(cur["temp_c"] + float(policy.get("temp_delta", 0.0)) * scale, 16.0, 32.0), 1
        ),
        "rh_pct": round(
            _clip(cur["rh_pct"] + float(policy.get("rh_delta", 0.0)) * scale, 45.0, 95.0), 1
        ),
        "vent_pct": round(
            _clip(cur["vent_pct"] + float(policy.get("vent_delta", 0.0)) * scale, 0.0, 100.0), 0
        ),
        "fan_pct": round(
            _clip(cur["fan_pct"] + float(policy.get("fan_delta", 0.0)) * scale, 0.0, 100.0), 0
        ),
        "fogger_on": cur["fogger_on"] if policy.get("fogger_on") is None else bool(policy["fogger_on"]),
        "drip_mode": cur["drip_mode"] if policy.get("drip_mode") is None else policy["drip_mode"],
        "shade_pct": cur["shade_pct"],
        "heating_set_c": round(
            _clip(
                cur["heating_set_c"] + float(policy.get("heating_set_delta", 0.0)) * scale,
                12.0,
                24.0,
            ),
            1,
        ),
    }
    targets["vpd_kpa"] = _estimate_vpd(targets["temp_c"], targets["rh_pct"])
    return targets


def _actions(cur: dict[str, Any], targets: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    mapping = [
        ("rh_pct", "Humidity setpoint", "%"),
        ("vent_pct", "Roof / side vents", "%"),
        ("fan_pct", "Circulation fans", "%"),
        ("temp_c", "Air temperature", "°C"),
        ("heating_set_c", "Heating setpoint", "°C"),
    ]
    for key, label, unit in mapping:
        before, after = cur[key], targets[key]
        if abs(float(after) - float(before)) >= 0.05:
            actions.append({"actuator": key, "label": label, "from": before, "to": after, "unit": unit})
    if targets["fogger_on"] != cur["fogger_on"]:
        actions.append(
            {
                "actuator": "fogger_on",
                "label": "Fogger / misting",
                "from": cur["fogger_on"],
                "to": targets["fogger_on"],
                "unit": "bool",
            }
        )
    if targets["drip_mode"] != cur["drip_mode"]:
        actions.append(
            {
                "actuator": "drip_mode",
                "label": "Drip irrigation mode",
                "from": cur["drip_mode"],
                "to": targets["drip_mode"],
                "unit": "mode",
            }
        )
    return actions


def _pick_driver(detections: list[dict[str, Any]]) -> tuple[str, list[str], dict[str, Any]]:
    if not detections:
        return "no_detection", [], _POLICIES["healthy_leaf"]

    ranked = sorted(detections, key=lambda p: float(p.get("confidence", 0)), reverse=True)
    top_ids: list[str] = []
    for p in ranked[:5]:
        cid = p.get("class_id") or p.get("class_name")
        if cid and cid not in top_ids:
            top_ids.append(cid)

    driver = None
    for cid in top_ids:
        if cid != "healthy_leaf":
            driver = cid
            break
    if driver is None:
        driver = top_ids[0] if top_ids else "healthy_leaf"

    policy = copy.deepcopy(_POLICIES.get(driver, _POLICIES["healthy_leaf"]))
    for cid in top_ids:
        other = _POLICIES.get(cid)
        if other and _RISK_RANK.get(other["risk"], 0) > _RISK_RANK.get(policy["risk"], 0):
            policy = copy.deepcopy(other)
            driver = cid

    has_mites = "Tomato__Spider_Mites" in top_ids
    fungalish = any(
        x in top_ids
        for x in (
            "Tomato___Late_blight",
            "Tomato___Leaf_Mold",
            "Tomato___Early_blight",
            "Tomato___Target_Spot",
            "Tomato___Septoria_leaf_spot",
        )
    )
    if has_mites and fungalish and policy.get("rh_delta", 0) < -4:
        policy["rh_delta"] = max(policy["rh_delta"], -4)
        policy.setdefault("notes", []).append(
            "Mites + fungal signals: limited dry-down to avoid mite flare."
        )
    return driver, top_ids, policy


def build_linked_plan(
    detections: list[dict[str, Any]],
    *,
    house_id: str | None = None,
) -> dict[str, Any]:
    """Primary house plan + neighbour spillover (multi-greenhouse linkage)."""
    global _LAST_LINKED_PLAN
    hid = house_id or _ACTIVE
    if hid not in _HOUSES:
        raise KeyError(hid)

    primary = _HOUSES[hid]
    driver, top_ids, policy = _pick_driver(detections)
    if not detections:
        plan = {
            "plan_id": uuid.uuid4().hex[:10],
            "kind": "linked",
            "risk": "low",
            "title": "No detection — no multi-house climate change",
            "primary_house_id": hid,
            "primary_driver": "no_detection",
            "drivers": [],
            "house_plans": [],
            "notes": ["Recapture or continue scouting; do not change farm setpoints."],
            "requires_confirm": False,
            "farm_snapshot": get_farm(),
        }
        _LAST_LINKED_PLAN = plan
        return plan

    primary_targets = _targets_from_policy(primary, policy, scale=1.0)
    house_plans = [
        {
            "house_id": hid,
            "role": "primary",
            "name": primary["name"],
            "risk": policy.get("risk", "low"),
            "title": policy.get("title", "Primary climate plan"),
            "current": _snapshot(primary),
            "targets": primary_targets,
            "actions": _actions(primary, primary_targets),
            "quarantine": policy.get("risk") in {"high", "critical"} and policy.get("contagious", False),
            "notes": list(policy.get("notes", [])),
        }
    ]

    # Neighbour spillover: milder climate + optional quarantine flag
    if policy.get("contagious") and policy.get("risk") in {"medium", "high", "critical"}:
        scale = 0.55 if policy.get("risk") == "critical" else 0.4
        for nid in primary.get("neighbours", []):
            nh = _HOUSES[nid]
            spill = copy.deepcopy(policy)
            spill["title"] = f"Neighbour barrier — linked from {hid}"
            spill["notes"] = [
                f"Preventive linkage from {primary['name']}",
                "Milder dry-down / airflow than primary house",
                "Restrict staff / tool movement into primary bay",
            ]
            # mites policy should not force dry-down on neighbours
            if driver == "Tomato__Spider_Mites":
                spill["rh_delta"] = max(float(spill.get("rh_delta", 0)), 0)
            targets = _targets_from_policy(nh, spill, scale=scale)
            house_plans.append(
                {
                    "house_id": nid,
                    "role": "neighbour",
                    "name": nh["name"],
                    "risk": "medium" if policy.get("risk") == "critical" else "low",
                    "title": spill["title"],
                    "current": _snapshot(nh),
                    "targets": targets,
                    "actions": _actions(nh, targets),
                    "quarantine": policy.get("risk") == "critical",
                    "notes": spill["notes"],
                }
            )

    notes = [
        f"Scan attributed to {primary['name']}.",
        f"Primary driver: {driver}.",
    ]
    if len(house_plans) > 1:
        notes.append(
            f"Linked spillover prepared for {len(house_plans) - 1} neighbour house(s)."
        )
    else:
        notes.append("No contagious spillover required for this class.")

    plan = {
        "plan_id": uuid.uuid4().hex[:10],
        "kind": "linked",
        "risk": policy.get("risk", "low"),
        "title": policy.get("title", "Linked climate plan"),
        "primary_house_id": hid,
        "primary_driver": driver,
        "drivers": top_ids,
        "house_plans": house_plans,
        "notes": notes + list(policy.get("notes", [])),
        "requires_confirm": bool(house_plans[0]["actions"])
        or any(hp.get("quarantine") for hp in house_plans),
        "farm_snapshot": get_farm(),
    }
    # Backward-compatible single-house fields for older UI bits
    plan["current"] = house_plans[0]["current"]
    plan["targets"] = house_plans[0]["targets"]
    plan["actions"] = house_plans[0]["actions"]
    _LAST_LINKED_PLAN = plan
    return plan


# aliases used by older app paths
def build_plan(detections: list[dict[str, Any]], state: dict[str, Any] | None = None) -> dict[str, Any]:
    hid = (state or {}).get("house_id") or _ACTIVE
    return build_linked_plan(detections, house_id=hid)


def apply_plan(plan: dict[str, Any], *, operator: str = "demo") -> dict[str, Any]:
    """Apply primary + neighbour house plans to the farm soft-PLC."""
    global _LAST_LINKED_PLAN
    house_plans = plan.get("house_plans") or []
    if not house_plans and plan.get("targets"):
        # legacy single-house plan
        house_plans = [
            {
                "house_id": plan.get("primary_house_id") or _ACTIVE,
                "role": "primary",
                "targets": plan["targets"],
                "actions": plan.get("actions", []),
                "quarantine": False,
                "risk": plan.get("risk", "low"),
                "title": plan.get("title"),
            }
        ]

    applied = []
    for hp in house_plans:
        hid = hp["house_id"]
        if hid not in _HOUSES:
            continue
        house = _HOUSES[hid]
        if house.get("mode") == "manual_hold":
            return {
                "ok": False,
                "error": f"{hid} is in manual_hold; release hold before applying linked plans.",
            }
        before = _snapshot(house)
        targets = hp.get("targets") or {}
        for key in (
            "temp_c",
            "rh_pct",
            "vent_pct",
            "fan_pct",
            "fogger_on",
            "drip_mode",
            "shade_pct",
            "heating_set_c",
        ):
            if key in targets:
                house[key] = targets[key]
        house["vpd_kpa"] = _estimate_vpd(float(house["temp_c"]), float(house["rh_pct"]))
        if hp.get("quarantine"):
            house["quarantine"] = True
            house["alert"] = "quarantine"
        risk = hp.get("risk") or plan.get("risk") or "low"
        house["last_risk"] = risk
        if risk in {"high", "critical"}:
            house["alert"] = "disease"
        elif house["alert"] == "nominal" and float(house["rh_pct"]) >= 80:
            house["alert"] = "humid"
        if plan.get("primary_house_id") == hid:
            house["last_scan_class"] = plan.get("primary_driver")
        after = _snapshot(house)
        applied.append({"house_id": hid, "role": hp.get("role"), "before": before, "after": after})

    record = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "operator": operator,
        "plan_id": plan.get("plan_id"),
        "risk": plan.get("risk"),
        "title": plan.get("title"),
        "primary_house_id": plan.get("primary_house_id"),
        "applied": applied,
        "actions_total": sum(len(hp.get("actions") or []) for hp in house_plans),
    }
    _AUDIT.append(record)
    farm = get_farm()
    _LAST_LINKED_PLAN = plan
    return {"ok": True, "farm": farm, "state": get_house(plan.get("primary_house_id") or _ACTIVE), "audit": record}


def tick_simulation(step: float = 1.0) -> dict[str, Any]:
    """Lightweight ambient drift so the farm scene feels alive."""
    for house in _HOUSES.values():
        if house.get("quarantine"):
            continue
        # gentle RH drift toward 70–75 if fans high
        if house["fan_pct"] >= 50 and house["rh_pct"] > 70:
            house["rh_pct"] = round(_clip(house["rh_pct"] - 0.15 * step, 45, 95), 1)
        elif house["fogger_on"]:
            house["rh_pct"] = round(_clip(house["rh_pct"] + 0.2 * step, 45, 95), 1)
        house["vpd_kpa"] = _estimate_vpd(float(house["temp_c"]), float(house["rh_pct"]))
        if house["rh_pct"] >= 82 and house["alert"] == "nominal":
            house["alert"] = "humid"
        elif house["rh_pct"] < 78 and house["alert"] == "humid" and not house["quarantine"]:
            house["alert"] = "nominal"
    return get_farm()


# Back-compat helpers expected by older call sites
def get_state() -> dict[str, Any]:
    return get_house(_ACTIVE)


def reset_state() -> dict[str, Any]:
    return reset_farm()["houses"][1]  # H2 default after reset
