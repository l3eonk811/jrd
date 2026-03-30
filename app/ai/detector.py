"""
Object detection for AI pipeline using YOLOv5.

Detects the main object in an image and returns a crop focused on that object.
Falls back to full image if detection is uncertain.
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Detection:
    """Single detected object with bounding box and confidence."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    class_name: str

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        """Return bbox as (x1, y1, x2, y2)."""
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def area(self) -> int:
        """Area of the bounding box in pixels."""
        return (self.x2 - self.x1) * (self.y2 - self.y1)


@dataclass
class DetectionResult:
    """Result of object detection on an image."""
    detections: List[Detection]
    image_width: int
    image_height: int
    model_used: str
    inference_time_ms: float


class ObjectDetector:
    """
    YOLOv5-based object detector.
    
    Provides three cropping policies:
    1. balanced (default): crop if confident (>0.4) and bbox is reasonable size
    2. confident: crop only if very confident (>0.6)
    3. largest: always crop to largest detected object if any exist
    """
    
    def __init__(self, model_name: str = "yolov5s", device: Optional[str] = None):
        """
        Initialize detector.
        
        Args:
            model_name: YOLOv5 model variant (yolov5s, yolov5m, yolov5l, etc.)
            device: 'cuda', 'cpu', or None for auto-detect
        """
        import torch  # Lazy import
        
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None
    
    def _load_model(self):
        """Lazy-load the YOLOv5 model."""
        if self._model is None:
            import torch  # Lazy import to avoid blocking startup
            
            log.info(f"Loading YOLOv5 model: {self.model_name} on {self.device}")
            try:
                # ultralytics/yolov5 from torch.hub
                self._model = torch.hub.load(
                    "ultralytics/yolov5",
                    self.model_name,
                    pretrained=True,
                    device=self.device,
                    verbose=False
                )
                self._model.conf = 0.25  # confidence threshold
                self._model.iou = 0.45   # NMS IOU threshold
                log.info(f"YOLOv5 model loaded successfully on {self.device}")
            except Exception as e:
                log.error(f"Failed to load YOLOv5: {e}")
                raise
        return self._model
    
    def detect(self, image_path: str) -> DetectionResult:
        """
        Run object detection on an image.
        
        Args:
            image_path: Path to image file
            
        Returns:
            DetectionResult with all detected objects
        """
        import time
        import torch  # Lazy import
        from PIL import Image  # Lazy import
        
        start = time.time()
        
        model = self._load_model()
        
        # Run inference
        results = model(image_path)
        
        # Parse results
        detections = []
        img = Image.open(image_path)
        img_width, img_height = img.size
        
        # results.xyxy[0] contains: [x1, y1, x2, y2, confidence, class_id]
        for det in results.xyxy[0].cpu().numpy():
            x1, y1, x2, y2, conf, cls = det
            class_name = model.names[int(cls)]
            
            detections.append(Detection(
                x1=int(x1),
                y1=int(y1),
                x2=int(x2),
                y2=int(y2),
                confidence=float(conf),
                class_id=int(cls),
                class_name=class_name
            ))
        
        elapsed_ms = (time.time() - start) * 1000
        
        return DetectionResult(
            detections=detections,
            image_width=img_width,
            image_height=img_height,
            model_used=self.model_name,
            inference_time_ms=elapsed_ms
        )
    
    def detect_and_crop(
        self,
        image_path: str,
        policy: str = "balanced",
        padding_pct: float = 0.1
    ) -> Tuple:
        """
        Detect main object and return a cropped image focused on it.
        
        Args:
            image_path: Path to input image
            policy: Cropping policy - "balanced", "confident", or "largest"
            padding_pct: Padding around crop as % of bbox size (0.1 = 10%)
            
        Returns:
            (cropped_image, metadata_dict)
            metadata includes: detection_used, crop_bbox, fallback_reason if any
        """
        from PIL import Image  # Lazy import
        
        det_result = self.detect(image_path)
        
        if not det_result.detections:
            # No detections → return full image
            img = Image.open(image_path)
            return img, {
                "detection_method": "full_image",
                "fallback_reason": "no_detections",
                "num_detections": 0,
                "detection_time_ms": det_result.inference_time_ms
            }
        
        # Select detection based on policy
        selected = self._select_detection(det_result, policy)
        
        if selected is None:
            # Policy rejected all detections → return full image
            img = Image.open(image_path)
            return img, {
                "detection_method": "full_image",
                "fallback_reason": f"policy_{policy}_rejected",
                "num_detections": len(det_result.detections),
                "detection_time_ms": det_result.inference_time_ms
            }
        
        # Crop with padding
        img = Image.open(image_path)
        crop_bbox = self._add_padding(
            selected.bbox,
            det_result.image_width,
            det_result.image_height,
            padding_pct
        )
        cropped = img.crop(crop_bbox)
        
        return cropped, {
            "detection_method": "cropped",
            "detection_policy": policy,
            "detected_class": selected.class_name,
            "detection_confidence": selected.confidence,
            "crop_bbox": crop_bbox,
            "original_bbox": selected.bbox,
            "padding_pct": padding_pct,
            "num_detections": len(det_result.detections),
            "detection_time_ms": det_result.inference_time_ms
        }
    
    def _select_detection(
        self,
        det_result: DetectionResult,
        policy: str
    ) -> Optional[Detection]:
        """Select the best detection based on policy."""
        if not det_result.detections:
            return None
        
        # Sort by area (largest first)
        sorted_dets = sorted(det_result.detections, key=lambda d: d.area, reverse=True)
        
        if policy == "largest":
            # Always return largest
            return sorted_dets[0]
        
        elif policy == "confident":
            # Only if confidence > 0.6
            for det in sorted_dets:
                if det.confidence > 0.6:
                    return det
            return None
        
        else:  # balanced (default)
            # confidence > 0.4 AND bbox is reasonable size (>5% of image)
            img_area = det_result.image_width * det_result.image_height
            for det in sorted_dets:
                bbox_ratio = det.area / img_area
                if det.confidence > 0.4 and bbox_ratio > 0.05:
                    return det
            return None
    
    def _add_padding(
        self,
        bbox: Tuple[int, int, int, int],
        img_width: int,
        img_height: int,
        padding_pct: float
    ) -> Tuple[int, int, int, int]:
        """Add padding around bbox, clipped to image boundaries."""
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        
        pad_x = int(width * padding_pct)
        pad_y = int(height * padding_pct)
        
        x1_padded = max(0, x1 - pad_x)
        y1_padded = max(0, y1 - pad_y)
        x2_padded = min(img_width, x2 + pad_x)
        y2_padded = min(img_height, y2 + pad_y)
        
        return (x1_padded, y1_padded, x2_padded, y2_padded)
