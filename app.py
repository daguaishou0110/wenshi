"""
Canopy Disease — multi-greenhouse leaf scan + linked climate simulation.

Local:  python app.py
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

import greenhouse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
UPLOADS = STATIC / "uploads"
KNOWLEDGE = ROOT / "knowledge"
LOGS = ROOT / "logs"
UPLOADS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("OPENCLAW_BASE_URL", "https://openclaw-api.com/v1")
API_KEY = os.getenv("OPENCLAW_API_KEY", "")
DEFAULT_MODEL = os.getenv("OPENCLAW_MODEL", "claude-haiku-4-5-20251001")
CONF_THRESHOLD = float(os.getenv("EXPLAIN_CONF_THRESHOLD", "0.55"))
DETECT_CONF = float(os.getenv("YOLO_CONF", "0.25"))
DEFAULT_WEIGHTS = ROOT / "weights" / "best.onnx"

app = FastAPI(title="Canopy Disease Farm")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY else None

with (KNOWLEDGE / "disease_kb.json").open(encoding="utf-8") as f:
    KB: dict[str, Any] = json.load(f)

_LAST: dict[str, Any] | None = None

SYSTEM_PROMPT = """Greenhouse multi-house advisory assistant. Use only the JSON facts given.
Style: clear English for technicians; 80-120 words; no model/API/thesis jargon.
Cover: scanned house + disease; primary climate actions; neighbour linkage if any; one caution line.
End: assisted screening, not lab diagnosis.
"""


class ExplainRequest(BaseModel):
    model: str | None = None


class ApplyRequest(BaseModel):
    plan_id: str | None = None
    operator: str = "demo"


class ActiveHouseRequest(BaseModel):
    house_id: str


def _kb_snippets(class_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for cid in class_ids:
        key = cid if cid in KB else "no_detection"
        if key in seen:
            continue
        seen.add(key)
        out.append({"class_id": key, **KB[key]})
    if not out:
        out.append({"class_id": "no_detection", **KB["no_detection"]})
    return out


def _build_bundle(detect: dict[str, Any], house_id: str) -> dict[str, Any]:
    preds = detect.get("predictions", [])
    class_ids = [p["class_id"] for p in preds] or ["no_detection"]
    max_conf = max((p["confidence"] for p in preds), default=0.0)
    plan = greenhouse.build_linked_plan(preds, house_id=house_id)
    farm = greenhouse.get_farm()
    return {
        "n_detections": detect["n_detections"],
        "class_counts": detect.get("class_counts", {}),
        "predictions": [
            {
                "class_id": p["class_id"],
                "class_name": p["class_name"],
                "confidence": p["confidence"],
                "bbox_xyxy": p["bbox_xyxy"],
            }
            for p in preds[:20]
        ],
        "detect_conf": detect["conf_threshold"],
        "confidence_threshold": CONF_THRESHOLD,
        "low_confidence": bool(preds) and max_conf < CONF_THRESHOLD,
        "no_detection": len(preds) == 0,
        "knowledge_snippets": _kb_snippets(class_ids[:3]),
        "house_id": house_id,
        "greenhouse_state": greenhouse.get_house(house_id),
        "farm": farm,
        "control_plan": plan,
        "overlay_image": detect["overlay_image"],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "yolo_ready": Path(DEFAULT_WEIGHTS).exists(),
        "api_ready": bool(client),
        "product": "Canopy Disease Farm",
        "houses": len(greenhouse.list_houses()),
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    farm = greenhouse.get_farm()
    return {
        "default_model": DEFAULT_MODEL,
        "api_ready": bool(client),
        "yolo_ready": Path(DEFAULT_WEIGHTS).exists(),
        "yolo_weights": Path(DEFAULT_WEIGHTS).name,
        "yolo_conf": DETECT_CONF,
        "confidence_threshold": CONF_THRESHOLD,
        "detector_name": "TL-BS leaf disease detector",
        "product_name": "Canopy Disease Farm",
        "site_label": farm.get("site"),
        "active_house_id": farm.get("active_house_id"),
        "farm_risk": farm.get("farm_risk"),
    }


@app.get("/api/samples")
def samples() -> list[dict[str, str]]:
    from detector import list_sample_images

    return list_sample_images(STATIC)


@app.get("/api/farm")
def farm_state() -> dict[str, Any]:
    return greenhouse.get_farm()


@app.post("/api/farm/active")
def farm_active(req: ActiveHouseRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "farm": greenhouse.set_active(req.house_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown house: {req.house_id}") from exc


@app.post("/api/farm/reset")
def farm_reset() -> dict[str, Any]:
    return {"ok": True, "farm": greenhouse.reset_farm()}


@app.post("/api/farm/tick")
def farm_tick() -> dict[str, Any]:
    return {"ok": True, "farm": greenhouse.tick_simulation()}


@app.get("/api/greenhouse")
def greenhouse_state() -> dict[str, Any]:
    farm = greenhouse.get_farm()
    return {"state": greenhouse.get_state(), "farm": farm, "audit": farm.get("audit", [])}


@app.post("/api/greenhouse/reset")
def greenhouse_reset() -> dict[str, Any]:
    farm = greenhouse.reset_farm()
    return {"ok": True, "state": greenhouse.get_state(), "farm": farm}


@app.post("/api/detect")
async def detect(
    sample_file: str | None = Form(default=None),
    conf: float | None = Form(default=None),
    house_id: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    global _LAST

    hid = house_id or greenhouse.get_farm()["active_house_id"]
    try:
        greenhouse.set_active(hid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown house: {hid}") from exc

    conf_v = float(conf) if conf is not None else DETECT_CONF
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            raise HTTPException(status_code=400, detail="Unsupported image type")
        name = f"upload_{uuid.uuid4().hex}{suffix}"
        path = UPLOADS / name
        path.write_bytes(await file.read())
        rel = f"uploads/{name}"
    elif sample_file:
        path = STATIC / sample_file
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Sample not found: {sample_file}")
        rel = sample_file.replace("\\", "/")
    else:
        raise HTTPException(status_code=400, detail="Provide sample_file or upload file")

    t0 = time.time()
    try:
        from detector import run_detect

        detect_out = run_detect(path, conf=conf_v, overlay_dir=STATIC / "samples")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Detection failed: {exc}") from exc
    latency_ms = int((time.time() - t0) * 1000)

    bundle = _build_bundle(detect_out, hid)
    bundle["source_rel"] = rel
    bundle["detect_latency_ms"] = latency_ms
    _LAST = bundle

    (LOGS / "last_detection.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "ok": True,
        "latency_ms": latency_ms,
        "source_image": rel,
        "overlay_image": detect_out["overlay_image"],
        "house_id": hid,
        "evidence": bundle,
        "control_plan": bundle["control_plan"],
        "greenhouse_state": bundle["greenhouse_state"],
        "farm": bundle["farm"],
    }


@app.post("/api/control/apply")
def control_apply(req: ApplyRequest) -> dict[str, Any]:
    if _LAST is None or "control_plan" not in _LAST:
        raise HTTPException(status_code=400, detail="Run detection first")
    plan = _LAST["control_plan"]
    if req.plan_id and req.plan_id != plan.get("plan_id"):
        raise HTTPException(status_code=409, detail="Plan expired — run detection again")
    result = greenhouse.apply_plan(plan, operator=req.operator)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "Apply failed"))
    _LAST["greenhouse_state"] = result["state"]
    _LAST["farm"] = result["farm"]
    return result


def _rule_advisory(evidence: dict[str, Any]) -> str:
    """Offline advisory when LLM is unavailable or out of credit."""
    house = evidence.get("house_id") or "the scanned house"
    top = evidence.get("top") or []
    if top:
        labels = ", ".join(f"{t.get('class')} ({t.get('conf')})" for t in top[:3])
        disease_line = f"Scan on {house} highlights: {labels}."
    elif evidence.get("class_counts"):
        disease_line = f"Scan on {house} reports: {evidence.get('class_counts')}."
    else:
        disease_line = f"Scan on {house} found no lesions above threshold."

    plan_title = evidence.get("plan_title") or "hold current climate setpoints"
    risk = evidence.get("plan_risk") or "low"
    climate_bits = []
    for snip in evidence.get("knowledge") or []:
        if snip.get("climate_focus"):
            climate_bits.append(str(snip["climate_focus"]))
        for tip in snip.get("management") or []:
            climate_bits.append(str(tip))
    climate_line = " ".join(climate_bits[:3]) if climate_bits else "Keep canopy inspectable and avoid unnecessary wetting."

    linked = []
    for hp in evidence.get("house_plans") or []:
        role = hp.get("role") or "house"
        hid = hp.get("house_id")
        if hp.get("quarantine"):
            linked.append(f"{hid} ({role}, quarantine)")
        else:
            linked.append(f"{hid} ({role})")
    link_line = (
        "Linked houses: " + ", ".join(linked) + "."
        if linked
        else "No neighbour spillover actions in the current plan."
    )

    caution = (
        "This is assisted screening from detector evidence and a fixed knowledge base, "
        "not a laboratory diagnosis. Confirm before changing commercial climate computers."
    )
    return (
        f"{disease_line} Proposed plan ({risk}): {plan_title}. "
        f"{climate_line} {link_line} {caution}"
    )


@app.post("/api/explain")
def explain(req: ExplainRequest) -> dict[str, Any]:
    if _LAST is None:
        raise HTTPException(status_code=400, detail="Run detection first")

    # Compact payload — full farm JSON + bboxes makes OpenClaw calls very slow.
    plan = _LAST.get("control_plan") or {}
    house_plans = []
    for hp in (plan.get("house_plans") or [])[:4]:
        house_plans.append(
            {
                "house_id": hp.get("house_id"),
                "role": hp.get("role"),
                "risk": hp.get("risk"),
                "quarantine": hp.get("quarantine"),
                "actions": [
                    {"label": a.get("label"), "from": a.get("from"), "to": a.get("to")}
                    for a in (hp.get("actions") or [])[:6]
                ],
            }
        )
    kb = []
    for snip in (_LAST.get("knowledge_snippets") or [])[:2]:
        kb.append(
            {
                "class_id": snip.get("class_id"),
                "short": snip.get("short") or snip.get("name_en"),
                "climate_focus": snip.get("climate_focus"),
                "management": (snip.get("management") or [])[:2],
            }
        )
    preds = _LAST.get("predictions") or []
    evidence = {
        "house_id": _LAST.get("house_id"),
        "class_counts": _LAST.get("class_counts"),
        "top": [
            {"class": p.get("class_name"), "conf": p.get("confidence")}
            for p in preds[:5]
        ],
        "low_confidence": _LAST.get("low_confidence"),
        "plan_risk": plan.get("risk"),
        "plan_title": plan.get("title"),
        "house_plans": house_plans,
        "knowledge": kb,
    }

    model = (req.model or DEFAULT_MODEL).strip()
    source = "rule_fallback"
    text = ""
    latency_ms = 0
    llm_error = None

    if client:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Write the advisory from this JSON:\n"
                + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=220,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                source = "llm"
            latency_ms = int((time.time() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            llm_error = str(exc)
            latency_ms = int((time.time() - t0) * 1000)

    if source != "llm":
        text = _rule_advisory(evidence)
        if llm_error and "Insufficient account balance" in llm_error:
            text += " [Note: LLM skipped — OpenClaw account balance insufficient; rule-based advisory used.]"
        elif llm_error:
            text += " [Note: LLM unavailable; rule-based advisory used.]"
        elif not client:
            text += " [Note: no LLM key configured; rule-based advisory used.]"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model if source == "llm" else "rule_fallback",
        "source": source,
        "latency_ms": latency_ms,
        "evidence": evidence,
        "explanation": text,
        "llm_error": llm_error,
    }
    log_path = LOGS / f"explain_{int(time.time())}.json"
    log_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "model": record["model"],
        "source": source,
        "latency_ms": latency_ms,
        "explanation": text,
        "evidence": evidence,
        "log_file": log_path.name,
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8899"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
