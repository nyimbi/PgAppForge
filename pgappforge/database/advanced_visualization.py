"""
Advanced Visualization Engine for Graph Data

Provides sophisticated visualization capabilities including interactive layouts,
3D rendering, dynamic animations, and customizable visual themes.
"""

import json
import logging
import math
import threading
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
import hashlib
import colorsys
import random

import numpy as np
from sqlalchemy import text

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType
from .performance_optimizer import get_performance_monitor, performance_cache

logger = logging.getLogger(__name__)


class LayoutType(Enum):
	"""Types of graph layout algorithms"""
	FORCE_DIRECTED = "force_directed"
	CIRCULAR = "circular"
	HIERARCHICAL = "hierarchical"
	GRID = "grid"
	CONCENTRIC = "concentric"
	COSE = "cose"
	DAGRE = "dagre"
	BREADTHFIRST = "breadthfirst"
	RANDOM = "random"
	PRESET = "preset"
	FCOSE = "fcose"
	KLAY = "klay"
	EULER = "euler"


class VisualizationType(Enum):
	"""Types of visualizations"""
	NETWORK_2D = "network_2d"
	NETWORK_3D = "network_3d"
	MATRIX = "matrix"
	SANKEY = "sankey"
	TREEMAP = "treemap"
	SUNBURST = "sunburst"
	FORCE_GRAPH = "force_graph"
	ARC_DIAGRAM = "arc_diagram"
	CHORD_DIAGRAM = "chord_diagram"
	HIVE_PLOT = "hive_plot"


class RenderingMode(Enum):
	"""Rendering modes for performance optimization"""
	CANVAS = "canvas"
	SVG = "svg"
	WEBGL = "webgl"
	AUTO = "auto"


class AnimationType(Enum):
	"""Types of animations"""
	NONE = "none"
	FADE_IN = "fade_in"
	SLIDE_IN = "slide_in"
	SPRING = "spring"
	MORPHING = "morphing"
	CLUSTERING = "clustering"
	PATH_TRACING = "path_tracing"


@dataclass
class NodeStyle:
	"""
	Node visual styling configuration
	
	Attributes:
		size: Node size (radius for circles, side length for squares)
		color: Node color (hex, rgb, or color name)
		shape: Node shape (circle, square, triangle, diamond, etc.)
		border_color: Border color
		border_width: Border width in pixels
		opacity: Node opacity (0-1)
		label_visible: Whether to show node labels
		label_color: Label text color
		label_size: Label font size
		image_url: URL for node image/icon
		metadata: Additional styling metadata
	"""
	
	size: float = 10.0
	color: str = "#1f77b4"
	shape: str = "circle"
	border_color: str = "#ffffff"
	border_width: float = 1.0
	opacity: float = 1.0
	label_visible: bool = True
	label_color: str = "#000000"
	label_size: int = 12
	image_url: str = ""
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		return asdict(self)


@dataclass
class EdgeStyle:
	"""
	Edge visual styling configuration
	
	Attributes:
		width: Edge width in pixels
		color: Edge color
		style: Edge style (solid, dashed, dotted)
		opacity: Edge opacity (0-1)
		curved: Whether edge should be curved
		arrow_size: Arrow size for directed edges
		arrow_color: Arrow color
		label_visible: Whether to show edge labels
		label_color: Label text color
		label_size: Label font size
		animation_speed: Animation speed for dynamic effects
		metadata: Additional styling metadata
	"""
	
	width: float = 2.0
	color: str = "#999999"
	style: str = "solid"
	opacity: float = 0.8
	curved: bool = False
	arrow_size: float = 8.0
	arrow_color: str = "#666666"
	label_visible: bool = False
	label_color: str = "#666666"
	label_size: int = 10
	animation_speed: float = 1.0
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		return asdict(self)


@dataclass
class VisualizationTheme:
	"""
	Complete visualization theme configuration
	
	Attributes:
		theme_id: Unique theme identifier
		name: Theme display name
		description: Theme description
		background_color: Canvas background color
		grid_visible: Whether to show grid
		grid_color: Grid line color
		default_node_style: Default node styling
		default_edge_style: Default edge styling
		color_palette: Color palette for categorical data
		node_size_mapping: Size mapping configuration
		edge_width_mapping: Width mapping configuration
		layout_config: Layout algorithm configuration
		interaction_config: Interaction behavior settings
		animation_config: Animation settings
		created_at: Theme creation timestamp
	"""
	
	theme_id: str
	name: str
	description: str = ""
	background_color: str = "#ffffff"
	grid_visible: bool = False
	grid_color: str = "#f0f0f0"
	default_node_style: NodeStyle = field(default_factory=NodeStyle)
	default_edge_style: EdgeStyle = field(default_factory=EdgeStyle)
	color_palette: List[str] = field(default_factory=lambda: [
		"#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
		"#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
	])
	node_size_mapping: Dict[str, Any] = field(default_factory=dict)
	edge_width_mapping: Dict[str, Any] = field(default_factory=dict)
	layout_config: Dict[str, Any] = field(default_factory=dict)
	interaction_config: Dict[str, Any] = field(default_factory=dict)
	animation_config: Dict[str, Any] = field(default_factory=dict)
	created_at: datetime = field(default_factory=datetime.utcnow)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["default_node_style"] = self.default_node_style.to_dict()
		data["default_edge_style"] = self.default_edge_style.to_dict()
		data["created_at"] = self.created_at.isoformat()
		return data


@dataclass
class VisualizationConfig:
	"""
	Complete visualization configuration
	
	Attributes:
		config_id: Unique configuration identifier
		graph_name: Target graph name
		visualization_type: Type of visualization
		layout_type: Layout algorithm to use
		rendering_mode: Rendering mode
		animation_type: Animation type
		theme: Visual theme configuration
		filters: Data filters to apply
		viewport: Viewport configuration (zoom, pan, etc.)
		performance_settings: Performance optimization settings
		export_settings: Export configuration
		created_at: Configuration creation timestamp
		metadata: Additional configuration metadata
	"""
	
	config_id: str
	graph_name: str
	visualization_type: VisualizationType
	layout_type: LayoutType
	rendering_mode: RenderingMode = RenderingMode.AUTO
	animation_type: AnimationType = AnimationType.FADE_IN
	theme: VisualizationTheme = None
	filters: Dict[str, Any] = field(default_factory=dict)
	viewport: Dict[str, Any] = field(default_factory=lambda: {"zoom": 1.0, "pan": {"x": 0, "y": 0}})
	performance_settings: Dict[str, Any] = field(default_factory=dict)
	export_settings: Dict[str, Any] = field(default_factory=dict)
	created_at: datetime = field(default_factory=datetime.utcnow)
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["visualization_type"] = self.visualization_type.value
		data["layout_type"] = self.layout_type.value
		data["rendering_mode"] = self.rendering_mode.value
		data["animation_type"] = self.animation_type.value
		data["theme"] = self.theme.to_dict() if self.theme else None
		data["created_at"] = self.created_at.isoformat()
		return data


class ColorPaletteGenerator:
	"""
	Advanced color palette generation
	
	Generates perceptually distinct colors for categorical data visualization
	with support for colorblind-friendly palettes.
	"""
	
	def __init__(self):
		self.predefined_palettes = self._load_predefined_palettes()
	
	def _load_predefined_palettes(self) -> Dict[str, List[str]]:
		"""Load predefined color palettes"""
		return {
			"default": [
				"#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
				"#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
			],
			"pastel": [
				"#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
				"#c49c94", "#f7b6d3", "#c7c7c7", "#dbdb8d", "#9edae5"
			],
			"dark": [
				"#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2",
				"#7f7f7f", "#bcbd22", "#17becf", "#1f77b4", "#ff7f0e"
			],
			"colorblind_friendly": [
				"#0173b2", "#de8f05", "#029e73", "#cc78bc", "#ca9161",
				"#fbafe4", "#949494", "#ece133", "#ad002a", "#56b4e9"
			],
			"high_contrast": [
				"#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff",
				"#ffff00", "#ff00ff", "#00ffff", "#800000", "#008000"
			],
			"earth_tones": [
				"#8B4513", "#A0522D", "#CD853F", "#DEB887", "#F4A460",
				"#D2691E", "#BC8F8F", "#F5DEB3", "#FAEBD7", "#FFE4B5"
			],
			"ocean": [
				"#000080", "#0000CD", "#4169E1", "#6495ED", "#87CEEB",
				"#87CEFA", "#ADD8E6", "#B0E0E6", "#E0F6FF", "#F0F8FF"
			],
			"sunset": [
				"#FF4500", "#FF6347", "#FF7F50", "#FFA500", "#FFB347",
				"#FFCBA4", "#FFD700", "#FFDF00", "#FFFF00", "#FFFFE0"
			]
		}
	
	def get_palette(self, palette_name: str, count: int = 10) -> List[str]:
		"""Get predefined color palette"""
		if palette_name not in self.predefined_palettes:
			palette_name = "default"
		
		palette = self.predefined_palettes[palette_name]
		
		if count <= len(palette):
			return palette[:count]
		else:
			# Extend palette by generating similar colors
			extended = palette.copy()
			while len(extended) < count:
				base_color = random.choice(palette)
				new_color = self._generate_similar_color(base_color)
				extended.append(new_color)
			return extended[:count]
	
	def generate_categorical_palette(self, categories: List[str], 
									base_palette: str = "default") -> Dict[str, str]:
		"""Generate categorical color mapping"""
		colors = self.get_palette(base_palette, len(categories))
		return dict(zip(categories, colors))
	
	def generate_continuous_palette(self, min_value: float, max_value: float,
								   color_scheme: str = "viridis") -> Dict[str, Any]:
		"""Generate continuous color mapping configuration"""
		if color_scheme == "viridis":
			color_stops = [
				"#440154", "#31688e", "#35b779", "#fde725"
			]
		elif color_scheme == "plasma":
			color_stops = [
				"#0d0887", "#7e03a8", "#cc4778", "#f89441", "#f0f921"
			]
		elif color_scheme == "inferno":
			color_stops = [
				"#000004", "#420a68", "#932667", "#dd513a", "#fca50a", "#fcffa4"
			]
		else:  # Default blue-red gradient
			color_stops = ["#0000ff", "#00ffff", "#00ff00", "#ffff00", "#ff0000"]
		
		return {
			"type": "continuous",
			"min_value": min_value,
			"max_value": max_value,
			"color_stops": color_stops,
			"interpolation": "linear"
		}
	
	def _generate_similar_color(self, base_color: str) -> str:
		"""Generate a similar but distinct color"""
		# Convert hex to HSL
		base_color = base_color.lstrip('#')
		r, g, b = tuple(int(base_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
		h, l, s = colorsys.rgb_to_hls(r, g, b)
		
		# Slightly modify hue and lightness
		new_h = (h + random.uniform(-0.1, 0.1)) % 1.0
		new_l = max(0.1, min(0.9, l + random.uniform(-0.2, 0.2)))
		new_s = max(0.3, min(1.0, s + random.uniform(-0.1, 0.1)))
		
		# Convert back to RGB
		new_r, new_g, new_b = colorsys.hls_to_rgb(new_h, new_l, new_s)
		
		# Convert to hex
		return "#{:02x}{:02x}{:02x}".format(
			int(new_r * 255), int(new_g * 255), int(new_b * 255)
		)


class LayoutEngine:
	"""
	Advanced graph layout computation
	
	Implements various layout algorithms optimized for different graph types
	and visualization requirements.
	"""
	
	def __init__(self):
		self.layout_cache: Dict[str, Any] = {}
		self._lock = threading.RLock()
	
	@performance_cache(ttl_seconds=1800)
	def compute_layout(self, graph_data: Dict[str, Any], layout_type: LayoutType,
					  config: Dict[str, Any] = None) -> Dict[str, Any]:
		"""
		Compute node positions using specified layout algorithm
		
		Args:
			graph_data: Graph data with nodes and edges
			layout_type: Layout algorithm to use
			config: Layout-specific configuration
			
		Returns:
			Dictionary with node positions and layout metadata
		"""
		nodes = graph_data.get("nodes", [])
		edges = graph_data.get("edges", [])
		config = config or {}
		
		if layout_type == LayoutType.FORCE_DIRECTED:
			return self._compute_force_directed_layout(nodes, edges, config)
		elif layout_type == LayoutType.CIRCULAR:
			return self._compute_circular_layout(nodes, config)
		elif layout_type == LayoutType.HIERARCHICAL:
			return self._compute_hierarchical_layout(nodes, edges, config)
		elif layout_type == LayoutType.GRID:
			return self._compute_grid_layout(nodes, config)
		elif layout_type == LayoutType.CONCENTRIC:
			return self._compute_concentric_layout(nodes, edges, config)
		elif layout_type == LayoutType.RANDOM:
			return self._compute_random_layout(nodes, config)
		else:
			# Default to force-directed
			return self._compute_force_directed_layout(nodes, edges, config)
	
	def _compute_force_directed_layout(self, nodes: List[Dict], edges: List[Dict],
									  config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute force-directed layout using spring-mass simulation"""
		
		# Configuration parameters
		width = config.get("width", 800)
		height = config.get("height", 600)
		iterations = config.get("iterations", 100)
		spring_strength = config.get("spring_strength", 0.1)
		repulsion_strength = config.get("repulsion_strength", 100)
		damping = config.get("damping", 0.9)
		
		# Initialize positions randomly
		positions = {}
		velocities = {}
		
		for node in nodes:
			node_id = node["id"]
			positions[node_id] = {
				"x": random.uniform(0, width),
				"y": random.uniform(0, height)
			}
			velocities[node_id] = {"x": 0, "y": 0}
		
		# Create adjacency for faster lookup
		adjacency = {}
		for edge in edges:
			source, target = edge["source"], edge["target"]
			if source not in adjacency:
				adjacency[source] = []
			if target not in adjacency:
				adjacency[target] = []
			adjacency[source].append(target)
			adjacency[target].append(source)
		
		# Simulation loop
		for iteration in range(iterations):
			forces = {node_id: {"x": 0, "y": 0} for node_id in positions}
			
			# Repulsion forces (between all pairs)
			for i, node1_id in enumerate(positions):
				for node2_id in list(positions.keys())[i+1:]:
					pos1, pos2 = positions[node1_id], positions[node2_id]
					
					dx = pos1["x"] - pos2["x"]
					dy = pos1["y"] - pos2["y"]
					distance = max(1, math.sqrt(dx*dx + dy*dy))
					
					force = repulsion_strength / (distance * distance)
					fx = force * dx / distance
					fy = force * dy / distance
					
					forces[node1_id]["x"] += fx
					forces[node1_id]["y"] += fy
					forces[node2_id]["x"] -= fx
					forces[node2_id]["y"] -= fy
			
			# Spring forces (between connected nodes)
			for edge in edges:
				source, target = edge["source"], edge["target"]
				if source in positions and target in positions:
					pos1, pos2 = positions[source], positions[target]
					
					dx = pos2["x"] - pos1["x"]
					dy = pos2["y"] - pos1["y"]
					distance = max(1, math.sqrt(dx*dx + dy*dy))
					
					force = spring_strength * (distance - 50)  # Rest length = 50
					fx = force * dx / distance
					fy = force * dy / distance
					
					forces[source]["x"] += fx
					forces[source]["y"] += fy
					forces[target]["x"] -= fx
					forces[target]["y"] -= fy
			
			# Update positions
			for node_id in positions:
				# Apply forces to velocities
				velocities[node_id]["x"] = (velocities[node_id]["x"] + forces[node_id]["x"]) * damping
				velocities[node_id]["y"] = (velocities[node_id]["y"] + forces[node_id]["y"]) * damping
				
				# Update positions
				positions[node_id]["x"] += velocities[node_id]["x"]
				positions[node_id]["y"] += velocities[node_id]["y"]
				
				# Keep nodes within bounds
				positions[node_id]["x"] = max(50, min(width - 50, positions[node_id]["x"]))
				positions[node_id]["y"] = max(50, min(height - 50, positions[node_id]["y"]))
		
		return {
			"positions": positions,
			"layout_type": "force_directed",
			"bounds": {"width": width, "height": height},
			"metadata": {
				"iterations": iterations,
				"spring_strength": spring_strength,
				"repulsion_strength": repulsion_strength
			}
		}
	
	def _compute_circular_layout(self, nodes: List[Dict], config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute circular layout"""
		center_x = config.get("center_x", 400)
		center_y = config.get("center_y", 300)
		radius = config.get("radius", 200)
		
		positions = {}
		angle_step = 2 * math.pi / len(nodes) if nodes else 0
		
		for i, node in enumerate(nodes):
			angle = i * angle_step
			positions[node["id"]] = {
				"x": center_x + radius * math.cos(angle),
				"y": center_y + radius * math.sin(angle)
			}
		
		return {
			"positions": positions,
			"layout_type": "circular",
			"bounds": {"width": (center_x + radius) * 2, "height": (center_y + radius) * 2},
			"metadata": {"center": {"x": center_x, "y": center_y}, "radius": radius}
		}
	
	def _compute_hierarchical_layout(self, nodes: List[Dict], edges: List[Dict],
									config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute hierarchical/tree layout"""
		width = config.get("width", 800)
		height = config.get("height", 600)
		
		# Find root nodes (nodes with no incoming edges)
		incoming = set()
		outgoing = {}
		
		for edge in edges:
			incoming.add(edge["target"])
			if edge["source"] not in outgoing:
				outgoing[edge["source"]] = []
			outgoing[edge["source"]].append(edge["target"])
		
		roots = [node for node in nodes if node["id"] not in incoming]
		if not roots:
			roots = nodes[:1]  # Fallback to first node if no clear root
		
		positions = {}
		levels = {}
		
		# BFS to assign levels
		queue = [(root["id"], 0) for root in roots]
		visited = set()
		
		while queue:
			node_id, level = queue.pop(0)
			if node_id in visited:
				continue
			
			visited.add(node_id)
			levels[node_id] = level
			
			if node_id in outgoing:
				for child in outgoing[node_id]:
					if child not in visited:
						queue.append((child, level + 1))
		
		# Assign positions based on levels
		max_level = max(levels.values()) if levels else 0
		level_height = height / (max_level + 1) if max_level > 0 else height
		
		level_nodes = {}
		for node_id, level in levels.items():
			if level not in level_nodes:
				level_nodes[level] = []
			level_nodes[level].append(node_id)
		
		for level, node_ids in level_nodes.items():
			y = (level + 0.5) * level_height
			node_width = width / len(node_ids)
			
			for i, node_id in enumerate(node_ids):
				x = (i + 0.5) * node_width
				positions[node_id] = {"x": x, "y": y}
		
		# Handle nodes not in the hierarchy
		for node in nodes:
			if node["id"] not in positions:
				positions[node["id"]] = {
					"x": random.uniform(50, width - 50),
					"y": random.uniform(50, height - 50)
				}
		
		return {
			"positions": positions,
			"layout_type": "hierarchical",
			"bounds": {"width": width, "height": height},
			"metadata": {"levels": levels, "max_level": max_level}
		}
	
	def _compute_grid_layout(self, nodes: List[Dict], config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute grid layout"""
		width = config.get("width", 800)
		height = config.get("height", 600)
		padding = config.get("padding", 50)
		
		# Calculate grid dimensions
		n_nodes = len(nodes)
		cols = math.ceil(math.sqrt(n_nodes))
		rows = math.ceil(n_nodes / cols)
		
		cell_width = (width - 2 * padding) / cols
		cell_height = (height - 2 * padding) / rows
		
		positions = {}
		
		for i, node in enumerate(nodes):
			row = i // cols
			col = i % cols
			
			x = padding + col * cell_width + cell_width / 2
			y = padding + row * cell_height + cell_height / 2
			
			positions[node["id"]] = {"x": x, "y": y}
		
		return {
			"positions": positions,
			"layout_type": "grid",
			"bounds": {"width": width, "height": height},
			"metadata": {"grid": {"rows": rows, "cols": cols}}
		}
	
	def _compute_concentric_layout(self, nodes: List[Dict], edges: List[Dict],
								  config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute concentric layout based on node degree"""
		center_x = config.get("center_x", 400)
		center_y = config.get("center_y", 300)
		min_radius = config.get("min_radius", 50)
		radius_step = config.get("radius_step", 80)
		
		# Calculate node degrees
		degrees = {}
		for node in nodes:
			degrees[node["id"]] = 0
		
		for edge in edges:
			if edge["source"] in degrees:
				degrees[edge["source"]] += 1
			if edge["target"] in degrees:
				degrees[edge["target"]] += 1
		
		# Group nodes by degree
		degree_groups = {}
		for node_id, degree in degrees.items():
			if degree not in degree_groups:
				degree_groups[degree] = []
			degree_groups[degree].append(node_id)
		
		positions = {}
		sorted_degrees = sorted(degree_groups.keys(), reverse=True)
		
		for i, degree in enumerate(sorted_degrees):
			radius = min_radius + i * radius_step
			node_ids = degree_groups[degree]
			angle_step = 2 * math.pi / len(node_ids) if node_ids else 0
			
			for j, node_id in enumerate(node_ids):
				angle = j * angle_step
				positions[node_id] = {
					"x": center_x + radius * math.cos(angle),
					"y": center_y + radius * math.sin(angle)
				}
		
		max_radius = min_radius + len(sorted_degrees) * radius_step
		
		return {
			"positions": positions,
			"layout_type": "concentric",
			"bounds": {"width": (center_x + max_radius) * 2, "height": (center_y + max_radius) * 2},
			"metadata": {"center": {"x": center_x, "y": center_y}, "max_radius": max_radius}
		}
	
	def _compute_random_layout(self, nodes: List[Dict], config: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute random layout"""
		width = config.get("width", 800)
		height = config.get("height", 600)
		padding = config.get("padding", 50)
		
		positions = {}
		
		for node in nodes:
			positions[node["id"]] = {
				"x": random.uniform(padding, width - padding),
				"y": random.uniform(padding, height - padding)
			}
		
		return {
			"positions": positions,
			"layout_type": "random",
			"bounds": {"width": width, "height": height},
			"metadata": {"seed": config.get("seed", "random")}
		}


class StyleEngine:
	"""
	Advanced styling and theming engine
	
	Applies sophisticated visual styling based on data properties,
	user preferences, and visualization context.
	"""
	
	def __init__(self):
		self.color_generator = ColorPaletteGenerator()
		self.default_themes = self._create_default_themes()
	
	def _create_default_themes(self) -> Dict[str, VisualizationTheme]:
		"""Create default visualization themes"""
		themes = {}
		
		# Light theme
		themes["light"] = VisualizationTheme(
			theme_id="light",
			name="Light Theme",
			description="Clean light theme with subtle colors",
			background_color="#ffffff",
			grid_visible=True,
			grid_color="#f5f5f5",
			default_node_style=NodeStyle(
				size=12.0,
				color="#3498db",
				border_color="#2c3e50",
				border_width=2.0
			),
			default_edge_style=EdgeStyle(
				width=1.5,
				color="#bdc3c7",
				opacity=0.7
			),
			color_palette=self.color_generator.get_palette("default")
		)
		
		# Dark theme
		themes["dark"] = VisualizationTheme(
			theme_id="dark",
			name="Dark Theme",
			description="Modern dark theme with vibrant accents",
			background_color="#2c3e50",
			grid_visible=True,
			grid_color="#34495e",
			default_node_style=NodeStyle(
				size=12.0,
				color="#e74c3c",
				border_color="#ecf0f1",
				border_width=2.0,
				label_color="#ecf0f1"
			),
			default_edge_style=EdgeStyle(
				width=1.5,
				color="#7f8c8d",
				opacity=0.8
			),
			color_palette=["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
						  "#1abc9c", "#e67e22", "#95a5a6", "#f1c40f", "#34495e"]
		)
		
		# High contrast theme
		themes["high_contrast"] = VisualizationTheme(
			theme_id="high_contrast",
			name="High Contrast",
			description="High contrast theme for accessibility",
			background_color="#000000",
			grid_visible=False,
			default_node_style=NodeStyle(
				size=14.0,
				color="#ffffff",
				border_color="#ffff00",
				border_width=3.0,
				label_color="#ffffff",
				label_size=14
			),
			default_edge_style=EdgeStyle(
				width=2.5,
				color="#ffffff",
				opacity=1.0
			),
			color_palette=self.color_generator.get_palette("high_contrast")
		)
		
		# Scientific theme
		themes["scientific"] = VisualizationTheme(
			theme_id="scientific",
			name="Scientific",
			description="Professional theme for scientific publications",
			background_color="#ffffff",
			grid_visible=True,
			grid_color="#e0e0e0",
			default_node_style=NodeStyle(
				size=10.0,
				color="#1f77b4",
				border_color="#000000",
				border_width=1.0,
				label_color="#000000",
				label_size=11
			),
			default_edge_style=EdgeStyle(
				width=1.0,
				color="#333333",
				opacity=0.8
			),
			color_palette=self.color_generator.get_palette("colorblind_friendly")
		)
		
		return themes
	
	def apply_data_driven_styling(self, graph_data: Dict[str, Any], 
								 theme: VisualizationTheme,
								 style_mappings: Dict[str, Any] = None) -> Dict[str, Any]:
		"""
		Apply data-driven styling to graph elements
		
		Args:
			graph_data: Graph data with nodes and edges
			theme: Base theme to apply
			style_mappings: Property-to-style mappings
			
		Returns:
			Graph data with applied styling
		"""
		style_mappings = style_mappings or {}
		styled_data = {
			"nodes": [],
			"edges": [],
			"theme": theme.to_dict()
		}
		
		# Process nodes
		node_properties = self._analyze_node_properties(graph_data["nodes"])
		node_styles = self._compute_node_styles(graph_data["nodes"], theme, 
												node_properties, style_mappings)
		
		for i, node in enumerate(graph_data["nodes"]):
			styled_node = node.copy()
			styled_node["style"] = node_styles[i].to_dict()
			styled_data["nodes"].append(styled_node)
		
		# Process edges
		edge_properties = self._analyze_edge_properties(graph_data["edges"])
		edge_styles = self._compute_edge_styles(graph_data["edges"], theme,
												edge_properties, style_mappings)
		
		for i, edge in enumerate(graph_data["edges"]):
			styled_edge = edge.copy()
			styled_edge["style"] = edge_styles[i].to_dict()
			styled_data["edges"].append(styled_edge)
		
		return styled_data
	
	def _analyze_node_properties(self, nodes: List[Dict]) -> Dict[str, Any]:
		"""Analyze node properties for styling purposes"""
		properties = {}
		
		for node in nodes:
			node_props = node.get("properties", {})
			for prop_name, prop_value in node_props.items():
				if prop_name not in properties:
					properties[prop_name] = {
						"type": type(prop_value).__name__,
						"values": [],
						"min_value": None,
						"max_value": None,
						"unique_values": set()
					}
				
				properties[prop_name]["values"].append(prop_value)
				properties[prop_name]["unique_values"].add(prop_value)
				
				if isinstance(prop_value, (int, float)):
					if properties[prop_name]["min_value"] is None:
						properties[prop_name]["min_value"] = prop_value
						properties[prop_name]["max_value"] = prop_value
					else:
						properties[prop_name]["min_value"] = min(properties[prop_name]["min_value"], prop_value)
						properties[prop_name]["max_value"] = max(properties[prop_name]["max_value"], prop_value)
		
		# Convert sets to lists for JSON serialization
		for prop_info in properties.values():
			prop_info["unique_values"] = list(prop_info["unique_values"])
		
		return properties
	
	def _analyze_edge_properties(self, edges: List[Dict]) -> Dict[str, Any]:
		"""Analyze edge properties for styling purposes"""
		properties = {}
		
		for edge in edges:
			edge_props = edge.get("properties", {})
			for prop_name, prop_value in edge_props.items():
				if prop_name not in properties:
					properties[prop_name] = {
						"type": type(prop_value).__name__,
						"values": [],
						"min_value": None,
						"max_value": None,
						"unique_values": set()
					}
				
				properties[prop_name]["values"].append(prop_value)
				properties[prop_name]["unique_values"].add(prop_value)
				
				if isinstance(prop_value, (int, float)):
					if properties[prop_name]["min_value"] is None:
						properties[prop_name]["min_value"] = prop_value
						properties[prop_name]["max_value"] = prop_value
					else:
						properties[prop_name]["min_value"] = min(properties[prop_name]["min_value"], prop_value)
						properties[prop_name]["max_value"] = max(properties[prop_name]["max_value"], prop_value)
		
		# Convert sets to lists for JSON serialization
		for prop_info in properties.values():
			prop_info["unique_values"] = list(prop_info["unique_values"])
		
		return properties
	
	def _compute_node_styles(self, nodes: List[Dict], theme: VisualizationTheme,
							properties: Dict[str, Any], mappings: Dict[str, Any]) -> List[NodeStyle]:
		"""Compute individual node styles"""
		styles = []
		
		# Get color mapping if specified
		color_property = mappings.get("node_color_property")
		size_property = mappings.get("node_size_property")
		
		color_mapping = None
		if color_property and color_property in properties:
			prop_info = properties[color_property]
			if prop_info["type"] in ["str"]:
				# Categorical mapping
				unique_values = prop_info["unique_values"]
				color_mapping = self.color_generator.generate_categorical_palette(
					unique_values, mappings.get("color_palette", "default")
				)
			else:
				# Continuous mapping
				color_mapping = self.color_generator.generate_continuous_palette(
					prop_info["min_value"], prop_info["max_value"],
					mappings.get("color_scheme", "viridis")
				)
		
		for node in nodes:
			style = NodeStyle(
				size=theme.default_node_style.size,
				color=theme.default_node_style.color,
				shape=theme.default_node_style.shape,
				border_color=theme.default_node_style.border_color,
				border_width=theme.default_node_style.border_width,
				opacity=theme.default_node_style.opacity,
				label_visible=theme.default_node_style.label_visible,
				label_color=theme.default_node_style.label_color,
				label_size=theme.default_node_style.label_size
			)
			
			node_props = node.get("properties", {})
			
			# Apply color mapping
			if color_mapping and color_property in node_props:
				prop_value = node_props[color_property]
				if isinstance(color_mapping, dict):
					if prop_value in color_mapping:
						style.color = color_mapping[prop_value]
				else:  # Continuous mapping
					# Interpolate color based on value
					style.color = self._interpolate_color(prop_value, color_mapping)
			
			# Apply size mapping
			if size_property and size_property in node_props and size_property in properties:
				prop_value = node_props[size_property]
				prop_info = properties[size_property]
				
				if prop_info["min_value"] is not None and prop_info["max_value"] is not None:
					# Normalize to 0-1 range
					normalized = (prop_value - prop_info["min_value"]) / max(1, prop_info["max_value"] - prop_info["min_value"])
					# Map to size range (5-25)
					style.size = 5 + normalized * 20
			
			styles.append(style)
		
		return styles
	
	def _compute_edge_styles(self, edges: List[Dict], theme: VisualizationTheme,
							properties: Dict[str, Any], mappings: Dict[str, Any]) -> List[EdgeStyle]:
		"""Compute individual edge styles"""
		styles = []
		
		# Get width mapping if specified
		width_property = mappings.get("edge_width_property")
		
		for edge in edges:
			style = EdgeStyle(
				width=theme.default_edge_style.width,
				color=theme.default_edge_style.color,
				style=theme.default_edge_style.style,
				opacity=theme.default_edge_style.opacity,
				curved=theme.default_edge_style.curved,
				arrow_size=theme.default_edge_style.arrow_size,
				arrow_color=theme.default_edge_style.arrow_color
			)
			
			edge_props = edge.get("properties", {})
			
			# Apply width mapping
			if width_property and width_property in edge_props and width_property in properties:
				prop_value = edge_props[width_property]
				prop_info = properties[width_property]
				
				if prop_info["min_value"] is not None and prop_info["max_value"] is not None:
					# Normalize to 0-1 range
					normalized = (prop_value - prop_info["min_value"]) / max(1, prop_info["max_value"] - prop_info["min_value"])
					# Map to width range (0.5-5)
					style.width = 0.5 + normalized * 4.5
			
			styles.append(style)
		
		return styles
	
	def _interpolate_color(self, value: float, color_mapping: Dict[str, Any]) -> str:
		"""Interpolate color in continuous mapping"""
		color_stops = color_mapping["color_stops"]
		min_val = color_mapping["min_value"]
		max_val = color_mapping["max_value"]
		
		# Normalize value
		normalized = (value - min_val) / max(1, max_val - min_val)
		normalized = max(0, min(1, normalized))
		
		# Find color segment
		segment_size = 1.0 / (len(color_stops) - 1)
		segment_index = min(len(color_stops) - 2, int(normalized / segment_size))
		local_t = (normalized - segment_index * segment_size) / segment_size
		
		# Simple linear interpolation between two colors
		color1 = color_stops[segment_index]
		color2 = color_stops[segment_index + 1]
		
		# Convert hex to RGB, interpolate, convert back
		r1, g1, b1 = tuple(int(color1.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
		r2, g2, b2 = tuple(int(color2.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
		
		r = int(r1 + (r2 - r1) * local_t)
		g = int(g1 + (g2 - g1) * local_t)
		b = int(b1 + (b2 - b1) * local_t)
		
		return "#{:02x}{:02x}{:02x}".format(r, g, b)
	
	def get_default_theme(self, theme_name: str) -> VisualizationTheme:
		"""Get default theme by name"""
		return self.default_themes.get(theme_name, self.default_themes["light"])


class AdvancedVisualizationEngine:
	"""
	Main advanced visualization engine
	
	Coordinates layout computation, styling, and rendering configuration
	for sophisticated graph visualizations.
	"""
	
	def __init__(self):
		self.layout_engine = LayoutEngine()
		self.style_engine = StyleEngine()
		self.visualization_configs: Dict[str, VisualizationConfig] = {}
		self._lock = threading.RLock()
	
	def create_visualization(self, graph_name: str, visualization_type: VisualizationType,
							layout_type: LayoutType = LayoutType.FORCE_DIRECTED,
							theme_name: str = "light",
							style_mappings: Dict[str, Any] = None) -> str:
		"""
		Create complete visualization configuration
		
		Args:
			graph_name: Target graph name
			visualization_type: Type of visualization
			layout_type: Layout algorithm
			theme_name: Theme to apply
			style_mappings: Property-to-style mappings
			
		Returns:
			Visualization configuration ID
		"""
		from uuid_extensions import uuid7str
		
		config_id = uuid7str()
		
		# Get theme
		theme = self.style_engine.get_default_theme(theme_name)
		
		# Create configuration
		config = VisualizationConfig(
			config_id=config_id,
			graph_name=graph_name,
			visualization_type=visualization_type,
			layout_type=layout_type,
			theme=theme
		)
		
		with self._lock:
			self.visualization_configs[config_id] = config
		
		# Track activity
		track_database_activity(
			activity_type=ActivityType.VISUALIZATION_CREATED,
			target=f"Graph: {graph_name}",
			description=f"Created {visualization_type.value} visualization with {layout_type.value} layout",
			details={
				"config_id": config_id,
				"visualization_type": visualization_type.value,
				"layout_type": layout_type.value,
				"theme": theme_name
			}
		)
		
		return config_id
	
	def render_visualization(self, config_id: str) -> Dict[str, Any]:
		"""
		Render complete visualization
		
		Args:
			config_id: Visualization configuration ID
			
		Returns:
			Complete visualization data ready for frontend rendering
		"""
		with self._lock:
			config = self.visualization_configs.get(config_id)
		
		if not config:
			raise ValueError(f"Visualization config {config_id} not found")
		
		try:
			# Get graph data
			graph_manager = get_graph_manager(config.graph_name)
			graph_data = graph_manager.get_graph_data()
			
			if not graph_data.get("success"):
				raise Exception(f"Failed to get graph data: {graph_data.get('error')}")
			
			# Compute layout
			layout_result = self.layout_engine.compute_layout(
				graph_data, config.layout_type, config.theme.layout_config
			)
			
			# Apply styling
			styled_data = self.style_engine.apply_data_driven_styling(
				graph_data, config.theme, config.metadata.get("style_mappings", {})
			)
			
			# Combine everything
			visualization_data = {
				"config": config.to_dict(),
				"layout": layout_result,
				"graph_data": styled_data,
				"metadata": {
					"generated_at": datetime.now(tz=timezone.utc).isoformat(),
					"node_count": len(graph_data["nodes"]),
					"edge_count": len(graph_data["edges"])
				}
			}
			
			return visualization_data
			
		except Exception as e:
			logger.error(f"Visualization rendering failed: {e}")
			raise
	
	def get_available_themes(self) -> List[Dict[str, Any]]:
		"""Get available visualization themes"""
		return [theme.to_dict() for theme in self.style_engine.default_themes.values()]
	
	def get_available_layouts(self) -> List[Dict[str, Any]]:
		"""Get available layout algorithms"""
		return [
			{
				"value": layout.value,
				"name": layout.value.replace("_", " ").title(),
				"description": self._get_layout_description(layout)
			}
			for layout in LayoutType
		]
	
	def get_available_visualizations(self) -> List[Dict[str, Any]]:
		"""Get available visualization types"""
		return [
			{
				"value": viz.value,
				"name": viz.value.replace("_", " ").title(),
				"description": self._get_visualization_description(viz)
			}
			for viz in VisualizationType
		]
	
	def _get_layout_description(self, layout_type: LayoutType) -> str:
		"""Get description for layout type"""
		descriptions = {
			LayoutType.FORCE_DIRECTED: "Physics-based simulation with springs and repulsion",
			LayoutType.CIRCULAR: "Arrange nodes in a circular pattern",
			LayoutType.HIERARCHICAL: "Tree-like hierarchy with clear levels",
			LayoutType.GRID: "Regular grid arrangement",
			LayoutType.CONCENTRIC: "Concentric circles based on node importance",
			LayoutType.RANDOM: "Random node positioning",
			LayoutType.COSE: "Compound spring embedder layout",
			LayoutType.DAGRE: "Directed acyclic graph layout",
			LayoutType.BREADTHFIRST: "Breadth-first search based positioning"
		}
		return descriptions.get(layout_type, "Unknown layout algorithm")
	
	def _get_visualization_description(self, viz_type: VisualizationType) -> str:
		"""Get description for visualization type"""
		descriptions = {
			VisualizationType.NETWORK_2D: "Interactive 2D network graph",
			VisualizationType.NETWORK_3D: "Immersive 3D network visualization",
			VisualizationType.MATRIX: "Adjacency matrix representation",
			VisualizationType.SANKEY: "Flow diagram showing relationships",
			VisualizationType.TREEMAP: "Hierarchical space-filling visualization",
			VisualizationType.SUNBURST: "Radial space-filling hierarchy",
			VisualizationType.FORCE_GRAPH: "Dynamic force-directed visualization",
			VisualizationType.ARC_DIAGRAM: "Linear node arrangement with arcs",
			VisualizationType.CHORD_DIAGRAM: "Circular relationship diagram",
			VisualizationType.HIVE_PLOT: "Linear axes network visualization"
		}
		return descriptions.get(viz_type, "Unknown visualization type")


# Global visualization engine instance
_visualization_engine = None


def get_visualization_engine() -> AdvancedVisualizationEngine:
	"""Get or create global visualization engine instance"""
	global _visualization_engine
	if _visualization_engine is None:
		_visualization_engine = AdvancedVisualizationEngine()
	return _visualization_engine