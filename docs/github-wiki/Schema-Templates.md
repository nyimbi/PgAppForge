# Schema Templates

[Home](Home) > Schema Templates

pgappforge ships 62 bundled schema templates covering 15 industry domains. Templates are JSON files that describe PostgreSQL tables, columns, and relationships in a format the ERD Designer and code generator can consume directly.

---

## Three-Tier System

| Tier | Location | Managed by |
|---|---|---|
| **Bundled** | `pgappforge/templates/bundled/` | Shipped with the package; cannot be removed |
| **User-installed** | `~/.pgappforge/templates/` | `flask forge templates install` or `TemplateRegistry.install_from_file()` |
| **Project-local** | `.pgappforge/templates/` in cwd | Committed to the project repo |

The registry loads all three tiers at startup. Project-local templates override user-installed, which override bundled (last-write-wins on name collision).

---

## CLI Commands

```bash
# List all templates (optionally filter by tag)
flask forge templates list
flask forge templates list --tag healthcare

# Show details for a specific template
flask forge templates info fhir-r4

# Apply a template to the current database (creates a new schema by default)
flask forge templates apply fhir-r4
flask forge templates apply fhir-r4 --schema clinical

# Install from a local JSON file
flask forge templates install /path/to/my-template.json

# Import a named template from the online registry
flask forge templates import fhir-r4

# Export a template to JSON
flask forge templates export fhir-r4
flask forge templates export fhir-r4 --output fhir-r4-backup.json

# Remove a user-installed template (bundled templates cannot be removed)
flask forge templates remove my-template
```

---

## All 62 Bundled Templates

| Name | Tables | Tags |
|---|---|---|
| `acord` | 5 | insurance, acord, enterprise |
| `activitypub` | 4 | social, federated, w3c |
| `actus` | 4 | finance, contracts, regulatory |
| `adapt` | 8 | agriculture, farming, iot |
| `akoma-ntoso` | 5 | legal, legislation, un |
| `ap` | 10 | finance, ap, invoicing |
| `ar` | 8 | finance, ar, invoicing |
| `arts` | 5 | retail, pos, inventory |
| `automationml` | 4 | manufacturing, digital-twin, industry40 |
| `cf-conventions` | 4 | climate, meteorology, science |
| `citygml` | 5 | smart-city, digital-twin, 3d |
| `crm` | 12 | crm, sales, marketing |
| `darwin-core` | 4 | biodiversity, ecology, science |
| `datacite` | 4 | science, research-data, doi |
| `dbt-semantic` | 6 | analytics, dbt, olap |
| `dcat` | 4 | government, open-data, w3c |
| `dicom-sr` | 5 | healthcare, radiology, imaging |
| `dublin-core` | 3 | metadata, libraries, iso |
| `ecommerce` | 17 | ecommerce, retail, online-store |
| `fao-agrovoc` | 5 | agriculture, fao, food-security |
| `fhir-r4` | 10 | healthcare, hl7, regulation |
| `fibo` | 5 | finance, ontology, edm-council |
| `fiware` | 5 | smart-city, eu, iot |
| `geonames` | 8 | spatial, geography, geocoding |
| `gl` | 9 | finance, gl, accounting |
| `gleif` | 2 | finance, entity-id, regulation |
| `green-button` | 4 | energy, utilities, us-mandate |
| `gs1-epcis` | 5 | supply-chain, gs1, pharma |
| `gs1-product` | 4 | ecommerce, gs1, seo |
| `gtfs` | 9 | transit, mobility, government |
| `hr-open` | 5 | hr, payroll, ieee |
| `hrm` | 15 | hr, hrm, payroll |
| `iati` | 5 | development-aid, ngo, transparency |
| `icd10` | 4 | healthcare, billing, clinical |
| `iec-cim` | 5 | energy, utilities, power-grid |
| `inspire` | 5 | eu-mandate, spatial, gis |
| `inventory` | 13 | inventory, warehouse, supply-chain |
| `iptc` | 4 | journalism, news, media |
| `iso15926` | 4 | oil-gas, energy, plant-lifecycle |
| `iso20022` | 5 | finance, banking, regulation |
| `loinc` | 4 | healthcare, terminology, laboratory |
| `lti` | 4 | education, lms, edtech |
| `niem` | 5 | us-government, federal, regulation |
| `ocds` | 6 | government, procurement, transparency |
| `opcua` | 5 | industrial, iiot, automation |
| `open-badges` | 4 | education, credentials, w3c |
| `open311` | 4 | civic, government, smart-city |
| `prov-o` | 7 | provenance, data-lineage, w3c |
| `qti` | 5 | education, assessment, testing |
| `reso` | 5 | real-estate, mls, idx |
| `saref` | 4 | iot, smart-home, eu |
| `schema-org-commerce` | 6 | ecommerce, seo, google |
| `scim` | 4 | identity, security, sso |
| `snomed-ct` | 4 | healthcare, terminology, clinical |
| `stix` | 7 | security, siem, threat-intel |
| `tmforum-sid` | 6 | telecoms, bss-oss, enterprise |
| `ubl-invoice` | 4 | finance, invoicing, eu-mandate |
| `vcard-ical` | 5 | contacts, calendar, crm |
| `w3c-wot` | 6 | iot, w3c, smart-home |
| `waterml` | 4 | water, hydrology, environmental |
| `xapi` | 4 | education, learning-analytics, lms |
| `xbrl-ifrs` | 4 | finance, reporting, ifrs |

---

## Template JSON Format

```json
{
  "name": "fhir-r4",
  "label": "HL7 FHIR R4",
  "description": "Healthcare resources — Patient, Encounter, Observation",
  "color": "#3498db",
  "icon": "fa-heartbeat",
  "version": "4.0.1",
  "source_url": "https://hl7.org/fhir/R4/",
  "tags": ["healthcare", "hl7", "regulation"],
  "tables": {
    "patient": [
      {"name": "id", "type": "UUID", "pk": true},
      {"name": "family_name", "type": "VARCHAR(100)"}
    ]
  }
}
```

---

## Further Reading

Full reference: [docs/templates/overview.md](../templates/overview.md)

---

## See also

- [Business Templates](Business-Templates)
- [Actor Pattern](Actor-Pattern)
- [ERD Designer](ERD-Designer)
- [CLI Reference](../api/cli.md)
- [Python API — TemplateRegistry](../api/python.md)
