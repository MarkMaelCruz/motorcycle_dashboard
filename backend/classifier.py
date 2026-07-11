"""
classifier.py
=============
Loads the LightGBM riding-control bundle (model + label encoder +
feature column order, produced by save_lgbm_model.py) exactly once
per process, and exposes a single classify() call the Flask backend
uses on every incoming telemetry POST.

This mirrors classify_latest() from rider_control_classification.py,
but is safe to import inside a web server:
  * never touches stdin/serial/argv
  * fails SOFT (returns None) if the .pkl is missing, so /telemetry
    keeps accepting raw data even before the model file is deployed
  * loads lazily + caches, so Cloud Run cold starts only pay the
    joblib.load() cost once per container instance
"""

import os
import traceback
import logging
from typing import Optional

logger = logging.getLogger("classifier")

MODEL_PATH = os.environ.get(
    "RIDING_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "model", "lgbm_model_bundle.pkl"),
)

_bundle = None
_load_attempted = False
_load_error: Optional[str] = None          # --- diagnostics
_last_classify_error: Optional[str] = None  # --- diagnostics


def _load_bundle():
    global _bundle, _load_attempted, _load_error
    if _load_attempted:
        return _bundle
    _load_attempted = True
    try:
        import joblib
        bundle = joblib.load(MODEL_PATH)
        bundle["label_encoder"].classes_  # raises AttributeError if unfitted
        bundle["model"]                    # raises KeyError if bundle shape is wrong
        bundle["feature_cols"]             # raises KeyError if bundle shape is wrong
        _bundle = bundle
        _load_error = None
        logger.info(
            "Loaded riding-state model from %s (classes=%s)",
            MODEL_PATH, list(bundle["label_encoder"].classes_),
        )
    except Exception as exc:  # noqa: BLE001 - intentionally broad: fail soft
        _load_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Riding-state model NOT loaded (%s): %s", MODEL_PATH, exc)
        logger.warning(traceback.format_exc())
        _bundle = None
    return _bundle


def status() -> dict:
    """Diagnostic snapshot — hit this from a Flask route to see EXACTLY
    why riding_state is null in production, without digging through
    Cloud Logging. Safe to expose: no secrets, just paths/booleans."""
    bundle = _load_bundle()
    return {
        "model_path": MODEL_PATH,
        "model_path_exists_on_disk": os.path.exists(MODEL_PATH),
        "loaded": bundle is not None,
        "load_error": _load_error,
        "classes": list(bundle["label_encoder"].classes_) if bundle else None,
        "feature_cols": bundle["feature_cols"] if bundle else None,
        "last_classify_error": _last_classify_error,
    }


def classify(acc_forward: float, lean_angle: float, lean_rate: float,
             throttle: float, brake: float) -> Optional[dict]:
    """
    Returns {"label": str, "confidence": float | None} or None if the
    model bundle is unavailable (e.g. not yet deployed to backend/model/)
    OR if prediction itself raised (see status()["last_classify_error"]).
    """
    global _last_classify_error

    bundle = _load_bundle()
    if bundle is None:
        return None

    try:
        model = bundle["model"]
        le = bundle["label_encoder"]
        feature_cols = bundle["feature_cols"]

        row = {
            "acc_forward": acc_forward,
            "lean_angle": lean_angle,
            "lean_rate": lean_rate,
            "throttle": throttle,
            "brake": brake,
        }
        X = [[row[c] for c in feature_cols]]

        pred = model.predict(X)
        label = le.inverse_transform(pred)[0]

        confidence = None
        if hasattr(model, "predict_proba"):
            try:
                proba = model.predict_proba(X)[0]
                confidence = float(max(proba))
            except Exception:  # noqa: BLE001
                confidence = None

        _last_classify_error = None
        return {"label": str(label), "confidence": confidence}

    except Exception as exc:  # noqa: BLE001 - classify() must also fail soft
        _last_classify_error = f"{type(exc).__name__}: {exc}"
        logger.warning("classify() failed on a valid, loaded model: %s", exc)
        logger.warning(traceback.format_exc())
        return None