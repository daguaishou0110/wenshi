"""ONNX Runtime detector for Canopy Disease (tomato leaf pests/diseases)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

if TYPE_CHECKING:
    import onnxruntime as ort

ROOT = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = Path(os.getenv("YOLO_WEIGHTS", str(ROOT / "weights" / "best.onnx")))

CLASS_NAMES = [
    "Tomato_Yellow_Leaf_Curl_Virus",
    "Tomato__Spider_Mites",
    "Tomato___Bacterial_spot",
    "Tomato___Early_blight",
    "Tomato___Late_blight",
    "Tomato___Leaf_Mold",
    "Tomato___Septoria_leaf_spot",
    "Tomato___Target_Spot",
    "Tomato_mosaic_virus",
    "healthy_leaf",
]

DISPLAY_NAMES = {
    "Tomato_Yellow_Leaf_Curl_Virus": "YLCV",
    "Tomato__Spider_Mites": "Spider mites",
    "Tomato___Bacterial_spot": "Bacterial spot",
    "Tomato___Early_blight": "Early blight",
    "Tomato___Late_blight": "Late blight",
    "Tomato___Leaf_Mold": "Leaf mold",
    "Tomato___Septoria_leaf_spot": "Septoria",
    "Tomato___Target_Spot": "Target spot",
    "Tomato_mosaic_virus": "Mosaic virus",
    "healthy_leaf": "Healthy",
}

IMGSZ = 640
_session: Any | None = None
_session_path: str | None = None


def get_model(weights: str | Path | None = None) -> Any:
    """Lazy-load ONNX so the web process can boot on small Render free instances."""
    global _session, _session_path
    import onnxruntime as ort

    path = str(Path(weights) if weights else DEFAULT_WEIGHTS)
    if _session is None or _session_path != path:
        if not Path(path).exists():
            raise FileNotFoundError(f"ONNX weights not found: {path}")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = int(os.getenv("ORT_INTRA_THREADS", "1"))
        opts.inter_op_num_threads = int(os.getenv("ORT_INTER_THREADS", "1"))
        _session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        _session_path = path
    return _session


def list_sample_images(static_dir: Path) -> list[dict[str, str]]:
    samples = static_dir / "samples"
    out: list[dict[str, str]] = []
    for p in sorted(samples.glob("leaf_*.jpg")) + sorted(samples.glob("leaf_*.png")):
        out.append({"id": p.stem, "file": f"samples/{p.name}", "name": p.stem.replace("leaf_", "").replace("_", " ")})
    return out


def _letterbox(img: Image.Image, new_shape: int = IMGSZ) -> tuple[np.ndarray, float, tuple[float, float]]:
    w0, h0 = img.size
    r = min(new_shape / h0, new_shape / w0)
    nw, nh = int(round(w0 * r)), int(round(h0 * r))
    resized = img.resize((nw, nh), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (new_shape, new_shape), (114, 114, 114))
    dw, dh = (new_shape - nw) / 2, (new_shape - nh) / 2
    canvas.paste(resized, (int(round(dw - 0.1)), int(round(dh - 0.1))))
    arr = np.asarray(canvas).astype(np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[None, ...]
    return arr, r, (dw, dh)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float = 0.45) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= iou_thres]
    return keep


def _draw_overlay(image_path: Path, predictions: list[dict[str, Any]], out_path: Path) -> str:
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    heat = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    heat_draw = ImageDraw.Draw(heat)
    box_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    box_draw = ImageDraw.Draw(box_layer)
    try:
        font = ImageFont.truetype("arial.ttf", max(13, w // 48))
    except OSError:
        font = ImageFont.load_default()

    for pred in predictions:
        x1, y1, x2, y2 = pred["bbox_xyxy"]
        x1, y1 = int(max(0, x1)), int(max(0, y1))
        x2, y2 = int(min(w, x2)), int(min(h, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rw, rh = (x2 - x1) * 0.55, (y2 - y1) * 0.55
        heat_draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(196, 70, 40, 95))
        box_draw.rectangle([x1, y1, x2, y2], outline=(20, 110, 72, 255), width=max(2, w // 220))
        label = f"{pred['class_name']} {pred['confidence']:.2f}"
        ty = max(0, y1 - 22)
        tw = min(w - x1, max(100, int(7.0 * len(label))))
        box_draw.rectangle([x1, ty, x1 + tw, ty + 20], fill=(20, 110, 72, 220))
        box_draw.text((x1 + 4, ty + 2), label, fill=(255, 255, 255, 255), font=font)

    heat = heat.filter(ImageFilter.GaussianBlur(radius=max(6, w // 55)))
    blended = Image.alpha_composite(Image.alpha_composite(img, heat), box_layer)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blended.convert("RGB").save(out_path, quality=92)
    return out_path.name


def run_detect(
    image_path: Path,
    *,
    conf: float = 0.25,
    iou: float = 0.45,
    weights: str | Path | None = None,
    overlay_dir: Path | None = None,
    max_det: int = 50,
) -> dict[str, Any]:
    session = get_model(weights)
    img = Image.open(image_path).convert("RGB")
    w0, h0 = img.size
    inp, ratio, (dw, dh) = _letterbox(img, IMGSZ)

    input_name = session.get_inputs()[0].name
    out = session.run(None, {input_name: inp})[0]
    pred = np.squeeze(out, axis=0)
    if pred.shape[0] >= pred.shape[1]:
        pred = pred.T

    boxes_xywh = pred[:4, :].T
    cls_scores = pred[4:, :].T
    class_ids = cls_scores.argmax(axis=1)
    scores = cls_scores.max(axis=1)

    mask = scores >= conf
    boxes_xywh = boxes_xywh[mask]
    scores = scores[mask]
    class_ids = class_ids[mask]

    if len(boxes_xywh):
        x, y, bw, bh = boxes_xywh.T
        boxes = np.stack([x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2], axis=1)
        boxes[:, [0, 2]] -= dw
        boxes[:, [1, 3]] -= dh
        boxes /= ratio
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w0)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h0)
        keep = _nms(boxes, scores, iou_thres=iou)[:max_det]
        boxes = boxes[keep]
        scores = scores[keep]
        class_ids = class_ids[keep]
    else:
        boxes = np.zeros((0, 4), dtype=np.float32)

    predictions: list[dict[str, Any]] = []
    for box, score, cid in zip(boxes, scores, class_ids):
        raw = CLASS_NAMES[int(cid)] if int(cid) < len(CLASS_NAMES) else str(int(cid))
        predictions.append(
            {
                "class_id": raw,
                "class_name": DISPLAY_NAMES.get(raw, raw),
                "confidence": round(float(score), 4),
                "bbox_xyxy": [round(float(v), 1) for v in box.tolist()],
            }
        )
    predictions.sort(key=lambda p: p["confidence"], reverse=True)

    overlay_dir = overlay_dir or (ROOT / "static" / "samples")
    overlay_name = f"yolo_overlay_{image_path.stem}.jpg"
    overlay_path = overlay_dir / overlay_name
    _draw_overlay(image_path, predictions, overlay_path)

    counts: dict[str, int] = {}
    for p in predictions:
        counts[p["class_name"]] = counts.get(p["class_name"], 0) + 1

    return {
        "detector": "Canopy Disease Detector (TL-BS)",
        "weights": str(_session_path),
        "image": str(image_path),
        "conf_threshold": conf,
        "n_detections": len(predictions),
        "class_counts": counts,
        "class_names": {i: DISPLAY_NAMES.get(n, n) for i, n in enumerate(CLASS_NAMES)},
        "predictions": predictions,
        "overlay_image": f"samples/{overlay_name}",
        "native_plot": f"samples/{overlay_name}",
    }
