import datetime
import logging
import re

try:
    # Flask-SQLAlchemy 3.x (SQLAlchemy 2.x compatible)
    from flask_sqlalchemy import SQLAlchemy
    from sqlalchemy.orm import Session as SessionBase
    HAS_FLASK_SQLALCHEMY_3 = True
except ImportError:
    # Flask-SQLAlchemy 2.x (SQLAlchemy 1.x compatible)  
    from flask_sqlalchemy import (
        _QueryProperty,
        DefaultMeta,
        get_state,
        SessionBase,
        SignallingSession,
        SQLAlchemy,
    )
    HAS_FLASK_SQLALCHEMY_3 = False
from sqlalchemy import orm

try:
    from sqlalchemy.orm import as_declarative
except ImportError:
    try:
        from sqlalchemy.ext.declarative import as_declarative
    except ImportError:
        from sqlalchemy.ext.declarative.api import as_declarative

try:
    from sqlalchemy.orm.util import identity_key  # noqa

    has_identity_key = True
except ImportError:
    has_identity_key = False

log = logging.getLogger(__name__)

_camelcase_re = re.compile(r"([A-Z]+)(?=[a-z0-9])")


if HAS_FLASK_SQLALCHEMY_3:
    # Flask-SQLAlchemy 3.x uses different session base
    from sqlalchemy.orm import Session as _SessionBase
else:
    # Flask-SQLAlchemy 2.x 
    _SessionBase = SignallingSession

class CustomSignallingSession(_SessionBase):
    """
    Custom Signaling Session to support SQLALchemy>=1.4 with flask-sqlalchemy 2.X
    https://github.com/pallets/flask-sqlalchemy/issues/953
    """

    def get_bind(self, mapper=None, *args, **kwargs):
        """Return the engine or connection for a given model or
        table, using the ``__bind_key__`` if it is set.

        Patch from https://github.com/pallets/flask-sqlalchemy/pull/1001
        """
        # mapper is None if someone tries to just get a connection
        if mapper is not None:
            try:
                # SA >= 1.3
                persist_selectable = mapper.persist_selectable
            except AttributeError:
                # SA < 1.3
                persist_selectable = mapper.mapped_table
            info = getattr(persist_selectable, "info", {})
            bind_key = info.get("bind_key")
            if bind_key is not None:
                if HAS_FLASK_SQLALCHEMY_3:
                    # Flask-SQLAlchemy 3.x
                    return self.db.get_engine(bind_key=bind_key)
                else:
                    # Flask-SQLAlchemy 2.x
                    state = get_state(self.app)
                    return state.db.get_engine(self.app, bind=bind_key)
        return SessionBase.get_bind(self, mapper, *args, **kwargs)


class SQLA(SQLAlchemy):
    """
    This is a child class of flask_SQLAlchemy
    It's purpose is to override the declarative base of the original
    package. So that it is bound to F.A.B. Model class allowing the dev
    to be in the same namespace of the security tables (and others)
    and can use AuditMixin class alike.

    Use it and configure it just like flask_SQLAlchemy
    """

    def make_declarative_base(self, model, metadata=None):
        base = Model
        if not HAS_FLASK_SQLALCHEMY_3:
            # Flask-SQLAlchemy 2.x
            base.query = _QueryProperty(self)
        # Flask-SQLAlchemy 3.x doesn't use query property
        return base

    def get_tables_for_bind(self, bind=None):
        """Returns a list of all tables relevant for a bind."""
        result = []
        tables = Model.metadata.tables
        for key in tables:
            if tables[key].info.get("bind_key") == bind:
                result.append(tables[key])
        return result

    def create_all(self, bind_key="__all__", app=None):
        """Override Flask-SQLAlchemy create_all to use checkfirst=True.

        Without checkfirst=True, calling create_all after AppBuilder has already
        run _safe_create_all (which also calls create_all) raises DuplicateTable
        when both attempts try to create the same indexes in the same session.
        """
        Model.metadata.create_all(self.engine, checkfirst=True)

    def create_session(self, options):
        """
        Custom Session factory to support SQLALchemy>=1.4 with flask-sqlalchemy 2.X

        https://github.com/pallets/flask-sqlalchemy/issues/953

        :param options: dict of keyword arguments passed to session class
        """
        if HAS_FLASK_SQLALCHEMY_3:
            # Flask-SQLAlchemy 3.x uses a different session creation approach
            return super().create_session(options)
        else:
            # Flask-SQLAlchemy 2.x custom session
            return orm.sessionmaker(class_=CustomSignallingSession, db=self, **options)


if HAS_FLASK_SQLALCHEMY_3:
    # Flask-SQLAlchemy 3.x doesn't use DefaultMeta
    from sqlalchemy.orm import DeclarativeMeta
    _BaseMeta = DeclarativeMeta
else:
    # Flask-SQLAlchemy 2.x
    _BaseMeta = DefaultMeta

class ModelDeclarativeMeta(_BaseMeta):
    """
    Base Model declarative meta for all Models definitions.
    Setups bind_keys to support multiple databases.
    Setup the table name based on the class camelcase name.
    """

    def __new__(cls, name, bases, namespace, **kwargs):
        # Auto-generate table name from class name if not specified
        if (
            "__tablename__" not in namespace 
            and name != "Model"  # Skip the base Model class
            and not namespace.get("__abstract__", False)
        ):
            # Convert CamelCase to snake_case
            table_name = _camelcase_re.sub(r"_\1", name).lower().lstrip("_")
            namespace["__tablename__"] = table_name
            
        return super().__new__(cls, name, bases, namespace, **kwargs)


@as_declarative(name="Model", metaclass=ModelDeclarativeMeta)
class Model(object):
    """
    Use this class has the base for your models,
    it will define your table names automatically
    MyModel will be called my_model on the database.

    ::

        from sqlalchemy import Integer, String
        from pgappforge import Model

        class MyModel(Model):
            id = Column(Integer, primary_key=True)
            name = Column(String(50), unique = True, nullable=False)

    """

    __table_args__ = {"extend_existing": True}

    def to_json(self):
        result = dict()
        for key in self.__mapper__.c.keys():
            col = getattr(self, key)
            if isinstance(col, datetime.datetime) or isinstance(col, datetime.date):
                col = col.isoformat()
            result[key] = col
        return result


"""
    This is for retro compatibility
"""
Base = Model
