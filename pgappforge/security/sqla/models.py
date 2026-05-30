import datetime

from flask import g
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Table,
    UniqueConstraint,
)
try:
    from sqlalchemy.orm import declared_attr
except ImportError:
    from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import backref, relationship

from ... import Model
from ..._compat import as_unicode

_dont_audit = False


class Permission(Model):
    __tablename__ = "ab_permission"
    id = Column(Integer, Sequence("ab_permission_id_seq"), primary_key=True)
    name = Column(String(100), unique=True, nullable=False)

    def __repr__(self):
        return self.name


class ViewMenu(Model):
    __tablename__ = "ab_view_menu"
    id = Column(Integer, Sequence("ab_view_menu_id_seq"), primary_key=True)
    name = Column(String(250), unique=True, nullable=False)

    def __eq__(self, other):
        return (isinstance(other, self.__class__)) and (self.name == other.name)

    def __neq__(self, other):
        return self.name != other.name

    def __repr__(self):
        return self.name


assoc_permissionview_role = Table(
    "ab_permission_view_role",
    Model.metadata,
    Column("id", Integer, Sequence("ab_permission_view_role_id_seq"), primary_key=True),
    Column(
        "permission_view_id",
        Integer,
        ForeignKey("ab_permission_view.id", ondelete="CASCADE"),
    ),
    Column("role_id", Integer, ForeignKey("ab_role.id", ondelete="CASCADE")),
    UniqueConstraint("permission_view_id", "role_id"),
    Index("idx_permission_view_id", "permission_view_id"),
    Index("idx_role_id", "role_id"),
)


class Role(Model):
    __tablename__ = "ab_role"

    id = Column(Integer, Sequence("ab_role_id_seq"), primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    permissions = relationship(
        "PermissionView",
        secondary=assoc_permissionview_role,
        backref="role",
        passive_deletes=True,
    )

    def __repr__(self):
        return self.name


class PermissionView(Model):
    __tablename__ = "ab_permission_view"
    __table_args__ = (
        UniqueConstraint("permission_id", "view_menu_id"),
        Index("idx_permission_id", "permission_id"),
        Index("idx_view_menu_id", "view_menu_id"),
    )
    id = Column(Integer, Sequence("ab_permission_view_id_seq"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("ab_permission.id"))
    permission = relationship("Permission", lazy="joined")
    view_menu_id = Column(Integer, ForeignKey("ab_view_menu.id"))
    view_menu = relationship("ViewMenu", lazy="joined")

    def __repr__(self):
        return str(self.permission).replace("_", " ") + " on " + str(self.view_menu)


assoc_user_role = Table(
    "ab_user_role",
    Model.metadata,
    Column("id", Integer, Sequence("ab_user_role_id_seq"), primary_key=True),
    Column("user_id", Integer, ForeignKey("ab_user.id", ondelete="CASCADE")),
    Column("role_id", Integer, ForeignKey("ab_role.id", ondelete="CASCADE")),
    UniqueConstraint("user_id", "role_id"),
)


class User(Model):
    __tablename__ = "ab_user"
    id = Column(Integer, Sequence("ab_user_id_seq"), primary_key=True)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(256))
    active = Column(Boolean)
    email = Column(String(320), unique=True, nullable=False)
    last_login = Column(DateTime)
    login_count = Column(Integer)
    fail_login_count = Column(Integer)
    roles = relationship(
        "Role", secondary=assoc_user_role, backref="user", passive_deletes=True
    )
    created_on = Column(
        DateTime, default=lambda: datetime.datetime.now(), nullable=True
    )
    changed_on = Column(
        DateTime, default=lambda: datetime.datetime.now(), nullable=True
    )

    @declared_attr
    def created_by_fk(self):
        return Column(
            Integer, ForeignKey("ab_user.id"), default=self.get_user_id, nullable=True
        )

    @declared_attr
    def changed_by_fk(self):
        return Column(
            Integer, ForeignKey("ab_user.id"), default=self.get_user_id, nullable=True
        )

    created_by = relationship(
        "User",
        backref=backref("created", uselist=True),
        remote_side=[id],
        primaryjoin="User.created_by_fk == User.id",
        uselist=False,
    )
    changed_by = relationship(
        "User",
        backref=backref("changed", uselist=True),
        remote_side=[id],
        primaryjoin="User.changed_by_fk == User.id",
        uselist=False,
    )

    @classmethod
    def get_user_id(cls):
        try:
            return g.user.id
        except Exception:
            return None

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return self.active

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return as_unicode(self.id)

    def get_full_name(self):
        return "{0} {1}".format(self.first_name, self.last_name)
    
    # Association-based relationships (clean separation of concerns)
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # Convenience methods for wallet integration (delegates to profile)
    def has_wallet(self):
        """Check if user has a wallet profile with linked wallet"""
        return self.profile and self.profile.has_wallet()
    
    def is_wallet_verified(self):
        """Check if user's wallet is verified"""
        return self.profile and self.profile.is_wallet_verified()
    
    def get_wallet_info(self):
        """Get comprehensive wallet information"""
        return self.profile.get_wallet_info() if self.profile else None
    
    def has_mpesa_account(self):
        """Check if user has any MPESA accounts"""
        return self.profile and self.profile.has_mpesa_account()
    
    def get_verified_mpesa_accounts(self):
        """Get user's verified MPESA accounts"""
        return self.profile.get_verified_mpesa_accounts() if self.profile else []
    
    def get_or_create_profile(self):
        """Get or create user profile"""
        if not self.profile:
            self.profile = UserProfile(user_id=self.id)
        return self.profile

    def __repr__(self):
        return self.get_full_name()


assoc_user_group = Table(
    "ab_user_group",
    Model.metadata,
    Column("id", Integer, Sequence("ab_user_group_id_seq"), primary_key=True),
    Column("user_id", Integer, ForeignKey("ab_user.id", ondelete="CASCADE")),
    Column("group_id", Integer, ForeignKey("ab_group.id", ondelete="CASCADE")),
    UniqueConstraint("user_id", "group_id"),
    Index("idx_user_id", "user_id"),
    Index("idx_user_group_id", "group_id"),
)


assoc_group_role = Table(
    "ab_group_role",
    Model.metadata,
    Column("id", Integer, Sequence("ab_group_role_id_seq"), primary_key=True),
    Column("group_id", Integer, ForeignKey("ab_group.id", ondelete="CASCADE")),
    Column("role_id", Integer, ForeignKey("ab_role.id", ondelete="CASCADE")),
    UniqueConstraint("group_id", "role_id"),
    Index("idx_group_id", "group_id"),
    Index("idx_group_role_id", "role_id"),
)


class Group(Model):
    __tablename__ = "ab_group"
    id = Column(Integer, Sequence("ab_group_id_seq"), primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    label = Column(String(150))
    description = Column(String(512))
    users = relationship(
        "User", secondary=assoc_user_group, backref="groups", passive_deletes=True
    )
    roles = relationship(
        "Role", secondary=assoc_group_role, backref="groups", passive_deletes=True
    )

    def __repr__(self):
        return self.name


class RegisterUser(Model):
    __tablename__ = "ab_register_user"
    id = Column(Integer, Sequence("ab_register_user_id_seq"), primary_key=True)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(256))
    email = Column(String(64), nullable=False)
    registration_date = Column(DateTime, default=datetime.datetime.now, nullable=True)
    registration_hash = Column(String(256))


class UserProfile(Model):
    """Extended user profile for wallet, M-Pesa, and other integrations.
    
    This model follows the association pattern to keep core User model clean
    while providing extended functionality through composition.
    """
    __tablename__ = "ab_user_profile"
    __table_args__ = (
        Index('idx_user_profile_wallet_address', 'wallet_address'),
        Index('idx_user_profile_user_id', 'user_id'),
    )
    
    id = Column(Integer, Sequence("ab_user_profile_id_seq"), primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False, unique=True)
    
    # Wallet integration fields
    wallet_address = Column(String(128), unique=True, nullable=True, index=True)
    wallet_type = Column(String(50), nullable=True)  # e.g., 'metamask', 'coinbase', 'walletconnect'
    wallet_provider = Column(String(100), nullable=True)
    wallet_verified = Column(Boolean, default=False, nullable=False)
    wallet_verification_date = Column(DateTime, nullable=True)
    wallet_metadata = Column(String(1024), nullable=True)  # JSON metadata for wallet info
    
    # Process engine preferences
    process_preferences = Column(String(2048), nullable=True)  # JSON preferences
    
    # Audit fields
    created_on = Column(DateTime, default=lambda: datetime.datetime.now(), nullable=True)
    changed_on = Column(DateTime, default=lambda: datetime.datetime.now(), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="profile")
    # wallet and mpesa_accounts relationships removed: wallet models have a SQLAlchemy
    # naming conflict (metadata hybrid_property) that prevents mapper configuration.
    
    # Wallet integration methods
    def has_wallet(self):
        """Check if profile has a linked wallet"""
        return bool(self.wallet_address)
    
    def is_wallet_verified(self):
        """Check if profile's wallet is verified"""
        return self.wallet_verified and self.wallet_address
    
    def link_wallet(self, address, wallet_type, provider=None, metadata=None):
        """Link a wallet to the user profile"""
        import json
        self.wallet_address = address
        self.wallet_type = wallet_type
        self.wallet_provider = provider
        self.wallet_verified = False  # Requires verification
        self.wallet_verification_date = None
        if metadata:
            self.wallet_metadata = json.dumps(metadata)
        self.changed_on = datetime.datetime.now()
        
    def verify_wallet(self):
        """Mark wallet as verified"""
        self.wallet_verified = True
        self.wallet_verification_date = datetime.datetime.now()
        self.changed_on = datetime.datetime.now()
        
    def unlink_wallet(self):
        """Remove wallet from user profile"""
        self.wallet_address = None
        self.wallet_type = None
        self.wallet_provider = None
        self.wallet_verified = False
        self.wallet_verification_date = None
        self.wallet_metadata = None
        self.changed_on = datetime.datetime.now()
        
    def get_wallet_metadata(self):
        """Get wallet metadata as dict"""
        if self.wallet_metadata:
            import json
            try:
                return json.loads(self.wallet_metadata)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def get_wallet_info(self):
        """Get comprehensive wallet information"""
        if not self.has_wallet():
            return None
            
        return {
            'address': self.wallet_address,
            'type': self.wallet_type,
            'provider': self.wallet_provider,
            'verified': self.wallet_verified,
            'verification_date': self.wallet_verification_date.isoformat() if self.wallet_verification_date else None,
            'metadata': self.get_wallet_metadata()
        }
    
    # M-Pesa integration methods
    def has_mpesa_account(self):
        """Check if profile has any MPESA accounts (wallet module must be separately imported)."""
        return False
    
    def get_verified_mpesa_accounts(self):
        """Get profile's verified MPESA accounts (wallet module must be separately imported)."""
        return []
    
    def get_primary_wallet(self):
        """Get user's primary wallet (wallet module must be separately imported)."""
        return None
    
    def get_process_preferences(self):
        """Get process engine preferences as dict"""
        if self.process_preferences:
            import json
            try:
                return json.loads(self.process_preferences)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def set_process_preferences(self, preferences):
        """Set process engine preferences"""
        import json
        self.process_preferences = json.dumps(preferences) if preferences else None
        self.changed_on = datetime.datetime.now()
    
    def __repr__(self):
        return f"<UserProfile(id={self.id}, user_id={self.user_id}, wallet={bool(self.wallet_address)})>"


# Import MFA models when MFA is enabled
try:
    from ..mfa.models import UserMFA, MFABackupCodes, MFAVerificationAttempt, MFAPolicy
    __all__ = ['Permission', 'ViewMenu', 'PermissionView', 'Role', 'User', 'Group', 'RegisterUser', 'UserProfile',
               'UserMFA', 'MFABackupCodes', 'MFAVerificationAttempt', 'MFAPolicy', 'assoc_permissionview_role']
except ImportError:
    # MFA models not available, proceed without them
    __all__ = ['Permission', 'ViewMenu', 'PermissionView', 'Role', 'User', 'Group', 'RegisterUser', 'UserProfile', 'assoc_permissionview_role']

