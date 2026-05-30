"""
Graph Machine Learning Integration

Provides machine learning capabilities for graph analysis including node classification,
link prediction, anomaly detection, graph embeddings, and pattern discovery.
"""

import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
import numpy as np
import networkx as nx
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ML Libraries
try:
    from sklearn.ensemble import RandomForestClassifier, IsolationForest
    from sklearn.linear_model import LogisticRegression
    from sklearn.cluster import KMeans, DBSCAN
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    from sklearn.neighbors import NearestNeighbors
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("scikit-learn not available. ML features will be limited.")

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType

logger = logging.getLogger(__name__)


class MLTaskType(Enum):
    """Types of machine learning tasks"""
    NODE_CLASSIFICATION = "node_classification"
    LINK_PREDICTION = "link_prediction"
    ANOMALY_DETECTION = "anomaly_detection"
    COMMUNITY_DETECTION = "community_detection"
    GRAPH_EMBEDDING = "graph_embedding"
    PATTERN_MINING = "pattern_mining"
    SIMILARITY_ANALYSIS = "similarity_analysis"
    TREND_PREDICTION = "trend_prediction"


class MLAlgorithm(Enum):
    """Available ML algorithms"""
    RANDOM_FOREST = "random_forest"
    LOGISTIC_REGRESSION = "logistic_regression"
    ISOLATION_FOREST = "isolation_forest"
    KMEANS = "kmeans"
    DBSCAN = "dbscan"
    PCA = "pca"
    TSNE = "tsne"
    NEAREST_NEIGHBORS = "nearest_neighbors"
    GRAPH_NEURAL_NETWORK = "gnn"
    NODE2VEC = "node2vec"
    DEEPWALK = "deepwalk"


@dataclass
class MLModel:
    """
    Machine learning model metadata
    
    Attributes:
        id: Model identifier
        name: Human-readable model name
        task_type: Type of ML task
        algorithm: ML algorithm used
        graph_name: Source graph name
        created_at: Creation timestamp
        updated_at: Last update timestamp
        version: Model version
        parameters: Model hyperparameters
        metrics: Performance metrics
        features: Feature configuration
        status: Model status
        model_path: Serialized model storage path
    """
    
    id: str
    name: str
    task_type: MLTaskType
    algorithm: MLAlgorithm
    graph_name: str
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    parameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    features: List[str] = field(default_factory=list)
    status: str = "untrained"
    model_path: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["task_type"] = self.task_type.value
        data["algorithm"] = self.algorithm.value
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data


@dataclass
class MLPrediction:
    """
    ML prediction result
    
    Attributes:
        model_id: Source model ID
        target_id: Target element ID (node/edge)
        prediction: Predicted value/class
        confidence: Prediction confidence score
        probabilities: Class probabilities (if applicable)
        features: Input features used
        timestamp: Prediction timestamp
        metadata: Additional metadata
    """
    
    model_id: str
    target_id: str
    prediction: Any
    confidence: float
    probabilities: Dict[str, float] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class GraphFeatureExtractor:
    """
    Extracts features from graph data for machine learning
    
    Provides various feature extraction methods for nodes, edges, and graph-level features.
    """
    
    def __init__(self, graph_manager: GraphDatabaseManager = None):
        self.graph_manager = graph_manager or get_graph_manager()
    
    def extract_node_features(self, graph_data: Dict[str, Any], 
                             feature_types: List[str] = None) -> Tuple[np.ndarray, List[str], List[str]]:
        """
        Extract features for all nodes in the graph
        
        Args:
            graph_data: Graph data from graph manager
            feature_types: Types of features to extract
            
        Returns:
            Tuple of (feature_matrix, feature_names, node_ids)
        """
        if not graph_data.get("success") or not SKLEARN_AVAILABLE:
            return np.array([]), [], []
        
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        
        if not nodes:
            return np.array([]), [], []
        
        # Create NetworkX graph for analysis
        G = self._create_networkx_graph(nodes, edges)
        
        # Default feature types
        if feature_types is None:
            feature_types = [
                "degree_centrality", "betweenness_centrality", "closeness_centrality",
                "clustering_coefficient", "pagerank", "node_properties"
            ]
        
        features = []
        feature_names = []
        node_ids = []
        
        for node in nodes:
            node_id = node["id"]
            node_ids.append(node_id)
            
            node_features = []
            
            # Centrality features
            if "degree_centrality" in feature_types:
                dc = nx.degree_centrality(G).get(node_id, 0)
                node_features.append(dc)
                if len(features) == 0:
                    feature_names.append("degree_centrality")
            
            if "betweenness_centrality" in feature_types:
                bc = nx.betweenness_centrality(G).get(node_id, 0)
                node_features.append(bc)
                if len(features) == 0:
                    feature_names.append("betweenness_centrality")
            
            if "closeness_centrality" in feature_types:
                cc = nx.closeness_centrality(G).get(node_id, 0)
                node_features.append(cc)
                if len(features) == 0:
                    feature_names.append("closeness_centrality")
            
            if "clustering_coefficient" in feature_types:
                cluster = nx.clustering(G, node_id) if node_id in G else 0
                node_features.append(cluster)
                if len(features) == 0:
                    feature_names.append("clustering_coefficient")
            
            if "pagerank" in feature_types:
                pr = nx.pagerank(G).get(node_id, 0)
                node_features.append(pr)
                if len(features) == 0:
                    feature_names.append("pagerank")
            
            # Property-based features
            if "node_properties" in feature_types:
                properties = node.get("properties", {})
                
                # Extract numeric properties
                for prop_name, prop_value in properties.items():
                    if isinstance(prop_value, (int, float)):
                        node_features.append(prop_value)
                        if len(features) == 0:
                            feature_names.append(f"prop_{prop_name}")
                    elif isinstance(prop_value, str):
                        # Convert string to hash for categorical features
                        node_features.append(hash(prop_value) % 1000)
                        if len(features) == 0:
                            feature_names.append(f"prop_{prop_name}_hash")
            
            features.append(node_features)
        
        # Convert to numpy array and handle missing values
        feature_matrix = np.array(features, dtype=float)
        if feature_matrix.size > 0:
            feature_matrix = np.nan_to_num(feature_matrix, nan=0.0)
        
        return feature_matrix, feature_names, node_ids
    
    def extract_edge_features(self, graph_data: Dict[str, Any]) -> Tuple[np.ndarray, List[str], List[str]]:
        """Extract features for all edges in the graph"""
        if not graph_data.get("success") or not SKLEARN_AVAILABLE:
            return np.array([]), [], []
        
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        
        if not edges:
            return np.array([]), [], []
        
        # Create NetworkX graph
        G = self._create_networkx_graph(nodes, edges)
        
        features = []
        feature_names = ["weight", "source_degree", "target_degree", "common_neighbors"]
        edge_ids = []
        
        for edge in edges:
            edge_id = edge["id"]
            source = edge["source"]
            target = edge["target"]
            edge_ids.append(edge_id)
            
            edge_features = []
            
            # Edge weight
            weight = edge.get("weight", 1.0)
            edge_features.append(weight)
            
            # Source and target node degrees
            source_degree = G.degree(source) if source in G else 0
            target_degree = G.degree(target) if target in G else 0
            edge_features.append(source_degree)
            edge_features.append(target_degree)
            
            # Common neighbors
            if source in G and target in G:
                common_neighbors = len(list(nx.common_neighbors(G, source, target)))
            else:
                common_neighbors = 0
            edge_features.append(common_neighbors)
            
            features.append(edge_features)
        
        feature_matrix = np.array(features, dtype=float)
        if feature_matrix.size > 0:
            feature_matrix = np.nan_to_num(feature_matrix, nan=0.0)
        
        return feature_matrix, feature_names, edge_ids
    
    def extract_graph_features(self, graph_data: Dict[str, Any]) -> Dict[str, float]:
        """Extract graph-level features"""
        if not graph_data.get("success"):
            return {}
        
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        
        if not nodes:
            return {}
        
        G = self._create_networkx_graph(nodes, edges)
        
        features = {}
        
        try:
            # Basic graph statistics
            features["num_nodes"] = G.number_of_nodes()
            features["num_edges"] = G.number_of_edges()
            features["density"] = nx.density(G)
            features["avg_degree"] = np.mean([G.degree(n) for n in G.nodes()])
            
            # Connectivity features
            if nx.is_connected(G.to_undirected()):
                features["diameter"] = nx.diameter(G.to_undirected())
                features["avg_shortest_path"] = nx.average_shortest_path_length(G.to_undirected())
            else:
                features["diameter"] = 0
                features["avg_shortest_path"] = 0
            
            # Clustering features
            features["avg_clustering"] = nx.average_clustering(G.to_undirected())
            features["transitivity"] = nx.transitivity(G.to_undirected())
            
            # Centralization features
            centralities = nx.degree_centrality(G)
            features["centralization"] = max(centralities.values()) - min(centralities.values())
            
        except Exception as e:
            logger.warning(f"Error extracting graph features: {e}")
        
        return features
    
    def _create_networkx_graph(self, nodes: List[Dict], edges: List[Dict]) -> nx.Graph:
        """Create NetworkX graph from node/edge data"""
        G = nx.Graph()
        
        # Add nodes
        for node in nodes:
            G.add_node(node["id"], **node.get("properties", {}))
        
        # Add edges
        for edge in edges:
            weight = edge.get("weight", 1.0)
            G.add_edge(edge["source"], edge["target"], weight=weight, **edge.get("properties", {}))
        
        return G


class GraphMLEngine:
    """
    Machine learning engine for graph analysis
    
    Provides training, prediction, and model management capabilities for graph ML tasks.
    """
    
    def __init__(self, graph_manager: GraphDatabaseManager = None):
        self.graph_manager = graph_manager or get_graph_manager()
        self.feature_extractor = GraphFeatureExtractor(graph_manager)
        self.models: Dict[str, Any] = {}  # In-memory model cache
        self.model_metadata: Dict[str, MLModel] = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    def train_node_classifier(self, graph_name: str, target_property: str, 
                             algorithm: MLAlgorithm = MLAlgorithm.RANDOM_FOREST,
                             test_size: float = 0.2, **kwargs) -> MLModel:
        """
        Train a node classification model
        
        Args:
            graph_name: Name of the graph
            target_property: Node property to predict
            algorithm: ML algorithm to use
            test_size: Fraction of data for testing
            
        Returns:
            Trained MLModel instance
        """
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required for ML functionality")
        
        try:
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=5000)
            
            # Extract features
            features, feature_names, node_ids = self.feature_extractor.extract_node_features(graph_data)
            
            if features.size == 0:
                raise ValueError("No features could be extracted from the graph")
            
            # Extract target labels
            nodes = graph_data["nodes"]
            node_dict = {node["id"]: node for node in nodes}
            
            labels = []
            valid_indices = []
            
            for i, node_id in enumerate(node_ids):
                node = node_dict.get(node_id, {})
                properties = node.get("properties", {})
                
                if target_property in properties:
                    labels.append(properties[target_property])
                    valid_indices.append(i)
            
            if not labels:
                raise ValueError(f"No nodes have the target property '{target_property}'")
            
            # Filter features to valid indices
            X = features[valid_indices]
            y = np.array(labels)
            
            # Encode labels if they are strings
            label_encoder = None
            if y.dtype == object:
                label_encoder = LabelEncoder()
                y = label_encoder.fit_transform(y)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42, stratify=y
            )
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train model
            model = self._create_classifier(algorithm, **kwargs)
            model.fit(X_train_scaled, y_train)
            
            # Evaluate model
            y_pred = model.predict(X_test_scaled)
            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),
                "precision": precision_score(y_test, y_pred, average="weighted", zero_division=0),
                "recall": recall_score(y_test, y_pred, average="weighted", zero_division=0),
                "f1_score": f1_score(y_test, y_pred, average="weighted", zero_division=0)
            }
            
            # Create model metadata
            model_id = f"node_classifier_{graph_name}_{target_property}_{int(datetime.now(tz=timezone.utc).timestamp())}"
            
            ml_model = MLModel(
                id=model_id,
                name=f"Node Classifier for {target_property}",
                task_type=MLTaskType.NODE_CLASSIFICATION,
                algorithm=algorithm,
                graph_name=graph_name,
                created_at=datetime.now(tz=timezone.utc),
                updated_at=datetime.now(tz=timezone.utc),
                parameters=kwargs,
                metrics=metrics,
                features=feature_names,
                status="trained"
            )
            
            # Store model and metadata
            self.models[model_id] = {
                "model": model,
                "scaler": scaler,
                "label_encoder": label_encoder,
                "feature_names": feature_names
            }
            self.model_metadata[model_id] = ml_model
            
            # Track training activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"ML Model Training: {model_id}",
                description=f"Trained node classifier for property '{target_property}' on graph '{graph_name}'",
                details={
                    "model_id": model_id,
                    "algorithm": algorithm.value,
                    "graph_name": graph_name,
                    "target_property": target_property,
                    "accuracy": metrics["accuracy"],
                    "training_samples": len(X_train),
                    "test_samples": len(X_test)
                }
            )
            
            logger.info(f"Successfully trained node classifier {model_id} with accuracy: {metrics['accuracy']:.3f}")
            return ml_model
            
        except Exception as e:
            logger.error(f"Node classifier training failed: {e}")
            raise
    
    def train_link_predictor(self, graph_name: str, 
                           algorithm: MLAlgorithm = MLAlgorithm.LOGISTIC_REGRESSION,
                           negative_samples_ratio: float = 1.0, **kwargs) -> MLModel:
        """Train a link prediction model"""
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required for ML functionality")
        
        try:
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=5000)
            
            nodes = graph_data["nodes"]
            edges = graph_data["edges"]
            
            if not nodes or not edges:
                raise ValueError("Graph must have both nodes and edges for link prediction")
            
            # Create NetworkX graph
            G = self.feature_extractor._create_networkx_graph(nodes, edges)
            
            # Generate positive samples (existing edges)
            positive_samples = []
            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                if source in G and target in G:
                    positive_samples.append((source, target, 1))
            
            # Generate negative samples (non-existing edges)
            negative_samples = []
            node_ids = [node["id"] for node in nodes]
            
            import random
            random.seed(42)
            
            num_negative = int(len(positive_samples) * negative_samples_ratio)
            attempts = 0
            max_attempts = num_negative * 10
            
            while len(negative_samples) < num_negative and attempts < max_attempts:
                source = random.choice(node_ids)
                target = random.choice(node_ids)
                
                if source != target and not G.has_edge(source, target):
                    negative_samples.append((source, target, 0))
                
                attempts += 1
            
            # Combine samples
            all_samples = positive_samples + negative_samples
            random.shuffle(all_samples)
            
            # Extract features for each node pair
            features = []
            labels = []
            
            for source, target, label in all_samples:
                # Node pair features
                pair_features = self._extract_node_pair_features(G, source, target)
                features.append(pair_features)
                labels.append(label)
            
            X = np.array(features, dtype=float)
            y = np.array(labels)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train model
            model = self._create_classifier(algorithm, **kwargs)
            model.fit(X_train_scaled, y_train)
            
            # Evaluate model
            y_pred = model.predict(X_test_scaled)
            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),
                "precision": precision_score(y_test, y_pred),
                "recall": recall_score(y_test, y_pred),
                "f1_score": f1_score(y_test, y_pred)
            }
            
            # Create model metadata
            model_id = f"link_predictor_{graph_name}_{int(datetime.now(tz=timezone.utc).timestamp())}"
            
            ml_model = MLModel(
                id=model_id,
                name=f"Link Predictor for {graph_name}",
                task_type=MLTaskType.LINK_PREDICTION,
                algorithm=algorithm,
                graph_name=graph_name,
                created_at=datetime.now(tz=timezone.utc),
                updated_at=datetime.now(tz=timezone.utc),
                parameters=kwargs,
                metrics=metrics,
                features=["common_neighbors", "jaccard_coefficient", "adamic_adar", "preferential_attachment"],
                status="trained"
            )
            
            # Store model
            self.models[model_id] = {
                "model": model,
                "scaler": scaler,
                "feature_names": ml_model.features
            }
            self.model_metadata[model_id] = ml_model
            
            logger.info(f"Successfully trained link predictor {model_id} with accuracy: {metrics['accuracy']:.3f}")
            return ml_model
            
        except Exception as e:
            logger.error(f"Link predictor training failed: {e}")
            raise
    
    def train_anomaly_detector(self, graph_name: str, 
                             algorithm: MLAlgorithm = MLAlgorithm.ISOLATION_FOREST,
                             contamination: float = 0.1, **kwargs) -> MLModel:
        """Train an anomaly detection model for nodes"""
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required for ML functionality")
        
        try:
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=5000)
            
            # Extract features
            features, feature_names, node_ids = self.feature_extractor.extract_node_features(graph_data)
            
            if features.size == 0:
                raise ValueError("No features could be extracted from the graph")
            
            # Scale features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(features)
            
            # Train anomaly detector
            if algorithm == MLAlgorithm.ISOLATION_FOREST:
                model = IsolationForest(contamination=contamination, random_state=42, **kwargs)
            else:
                raise ValueError(f"Algorithm {algorithm} not supported for anomaly detection")
            
            model.fit(X_scaled)
            
            # Get anomaly scores and predictions
            anomaly_scores = model.decision_function(X_scaled)
            predictions = model.predict(X_scaled)
            
            # Calculate metrics
            num_anomalies = np.sum(predictions == -1)
            anomaly_ratio = num_anomalies / len(predictions)
            
            metrics = {
                "num_anomalies": int(num_anomalies),
                "anomaly_ratio": float(anomaly_ratio),
                "avg_anomaly_score": float(np.mean(anomaly_scores[predictions == -1])) if num_anomalies > 0 else 0.0,
                "avg_normal_score": float(np.mean(anomaly_scores[predictions == 1]))
            }
            
            # Create model metadata
            model_id = f"anomaly_detector_{graph_name}_{int(datetime.now(tz=timezone.utc).timestamp())}"
            
            ml_model = MLModel(
                id=model_id,
                name=f"Anomaly Detector for {graph_name}",
                task_type=MLTaskType.ANOMALY_DETECTION,
                algorithm=algorithm,
                graph_name=graph_name,
                created_at=datetime.now(tz=timezone.utc),
                updated_at=datetime.now(tz=timezone.utc),
                parameters={"contamination": contamination, **kwargs},
                metrics=metrics,
                features=feature_names,
                status="trained"
            )
            
            # Store model
            self.models[model_id] = {
                "model": model,
                "scaler": scaler,
                "feature_names": feature_names,
                "node_ids": node_ids
            }
            self.model_metadata[model_id] = ml_model
            
            logger.info(f"Successfully trained anomaly detector {model_id}. Found {num_anomalies} anomalies ({anomaly_ratio:.2%})")
            return ml_model
            
        except Exception as e:
            logger.error(f"Anomaly detector training failed: {e}")
            raise
    
    def predict(self, model_id: str, target_ids: List[str] = None) -> List[MLPrediction]:
        """Make predictions using a trained model"""
        if model_id not in self.models or model_id not in self.model_metadata:
            raise ValueError(f"Model {model_id} not found")
        
        try:
            model_data = self.models[model_id]
            model_meta = self.model_metadata[model_id]
            
            model = model_data["model"]
            scaler = model_data["scaler"]
            feature_names = model_data["feature_names"]
            
            # Get current graph data
            graph_manager = get_graph_manager(model_meta.graph_name)
            graph_data = graph_manager.get_graph_data(limit=5000)
            
            predictions = []
            
            if model_meta.task_type == MLTaskType.NODE_CLASSIFICATION:
                # Extract features for target nodes
                features, _, node_ids = self.feature_extractor.extract_node_features(graph_data)
                
                if target_ids:
                    # Filter to specific target nodes
                    target_indices = [i for i, node_id in enumerate(node_ids) if node_id in target_ids]
                    features = features[target_indices]
                    node_ids = [node_ids[i] for i in target_indices]
                
                # Scale features and predict
                X_scaled = scaler.transform(features)
                predictions_array = model.predict(X_scaled)
                probabilities_array = model.predict_proba(X_scaled) if hasattr(model, "predict_proba") else None
                
                # Convert predictions to MLPrediction objects
                for i, node_id in enumerate(node_ids):
                    pred = predictions_array[i]
                    confidence = 1.0
                    probs = {}
                    
                    if probabilities_array is not None:
                        prob_values = probabilities_array[i]
                        confidence = max(prob_values)
                        
                        # Map class probabilities
                        classes = model.classes_ if hasattr(model, "classes_") else range(len(prob_values))
                        probs = {str(cls): float(prob) for cls, prob in zip(classes, prob_values)}
                    
                    # Decode label if label encoder was used
                    if "label_encoder" in model_data and model_data["label_encoder"]:
                        pred = model_data["label_encoder"].inverse_transform([pred])[0]
                    
                    prediction = MLPrediction(
                        model_id=model_id,
                        target_id=node_id,
                        prediction=pred,
                        confidence=confidence,
                        probabilities=probs,
                        features={name: float(features[i][j]) for j, name in enumerate(feature_names)}
                    )
                    predictions.append(prediction)
            
            elif model_meta.task_type == MLTaskType.ANOMALY_DETECTION:
                # Extract features for all nodes
                features, _, node_ids = self.feature_extractor.extract_node_features(graph_data)
                
                if target_ids:
                    # Filter to specific target nodes
                    target_indices = [i for i, node_id in enumerate(node_ids) if node_id in target_ids]
                    features = features[target_indices]
                    node_ids = [node_ids[i] for i in target_indices]
                
                # Scale features and predict
                X_scaled = scaler.transform(features)
                anomaly_predictions = model.predict(X_scaled)
                anomaly_scores = model.decision_function(X_scaled)
                
                # Convert to MLPrediction objects
                for i, node_id in enumerate(node_ids):
                    is_anomaly = anomaly_predictions[i] == -1
                    score = anomaly_scores[i]
                    confidence = abs(score)  # Use absolute score as confidence
                    
                    prediction = MLPrediction(
                        model_id=model_id,
                        target_id=node_id,
                        prediction="anomaly" if is_anomaly else "normal",
                        confidence=confidence,
                        features={name: float(features[i][j]) for j, name in enumerate(feature_names)},
                        metadata={"anomaly_score": float(score)}
                    )
                    predictions.append(prediction)
            
            return predictions
            
        except Exception as e:
            logger.error(f"Prediction failed for model {model_id}: {e}")
            raise
    
    def _create_classifier(self, algorithm: MLAlgorithm, **kwargs):
        """Create classifier instance based on algorithm"""
        if algorithm == MLAlgorithm.RANDOM_FOREST:
            return RandomForestClassifier(random_state=42, **kwargs)
        elif algorithm == MLAlgorithm.LOGISTIC_REGRESSION:
            return LogisticRegression(random_state=42, max_iter=1000, **kwargs)
        else:
            raise ValueError(f"Classifier algorithm {algorithm} not supported")
    
    def _extract_node_pair_features(self, G: nx.Graph, source: str, target: str) -> List[float]:
        """Extract features for a node pair for link prediction"""
        features = []
        
        try:
            # Common neighbors
            if source in G and target in G:
                common_neighbors = len(list(nx.common_neighbors(G, source, target)))
                
                # Jaccard coefficient
                jaccard = list(nx.jaccard_coefficient(G, [(source, target)]))[0][2]
                
                # Adamic-Adar index
                adamic_adar = list(nx.adamic_adar_index(G, [(source, target)]))[0][2]
                
                # Preferential attachment
                pref_attachment = list(nx.preferential_attachment(G, [(source, target)]))[0][2]
                
            else:
                common_neighbors = 0
                jaccard = 0
                adamic_adar = 0
                pref_attachment = 0
            
            features = [common_neighbors, jaccard, adamic_adar, pref_attachment]
            
        except Exception as e:
            logger.warning(f"Error extracting node pair features: {e}")
            features = [0, 0, 0, 0]
        
        return features
    
    def get_model_list(self, graph_name: str = None) -> List[MLModel]:
        """Get list of trained models"""
        models = list(self.model_metadata.values())
        
        if graph_name:
            models = [model for model in models if model.graph_name == graph_name]
        
        return sorted(models, key=lambda m: m.updated_at, reverse=True)
    
    def get_model(self, model_id: str) -> Optional[MLModel]:
        """Get specific model metadata"""
        return self.model_metadata.get(model_id)
    
    def delete_model(self, model_id: str):
        """Delete a trained model"""
        self.models.pop(model_id, None)
        self.model_metadata.pop(model_id, None)
        logger.info(f"Deleted model: {model_id}")


class GraphPatternMiner:
    """
    Pattern mining and discovery in graph data
    
    Identifies frequent subgraphs, motifs, and structural patterns.
    """
    
    def __init__(self, graph_manager: GraphDatabaseManager = None):
        self.graph_manager = graph_manager or get_graph_manager()
    
    def find_frequent_subgraphs(self, graph_name: str, min_support: int = 3,
                               max_size: int = 5) -> List[Dict[str, Any]]:
        """Find frequent subgraph patterns"""
        try:
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=2000)
            
            if not graph_data.get("success"):
                return []
            
            nodes = graph_data["nodes"]
            edges = graph_data["edges"]
            
            # Create NetworkX graph
            G = nx.Graph()
            for node in nodes:
                G.add_node(node["id"], **node.get("properties", {}))
            
            for edge in edges:
                G.add_edge(edge["source"], edge["target"], **edge.get("properties", {}))
            
            # Find motifs and patterns
            patterns = []
            
            # Find triangles (3-node motifs)
            triangles = list(nx.enumerate_all_cliques(G))
            triangle_count = len([clique for clique in triangles if len(clique) == 3])
            
            if triangle_count >= min_support:
                patterns.append({
                    "pattern_type": "triangle",
                    "size": 3,
                    "frequency": triangle_count,
                    "description": "Three nodes fully connected to each other"
                })
            
            # Find stars (hub patterns)
            star_patterns = {}
            for node in G.nodes():
                degree = G.degree(node)
                if degree >= 3:  # Minimum star size
                    star_key = f"star_{degree}"
                    star_patterns[star_key] = star_patterns.get(star_key, 0) + 1
            
            for star_type, count in star_patterns.items():
                if count >= min_support:
                    degree = int(star_type.split("_")[1])
                    patterns.append({
                        "pattern_type": "star",
                        "size": degree + 1,
                        "frequency": count,
                        "description": f"Hub node connected to {degree} other nodes"
                    })
            
            # Find chains (path patterns)
            chain_patterns = {}
            for node in G.nodes():
                # Find paths of different lengths starting from this node
                for length in range(2, min(max_size, 6)):
                    try:
                        paths = list(nx.all_simple_paths(G, node, length=length))
                        if paths:
                            chain_key = f"chain_{length}"
                            chain_patterns[chain_key] = chain_patterns.get(chain_key, 0) + len(paths)
                    except:
                        continue
            
            for chain_type, count in chain_patterns.items():
                if count >= min_support:
                    length = int(chain_type.split("_")[1])
                    patterns.append({
                        "pattern_type": "chain",
                        "size": length + 1,
                        "frequency": count,
                        "description": f"Linear chain of {length + 1} connected nodes"
                    })
            
            # Sort by frequency
            patterns.sort(key=lambda p: p["frequency"], reverse=True)
            
            return patterns
            
        except Exception as e:
            logger.error(f"Pattern mining failed for graph {graph_name}: {e}")
            return []
    
    def analyze_node_similarity(self, graph_name: str, similarity_threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Analyze node similarity based on structural features"""
        try:
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=2000)
            
            if not graph_data.get("success"):
                return []
            
            # Extract node features
            feature_extractor = GraphFeatureExtractor(graph_manager)
            features, feature_names, node_ids = feature_extractor.extract_node_features(graph_data)
            
            if features.size == 0:
                return []
            
            # Calculate pairwise similarities
            from sklearn.metrics.pairwise import cosine_similarity
            similarities = cosine_similarity(features)
            
            similar_pairs = []
            
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    similarity = similarities[i, j]
                    
                    if similarity >= similarity_threshold:
                        similar_pairs.append({
                            "node_a": node_ids[i],
                            "node_b": node_ids[j],
                            "similarity": float(similarity),
                            "feature_vector_a": features[i].tolist(),
                            "feature_vector_b": features[j].tolist()
                        })
            
            # Sort by similarity
            similar_pairs.sort(key=lambda p: p["similarity"], reverse=True)
            
            return similar_pairs[:50]  # Return top 50 similar pairs
            
        except Exception as e:
            logger.error(f"Node similarity analysis failed: {e}")
            return []


# Global ML engine instance
_ml_engine = None
_pattern_miner = None


def get_ml_engine() -> GraphMLEngine:
    """Get or create global ML engine instance"""
    global _ml_engine
    if _ml_engine is None:
        _ml_engine = GraphMLEngine()
    return _ml_engine


def get_pattern_miner() -> GraphPatternMiner:
    """Get or create global pattern miner instance"""
    global _pattern_miner
    if _pattern_miner is None:
        _pattern_miner = GraphPatternMiner()
    return _pattern_miner