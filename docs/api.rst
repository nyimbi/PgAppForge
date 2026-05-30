=============
API Reference
=============

pgforge
====================

AppBuilder
----------

.. automodule:: pgforge.base

    .. autoclass:: AppBuilder
        :members:

        .. automethod:: __init__

pgforge.security.decorators
========================================

.. automodule:: pgforge.security.decorators

    .. autofunction:: protect
    .. autofunction:: has_access
    .. autofunction:: permission_name

pgforge.models.decorators
========================================

.. automodule:: pgforge.models.decorators

    .. autofunction:: renders

pgforge.hooks
======================
.. automodule:: pgforge.hooks

    .. autofunction:: before_request

pgforge.api
==============================

.. automodule:: pgforge.api

    .. autofunction:: expose
    .. autofunction:: rison
    .. autofunction:: safe

BaseApi
-------

.. autoclass:: BaseApi
    :members:

ModelRestApi
------------

.. autoclass:: ModelRestApi
    :members:

pgforge.baseviews
==============================

.. automodule:: pgforge.baseviews

    .. autofunction:: expose

BaseView
--------

.. autoclass:: BaseView
    :members:

BaseFormView
------------

.. autoclass:: BaseFormView
    :members:

BaseModelView
-------------

.. autoclass:: BaseModelView
    :members:

BaseCRUDView
------------

.. autoclass:: BaseCRUDView
    :members:

pgforge.views
==========================

.. automodule:: pgforge.views

IndexView
---------

.. autoclass:: IndexView
    :members:

SimpleFormView
--------------

.. autoclass:: SimpleFormView
    :members:

PublicFormView
--------------

.. autoclass:: PublicFormView
    :members:

ModelView
-----------

.. autoclass:: ModelView
    :members:

MultipleView
----------------

.. autoclass:: MultipleView
    :members:

MasterDetailView
----------------

.. autoclass:: MasterDetailView
    :members:

CompactCRUDMixin
----------------

.. autoclass:: CompactCRUDMixin
    :members:

pgforge.actions
============================

.. automodule:: pgforge.actions

    .. autofunction:: action

pgforge.security
=============================

.. automodule:: pgforge.security.manager

BaseSecurityManager
-------------------

.. autoclass:: BaseSecurityManager
    :members:

BaseRegisterUser
----------------

.. automodule:: pgforge.security.registerviews

    .. autoclass:: BaseRegisterUser
        :members:

pgforge.filemanager
================================

.. automodule:: pgforge.filemanager

    .. autofunction:: get_file_original_name

Aggr Functions for Group By Charts
==================================

.. automodule:: pgforge.models.group

    .. autofunction:: aggregate_count
    .. autofunction:: aggregate_avg
    .. autofunction:: aggregate_sum

pgforge.charts.views
=================================

.. automodule:: pgforge.charts.views

BaseChartView
-------------

.. autoclass:: BaseChartView
    :members:

DirectByChartView
-----------------

.. autoclass:: DirectByChartView
    :members:

GroupByChartView
----------------

.. autoclass:: GroupByChartView
    :members:

(Deprecated) ChartView
----------------------

.. autoclass:: ChartView
    :members:

(Deprecated) TimeChartView
--------------------------

.. autoclass:: TimeChartView
    :members:

(Deprecated) DirectChartView
----------------------------

.. autoclass:: DirectChartView
    :members:


pgforge.models.mixins
==================================

.. automodule:: pgforge.models.mixins

    .. autoclass:: BaseMixin
        :members:

    .. autoclass:: AuditMixin
        :members:

Extra Columns
-------------

.. autoclass:: FileColumn
    :members:

.. autoclass:: ImageColumn
    :members:

Generic Data Source (Beta)
--------------------------

pgforge.models.generic
===================================

.. automodule:: pgforge.models.generic

    .. autoclass:: GenericColumn
        :members:

    .. autoclass:: GenericModel
        :members:

    .. autoclass:: GenericSession
        :members:
