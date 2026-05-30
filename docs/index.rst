PgAppForge
==========

.. module:: pgappforge

**PostgreSQL-native application platform for Python/Flask.**

Build complete, production-ready web applications from your database schema —
with graph analytics, AI integration, security, and deployment tooling included.

.. code-block:: bash

   pip install pgappforge

   # Generate a complete app from any PostgreSQL database
   flask forge gen all postgresql://user:pass@localhost/mydb \
     --name MyApp --output-dir ./myapp/

.. note::

   PgAppForge is inspired by and acknowledges
   `Flask-AppBuilder <https://github.com/dpgaspar/Flask-AppBuilder>`_
   by Daniel Vaz Gaspar (BSD licence). PgAppForge adds PostgreSQL-native
   types, 55 domain schema templates, codegen, plugins, BPM, and more.

Getting Started
---------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickhowto
   quickminimal
   cli

Core Framework
--------------

.. toctree::
   :maxdepth: 2
   :caption: Core Framework

   config
   views
   rest_api
   relations
   actions
   advanced
   customizing

PostgreSQL & Schema Templates
-----------------------------

.. toctree::
   :maxdepth: 2
   :caption: PostgreSQL & Templates

   postgresql_types
   templates

Security & Auth
---------------

.. toctree::
   :maxdepth: 2
   :caption: Security

   security/security_architecture
   security/rbac_configuration
   security/mfa_configuration

Deployment
----------

.. toctree::
   :maxdepth: 2
   :caption: Deployment

   deployment/development_setup
   deployment/production_deployment
   deployment/cicd_setup
   deployment/SYSTEM_REQUIREMENTS

API Reference
-------------

.. toctree::
   :maxdepth: 1
   :caption: API Reference

   api
   api/core_api_reference
   api/models_api_reference

Other
-----

.. toctree::
   :maxdepth: 1
   :caption: Other

   addons
   diagrams
   breaking

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
