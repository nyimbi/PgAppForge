"""
Machine Learning View for Graph Analysis

Provides web interface for training ML models, making predictions,
and managing machine learning workflows for graph data.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.graph_ml import (
    get_ml_engine,
    get_pattern_miner,
    GraphMLEngine,
    GraphPatternMiner,
    MLTaskType,
    MLAlgorithm
)
from ..database.graph_manager import get_graph_manager
from ..database.multi_graph_manager import get_graph_registry
from ..database.activity_tracker import (
    track_database_activity,
    ActivityType,
    ActivitySeverity
)
from ..utils.error_handling import (
    WizardErrorHandler,
    WizardErrorType,
    WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class GraphMLView(BaseView):
    """
    Machine Learning interface for graph analysis
    
    Provides model training, prediction, and pattern mining capabilities
    with intuitive web interface and comprehensive API endpoints.
    """
    
    route_base = "/graph/ml"
    default_view = "index"
    
    def __init__(self):
        """Initialize ML view"""
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.ml_engine = None
        self.pattern_miner = None
    
    def _ensure_admin_access(self):
        """Ensure current user has admin privileges"""
        try:
            from flask_login import current_user
            
            if not current_user or not current_user.is_authenticated:
                raise Forbidden("Authentication required")
            
            # Check if user has admin role
            if hasattr(current_user, "roles"):
                admin_roles = ["Admin", "admin", "Administrator", "administrator"]
                user_roles = [
                    role.name if hasattr(role, "name") else str(role)
                    for role in current_user.roles
                ]
                
                if not any(role in admin_roles for role in user_roles):
                    raise Forbidden("Administrator privileges required")
            else:
                # Fallback check for is_admin attribute
                if not getattr(current_user, "is_admin", False):
                    raise Forbidden("Administrator privileges required")
                    
        except Exception as e:
            logger.error(f"Admin access check failed: {e}")
            raise Forbidden("Access denied")
    
    def _get_ml_engine(self) -> GraphMLEngine:
        """Get or initialize ML engine"""
        try:
            return get_ml_engine()
        except Exception as e:
            logger.error(f"Failed to initialize ML engine: {e}")
            self.error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            raise
    
    def _get_pattern_miner(self) -> GraphPatternMiner:
        """Get or initialize pattern miner"""
        try:
            return get_pattern_miner()
        except Exception as e:
            logger.error(f"Failed to initialize pattern miner: {e}")
            raise
    
    @expose("/")
    @has_access
    @permission_name("can_use_ml")
    def index(self):
        """Main ML dashboard"""
        try:
            self._ensure_admin_access()
            
            ml_engine = self._get_ml_engine()
            
            # Get available graphs
            registry = get_graph_registry()
            graphs = registry.list_graphs()
            
            # Get trained models
            models = ml_engine.get_model_list()
            
            # Get model statistics
            model_stats = {
                "total_models": len(models),
                "by_task_type": {},
                "by_graph": {},
                "recent_models": models[:5]
            }
            
            for model in models:
                task_type = model.task_type.value
                graph_name = model.graph_name
                
                model_stats["by_task_type"][task_type] = model_stats["by_task_type"].get(task_type, 0) + 1
                model_stats["by_graph"][graph_name] = model_stats["by_graph"].get(graph_name, 0) + 1
            
            return render_template(
                "ml/index.html",
                title="Graph Machine Learning",
                graphs=[graph.to_dict() for graph in graphs],
                models=[model.to_dict() for model in models],
                model_stats=model_stats
            )
            
        except Exception as e:
            logger.error(f"Error in ML dashboard: {e}")
            flash(f"Error loading ML dashboard: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/models/")
    @has_access
    @permission_name("can_use_ml")
    def models(self):
        """Model management interface"""
        try:
            self._ensure_admin_access()
            
            ml_engine = self._get_ml_engine()
            models = ml_engine.get_model_list()
            
            return render_template(
                "ml/models.html",
                title="ML Models",
                models=[model.to_dict() for model in models]
            )
            
        except Exception as e:
            logger.error(f"Error in models interface: {e}")
            flash(f"Error loading models: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/patterns/")
    @has_access
    @permission_name("can_use_ml")
    def patterns(self):
        """Pattern mining interface"""
        try:
            self._ensure_admin_access()
            
            # Get available graphs
            registry = get_graph_registry()
            graphs = registry.list_graphs()
            
            return render_template(
                "ml/patterns.html",
                title="Pattern Mining",
                graphs=[graph.to_dict() for graph in graphs]
            )
            
        except Exception as e:
            logger.error(f"Error in patterns interface: {e}")
            flash(f"Error loading patterns interface: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/predictions/")
    @has_access
    @permission_name("can_use_ml")
    def predictions(self):
        """Predictions interface"""
        try:
            self._ensure_admin_access()
            
            ml_engine = self._get_ml_engine()
            models = ml_engine.get_model_list()
            
            return render_template(
                "ml/predictions.html",
                title="ML Predictions",
                models=[model.to_dict() for model in models]
            )
            
        except Exception as e:
            logger.error(f"Error in predictions interface: {e}")
            flash(f"Error loading predictions interface: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    # API Endpoints
    
    @expose_api("get", "/api/task-types/")
    @has_access
    @permission_name("can_use_ml")
    def api_get_task_types(self):
        """API endpoint to get available ML task types"""
        try:
            self._ensure_admin_access()
            
            task_types = [
                {
                    "value": task_type.value,
                    "name": task_type.value.replace("_", " ").title(),
                    "description": self._get_task_description(task_type)
                }
                for task_type in MLTaskType
            ]
            
            return jsonify({
                "success": True,
                "task_types": task_types
            })
            
        except Exception as e:
            logger.error(f"API error getting task types: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/algorithms/")
    @has_access
    @permission_name("can_use_ml")
    def api_get_algorithms(self):
        """API endpoint to get available ML algorithms"""
        try:
            self._ensure_admin_access()
            
            task_type = request.args.get("task_type")
            
            algorithms = []
            for algorithm in MLAlgorithm:
                if self._is_algorithm_compatible(algorithm, task_type):
                    algorithms.append({
                        "value": algorithm.value,
                        "name": algorithm.value.replace("_", " ").title(),
                        "description": self._get_algorithm_description(algorithm)
                    })
            
            return jsonify({
                "success": True,
                "algorithms": algorithms
            })
            
        except Exception as e:
            logger.error(f"API error getting algorithms: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/train/")
    @has_access
    @permission_name("can_use_ml")
    def api_train_model(self):
        """API endpoint to train ML model"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            # Extract training parameters
            graph_name = data.get("graph_name")
            task_type = data.get("task_type")
            algorithm = data.get("algorithm")
            
            if not all([graph_name, task_type, algorithm]):
                raise BadRequest("graph_name, task_type, and algorithm are required")
            
            # Convert string enums
            task_type_enum = MLTaskType(task_type)
            algorithm_enum = MLAlgorithm(algorithm)
            
            ml_engine = self._get_ml_engine()
            
            # Train based on task type
            if task_type_enum == MLTaskType.NODE_CLASSIFICATION:
                target_property = data.get("target_property")
                if not target_property:
                    raise BadRequest("target_property is required for node classification")
                
                test_size = data.get("test_size", 0.2)
                model = ml_engine.train_node_classifier(
                    graph_name=graph_name,
                    target_property=target_property,
                    algorithm=algorithm_enum,
                    test_size=test_size
                )
                
            elif task_type_enum == MLTaskType.LINK_PREDICTION:
                negative_samples_ratio = data.get("negative_samples_ratio", 1.0)
                model = ml_engine.train_link_predictor(
                    graph_name=graph_name,
                    algorithm=algorithm_enum,
                    negative_samples_ratio=negative_samples_ratio
                )
                
            elif task_type_enum == MLTaskType.ANOMALY_DETECTION:
                contamination = data.get("contamination", 0.1)
                model = ml_engine.train_anomaly_detector(
                    graph_name=graph_name,
                    algorithm=algorithm_enum,
                    contamination=contamination
                )
                
            else:
                raise BadRequest(f"Task type {task_type} not supported yet")
            
            return jsonify({
                "success": True,
                "model": model.to_dict(),
                "message": f"Model {model.id} trained successfully"
            })
            
        except Exception as e:
            logger.error(f"API error training model: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/predict/")
    @has_access
    @permission_name("can_use_ml")
    def api_make_predictions(self):
        """API endpoint to make predictions with trained model"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            model_id = data.get("model_id")
            target_ids = data.get("target_ids")  # Optional
            
            if not model_id:
                raise BadRequest("model_id is required")
            
            ml_engine = self._get_ml_engine()
            predictions = ml_engine.predict(model_id, target_ids)
            
            return jsonify({
                "success": True,
                "predictions": [pred.to_dict() for pred in predictions],
                "count": len(predictions)
            })
            
        except Exception as e:
            logger.error(f"API error making predictions: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/models/")
    @has_access
    @permission_name("can_use_ml")
    def api_get_models(self):
        """API endpoint to get trained models"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph_name")
            
            ml_engine = self._get_ml_engine()
            models = ml_engine.get_model_list(graph_name)
            
            return jsonify({
                "success": True,
                "models": [model.to_dict() for model in models]
            })
            
        except Exception as e:
            logger.error(f"API error getting models: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/models/<model_id>/")
    @has_access
    @permission_name("can_use_ml")
    def api_get_model(self, model_id: str):
        """API endpoint to get specific model"""
        try:
            self._ensure_admin_access()
            
            ml_engine = self._get_ml_engine()
            model = ml_engine.get_model(model_id)
            
            if not model:
                return jsonify({"success": False, "error": "Model not found"}), 404
            
            return jsonify({
                "success": True,
                "model": model.to_dict()
            })
            
        except Exception as e:
            logger.error(f"API error getting model: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("delete", "/api/models/<model_id>/")
    @has_access
    @permission_name("can_use_ml")
    def api_delete_model(self, model_id: str):
        """API endpoint to delete model"""
        try:
            self._ensure_admin_access()
            
            ml_engine = self._get_ml_engine()
            ml_engine.delete_model(model_id)
            
            # Track model deletion
            track_database_activity(
                activity_type=ActivityType.TABLE_DELETED,
                target=f"ML Model: {model_id}",
                description=f"Deleted machine learning model",
                details={"model_id": model_id}
            )
            
            return jsonify({
                "success": True,
                "message": f"Model {model_id} deleted successfully"
            })
            
        except Exception as e:
            logger.error(f"API error deleting model: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/patterns/mine/")
    @has_access
    @permission_name("can_use_ml")
    def api_mine_patterns(self):
        """API endpoint to mine graph patterns"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            graph_name = data.get("graph_name")
            if not graph_name:
                raise BadRequest("graph_name is required")
            
            min_support = data.get("min_support", 3)
            max_size = data.get("max_size", 5)
            
            pattern_miner = self._get_pattern_miner()
            patterns = pattern_miner.find_frequent_subgraphs(
                graph_name=graph_name,
                min_support=min_support,
                max_size=max_size
            )
            
            # Track pattern mining activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Pattern Mining: {graph_name}",
                description=f"Mined {len(patterns)} patterns from graph",
                details={
                    "graph_name": graph_name,
                    "patterns_found": len(patterns),
                    "min_support": min_support,
                    "max_size": max_size
                }
            )
            
            return jsonify({
                "success": True,
                "patterns": patterns,
                "count": len(patterns)
            })
            
        except Exception as e:
            logger.error(f"API error mining patterns: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/similarity/analyze/")
    @has_access
    @permission_name("can_use_ml")
    def api_analyze_similarity(self):
        """API endpoint to analyze node similarity"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            graph_name = data.get("graph_name")
            if not graph_name:
                raise BadRequest("graph_name is required")
            
            similarity_threshold = data.get("similarity_threshold", 0.7)
            
            pattern_miner = self._get_pattern_miner()
            similar_pairs = pattern_miner.analyze_node_similarity(
                graph_name=graph_name,
                similarity_threshold=similarity_threshold
            )
            
            return jsonify({
                "success": True,
                "similar_pairs": similar_pairs,
                "count": len(similar_pairs)
            })
            
        except Exception as e:
            logger.error(f"API error analyzing similarity: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/graph-properties/<graph_name>/")
    @has_access
    @permission_name("can_use_ml")
    def api_get_graph_properties(self, graph_name: str):
        """API endpoint to get graph node properties for ML training"""
        try:
            self._ensure_admin_access()
            
            # Get graph data
            graph_manager = get_graph_manager(graph_name)
            graph_data = graph_manager.get_graph_data(limit=100)
            
            if not graph_data.get("success"):
                return jsonify({
                    "success": False, 
                    "error": "Could not load graph data"
                }), 500
            
            # Extract unique properties from nodes
            properties = set()
            node_properties = {}
            
            for node in graph_data["nodes"]:
                node_props = node.get("properties", {})
                for prop_name, prop_value in node_props.items():
                    properties.add(prop_name)
                    
                    if prop_name not in node_properties:
                        node_properties[prop_name] = {
                            "type": type(prop_value).__name__,
                            "sample_values": [],
                            "unique_values": set()
                        }
                    
                    # Collect sample values
                    if len(node_properties[prop_name]["sample_values"]) < 10:
                        node_properties[prop_name]["sample_values"].append(prop_value)
                    
                    # Track unique values for categorical properties
                    if isinstance(prop_value, str) and len(node_properties[prop_name]["unique_values"]) < 50:
                        node_properties[prop_name]["unique_values"].add(prop_value)
            
            # Convert sets to lists for JSON serialization
            for prop_name in node_properties:
                node_properties[prop_name]["unique_values"] = list(node_properties[prop_name]["unique_values"])
            
            return jsonify({
                "success": True,
                "properties": sorted(list(properties)),
                "property_details": node_properties
            })
            
        except Exception as e:
            logger.error(f"API error getting graph properties: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    def _get_task_description(self, task_type: MLTaskType) -> str:
        """Get description for ML task type"""
        descriptions = {
            MLTaskType.NODE_CLASSIFICATION: "Predict node labels/categories based on features",
            MLTaskType.LINK_PREDICTION: "Predict likelihood of connections between nodes",
            MLTaskType.ANOMALY_DETECTION: "Identify unusual or outlier nodes in the graph",
            MLTaskType.COMMUNITY_DETECTION: "Find clusters and communities of related nodes",
            MLTaskType.GRAPH_EMBEDDING: "Create vector representations of nodes/edges",
            MLTaskType.PATTERN_MINING: "Discover frequent subgraph patterns",
            MLTaskType.SIMILARITY_ANALYSIS: "Find similar nodes based on structural features",
            MLTaskType.TREND_PREDICTION: "Predict future graph evolution patterns"
        }
        return descriptions.get(task_type, "Unknown task type")
    
    def _get_algorithm_description(self, algorithm: MLAlgorithm) -> str:
        """Get description for ML algorithm"""
        descriptions = {
            MLAlgorithm.RANDOM_FOREST: "Ensemble method using multiple decision trees",
            MLAlgorithm.LOGISTIC_REGRESSION: "Linear classification with probabilistic output",
            MLAlgorithm.ISOLATION_FOREST: "Unsupervised anomaly detection algorithm",
            MLAlgorithm.KMEANS: "Centroid-based clustering algorithm",
            MLAlgorithm.DBSCAN: "Density-based clustering algorithm",
            MLAlgorithm.PCA: "Principal component analysis for dimensionality reduction",
            MLAlgorithm.TSNE: "t-SNE for non-linear dimensionality reduction",
            MLAlgorithm.NEAREST_NEIGHBORS: "k-NN algorithm for similarity-based prediction",
            MLAlgorithm.GRAPH_NEURAL_NETWORK: "Deep learning for graph-structured data",
            MLAlgorithm.NODE2VEC: "Node embedding algorithm using random walks",
            MLAlgorithm.DEEPWALK: "Deep learning approach for node embeddings"
        }
        return descriptions.get(algorithm, "Unknown algorithm")
    
    def _is_algorithm_compatible(self, algorithm: MLAlgorithm, task_type: str = None) -> bool:
        """Check if algorithm is compatible with task type"""
        if not task_type:
            return True
        
        compatibility = {
            "node_classification": [MLAlgorithm.RANDOM_FOREST, MLAlgorithm.LOGISTIC_REGRESSION],
            "link_prediction": [MLAlgorithm.LOGISTIC_REGRESSION, MLAlgorithm.RANDOM_FOREST],
            "anomaly_detection": [MLAlgorithm.ISOLATION_FOREST],
            "community_detection": [MLAlgorithm.KMEANS, MLAlgorithm.DBSCAN],
            "graph_embedding": [MLAlgorithm.PCA, MLAlgorithm.TSNE, MLAlgorithm.NODE2VEC],
            "pattern_mining": [],  # Uses specialized algorithms
            "similarity_analysis": [MLAlgorithm.NEAREST_NEIGHBORS],
            "trend_prediction": [MLAlgorithm.RANDOM_FOREST, MLAlgorithm.LOGISTIC_REGRESSION]
        }
        
        compatible_algorithms = compatibility.get(task_type, [])
        return algorithm in compatible_algorithms