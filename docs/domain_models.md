# Domain-Specific Schema Standards for pgappforge

Reference list of industry standards that pgappforge should support as importable schema templates (`flask forge templates import <name>`). Organized by domain with adoption, mandate status, and implementation priority.

**Priority legend:** 🔴 High (legal mandate or dominant adoption) | 🟡 Medium (strong industry standard) | 🟢 Lower (niche/growing)

---

## Healthcare & Life Sciences

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **HL7 FHIR R4** | 🔴 | ~150 clinical resource types (Patient, Encounter, Observation, Medication, Claim, Practitioner, Organization). Government-mandated in US (21st Century Cures Act), UK (NHS Digital), EU, Australia. JSONB-friendly — each resource maps to a PostgreSQL table with a JSONB `resource` column plus indexed top-level fields. | `flask forge templates import fhir-r4` |
| **HL7 LOINC** | 🟡 | 100,000+ coded clinical observations and lab results. Reference data table — not a full schema but required in any lab or clinical app. | Reference data import |
| **SNOMED CT** | 🟡 | Clinical terminology, 350,000+ concepts with hierarchy. Companion to FHIR for coded values. | Reference data import |
| **DICOM SR** | 🟡 | Medical imaging metadata — ~30 entity types for studies, series, and instances. Required for radiology/imaging apps. | `flask forge templates import dicom-sr` |

---

## Finance & Banking

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **ISO 20022** | 🔴 | Global financial messaging replacing SWIFT MT. US Fed migrated 2024, EU 2025. Covers payments (CreditTransfer, PaymentInitiation), securities, FX. Regulatory pressure on all banks. ~30 core message schemas. | `flask forge templates import iso20022` |
| **ACTUS** | 🔴 | Algorithmic Contract Types Unified Standards — mathematically rigorous taxonomy of all financial contract types (loans, bonds, derivatives, leases, annuities). 30+ contract types with precise cash flow algorithms. EU regulators pushing this for systemic risk reporting. | `flask forge templates import actus` |
| **XBRL + IFRS/GAAP Taxonomy** | 🔴 | SEC requires XBRL for public company financial filings. ~1,000 accounting concepts. Essential for any financial reporting or GL app. Taxonomies are free to download. | `flask forge templates import xbrl-ifrs` |
| **FIBO** | 🟡 | Financial Industry Business Ontology — ~10,000 financial concepts (EDM Council + OMG). Upper-layer entities (Currency, Organization, SecurityIdentifier) map directly to PostgreSQL. | Reference ontology |
| **ACORD** | 🔴 | Insurance data standard (~300 entities: Policy, Claim, Coverage, Risk). Every insurance app globally uses ACORD. Free for non-commercial use. | `flask forge templates import acord` |

---

## Supply Chain & Trade

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **GS1 / EPCIS 2.0** | 🔴 | Electronic Product Code Information Services — product identification (GTIN), location (GLN), event tracking (ObjectEvent, AggregationEvent, TransformationEvent). EU pharmaceutical supply chain mandate (FMD). Amazon, Walmart, most large retailers require GS1. | `flask forge templates import gs1-epcis` |
| **UN/CEFACT UBL** | 🔴 | Universal Business Language — OASIS standard for electronic business documents: Invoice, Order, DespatchAdvice, Catalogue. EU e-invoicing mandates in Italy, France, Germany, Spain (all 27 EU countries by 2028). Massive opportunity for invoice/ERP apps. | `flask forge templates import ubl-einvoice` |
| **Open Contracting (OCDS)** | 🔴 | WHO and ~70 governments publish procurement data in OCDS. ~20 entities (Tender, Award, Contract, Milestone, Amendment). Mandatory for many government procurement systems. | `flask forge templates import ocds` |

---

## Government & Public Sector

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **NIEM** | 🔴 | National Information Exchange Model — US government standard for inter-agency data exchange. ~2,000 data elements across Justice, Immigration, Emergency Management. Mandatory for many US federal contracts. | `flask forge templates import niem` |
| **INSPIRE** | 🔴 | EU spatial data infrastructure directive. ~30 geospatial themes (Addresses, Buildings, Transport Networks, Environmental zones). Required for any EU government geospatial app. | `flask forge templates import inspire` |
| **IATI** | 🟡 | International Aid Transparency Initiative — 1,500+ NGOs and governments publish aid data in IATI. ~15 entities (Activity, Budget, Transaction, Location). For any international development app. | `flask forge templates import iati` |
| **DCAT v3** | 🟡 | W3C Data Catalog Vocabulary — standard for publishing data catalogs. US data.gov, UK data.gov.uk, EU data.europa.eu all use DCAT. For data marketplace or catalog apps. | `flask forge templates import dcat` |
| **Schema.gov / Open311** | 🟢 | US government service request schema. For civic tech / 311 apps. | Reference |

---

## Human Resources

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **HR-Open Standards (PAPI)** | 🔴 | IEEE/ANSI-backed HR data standard. ~40 entities: Person, PositionOpening, Candidate, Assessment, Compensation. Genuinely cross-vendor — used for HR system integrations globally. Better than CDM for HR. | `flask forge templates import hr-open` |
| **IMS Global LTI** | 🟡 | Learning Tools Interoperability — for HR systems with training/LMS integration. Any corporate learning platform needs LTI. | Reference |

---

## Education

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **IMS Global QTI** | 🟡 | Question and Test Interoperability — ~20 entities for questions, tests, responses, rubrics. Used by every standardized testing platform. | `flask forge templates import qti` |
| **Open Badges / W3C Verifiable Credentials** | 🟡 | Digital credentials and certificates. Growing adoption for professional development and micro-credentialing apps. | `flask forge templates import open-badges` |
| **xAPI (Experience API)** | 🟡 | Learning analytics — Statement structure (Actor, Verb, Object, Result, Context). Used by US DoD and corporate training for learning analytics. | `flask forge templates import xapi` |

---

## Real Estate

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **RESO** | 🔴 | Real Estate Standards Organization — ~600 property attributes, ~50 entities (Property, Media, Member, Office, OpenHouse). Every MLS/real estate portal in North America. IDX compliance legally required in many US markets. | `flask forge templates import reso` |

---

## Legal & Compliance

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **Akoma Ntoso** | 🟡 | UN/EU standard for legislative and judicial documents. Used by EU Parliament, UN, national legislatures. For legal tech / regulatory compliance apps. | `flask forge templates import akoma-ntoso` |
| **SALI** | 🟡 | Standards Advancement for the Legal Industry — legal matter and billing codes. Growing adoption in law firms. | Reference |
| **STIX 2.1 / TAXII** | 🟡 | Cybersecurity threat intelligence — 18 entity types (ThreatActor, Indicator, Malware, Campaign). Used by every SIEM and threat intelligence platform. | `flask forge templates import stix` |

---

## Manufacturing & Industrial

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **OPC UA** | 🔴 | Dominant industrial automation data standard. Machines, sensors, production lines. Used by every IIoT platform (Siemens, Rockwell). High-value for Industry 4.0 apps. | `flask forge templates import opcua` |
| **ISO 15926** | 🟡 | Oil & gas / process plant lifecycle data. ~1,500 classes. Dominant in energy for plant information management. | Reference |
| **AutomationML** | 🟢 | Factory planning and engineering data exchange. Used by manufacturing digital twins. | Reference |

---

## Energy & Utilities

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **IEC CIM** | 🔴 | Common Information Model (IEC 61968/61970) — ~300 classes covering the electricity system (Generator, Line, Substation, Meter, Customer). Every electric utility worldwide uses CIM. NERC, ENTSO-E, and most regulators mandate it. | `flask forge templates import iec-cim` |
| **Green Button / ESPI** | 🟡 | Energy consumption data standard — 15 entities (UsagePoint, MeterReading, IntervalBlock). All US utilities must provide Green Button data. For energy analytics and smart home apps. | `flask forge templates import green-button` |

---

## Agriculture

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **ADAPT** | 🟡 | Agricultural Data Application Programming Toolkit — farm data standard from John Deere, AGCO, CNH. ~40 entities (Field, Crop, Operation, Machine, Recommendation). For precision agriculture apps. | `flask forge templates import adapt` |
| **FAO AgrInfo** | 🟢 | UN Food and Agriculture Organization data standards. For food security and agricultural statistics apps. | Reference |

---

## Environmental & Climate

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **OGC WaterML 2.0** | 🟡 | Water quality and hydrological data — ~20 entities (MonitoringPoint, ObservationProcess, MeasurementTimeSeries). For water management apps. | `flask forge templates import waterml` |
| **CF Conventions** | 🟢 | Climate and Forecast metadata for scientific atmospheric data. For climate analysis apps. | Reference |

---

## Geospatial

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **OGC CityGML 3.0** | 🟡 | 3D city model — ~50 feature types (Building, Bridge, Road, Vegetation, Water). Used for digital twins. Growing with smart city applications. | `flask forge templates import citygml` |
| **GTFS** | 🔴 | General Transit Feed Specification — transit schedules and maps. ~10 entities (Agency, Route, Stop, Trip). Every transit app worldwide uses GTFS. Cities legally required to publish GTFS in many jurisdictions. | `flask forge templates import gtfs` |

---

## Retail & E-commerce

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **Schema.org Commerce** | 🔴 | Google/Bing/Yahoo-backed semantic markup for products, offers, orders. Required for Google Shopping / rich results. Every e-commerce site needs this for SEO. | `flask forge templates import schema-org-commerce` |
| **ARTS** | 🟡 | Association for Retail Technology Standards — ~100 retail entities (Transaction, Item, RetailStore, POS). Used by large retailers for POS and inventory integrations. | Reference |

---

## IoT & Smart Systems

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **W3C WoT (Web of Things)** | 🟡 | Thing Description — standard for describing IoT devices and APIs. ~15 entities. Used by smart home, industrial IoT, building automation. | `flask forge templates import wot` |
| **FIWARE Smart Data Models** | 🟡 | EU-backed open data models for cities, agrifood, energy, environment. ~200+ models. Used by many EU smart city projects. | `flask forge templates import fiware` |
| **SAREF** | 🟢 | Smart Appliances Reference ontology (EU). ~40 entities. Required by some EU IoT regulations. | Reference |

---

## Telecoms

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **TM Forum Open API / SID** | 🔴 | Telecom industry — ~100+ entities (Customer, Product, Service, Resource, Party). Used by every telecom operator globally for BSS/OSS systems. | `flask forge templates import tmforum` |

---

## Scientific Research

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **DataCite Metadata** | 🟡 | Research data repository — ~15 metadata elements. Used by Zenodo, Figshare, DRYAD. For academic/research data management apps. | `flask forge templates import datacite` |
| **Darwin Core** | 🟢 | Biodiversity occurrence data — ~180 terms. Used by GBIF (global biodiversity database). For natural history, ecology, conservation apps. | `flask forge templates import darwin-core` |

---

## Identity & Security

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **SCIM 2.0** | 🔴 | System for Cross-domain Identity Management (RFC 7643/7644). ~5 core schemas (User, Group, EnterpriseUser). Every enterprise SSO system (Okta, Azure AD, Google Workspace) uses SCIM. | `flask forge templates import scim` |

---

## Social & Communication

| Standard | Priority | Description | Implementation |
|----------|----------|-------------|----------------|
| **ActivityPub / ActivityStreams 2.0** | 🟡 | W3C standard for federated social networks (Mastodon, Lemmy, PeerTube). ~20 activity types. For any social or community platform. | `flask forge templates import activitypub` |
| **vCard 4.0 + iCal** | 🟡 | RFC standards for contacts and calendar data. Interoperable with every phone/email client. For any CRM or scheduling app. | `flask forge templates import vcard-ical` |

---

## Implementation Roadmap

### Phase 1 — Regulatory mandates (must-have for specific markets)
1. **HL7 FHIR R4** — healthcare (US/EU/AU mandate)
2. **ISO 20022** — banking (global 2024-2026 migration)
3. **UN/CEFACT UBL** — EU e-invoicing (27 countries by 2028)
4. **GS1 / EPCIS 2.0** — pharma supply chain (EU FMD mandate)
5. **GTFS** — transit (legally required in many jurisdictions)
6. **SCIM 2.0** — enterprise identity (de-facto requirement)

### Phase 2 — Dominant industry standards
7. **RESO** — real estate (North America MLS)
8. **IEC CIM** — electric utilities (global)
9. **HR-Open Standards** — HR systems
10. **ACORD** — insurance
11. **OCDS** — government procurement
12. **Schema.org Commerce** — e-commerce / SEO

### Phase 3 — Growth markets
13. **W3C WoT** — IoT
14. **STIX 2.1** — cybersecurity
15. **ADAPT** — precision agriculture
16. **OPC UA** — industrial automation
17. **TM Forum SID** — telecoms

---

## Why NOT Microsoft CDM

CDM was designed for Dataverse (Microsoft's proprietary storage), carries Microsoft-centric naming conventions (`msdyn_` prefixes), and is not adopted outside the Microsoft ecosystem. The standards listed above are:

- Open/royalty-free (most are W3C, OASIS, ISO, or free-to-use industry standards)
- Actually adopted by the target industries
- Designed for real relational databases, not a vendor-specific CRM platform
- Maintained by standards bodies, not a single vendor

The domain-specific standards above will each unlock specific regulated industries where interoperability is legally required — a far stronger value proposition than general-purpose Microsoft compatibility.
