"""
Trainable classifier on top of OpenCLIP embeddings.

Architecture:
- Extract 512-d embedding from OpenCLIP (frozen)
- Train sklearn classifier (LogReg, SVM, etc.) on top
- Fall back to zero-shot CLIP if no trained classifier available

This module prepares the infrastructure for future training
once labeled data is available.
"""

import logging
import pickle
from pathlib import Path
from typing import Optional, Dict, Any, List
import numpy as np

log = logging.getLogger(__name__)


class EmbeddingClassifier:
    """
    Sklearn classifier trained on OpenCLIP embeddings.
    
    State:
    - UNTRAINED: No model file found, will use zero-shot fallback
    - TRAINED: Model loaded, ready for inference
    
    When untrained, this class acts as a pass-through that signals
    the pipeline to use zero-shot CLIP classification.
    """
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize classifier.
        
        Args:
            model_path: Path to pickled sklearn model. If None or file doesn't exist,
                       classifier will be in UNTRAINED state.
        """
        self.model_path = model_path
        self.model = None
        self.metadata: Dict[str, Any] = {}
        self.is_trained = False
        
        if model_path and Path(model_path).exists():
            self._load_model(model_path)
    
    def _load_model(self, path: str):
        """Load trained classifier from disk."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            
            self.model = data["model"]
            self.metadata = data.get("metadata", {})
            self.is_trained = True
            
            log.info(
                f"Loaded trained classifier: {self.metadata.get('model_type', 'unknown')}, "
                f"trained on {self.metadata.get('num_samples', 'unknown')} samples"
            )
        except Exception as e:
            log.warning(f"Failed to load classifier from {path}: {e}")
            self.is_trained = False
    
    def predict(
        self,
        embedding: np.ndarray,
        top_k: int = 3
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Predict class probabilities from embedding.
        
        Args:
            embedding: 512-d numpy array from OpenCLIP
            top_k: Return top-k predictions
            
        Returns:
            List of {class_name, probability} dicts if trained, None if untrained
        """
        if not self.is_trained:
            return None
        
        try:
            # Reshape for sklearn
            emb = embedding.reshape(1, -1)
            
            # Get probabilities
            if hasattr(self.model, "predict_proba"):
                probs = self.model.predict_proba(emb)[0]
            else:
                # SVM without probability=True → use decision function
                scores = self.model.decision_function(emb)[0]
                # Softmax
                exp_scores = np.exp(scores - np.max(scores))
                probs = exp_scores / exp_scores.sum()
            
            # Get top-k
            top_indices = np.argsort(probs)[-top_k:][::-1]
            class_names = self.metadata.get("class_names", [f"class_{i}" for i in range(len(probs))])
            
            results = []
            for idx in top_indices:
                results.append({
                    "class_name": class_names[idx],
                    "probability": float(probs[idx]),
                    "class_id": int(idx)
                })
            
            return results
            
        except Exception as e:
            log.error(f"Classifier prediction failed: {e}")
            return None
    
    def save(self, path: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Save trained classifier to disk.
        
        Args:
            path: Output pickle file path
            metadata: Optional metadata dict (model_type, num_samples, accuracy, etc.)
        """
        if not self.is_trained or self.model is None:
            raise ValueError("Cannot save untrained classifier")
        
        self.metadata.update(metadata or {})
        
        data = {
            "model": self.model,
            "metadata": self.metadata
        }
        
        with open(path, "wb") as f:
            pickle.dump(data, f)
        
        log.info(f"Saved classifier to {path}")
    
    def get_info(self) -> Dict[str, Any]:
        """Return classifier metadata for debugging."""
        return {
            "is_trained": self.is_trained,
            "model_path": self.model_path,
            "model_type": self.metadata.get("model_type", None),
            "num_classes": self.metadata.get("num_classes", None),
            "num_samples": self.metadata.get("num_samples", None),
            "accuracy": self.metadata.get("accuracy", None),
            "trained_at": self.metadata.get("trained_at", None),
        }


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING UTILITIES (for future use when labeled data is available)
# ══════════════════════════════════════════════════════════════════════════════

def train_classifier(
    embeddings: np.ndarray,
    labels: np.ndarray,
    class_names: List[str],
    model_type: str = "logistic_regression",
    output_path: Optional[str] = None
) -> EmbeddingClassifier:
    """
    Train a classifier on labeled embeddings.
    
    Args:
        embeddings: (N, 512) array of OpenCLIP embeddings
        labels: (N,) array of integer class labels
        class_names: List of class names (length = num_classes)
        model_type: 'logistic_regression', 'svm', or 'random_forest'
        output_path: If provided, save model to this path
        
    Returns:
        Trained EmbeddingClassifier
        
    Example:
        >>> embeddings = np.random.rand(100, 512)  # 100 samples
        >>> labels = np.random.randint(0, 10, 100)  # 10 classes
        >>> class_names = [f"class_{i}" for i in range(10)]
        >>> clf = train_classifier(embeddings, labels, class_names, output_path="model.pkl")
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import SVC
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    from datetime import datetime
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        embeddings, labels, test_size=0.2, random_state=42, stratify=labels
    )
    
    # Select model
    if model_type == "logistic_regression":
        model = LogisticRegression(max_iter=1000, random_state=42)
    elif model_type == "svm":
        model = SVC(kernel="rbf", probability=True, random_state=42)
    elif model_type == "random_forest":
        model = RandomForestClassifier(n_estimators=100, random_state=42)
    else:
        raise ValueError(f"Unknown model_type: {model_type}")
    
    # Train
    log.info(f"Training {model_type} on {len(X_train)} samples...")
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    log.info(f"Test accuracy: {accuracy:.3f}")
    
    # Create classifier object
    clf = EmbeddingClassifier()
    clf.model = model
    clf.is_trained = True
    clf.metadata = {
        "model_type": model_type,
        "num_classes": len(class_names),
        "class_names": class_names,
        "num_samples": len(embeddings),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "accuracy": float(accuracy),
        "trained_at": datetime.utcnow().isoformat(),
    }
    
    # Save if requested
    if output_path:
        clf.model_path = output_path
        clf.save(output_path)
    
    return clf
