"""
Mobile App Generator for PgForge

Generates a complete React Native (Expo) mobile application from a pgappforge
database schema, including screens, navigation, API client, and auth services.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database_inspector import ColumnType, EnhancedDatabaseInspector, TableInfo

logger = logging.getLogger(__name__)


@dataclass
class MobileGenerationConfig:
	app_name: str
	app_id: str  # e.g. "com.company.myapp"
	framework: str = "expo"  # "expo" | "pwa"
	api_base_url: str = "http://localhost:8080/api/v1"
	primary_color: str = "#007bff"
	features: list[str] = field(default_factory=lambda: ["auth", "list", "detail", "create", "edit"])


class MobileGenerator:
	"""
	Generates a complete React Native (Expo) mobile application from a pgappforge
	database schema.

	Produces:
	  - app.json                             Expo configuration
	  - App.tsx                              Root navigator (React Navigation)
	  - screens/{Model}ListScreen.tsx        List + search + pull-to-refresh
	  - screens/{Model}DetailScreen.tsx      Record detail view
	  - screens/{Model}FormScreen.tsx        Create / edit form
	  - services/api.ts                      Typed Axios client for pgappforge REST
	  - services/auth.ts                     JWT login / refresh / logout
	  - components/Field.tsx                 Auto-renders field by column type
	  - package.json                         Expo + React Navigation + Axios deps
	  - .env.example                         API_BASE_URL placeholder
	"""

	def __init__(
		self,
		inspector: EnhancedDatabaseInspector,
		config: MobileGenerationConfig,
		output_dir: str | Path,
	):
		self.inspector = inspector
		self.config = config
		self.output_dir = Path(output_dir)

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def generate_complete_app(self) -> dict[str, str]:
		"""
		Introspect the database and generate all mobile app source files.

		Returns a dict mapping relative file path -> file content.
		All files are also written to output_dir.
		"""
		analysis = self.inspector.analyze_database()
		tables = {
			name: info
			for name, info in analysis["tables"].items()
			if not info.is_association_table
		}

		files: dict[str, str] = {}

		# Top-level config / entry files
		files["app.json"] = self._generate_app_json()
		files["package.json"] = self._generate_package_json()
		files[".env.example"] = self._generate_env_example()
		files["App.tsx"] = self._generate_app_tsx(list(tables.keys()))

		# Shared services
		files["services/api.ts"] = self._generate_api_service()
		files["services/auth.ts"] = self._generate_auth_service()

		# Shared component
		files["components/Field.tsx"] = self._generate_field_component()

		# Per-table screens
		for table_name, table_info in tables.items():
			screen_files = self._generate_screen(table_info)
			files.update(screen_files)

		# Write all files to disk
		self._write_files(files)

		logger.info("Generated %d mobile app files in %s", len(files), self.output_dir)
		return files

	# ------------------------------------------------------------------
	# Screen generation
	# ------------------------------------------------------------------

	def _generate_screen(self, table_info: TableInfo) -> dict[str, str]:
		"""Return all screen files for a single table."""
		model = _pascal(table_info.name)
		resource = _camel(table_info.name)
		display = table_info.display_name
		files: dict[str, str] = {}

		visible_cols = [c for c in table_info.columns if not c.primary_key]
		list_cols = visible_cols[:5]  # cap list view columns

		# ---- ListScreen ----
		if "list" in self.config.features:
			files[f"screens/{model}ListScreen.tsx"] = self._list_screen(
				model, resource, display, list_cols
			)

		# ---- DetailScreen ----
		if "detail" in self.config.features:
			files[f"screens/{model}DetailScreen.tsx"] = self._detail_screen(
				model, resource, display, visible_cols
			)

		# ---- FormScreen (create + edit) ----
		if "create" in self.config.features or "edit" in self.config.features:
			files[f"screens/{model}FormScreen.tsx"] = self._form_screen(
				model, resource, display, visible_cols
			)

		return files

	def _list_screen(self, model: str, resource: str, display: str, cols: list) -> str:
		pk_field = "id"
		first_text_col = next(
			(c.name for c in cols if c.category in (ColumnType.TEXT, ColumnType.NUMERIC)),
			cols[0].name if cols else "id",
		)
		can_create = "create" in self.config.features
		can_edit = "edit" in self.config.features
		can_detail = "detail" in self.config.features

		create_fab = (
			f"""
      <TouchableOpacity style={{styles.fab}} onPress={{() => navigation.navigate('{model}Form', {{ mode: 'create' }})}}>
        <Text style={{styles.fabText}}>+</Text>
      </TouchableOpacity>"""
			if can_create
			else ""
		)

		item_press = (
			f"navigation.navigate('{model}Detail', {{ id: item.{pk_field} }})"
			if can_detail
			else "null"
		)
		item_edit = (
			f"""
          <TouchableOpacity onPress={{() => navigation.navigate('{model}Form', {{ mode: 'edit', id: item.{pk_field} }})}}>
            <Text style={{styles.editBtn}}>Edit</Text>
          </TouchableOpacity>"""
			if can_edit
			else ""
		)

		return f"""import React, {{ useState, useCallback }} from 'react';
import {{
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  StyleSheet,
}} from 'react-native';
import {{ useFocusEffect }} from '@react-navigation/native';
import {{ api }} from '../services/api';

type {model} = Record<string, any>;

export default function {model}ListScreen({{ navigation }}: any) {{
  const [items, setItems] = useState<{model}[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  const load = useCallback(async (reset = false) => {{
    if (loading && !reset) return;
    setLoading(true);
    try {{
      const currentPage = reset ? 1 : page;
      const response = await api.get('/{resource}', {{
        params: {{ q: search || undefined, page: currentPage, page_size: 25 }},
      }});
      const data: {model}[] = response.data.result ?? response.data;
      if (reset) {{
        setItems(data);
        setPage(2);
      }} else {{
        setItems(prev => [...prev, ...data]);
        setPage(p => p + 1);
      }}
      setHasMore(data.length === 25);
    }} catch (err) {{
      console.error('Failed to load {display}:', err);
    }} finally {{
      setLoading(false);
      setRefreshing(false);
    }}
  }}, [search, page, loading]);

  useFocusEffect(useCallback(() => {{ load(true); }}, [search]));

  const onRefresh = () => {{
    setRefreshing(true);
    load(true);
  }};

  const renderItem = ({{ item }}: {{ item: {model} }}) => (
    <TouchableOpacity style={{styles.row}} onPress={{() => {item_press}}}>
      <Text style={{styles.rowTitle}}>{{item.{first_text_col} ?? item.id}}</Text>
      <View style={{styles.rowActions}}>{item_edit}
      </View>
    </TouchableOpacity>
  );

  return (
    <View style={{styles.container}}>
      <TextInput
        style={{styles.search}}
        placeholder="Search {display}..."
        value={{search}}
        onChangeText={{t => {{ setSearch(t); setPage(1); }}}}
        returnKeyType="search"
        onSubmitEditing={{() => load(true)}}
      />
      <FlatList
        data={{items}}
        keyExtractor={{item => String(item.id)}}
        renderItem={{renderItem}}
        refreshControl={{<RefreshControl refreshing={{refreshing}} onRefresh={{onRefresh}} />}}
        onEndReached={{() => hasMore && load()}}
        onEndReachedThreshold={{0.3}}
        ListFooterComponent={{loading ? <ActivityIndicator style={{{{ margin: 16 }}}} /> : null}}
        ListEmptyComponent={{!loading ? <Text style={{styles.empty}}>No {display} found.</Text> : null}}
      />
      {create_fab}
    </View>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, backgroundColor: '#f5f5f5' }},
  search: {{
    margin: 12,
    padding: 10,
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#ddd',
    fontSize: 15,
  }},
  row: {{
    backgroundColor: '#fff',
    marginHorizontal: 12,
    marginBottom: 8,
    borderRadius: 8,
    padding: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    elevation: 1,
    shadowColor: '#000',
    shadowOpacity: 0.06,
    shadowRadius: 4,
    shadowOffset: {{ width: 0, height: 2 }},
  }},
  rowTitle: {{ fontSize: 16, color: '#222', flex: 1 }},
  rowActions: {{ flexDirection: 'row', gap: 8 }},
  editBtn: {{ color: '{self.config.primary_color}', fontWeight: '600' }},
  empty: {{ textAlign: 'center', color: '#999', marginTop: 48, fontSize: 15 }},
  fab: {{
    position: 'absolute',
    bottom: 24,
    right: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '{self.config.primary_color}',
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 4,
  }},
  fabText: {{ color: '#fff', fontSize: 28, lineHeight: 30 }},
}});
"""

	def _detail_screen(self, model: str, resource: str, display: str, cols: list) -> str:
		field_rows = "\n".join(
			f"      <Field label=\"{c.display_name}\" value={{item?.{c.name}}} type=\"{_ts_field_type(c)}\" />"
			for c in cols
		)
		can_edit = "edit" in self.config.features

		edit_btn = (
			f"""
  React.useLayoutEffect(() => {{
    navigation.setOptions({{
      headerRight: () => (
        <TouchableOpacity onPress={{() => navigation.navigate('{model}Form', {{ mode: 'edit', id }})}} style={{{{ marginRight: 16 }}}}>
          <Text style={{{{ color: '{self.config.primary_color}', fontWeight: '600' }}}}>Edit</Text>
        </TouchableOpacity>
      ),
    }});
  }}, [navigation, id]);"""
			if can_edit
			else ""
		)
		touch_import = "TouchableOpacity, " if can_edit else ""

		return f"""import React, {{ useState, useEffect }} from 'react';
import {{ View, Text, ScrollView, ActivityIndicator, {touch_import}StyleSheet }} from 'react-native';
import {{ Field }} from '../components/Field';
import {{ api }} from '../services/api';

export default function {model}DetailScreen({{ route, navigation }}: any) {{
  const {{ id }} = route.params;
  const [item, setItem] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
{edit_btn}

  useEffect(() => {{
    api.get(`/{resource}/${{id}}`)
      .then(r => setItem(r.data.result ?? r.data))
      .catch(e => setError(e.message ?? 'Failed to load'))
      .finally(() => setLoading(false));
  }}, [id]);

  if (loading) return <ActivityIndicator style={{{{ flex: 1 }}}} size="large" />;
  if (error) return <Text style={{styles.error}}>{{error}}</Text>;

  return (
    <ScrollView style={{styles.container}} contentContainerStyle={{styles.content}}>
      <Text style={{styles.title}}>{{item?.name ?? item?.title ?? `{display} ${{id}}`}}</Text>
{field_rows}
    </ScrollView>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, backgroundColor: '#f5f5f5' }},
  content: {{ padding: 16 }},
  title: {{ fontSize: 22, fontWeight: '700', color: '#111', marginBottom: 16 }},
  error: {{ flex: 1, textAlign: 'center', color: '#e53935', marginTop: 48 }},
}});
"""

	def _form_screen(self, model: str, resource: str, display: str, cols: list) -> str:
		editable_cols = [
			c for c in cols
			if not c.primary_key and not c.foreign_key and c.category not in (
				ColumnType.BINARY, ColumnType.VECTOR, ColumnType.GEOMETRY, ColumnType.GEOGRAPHY,
			)
		]

		state_lines = "\n".join(
			f"    {c.name}: ''," for c in editable_cols
		)
		load_lines = "\n".join(
			f"        {c.name}: data.{c.name} ?? ''," for c in editable_cols
		)
		field_inputs = "\n".join(
			self._form_field_input(c) for c in editable_cols
		)

		return f"""import React, {{ useState, useEffect }} from 'react';
import {{
  View,
  Text,
  TextInput,
  ScrollView,
  TouchableOpacity,
  Switch,
  ActivityIndicator,
  StyleSheet,
  Alert,
}} from 'react-native';
import {{ api }} from '../services/api';

export default function {model}FormScreen({{ route, navigation }}: any) {{
  const {{ mode, id }} = route.params ?? {{ mode: 'create' }};
  const [form, setForm] = useState<Record<string, any>>({{
{state_lines}
  }});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {{
    if (mode === 'edit' && id) {{
      setLoading(true);
      api.get(`/{resource}/${{id}}`)
        .then(r => {{
          const data = r.data.result ?? r.data;
          setForm(prev => ({{
            ...prev,
{load_lines}
          }}));
        }})
        .catch(e => Alert.alert('Error', e.message ?? 'Failed to load'))
        .finally(() => setLoading(false));
    }}
  }}, [mode, id]);

  const set = (key: string, value: any) => setForm(prev => ({{ ...prev, [key]: value }}));

  const save = async () => {{
    setSaving(true);
    try {{
      if (mode === 'edit') {{
        await api.put(`/{resource}/${{id}}`, form);
      }} else {{
        await api.post('/{resource}', form);
      }}
      navigation.goBack();
    }} catch (err: any) {{
      Alert.alert('Save failed', err.response?.data?.message ?? err.message ?? 'Unknown error');
    }} finally {{
      setSaving(false);
    }}
  }};

  if (loading) return <ActivityIndicator style={{{{ flex: 1 }}}} size="large" />;

  return (
    <ScrollView style={{styles.container}} contentContainerStyle={{styles.content}}>
      <Text style={{styles.heading}}>{{mode === 'edit' ? 'Edit' : 'New'}} {display}</Text>
{field_inputs}
      <TouchableOpacity style={{[styles.saveBtn, saving && styles.disabled]}} onPress={{save}} disabled={{saving}}>
        {{saving ? <ActivityIndicator color="#fff" /> : <Text style={{styles.saveBtnText}}>Save</Text>}}
      </TouchableOpacity>
    </ScrollView>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, backgroundColor: '#f5f5f5' }},
  content: {{ padding: 16, paddingBottom: 40 }},
  heading: {{ fontSize: 20, fontWeight: '700', color: '#111', marginBottom: 20 }},
  label: {{ fontSize: 13, color: '#555', marginBottom: 4, marginTop: 12, fontWeight: '600' }},
  input: {{
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: '#222',
  }},
  switchRow: {{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 }},
  saveBtn: {{
    marginTop: 28,
    backgroundColor: '{self.config.primary_color}',
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
  }},
  disabled: {{ opacity: 0.6 }},
  saveBtnText: {{ color: '#fff', fontSize: 16, fontWeight: '700' }},
}});
"""

	def _form_field_input(self, col) -> str:
		"""Return the JSX for a single form field input."""
		label = col.display_name
		name = col.name
		cat = col.category

		if cat == ColumnType.BOOLEAN:
			return (
				f"      <View style={{styles.switchRow}}>\n"
				f"        <Text style={{styles.label}}>{label}</Text>\n"
				f"        <Switch value={{!!form.{name}}} onValueChange={{v => set('{name}', v)}} />\n"
				f"      </View>"
			)

		kb = "numeric" if cat == ColumnType.NUMERIC else "email-address" if "email" in name.lower() else "default"
		multiline = cat == ColumnType.TEXT and "description" in name.lower()
		height = "height: 96, " if multiline else ""

		return (
			f"      <Text style={{styles.label}}>{label}</Text>\n"
			f"      <TextInput\n"
			f"        style={{[styles.input, {{{height}}}]}}\n"
			f"        value={{String(form.{name} ?? '')}}\n"
			f"        onChangeText={{t => set('{name}', t)}}\n"
			f"        keyboardType=\"{kb}\"\n"
			f"        multiline={{{str(multiline).lower()}}}\n"
			f"        placeholder=\"{label}\"\n"
			f"      />"
		)

	# ------------------------------------------------------------------
	# Services
	# ------------------------------------------------------------------

	def _generate_api_service(self) -> str:
		return f"""import axios, {{ AxiosInstance, AxiosRequestConfig }} from 'axios';
import {{ getTokens, refreshAccessToken, clearTokens }} from './auth';

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? '{self.config.api_base_url}';

const instance: AxiosInstance = axios.create({{
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: {{ 'Content-Type': 'application/json' }},
}});

// Attach JWT on every request
instance.interceptors.request.use(async config => {{
  const {{ accessToken }} = await getTokens();
  if (accessToken) {{
    config.headers = config.headers ?? {{}};
    config.headers['Authorization'] = `Bearer ${{accessToken}}`;
  }}
  return config;
}});

// Auto-refresh on 401
instance.interceptors.response.use(
  res => res,
  async err => {{
    const original = err.config as AxiosRequestConfig & {{ _retry?: boolean }};
    if (err.response?.status === 401 && !original._retry) {{
      original._retry = true;
      try {{
        await refreshAccessToken();
        return instance(original);
      }} catch {{
        await clearTokens();
        // Caller can listen to clearTokens event to navigate to Login
      }}
    }}
    return Promise.reject(err);
  }}
);

export const api = instance;
"""

	def _generate_auth_service(self) -> str:
		return f"""import axios from 'axios';
import * as SecureStore from 'expo-secure-store';

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? '{self.config.api_base_url}';

const ACCESS_KEY = 'access_token';
const REFRESH_KEY = 'refresh_token';

export interface AuthTokens {{
  accessToken: string | null;
  refreshToken: string | null;
}}

export async function getTokens(): Promise<AuthTokens> {{
  const [accessToken, refreshToken] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_KEY),
    SecureStore.getItemAsync(REFRESH_KEY),
  ]);
  return {{ accessToken, refreshToken }};
}}

export async function login(username: string, password: string): Promise<void> {{
  const res = await axios.post(`${{BASE_URL}}/security/login`, {{
    username,
    password,
    provider: 'db',
    refresh: true,
  }});
  const {{ access_token, refresh_token }} = res.data;
  await Promise.all([
    SecureStore.setItemAsync(ACCESS_KEY, access_token),
    SecureStore.setItemAsync(REFRESH_KEY, refresh_token ?? ''),
  ]);
}}

export async function refreshAccessToken(): Promise<void> {{
  const {{ refreshToken }} = await getTokens();
  if (!refreshToken) throw new Error('No refresh token');
  const res = await axios.post(
    `${{BASE_URL}}/security/refresh`,
    null,
    {{ headers: {{ Authorization: `Bearer ${{refreshToken}}` }} }}
  );
  await SecureStore.setItemAsync(ACCESS_KEY, res.data.access_token);
}}

export async function logout(): Promise<void> {{
  await clearTokens();
}}

export async function clearTokens(): Promise<void> {{
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
  ]);
}}

export async function isAuthenticated(): Promise<boolean> {{
  const {{ accessToken }} = await getTokens();
  return !!accessToken;
}}
"""

	# ------------------------------------------------------------------
	# Shared components
	# ------------------------------------------------------------------

	def _generate_field_component(self) -> str:
		return """import React from 'react';
import { View, Text, Image, StyleSheet } from 'react-native';

interface FieldProps {
  label: string;
  value: any;
  type?: string;
}

/**
 * Auto-renders a field value based on its column type.
 * Supported type hints: text, numeric, boolean, date, datetime, json, binary, uuid, enum, url, email
 */
export function Field({ label, value, type = 'text' }: FieldProps) {
  const rendered = renderValue(value, type);
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      {rendered}
    </View>
  );
}

function renderValue(value: any, type: string) {
  if (value === null || value === undefined || value === '') {
    return <Text style={styles.empty}>—</Text>;
  }

  switch (type) {
    case 'boolean':
      return <Text style={[styles.value, value ? styles.yes : styles.no]}>{value ? 'Yes' : 'No'}</Text>;

    case 'date':
      try {
        return <Text style={styles.value}>{new Date(value).toLocaleDateString()}</Text>;
      } catch {
        return <Text style={styles.value}>{String(value)}</Text>;
      }

    case 'datetime':
      try {
        return <Text style={styles.value}>{new Date(value).toLocaleString()}</Text>;
      } catch {
        return <Text style={styles.value}>{String(value)}</Text>;
      }

    case 'json':
      return (
        <Text style={[styles.value, styles.mono]} numberOfLines={4}>
          {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
        </Text>
      );

    case 'binary':
      return (
        <Image
          source={{ uri: typeof value === 'string' ? value : undefined }}
          style={styles.image}
          resizeMode="contain"
        />
      );

    case 'email':
      return <Text style={[styles.value, styles.link]}>{String(value)}</Text>;

    case 'url':
      return <Text style={[styles.value, styles.link]} numberOfLines={1}>{String(value)}</Text>;

    default:
      return <Text style={styles.value}>{String(value)}</Text>;
  }
}

const styles = StyleSheet.create({
  row: {
    backgroundColor: '#fff',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    elevation: 1,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
  },
  label: { fontSize: 11, color: '#888', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 },
  value: { fontSize: 15, color: '#222' },
  empty: { fontSize: 15, color: '#bbb', fontStyle: 'italic' },
  mono: { fontFamily: 'monospace', fontSize: 12, color: '#444' },
  link: { color: '#007bff', textDecorationLine: 'underline' },
  yes: { color: '#2e7d32' },
  no: { color: '#c62828' },
  image: { width: '100%', height: 180, borderRadius: 6, marginTop: 4 },
});
"""

	# ------------------------------------------------------------------
	# Navigation (App.tsx)
	# ------------------------------------------------------------------

	def _generate_app_tsx(self, table_names: list[str]) -> str:
		model_names = [_pascal(t) for t in table_names]

		screen_imports = "\n".join(
			f"import {m}ListScreen from './screens/{m}ListScreen';"
			for m in model_names
		) + ("\nimport LoginScreen from './screens/LoginScreen';" if "auth" in self.config.features else "")

		# Stack screens for each model
		stack_screens = "\n".join(
			f"        <Stack.Screen name=\"{m}List\" component={{{m}ListScreen}} options={{{{ title: '{_spaces(t)}' }}}} />"
			+ (
				f"\n        <Stack.Screen name=\"{m}Detail\" component={{{{({m}DetailScreen)}}}}"
				+ f" options={{{{ title: '{_spaces(t)} Detail' }}}} />"
				if "detail" in self.config.features
				else ""
			)
			+ (
				f"\n        <Stack.Screen name=\"{m}Form\" component={{{{({m}FormScreen)}}}}"
				+ f" options={{{{ title: 'Edit {_spaces(t)}' }}}} />"
				if "create" in self.config.features or "edit" in self.config.features
				else ""
			)
			for m, t in zip(model_names, table_names)
		)

		detail_imports = (
			"\n".join(
				f"import {m}DetailScreen from './screens/{m}DetailScreen';"
				for m in model_names
			)
			if "detail" in self.config.features
			else ""
		)
		form_imports = (
			"\n".join(
				f"import {m}FormScreen from './screens/{m}FormScreen';"
				for m in model_names
			)
			if "create" in self.config.features or "edit" in self.config.features
			else ""
		)

		tab_screens = "\n".join(
			f"        <Tab.Screen name=\"{m}List\" component={{{m}ListScreen}} options={{{{ tabBarLabel: '{_spaces(t)}' }}}} />"
			for m, t in zip(model_names[:5], table_names[:5])  # cap tabs at 5
		)

		auth_check = (
			"""
  const [authed, setAuthed] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    isAuthenticated().then(setAuthed);
  }, []);

  if (authed === null) return null; // splash while checking

  if (!authed) {
    return (
      <NavigationContainer>
        <Stack.Navigator>
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        </Stack.Navigator>
      </NavigationContainer>
    );
  }"""
			if "auth" in self.config.features
			else ""
		)

		auth_import = (
			"import { isAuthenticated } from './services/auth';"
			if "auth" in self.config.features
			else ""
		)

		return f"""import React from 'react';
import {{ NavigationContainer }} from '@react-navigation/native';
import {{ createBottomTabNavigator }} from '@react-navigation/bottom-tabs';
import {{ createNativeStackNavigator }} from '@react-navigation/native-stack';
{auth_import}
{screen_imports}
{detail_imports}
{form_imports}

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function TabNavigator() {{
  return (
    <Tab.Navigator screenOptions={{{{ headerShown: false }}}}>
{tab_screens}
    </Tab.Navigator>
  );
}}

export default function App() {{
{auth_check}

  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Tabs" component={{TabNavigator}} options={{{{ headerShown: false }}}} />
{stack_screens}
      </Stack.Navigator>
    </NavigationContainer>
  );
}}
"""

	# ------------------------------------------------------------------
	# Config files
	# ------------------------------------------------------------------

	def _generate_app_json(self) -> str:
		slug = self.config.app_name.lower().replace(" ", "-")
		cfg = {
			"expo": {
				"name": self.config.app_name,
				"slug": slug,
				"version": "1.0.0",
				"orientation": "portrait",
				"icon": "./assets/icon.png",
				"userInterfaceStyle": "light",
				"splash": {
					"image": "./assets/splash.png",
					"resizeMode": "contain",
					"backgroundColor": self.config.primary_color,
				},
				"ios": {
					"supportsTablet": True,
					"bundleIdentifier": self.config.app_id,
				},
				"android": {
					"adaptiveIcon": {
						"foregroundImage": "./assets/adaptive-icon.png",
						"backgroundColor": self.config.primary_color,
					},
					"package": self.config.app_id,
				},
				"web": {
					"favicon": "./assets/favicon.png",
				},
				"plugins": ["expo-secure-store"],
				"extra": {
					"apiBaseUrl": self.config.api_base_url,
				},
			}
		}
		return json.dumps(cfg, indent=2)

	def _generate_package_json(self) -> str:
		slug = self.config.app_name.lower().replace(" ", "-")
		pkg = {
			"name": slug,
			"version": "1.0.0",
			"main": "node_modules/expo/AppEntry.js",
			"scripts": {
				"start": "expo start",
				"android": "expo start --android",
				"ios": "expo start --ios",
				"web": "expo start --web",
			},
			"dependencies": {
				"expo": "~51.0.0",
				"expo-secure-store": "~13.0.0",
				"expo-status-bar": "~1.12.1",
				"react": "18.2.0",
				"react-native": "0.74.1",
				"@react-navigation/native": "^6.1.17",
				"@react-navigation/native-stack": "^6.9.26",
				"@react-navigation/bottom-tabs": "^6.5.20",
				"react-native-safe-area-context": "4.10.1",
				"react-native-screens": "3.31.1",
				"axios": "^1.7.2",
			},
			"devDependencies": {
				"@babel/core": "^7.24.0",
				"@types/react": "~18.2.79",
				"typescript": "^5.3.3",
			},
			"private": True,
		}
		return json.dumps(pkg, indent=2)

	def _generate_env_example(self) -> str:
		return f"# Copy to .env and fill in your values\nEXPO_PUBLIC_API_BASE_URL={self.config.api_base_url}\n"

	# ------------------------------------------------------------------
	# Field component helper
	# ------------------------------------------------------------------

	def _get_field_component(self, col) -> str:
		"""Return TypeScript JSX for a single read-only Field in a detail screen."""
		ts_type = _ts_field_type(col)
		return f'<Field label="{col.display_name}" value={{item?.{col.name}}} type="{ts_type}" />'

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _write_files(self, files: dict[str, str]) -> None:
		for rel_path, content in files.items():
			dest = self.output_dir / rel_path
			dest.parent.mkdir(parents=True, exist_ok=True)
			dest.write_text(content, encoding="utf-8")
			logger.debug("Wrote %s", dest)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _pascal(snake: str) -> str:
	"""snake_case -> PascalCase"""
	return "".join(w.capitalize() for w in snake.split("_"))


def _camel(snake: str) -> str:
	"""snake_case -> camelCase"""
	parts = snake.split("_")
	return parts[0] + "".join(w.capitalize() for w in parts[1:])


def _spaces(snake: str) -> str:
	"""snake_case -> Title Words"""
	return snake.replace("_", " ").title()


def _ts_field_type(col) -> str:
	"""Map a ColumnInfo category to a Field component type hint string."""
	_MAP = {
		ColumnType.BOOLEAN: "boolean",
		ColumnType.DATE_TIME: "datetime",
		ColumnType.NUMERIC: "numeric",
		ColumnType.JSON: "json",
		ColumnType.JSONB: "json",
		ColumnType.BINARY: "binary",
		ColumnType.UUID: "uuid",
		ColumnType.ENUM: "enum",
	}
	ts = _MAP.get(col.category, "text")
	name_lower = col.name.lower()
	if "email" in name_lower:
		return "email"
	if "url" in name_lower or "link" in name_lower:
		return "url"
	return ts
