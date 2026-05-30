Schema Templates
================

PgAppForge ships 55 bundled domain schema templates covering healthcare, finance,
supply chain, geospatial, education, IoT, and more. Each template defines a
ready-to-use PostgreSQL schema with columns, descriptions, and required extensions.

.. code-block:: bash

   # List all templates
   flask forge templates list

   # Get details on a template
   flask forge templates info fhir-r4

   # Apply a template to your database (creates schema + tables)
   flask forge templates apply fhir-r4 -d postgresql:///mydb

   # Load reference data (where available)
   flask forge templates install-data icd10 -d postgresql:///mydb
   flask forge templates install-data geonames -d postgresql:///mydb

Template structure
------------------

Each template JSON defines:

- ``name`` / ``schema`` — PostgreSQL schema name (e.g. ``fhir_r4``)
- ``extensions`` — required PostgreSQL extensions (auto-installed on apply)
- ``tables`` — column definitions with type, constraints, and ``description``
- ``table_notes`` — per-table documentation
- ``short_description`` / ``long_description`` / ``when_to_use`` — guidance

Healthcare & Life Sciences
--------------------------

+------------------+---------------------------+--------+------------+
| Template         | Standard                  | Tables | Extensions |
+==================+===========================+========+============+
| fhir-r4          | HL7 FHIR R4               | 10     |            |
+------------------+---------------------------+--------+------------+
| icd10            | ICD-10-CM/PCS (CMS)       | 4      |            |
+------------------+---------------------------+--------+------------+
| loinc            | HL7 LOINC 2.78            | 4      | ltree      |
+------------------+---------------------------+--------+------------+
| snomed-ct        | SNOMED CT Int.            | 4      |            |
+------------------+---------------------------+--------+------------+
| dicom-sr         | DICOM Structured Reporting| 5      |            |
+------------------+---------------------------+--------+------------+

Finance & Banking
-----------------

+------------------+---------------------------+--------+
| Template         | Standard                  | Tables |
+==================+===========================+========+
| iso20022         | ISO 20022 Payments        | 4      |
+------------------+---------------------------+--------+
| fibo             | FIBO Financial Ontology   | 5      |
+------------------+---------------------------+--------+
| xbrl-ifrs        | XBRL / IFRS Reporting     | 4      |
+------------------+---------------------------+--------+
| acord            | ACORD Insurance           | 5      |
+------------------+---------------------------+--------+
| gleif            | GLEIF LEI                 | 2      |
+------------------+---------------------------+--------+
| actus            | ACTUS Financial Contracts | 4      |
+------------------+---------------------------+--------+

Geospatial & Smart Cities
--------------------------

+------------------+---------------------------+--------+------------+
| Template         | Standard                  | Tables | Extensions |
+==================+===========================+========+============+
| geonames         | GeoNames (CC-BY 4.0)      | 8      | postgis    |
+------------------+---------------------------+--------+------------+
| citygml          | CityGML 3.0               | 5      | postgis    |
+------------------+---------------------------+--------+------------+
| inspire          | EU INSPIRE                | 5      | postgis    |
+------------------+---------------------------+--------+------------+
| fiware           | FIWARE Smart Data Models  | 5      | postgis    |
+------------------+---------------------------+--------+------------+
| waterml          | WaterML Hydrology         | 4      | postgis    |
+------------------+---------------------------+--------+------------+

Supply Chain & Trade
--------------------

+------------------+---------------------------+--------+
| Template         | Standard                  | Tables |
+==================+===========================+========+
| gs1-epcis        | GS1 EPCIS 2.0             | 5      |
+------------------+---------------------------+--------+
| gs1-product      | GS1 Product Data          | 4      |
+------------------+---------------------------+--------+
| ubl-invoice      | OASIS UBL Invoice         | 4      |
+------------------+---------------------------+--------+

Government & Public Sector
--------------------------

+------------------+---------------------------+--------+
| Template         | Standard                  | Tables |
+==================+===========================+========+
| gtfs             | GTFS Transit              | 9      |
+------------------+---------------------------+--------+
| niem             | NIEM US Federal           | 5      |
+------------------+---------------------------+--------+
| ocds             | Open Contracting Data     | 6      |
+------------------+---------------------------+--------+
| open311          | Open311 Civic             | 4      |
+------------------+---------------------------+--------+
| dcat             | W3C DCAT                  | 4      |
+------------------+---------------------------+--------+
| inspire          | EU INSPIRE Directive      | 5      |
+------------------+---------------------------+--------+

Reference Data Loaders
----------------------

Some templates include data loaders that download reference data automatically:

.. code-block:: bash

   # ICD-10-CM/PCS — US CMS, public domain, auto-downloads
   flask forge templates apply icd10 -d postgresql:///mydb
   flask forge templates install-data icd10 -d postgresql:///mydb

   # GeoNames — CC-BY 4.0, auto-downloads (~1.5GB)
   flask forge templates apply geonames -d postgresql:///mydb
   flask forge templates install-data geonames -d postgresql:///mydb

   # LOINC — free after registration at loinc.org
   flask forge templates install-data loinc -d postgresql:///mydb \
     --data-dir ~/Downloads/loinc/

   # SNOMED CT — requires UMLS license
   flask forge templates install-data snomed-ct -d postgresql:///mydb \
     --data-dir ~/Downloads/SnomedCT_Release/

Adding custom templates
-----------------------

Place a JSON file matching the template format in ``.pgappforge/templates/``
in your project directory, or ``~/.pgappforge/templates/`` for user-global templates:

.. code-block:: bash

   flask forge templates install path/to/my-schema.json
   flask forge templates list  # appears as source=user
   flask forge templates apply my-schema -d postgresql:///mydb
