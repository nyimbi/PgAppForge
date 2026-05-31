# Actor Pattern

[Home](Home) > Actor Pattern

The actor pattern is a first-class modelling concept in pgappforge. It names the primary domain entity — the thing everything else in a schema revolves around — and gives the code generator enough semantic information to produce human-readable labels, sensible view titles, and correct relationship navigations.

---

## Concept

An actor is not a user. It is a domain-level subject: a `patient` in healthcare, an `employee` in HR, a `customer` in e-commerce, a `contact` in CRM. Auth users optionally FK to actor records for login, but the two concepts are kept separate.

One primary actor per template. Additional actors are listed in `supporting[]`. Sub-roles (e.g. doctor vs. nurse within the same `practitioner` table) are filtered views, not separate tables.

---

## Detection from Table Comments

The ERD Designer and generator detect actor declarations by reading the PostgreSQL table comment as JSON:

```sql
COMMENT ON TABLE practitioner IS '{
  "pgaf_actor": {
    "type": "Practitioner",
    "display": {"singular": "Practitioner", "plural": "Practitioners", "icon": "fa-user-md"},
    "field_map": {"display_name": ["given_name", "family_name"], "status_field": "active"},
    "sub_roles": [
      {"name": "doctor", "filter_field": "qualification", "filter_value": "MD"},
      {"name": "nurse",  "filter_field": "qualification", "filter_value": "RN"}
    ]
  }
}';
```

Any table whose comment contains `"pgaf_actor"` is treated as an actor table. The ERD Designer renders it with a distinct icon.

---

## Template Declaration

Templates declare actors in JSON:

```json
{
  "name": "fhir-r4",
  "actor": {
    "type": "Patient",
    "display": {"singular": "Patient", "plural": "Patients", "icon": "fa-user"},
    "field_map": {
      "display_name": ["given_name", "family_name"],
      "status_field": "active",
      "status_map": {"true": "active", "false": "inactive"}
    }
  }
}
```

For templates with multiple actors use the `"actors"` array. The first entry with `"primary": true` is the primary actor.

---

## Key Classes

### `ActorConfig`

Parsed representation of an actor declaration. Attributes: `type`, `display` (`ActorDisplay`), `field_map` (`ActorFieldMap`), `sub_roles` (list of `ActorSubRole`).

### `ActorDisplay`

Human-readable labels: `singular`, `plural`, `icon`, `color`.

### `ActorFieldMap`

Maps canonical actor properties to actual column names: `display_name` (str or list), `contact_email`, `contact_phone`, `status_field`, `status_map`, `external_ids`.

### `ActorSubRole`

A filtered view of an actor table: `name`, `filter_field`, `filter_value`. Produces a separate navigation entry but reads from the same table.

### `ActorRegistry`

Singleton that holds all registered actors. Populated at startup by `TemplateRegistry.register_actors()`.

```python
from pgappforge.templates.core.actor import ActorRegistry

registry = ActorRegistry.instance()
all_actors = registry.all()         # {type_name: ActorConfig}
```

---

## How Generators Use Actors

When the model generator encounters an actor table, it:

1. Substitutes `display.singular` for the class docstring.
2. Replaces `field_map.display_name` columns with a `display_name` property.
3. Annotates the model with `ActorMixin` (adds `actor_type`, `actor_role` columns).
4. Generates sub-role views for each `ActorSubRole` entry.

The view generator uses `display.plural` for list view titles and `display.icon` for the menu icon.

---

## See also

- [Schema Templates](Schema-Templates)
- [Business Templates](Business-Templates)
- [ERD Designer](ERD-Designer)
- [Code Generator](Code-Generator)
- [Python API Reference](../api/python.md)
