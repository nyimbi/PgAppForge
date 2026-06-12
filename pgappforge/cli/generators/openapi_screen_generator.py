"""OpenAPI → React Native screen generator.

Reads an OpenAPI 3.0 spec and generates typed React Native screens
for each endpoint, wired to TanStack Query hooks.

Usage:
  from pgappforge.cli.generators.openapi_screen_generator import OpenAPIScreenGenerator, OpenAPIScreenConfig
  gen = OpenAPIScreenGenerator(OpenAPIScreenConfig(
      spec_url="http://localhost:8080/api/v1/banking/openapi.json",
      output_dir="./screens/banking/",
      base_url="http://localhost:8080",
  ))
  gen.generate()
"""

from __future__ import annotations
import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class OpenAPIScreenConfig:
	spec_url: str = ""					# URL to OpenAPI JSON spec (e.g. /api/v1/banking/openapi.json)
	spec_file: str = ""					# Or local file path
	output_dir: str = "./screens/"
	base_url: str = ""					# API base URL (overrides spec servers[0].url)
	api_key_env: str = "EXPO_PUBLIC_API_KEY"	# env var for auth
	auth_type: str = "bearer"			# bearer | apikey | none
	primary_color: str = "#1a56db"


class OpenAPIScreenGenerator:
	def __init__(self, config: OpenAPIScreenConfig):
		self.config = config
		self._spec: dict = {}

	def load_spec(self) -> dict:
		"""Load OpenAPI spec from URL or file."""
		if self.config.spec_file:
			with open(self.config.spec_file) as f:
				self._spec = json.load(f)
		elif self.config.spec_url:
			try:
				with urllib.request.urlopen(self.config.spec_url, timeout=10) as resp:
					self._spec = json.loads(resp.read())
			except Exception as exc:
				log.warning("Could not fetch OpenAPI spec from %s: %s", self.config.spec_url, exc)
				self._spec = {}
		return self._spec

	def generate(self) -> dict[str, str]:
		"""Generate all screens. Returns {filename: content} dict. Also writes to output_dir."""
		spec = self.load_spec()
		if not spec:
			return {}

		files: dict[str, str] = {}
		paths = spec.get("paths", {})

		# Group paths by resource (first path segment after base)
		resources: dict[str, list[dict]] = {}
		for path, methods in paths.items():
			# "/accounts/{account_number}/balance" → "accounts"
			parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
			resource = parts[0] if parts else "misc"
			if resource not in resources:
				resources[resource] = []
			for method, op in methods.items():
				if method in ("get", "post", "put", "patch", "delete") and isinstance(op, dict):
					resources[resource].append({
						"path": path,
						"method": method.upper(),
						"operationId": op.get("operationId", f"{method}_{resource}"),
						"summary": op.get("summary", ""),
						"description": op.get("description", ""),
						"parameters": op.get("parameters", []),
						"requestBody": op.get("requestBody"),
						"responses": op.get("responses", {}),
						"tags": op.get("tags", [resource]),
					})

		# Generate index screen (lists all resources)
		files["index.tsx"] = self._gen_index_screen(resources, spec)

		# Generate hooks file (TanStack Query hooks for every operation)
		files["hooks.ts"] = self._gen_hooks(resources, spec)

		# Generate a screen per resource
		for resource, ops in resources.items():
			screen_file = f"{resource}.tsx"
			files[screen_file] = self._gen_resource_screen(resource, ops, spec)

		# Write files
		out = Path(self.config.output_dir)
		out.mkdir(parents=True, exist_ok=True)
		for fname, content in files.items():
			(out / fname).write_text(content, encoding="utf-8")

		log.info("OpenAPIScreenGenerator: wrote %d files to %s", len(files), out)
		return files

	def _api_base(self, spec: dict) -> str:
		if self.config.base_url:
			return self.config.base_url
		servers = spec.get("servers", [])
		return servers[0]["url"] if servers else ""

	def _gen_index_screen(self, resources: dict, spec: dict) -> str:
		title = spec.get("info", {}).get("title", "API")
		version = spec.get("info", {}).get("version", "1.0")
		resource_items = "\n".join(
			f"      {{ name: '{r}', count: {len(ops)}, screen: '{r}' }},"
			for r, ops in sorted(resources.items())
		)
		return f"""import React from 'react';
import {{ View, Text, TouchableOpacity, FlatList, StyleSheet }} from 'react-native';
import {{ useRouter }} from 'expo-router';

const RESOURCES = [
{resource_items}
];

export default function APIIndexScreen() {{
  const router = useRouter();
  return (
    <View style={{styles.container}}>
      <View style={{styles.header}}>
        <Text style={{styles.title}}>{title}</Text>
        <Text style={{styles.subtitle}}>v{version}</Text>
      </View>
      <FlatList
        data={{RESOURCES}}
        keyExtractor={{item => item.name}}
        renderItem={{({{ item }}) => (
          <TouchableOpacity style={{styles.card}} onPress={{() => router.push(item.screen)}}>
            <Text style={{styles.cardTitle}}>{{item.name}}</Text>
            <Text style={{styles.cardSub}}>{{item.count}} endpoint{{item.count !== 1 ? 's' : ''}}</Text>
          </TouchableOpacity>
        )}}
      />
    </View>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, backgroundColor: '#f9fafb' }},
  header: {{ backgroundColor: '{self.config.primary_color}', padding: 24, paddingTop: 48 }},
  title: {{ fontSize: 22, fontWeight: '700', color: '#fff' }},
  subtitle: {{ fontSize: 12, color: 'rgba(255,255,255,0.7)', marginTop: 4 }},
  card: {{ margin: 12, marginBottom: 0, padding: 16, backgroundColor: '#fff',
            borderRadius: 8, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 4, elevation: 2 }},
  cardTitle: {{ fontSize: 16, fontWeight: '600', textTransform: 'capitalize' }},
  cardSub: {{ fontSize: 12, color: '#6b7280', marginTop: 4 }},
}});
"""

	def _gen_hooks(self, resources: dict, spec: dict) -> str:
		api_base = self._api_base(spec)
		auth_header = (
			f"'Authorization': `Bearer ${{token}}`"
			if self.config.auth_type == "bearer"
			else f"'X-API-Key': process.env.{self.config.api_key_env} ?? ''"
		)
		hooks = []
		for resource, ops in resources.items():
			for op in ops:
				op_id = _to_camel(op["operationId"])
				path = op["path"]
				method = op["method"]
				has_body = op.get("requestBody") is not None
				path_params = [p["name"] for p in op["parameters"] if p.get("in") == "path"]

				if method == "GET":
					params_sig = ", ".join(f"{p}: string" for p in path_params)
					path_expr = path
					for p in path_params:
						path_expr = path_expr.replace("{" + p + "}", "${" + p + "}")
					hook = (
						f"export function use{op_id[0].upper() + op_id[1:]}({params_sig}) {{\n"
						f"  return useQuery({{\n"
						f"    queryKey: ['{op_id}'{', ' + ', '.join(path_params) if path_params else ''}],\n"
						f"    queryFn: () => apiFetch(`{path_expr}`),\n"
						f"  }});\n}}"
					)
				else:
					params_sig = ", ".join(f"{p}: string" for p in path_params)
					if has_body:
						params_sig = (params_sig + ", " if params_sig else "") + "data: Record<string, unknown>"
					path_expr = path
					for p in path_params:
						path_expr = path_expr.replace("{" + p + "}", "${" + p + "}")
					hook = (
						f"export function use{op_id[0].upper() + op_id[1:]}Mutation() {{\n"
						f"  const qc = useQueryClient();\n"
						f"  return useMutation({{\n"
						f"    mutationFn: ({'data' if has_body else '_'}: Record<string, unknown>) => \n"
						f"      apiFetch(`{path_expr}`, {{ method: '{method}'{', body: JSON.stringify(data)' if has_body else ''} }}),\n"
						f"    onSuccess: () => qc.invalidateQueries({{ queryKey: ['{resource}'] }}),\n"
						f"  }});\n}}"
					)
				hooks.append(hook)

		return (
			"import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';\n\n"
			f"const API_BASE = process.env.EXPO_PUBLIC_API_BASE_URL ?? '{api_base}';\n\n"
			"async function apiFetch(path: string, init?: RequestInit) {\n"
			"  const token = await getToken();\n"
			"  const res = await fetch(`${API_BASE}${path}`, {\n"
			"    ...init,\n"
			f"    headers: {{ {auth_header}, 'Content-Type': 'application/json', ...init?.headers }},\n"
			"  });\n"
			"  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);\n"
			"  return res.json();\n"
			"}\n\n"
			"async function getToken(): Promise<string> {\n"
			"  const { getStoredToken } = await import('./auth');\n"
			"  return (await getStoredToken()) ?? '';\n"
			"}\n\n"
			+ "\n\n".join(hooks) + "\n"
		)

	def _gen_resource_screen(self, resource: str, ops: list, spec: dict) -> str:
		title = resource.replace("_", " ").replace("-", " ").title()
		get_ops = [o for o in ops if o["method"] == "GET"]
		post_ops = [o for o in ops if o["method"] == "POST"]

		# Find the list operation (GET without path params) and item op (GET with path params)
		list_op = next((o for o in get_ops if not any(p["in"] == "path" for p in o["parameters"])), None)
		detail_op = next((o for o in get_ops if any(p["in"] == "path" for p in o["parameters"])), None)
		create_op = post_ops[0] if post_ops else None

		list_hook = _to_camel("use_" + (list_op["operationId"] if list_op else f"list_{resource}"))
		screen_name = resource.title().replace("_", "").replace("-", "")

		return f"""import React, {{ useState }} from 'react';
import {{ View, Text, FlatList, TouchableOpacity, StyleSheet, ActivityIndicator }} from 'react-native';
import {{ use{list_hook[0].upper() + list_hook[1:]} }} from './hooks';

export default function {screen_name}Screen() {{
  const {{ data, isLoading, error, refetch }} = use{list_hook[0].upper() + list_hook[1:]}();
  const items = Array.isArray(data) ? data : data?.data ?? data?.items ?? [];

  if (isLoading) return <ActivityIndicator style={{{{flex:1}}}} />;
  if (error) return <Text style={{{{color:'red', padding:16}}}}>Error: {{error.message}}</Text>;

  return (
    <View style={{styles.container}}>
      <FlatList
        data={{items}}
        keyExtractor={{(item, i) => item.id?.toString() ?? String(i)}}
        onRefresh={{refetch}}
        refreshing={{isLoading}}
        renderItem={{({{ item }}) => (
          <View style={{styles.card}}>
            {{Object.entries(item).slice(0, 4).map(([k, v]) => (
              <Text key={{k}} style={{styles.row}}>
                <Text style={{styles.label}}>{{k}}: </Text>{{String(v)}}
              </Text>
            ))}}
          </View>
        )}}
      />
    </View>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, backgroundColor: '#f9fafb' }},
  card: {{ margin: 12, marginBottom: 0, padding: 16, backgroundColor: '#fff', borderRadius: 8,
           shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 4, elevation: 2 }},
  row: {{ fontSize: 14, marginBottom: 4 }},
  label: {{ fontWeight: '600', color: '#374151' }},
}});
"""


def _to_camel(s: str) -> str:
	return re.sub(r"[-_\s](.)", lambda m: m.group(1).upper(), s.strip())


__all__ = ["OpenAPIScreenGenerator", "OpenAPIScreenConfig"]
