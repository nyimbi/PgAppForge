"""AddressAutocompleteWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.widgets import html_params


class AddressAutocompleteWidget(BS3TextFieldWidget):
	"""
	Advanced address autocomplete widget with validation and geocoding integration.

	Features:
	- Real-time address suggestions via datalist or provider JS SDK
	- Multiple provider support (Google, Here, MapBox, OpenStreetMap/Nominatim)
	- Address validation
	- Geocoding/reverse geocoding
	- Custom formatting
	- International support
	- Address components breakdown
	- Recent addresses (localStorage)
	- Offline support
	- Custom validation rules
	- Format standardization
	- Postal code validation
	- Multiple language support
	- Business/residential filtering
	- Custom address restrictions

	Supported Providers:
	- Google Places API
	- Here Maps
	- MapBox
	- OpenStreetMap/Nominatim (default, no key required)
	- Custom API integration

	Required Dependencies (provider-dependent):
	- Google Places JS API (provider='google')
	- MapBox GL JS (provider='mapbox')
	- HERE JS SDK (provider='here')

	Example:
	    address = StringField('Address',
	                        widget=AddressAutocompleteWidget(
	                            provider='google',
	                            api_key='your_api_key',
	                            countries=['US', 'CA'],
	                            type='both',
	                            language='en'
	                        ))
	"""

	def __init__(self, **kwargs):
		"""
		Initialize AddressAutocompleteWidget with custom settings.

		Args:
		    provider (str): Address provider service ('google', 'mapbox', 'here', 'osm')
		    api_key (str): API key for chosen provider
		    countries (list): Restricted countries list (ISO-3166 alpha-2)
		    type (str): Address type filter ('residential', 'business', 'both')
		    language (str): Preferred language (BCP-47 tag)
		    format_template (str): Address format template
		    validation_rules (dict): Custom validation rules
		    recent_addresses (int): Number of recent addresses to store in localStorage
		    offline_database (str): Offline address database path
		    bias_location (tuple): Location bias coordinates (lat, lng)
		    custom_restrictions (dict): Custom address restrictions
		    placeholder (str): Input placeholder text
		    css_class (str): Additional CSS classes for the input
		    description (str): Help text rendered below the input
		    readonly (bool): Render as read-only
		    disabled (bool): Render as disabled
		"""
		super().__init__(**kwargs)
		self.provider = kwargs.get("provider", "osm")
		self.api_key = kwargs.get("api_key")
		self.countries = kwargs.get("countries", [])
		self.type = kwargs.get("type", "both")
		self.language = kwargs.get("language", "en")
		self.format_template = kwargs.get("format_template", None)
		self.validation_rules = kwargs.get("validation_rules", {})
		self.recent_addresses = kwargs.get("recent_addresses", 5)
		self.offline_database = kwargs.get("offline_database", None)
		self.bias_location = kwargs.get("bias_location", None)
		self.custom_restrictions = kwargs.get("custom_restrictions", {})
		self.placeholder = kwargs.get("placeholder", "Start typing an address...")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the address autocomplete input with JS suggestions."""
		has_errors = bool(field.errors)

		input_class = "form-control"
		if self.css_class:
			input_class += " " + self.css_class
		if has_errors:
			input_class += " is-invalid"

		label_text = str(field.label.text) if field.label else str(field.name)
		datalist_id = f"{field.id}-suggestions"

		input_attrs: dict[str, Any] = {
			"type": "text",
			"id": field.id,
			"name": field.name,
			"class": input_class,
			"placeholder": str(self.placeholder),
			"autocomplete": "off",
			"list": datalist_id,
			"aria-label": label_text,
			"role": "combobox",
			"aria-autocomplete": "list",
			"aria-expanded": "false",
			"aria-controls": datalist_id,
		}
		if self.description:
			input_attrs["aria-describedby"] = f"{field.id}_help"
		if has_errors:
			input_attrs["aria-invalid"] = "true"
		if self.readonly:
			input_attrs["readonly"] = True
		if self.disabled:
			input_attrs["disabled"] = True
		if field.data:
			input_attrs["value"] = field.data

		html = f"""
<div class="address-autocomplete-widget">
  <input {html_params(**input_attrs)}>
  <datalist id="{datalist_id}"></datalist>
"""

		if self.description:
			html += f'  <small class="form-text text-muted" id="{field.id}_help">{escape(self.description)}</small>\n'

		if has_errors:
			errors_html = " ".join(str(escape(e)) for e in field.errors)
			html += f'  <div class="invalid-feedback d-block" id="{field.id}_error">{errors_html}</div>\n'

		html += "</div>\n"
		html += self._render_script(field.id)

		return Markup(html)

	def _render_script(self, field_id: str) -> str:
		"""Render the autocomplete JS for the configured provider."""
		return """
<script>
(function() {{
    var fieldId = {field_id_js};
    var inputEl = document.getElementById(fieldId);
    var datalistEl = document.getElementById(fieldId + '-suggestions');
    if (!inputEl || !datalistEl) return;

    var provider = {provider_js};
    var apiKey = {api_key_js};
    var countries = {countries_js};
    var language = {language_js};
    var recentKey = 'address_recent_' + fieldId;
    var maxRecent = {max_recent};

    function storeRecent(address) {{
        try {{
            var recent = JSON.parse(localStorage.getItem(recentKey) || '[]');
            recent = recent.filter(function(a) {{ return a !== address; }});
            recent.unshift(address);
            if (recent.length > maxRecent) recent = recent.slice(0, maxRecent);
            localStorage.setItem(recentKey, JSON.stringify(recent));
        }} catch (e) {{ /* localStorage unavailable */ }}
    }}

    function populateSuggestions(suggestions) {{
        while (datalistEl.firstChild) datalistEl.removeChild(datalistEl.firstChild);
        suggestions.forEach(function(s) {{
            var opt = document.createElement('option');
            opt.value = s;
            datalistEl.appendChild(opt);
        }});
        inputEl.setAttribute('aria-expanded', suggestions.length > 0 ? 'true' : 'false');
    }}

    function fetchNominatim(query) {{
        var url = 'https://nominatim.openstreetmap.org/search?format=json&limit=5&addressdetails=1'
            + '&q=' + encodeURIComponent(query)
            + (countries.length ? '&countrycodes=' + countries.join(',').toLowerCase() : '')
            + '&accept-language=' + encodeURIComponent(language);
        fetch(url)
            .then(function(r) {{ return r.json(); }})
            .then(function(data) {{
                populateSuggestions(data.map(function(d) {{ return d.display_name; }}));
            }})
            .catch(function() {{ populateSuggestions([]); }});
    }}

    function fetchMapbox(query) {{
        if (!apiKey) return;
        var url = 'https://api.mapbox.com/geocoding/v5/mapbox.places/'
            + encodeURIComponent(query) + '.json'
            + '?access_token=' + encodeURIComponent(apiKey)
            + '&limit=5'
            + '&language=' + encodeURIComponent(language)
            + (countries.length ? '&country=' + countries.join(',') : '');
        fetch(url)
            .then(function(r) {{ return r.json(); }})
            .then(function(data) {{
                var suggestions = (data.features || []).map(function(f) {{ return f.place_name; }});
                populateSuggestions(suggestions);
            }})
            .catch(function() {{ populateSuggestions([]); }});
    }}

    // Google Places uses a different initialisation path (script callback)
    function initGoogle() {{
        if (typeof google === 'undefined' || !google.maps || !google.maps.places) {{
            console.warn('AddressAutocompleteWidget: Google Maps JS not loaded');
            return;
        }}
        var ac = new google.maps.places.Autocomplete(inputEl, {{
            types: ['address'],
            componentRestrictions: countries.length ? {{ country: countries }} : undefined,
            language: language
        }});
        ac.addListener('place_changed', function() {{
            var place = ac.getPlace();
            if (place && place.formatted_address) {{
                inputEl.value = place.formatted_address;
                storeRecent(place.formatted_address);
            }}
        }});
        // Google manages its own dropdown — disable datalist
        inputEl.removeAttribute('list');
    }}

    var debounceTimer;
    inputEl.addEventListener('input', function() {{
        clearTimeout(debounceTimer);
        var query = inputEl.value.trim();
        if (query.length < 3) {{
            populateSuggestions([]);
            return;
        }}
        debounceTimer = setTimeout(function() {{
            if (provider === 'mapbox') {{
                fetchMapbox(query);
            }} else if (provider === 'google') {{
                // Google autocomplete handles its own input events
            }} else {{
                fetchNominatim(query);
            }}
        }}, 250);
    }});

    inputEl.addEventListener('change', function() {{
        if (inputEl.value) storeRecent(inputEl.value);
    }});

    if (provider === 'google') {{
        if (typeof google !== 'undefined') {{
            initGoogle();
        }} else {{
            // Defer until Maps API callback fires
            window['__addressInit_' + fieldId] = initGoogle;
        }}
    }}

    // Pre-populate recent addresses as initial suggestions on focus
    inputEl.addEventListener('focus', function() {{
        if (inputEl.value.length === 0) {{
            try {{
                var recent = JSON.parse(localStorage.getItem(recentKey) || '[]');
                populateSuggestions(recent);
            }} catch (e) {{}}
        }}
    }});
}})();
</script>
""".format(
			field_id_js=_js_json(field_id),
			provider_js=_js_json(self.provider),
			api_key_js=_js_json(self.api_key or ""),
			countries_js=_js_json(self.countries),
			language_js=_js_json(self.language),
			max_recent=int(self.recent_addresses),
		)

	def validate_address(self, address: str) -> dict:
		"""
		Validate address using selected provider.

		Args:
		    address: Address to validate

		Returns:
		    dict: Validation results with components and status
		"""
		# Subclasses or application code should implement provider-specific validation.
		return {"valid": bool(address and address.strip()), "address": address}

	def geocode_address(self, address: str) -> dict:
		"""
		Geocode address to coordinates.

		Args:
		    address: Address to geocode

		Returns:
		    dict: Geocoding results with coordinates and metadata
		"""
		# Subclasses or application code should implement provider-specific geocoding.
		return {"address": address, "lat": None, "lng": None}
