from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp
from typing import Any, Dict, List, Sequence, Tuple, cast

import numpy as np

try:
    from sklearn.decomposition import PCA
    from sklearn.neighbors import KDTree
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    _SKLEARN_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    PCA = None
    KDTree = None
    OneHotEncoder = None
    StandardScaler = None
    _SKLEARN_IMPORT_ERROR = error


def _create_onehot_encoder() -> Any:
    if OneHotEncoder is None:
        raise RuntimeError(
            "HotspotSearchEngine requires scikit-learn. Install `scikit-learn` in backend environment."
        ) from _SKLEARN_IMPORT_ERROR

    try:
        return OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown='ignore', sparse=False)


@dataclass
class HotspotSearchConfig:
    n_components: int = 5
    leaf_size: int = 32
    grid_size: float = 0.02
    temporal_decay_hours: float = 36.0


class HotspotSearchEngine:
    """Local hybrid index engine (KDTree + PCA) for hotspot search."""

    def __init__(self, config: HotspotSearchConfig | None = None) -> None:
        if StandardScaler is None or PCA is None or KDTree is None:
            raise RuntimeError(
                "HotspotSearchEngine requires scikit-learn. Install `scikit-learn` in backend environment."
            ) from _SKLEARN_IMPORT_ERROR

        self.config = config or HotspotSearchConfig()
        self._encoder = _create_onehot_encoder()
        scaler_cls = cast(Any, StandardScaler)
        self._scaler = scaler_cls()
        self._pca: Any | None = None
        self._tree: Any | None = None
        self._events: List[Dict[str, Any]] = []
        self._projected: np.ndarray | None = None

    @property
    def fitted(self) -> bool:
        return self._tree is not None and self._projected is not None and len(self._events) > 0

    def _normalize_events(self, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, event in enumerate(events):
            raw_latitude = event.get('latitude')
            raw_longitude = event.get('longitude')
            if raw_latitude is None or raw_longitude is None:
                continue
            try:
                latitude = float(raw_latitude)
                longitude = float(raw_longitude)
            except (TypeError, ValueError):
                continue

            timestamp_raw = event.get('timestamp')
            if isinstance(timestamp_raw, datetime):
                timestamp = timestamp_raw
            else:
                text = str(timestamp_raw or '').strip().replace('Z', '+00:00')
                if not text:
                    continue
                try:
                    timestamp = datetime.fromisoformat(text)
                except ValueError:
                    continue

            try:
                volume = float(event.get('volume', 0.0) or 0.0)
            except (TypeError, ValueError):
                volume = 0.0

            waste_type = str(event.get('waste_type') or 'unknown').strip() or 'unknown'
            normalized.append(
                {
                    'id': event.get('id', index),
                    'latitude': latitude,
                    'longitude': longitude,
                    'timestamp': timestamp,
                    'waste_type': waste_type,
                    'volume': max(0.0, volume),
                }
            )
        return normalized

    def _build_feature_matrix(self, events: Sequence[Dict[str, Any]], fit: bool) -> np.ndarray:
        numeric_rows = []
        categorical_rows = []
        for event in events:
            timestamp: datetime = event['timestamp']
            numeric_rows.append(
                [
                    event['longitude'],
                    event['latitude'],
                    event['volume'],
                    timestamp.hour,
                    timestamp.weekday(),
                    timestamp.month,
                ]
            )
            categorical_rows.append([event['waste_type']])

        numeric = np.asarray(numeric_rows, dtype=np.float64)
        categorical_input = np.asarray(categorical_rows, dtype=object)
        if fit:
            categorical = self._encoder.fit_transform(categorical_input)
        else:
            categorical = self._encoder.transform(categorical_input)

        categorical_arr = np.asarray(categorical, dtype=np.float64)
        return np.hstack([numeric, categorical_arr])

    def fit(self, events: Sequence[Dict[str, Any]]) -> None:
        normalized = self._normalize_events(events)
        if not normalized:
            self._events = []
            self._projected = None
            self._tree = None
            self._pca = None
            return

        raw_features = self._build_feature_matrix(normalized, fit=True)
        scaled = self._scaler.fit_transform(raw_features)
        n_components = max(1, min(self.config.n_components, scaled.shape[0], scaled.shape[1]))
        pca_cls = cast(Any, PCA)
        tree_cls = cast(Any, KDTree)

        pca_model = pca_cls(n_components=n_components, random_state=42)
        projected = pca_model.fit_transform(scaled)

        self._tree = tree_cls(projected, leaf_size=self.config.leaf_size)
        self._pca = pca_model
        self._events = normalized
        self._projected = projected

    def search_similar(self, query_event: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.fitted or self._pca is None or self._tree is None:
            return []

        normalized_query = self._normalize_events([query_event])
        if not normalized_query:
            return []

        raw = self._build_feature_matrix(normalized_query, fit=False)
        scaled = self._scaler.transform(raw)
        projected = self._pca.transform(scaled)

        query_k = max(1, min(int(top_k), len(self._events)))
        distances, indices = self._tree.query(projected, k=query_k)

        results: List[Dict[str, Any]] = []
        for distance, index in zip(distances[0], indices[0]):
            event = self._events[int(index)]
            similarity = 1.0 / (1.0 + float(distance))
            results.append(
                {
                    'id': event.get('id'),
                    'latitude': event['latitude'],
                    'longitude': event['longitude'],
                    'timestamp': event['timestamp'].isoformat(),
                    'waste_type': event['waste_type'],
                    'volume': event['volume'],
                    'distance': float(distance),
                    'similarity': round(similarity, 6),
                }
            )
        return results

    def build_hotspots(self, top_k: int = 6) -> List[Dict[str, Any]]:
        if not self.fitted or self._tree is None or self._projected is None:
            return []

        total_events = len(self._events)
        if total_events == 0:
            return []

        neighbor_k = max(2, min(12, total_events))
        now_ts = datetime.now().timestamp()
        volume_values = np.asarray([event['volume'] for event in self._events], dtype=np.float64)
        volume_scale = float(np.percentile(volume_values, 90)) if len(volume_values) else 1.0
        volume_scale = max(1.0, volume_scale)

        distances, indices = self._tree.query(self._projected, k=neighbor_k)

        # Aggregate risk into spatial grid cells.
        grid_scores: Dict[Tuple[float, float], Dict[str, Any]] = {}
        for row_idx, event in enumerate(self._events):
            event_distances = distances[row_idx]
            event_indices = indices[row_idx]

            similarity_sum = 0.0
            for dist, candidate_idx in zip(event_distances, event_indices):
                if int(candidate_idx) == row_idx:
                    continue
                similarity_sum += 1.0 / (1.0 + float(dist))

            age_hours = max(0.0, (now_ts - event['timestamp'].timestamp()) / 3600.0)
            temporal_weight = exp(-age_hours / max(1.0, self.config.temporal_decay_hours))
            volume_weight = min(1.6, 1.0 + (event['volume'] / volume_scale))
            risk = similarity_sum * temporal_weight * volume_weight

            grid_lat = round(round(event['latitude'] / self.config.grid_size) * self.config.grid_size, 6)
            grid_lng = round(round(event['longitude'] / self.config.grid_size) * self.config.grid_size, 6)
            key = (grid_lat, grid_lng)

            bucket = grid_scores.setdefault(
                key,
                {
                    'center_lat': grid_lat,
                    'center_lng': grid_lng,
                    'risk_total': 0.0,
                    'event_count': 0,
                    'predicted_count': 0.0,
                    'label_weight': {},
                },
            )
            bucket['risk_total'] += risk
            bucket['event_count'] += 1
            bucket['predicted_count'] += max(1.0, event['volume']) * temporal_weight
            labels = bucket['label_weight']
            labels[event['waste_type']] = labels.get(event['waste_type'], 0.0) + (risk + 1.0)

        hotspots: List[Dict[str, Any]] = []
        for bucket in grid_scores.values():
            event_count = max(1, int(bucket['event_count']))
            risk_score = min(100.0, (bucket['risk_total'] / event_count) * 28.0)
            labels_sorted = sorted(bucket['label_weight'].items(), key=lambda item: item[1], reverse=True)
            dominant_labels = [label for label, _ in labels_sorted[:3]]

            hotspots.append(
                {
                    'center_lat': bucket['center_lat'],
                    'center_lng': bucket['center_lng'],
                    'risk_score': round(risk_score, 2),
                    'predicted_count': round(float(bucket['predicted_count']), 2),
                    'dominant_labels': dominant_labels,
                    'reason': '基于KDTree邻域密度、PCA特征投影与时间衰减评分',
                }
            )

        hotspots.sort(key=lambda item: (item['risk_score'], item['predicted_count']), reverse=True)
        trimmed = hotspots[: max(1, int(top_k))]
        for rank, item in enumerate(trimmed, start=1):
            item['rank'] = rank
        return trimmed
