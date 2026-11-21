"""Model loading and safe image preprocessing for bag-photo checks."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

CLASSES = ("healthy", "suspect", "contaminated")


class InferenceService:
    """Load only a model whose metadata agrees with the API class order."""

    def __init__(
        self, model_path: Path, metadata_path: Path, min_confidence: float = 0.55
    ) -> None:
        self.model_path = model_path
        self.metadata_path = metadata_path
        self.min_confidence = min_confidence
        self.model: Any = None
        self.version: str | None = None
        self.synthetic = False
        self._lock = threading.Lock()
        self._load()

    @property
    def loaded(self) -> bool:
        """Report whether a compatible model is ready to serve predictions."""
        return self.model is not None

    def _load(self) -> None:
        """Load TensorFlow lazily so offline API mode works without a model file."""
        if not self.model_path.is_file() or not self.metadata_path.is_file():
            return
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if tuple(metadata.get("classes", ())) != CLASSES:
            raise ValueError(
                "Model metadata class order does not match the API classes."
            )
        from tensorflow.keras.models import load_model

        model = load_model(self.model_path)
        output_size = model.output_shape[-1]
        if output_size != len(CLASSES):
            raise ValueError("Model output size does not match the three API classes.")
        self.model = model
        self.version = str(metadata.get("version", "unversioned"))
        self.synthetic = bool(metadata.get("synthetic", False))

    def predict(self, image_bytes: bytes) -> dict[str, Any]:
        """Decode, validate, normalize, and classify one uploaded image."""
        if self.model is None:
            raise RuntimeError(
                "AI model is not available. Add a trained model before using photo checks."
            )
        if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
            raise ValueError("Choose an image smaller than 8 MB.")
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("The selected file is not a readable image.")
        height, width = image.shape[:2]
        if width < 64 or height < 64 or width * height > 20_000_000:
            raise ValueError(
                "Image must be at least 64 by 64 pixels and no larger than 20 megapixels."
            )
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (224, 224)).astype(np.float32) / 255.0
        batch = np.expand_dims(resized, axis=0)
        with self._lock:
            probabilities = np.asarray(
                self.model.predict(batch, verbose=0)[0], dtype=float
            )
        if (
            probabilities.shape != (len(CLASSES),)
            or not np.isfinite(probabilities).all()
        ):
            raise ValueError("The AI model returned an invalid result.")
        probabilities = np.clip(probabilities, 0.0, 1.0)
        probabilities /= max(float(probabilities.sum()), 1e-12)
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        uncertain = confidence < self.min_confidence
        label = "suspect" if uncertain else CLASSES[index]
        return {
            "status": label,
            "confidence": confidence,
            "probabilities": dict(zip(CLASSES, probabilities.tolist())),
            "uncertain": uncertain,
            "model_version": self.version,
            "model_synthetic": self.synthetic,
        }
