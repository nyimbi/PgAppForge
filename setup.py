import io
import os
import re

from setuptools import find_packages, setup


with io.open("pgappforge/__init__.py", "rt", encoding="utf8") as f:
    version = re.search(r"__version__ = \"(.*?)\"", f.read()).group(1)


def fpath(name):
    return os.path.join(os.path.dirname(__file__), name)


def read(fname):
    return open(fpath(fname)).read()


def desc():
    return read("README.rst")


setup(
    name="pgappforge",
    version=version,
    url="https://github.com/dpgaspar/flask-appbuilder/",
    license="BSD",
    author="Daniel Vaz Gaspar",
    author_email="danielvazgaspar@gmail.com",
    description=(
        "Enhanced application development framework, built on top of Flask."
        " Includes detailed security, auto CRUD generation, advanced analytics dashboards,"
        " multi-format data export (CSV/Excel/PDF), alerting system, MFA authentication,"
        " customizable widgets, and comprehensive business intelligence tools."
    ),
    long_description=desc(),
    long_description_content_type="text/x-rst",
    packages=find_packages(exclude=["tests*"]),
    package_data={"": ["LICENSE"]},
    entry_points={
        "flask.commands": ["forge=pgappforge.cli:fab"],
        "console_scripts": ["pgappforge = pgappforge.console:cli"],
    },
    include_package_data=True,
    zip_safe=False,
    platforms="any",
    install_requires=[
        "apispec[yaml]>=6.0.0, <7",
        "colorama>=0.3.9, <1",
        "click>=8, <9",
        "cryptography>=3.4.8, <5.0.0",  # Required for MFA encryption
        "email_validator>=1.0.5",
        "Flask>=2, <4",
        "Flask-Babel>=4.0.0, <5",
        "Flask-Limiter>3,<4",
        "Flask-Login>=0.3, <0.7",
        "Flask-SQLAlchemy>=2.5, <4",
        "Flask-WTF>=0.14.2, <2",
        "Flask-JWT-Extended>=4.0.0, <5.0.0",
        "jsonschema>=3, <5",
        "marshmallow>=3.18.0, <5",
        "marshmallow-sqlalchemy>=0.22.0, <3.0.0",
        "pyotp>=2.9.0, <3.0.0",  # Required for MFA TOTP functionality
        "python-dateutil>=2.3, <3",
        "prison>=0.2.1, <1.0.0",
        "PyJWT>=2.0.0, <3.0.0",
        "sqlalchemy-utils>=0.32.21, <1",
        "WTForms<4",
        "werkzeug<4",
        "itsdangerous>=1.1.0, <3.0.0",  # Required for tenant email verification
        "inflect>=7.0.0, <8",
        "bleach>=6.0.0",  # XSS sanitisation for widgets
        "psycopg2-binary>=2.9.0",  # PostgreSQL only
    ],
    extras_require={
        "jmespath": ["jmespath>=0.9.5"],
        "mfa": [
            "Flask-Mail>=0.9.1, <1.0.0",   # Email MFA functionality
            "Pillow>=8.0.0, <12.0.0",      # Image processing for QR codes
            "qrcode[pil]>=7.0.0, <9.0.0",  # QR code generation with Pillow
            "twilio>=8.0.0, <11.0.0",      # SMS via Twilio (optional)
            "boto3>=1.26.0, <3.0.0",       # AWS SNS SMS (optional)
        ],
        "export": [
            "openpyxl>=3.0.0, <4.0.0",     # Excel (XLSX) export functionality
            "reportlab>=3.6.0, <5.0.0",    # PDF generation and export
            "xlsxwriter>=3.0.0, <4.0.0",   # Alternative Excel writer (better formatting)
            "python-docx>=0.8.11, <2.0.0", # Word document generation (optional)
            "Pillow>=8.0.0, <12.0.0",      # Image processing for PDF exports
        ],
        "billing": [
            "stripe>=7.0.0, <9.0.0",       # Stripe payment processing for multi-tenant billing
        ],
        "analytics": [
            "pandas>=1.5.0, <3.0.0",       # Data analysis for dashboard widgets
            "numpy>=1.21.0, <2.0.0",       # Numerical computing for metrics
            "matplotlib>=3.5.0, <4.0.0",   # Chart generation for dashboards
            "seaborn>=0.11.0, <1.0.0",     # Statistical visualization (optional)
        ],
        "oauth": ["Authlib>=0.14, <2.0.0"],
        "openid": ["Flask-OpenID>=1.2.5, <2"],
        "talisman": ["flask-talisman>=1.0.0, <2.0"],
        "speech": [
            "faster-whisper>=1.0.0",           # Local STT — CTranslate2 Whisper
            "supertone-tts>=0.1.0",             # Supertonic neural TTS (optional)
            "TTS>=0.22.0",                       # Coqui TTS fallback
            "pyttsx3>=2.90",                     # Lightweight offline TTS fallback
        ],
        "ai": [
            "openai>=1.0.0, <2.0.0",           # OpenAI GPT models
            "anthropic>=0.7.0, <1.0.0",        # Anthropic Claude models
            "google-generativeai>=0.3.0, <1.0.0",  # Google Gemini models
            "groq>=0.4.0, <1.0.0",             # Groq fast inference
            "ollama-python>=0.1.0, <1.0.0",    # Ollama local models
            "huggingface-hub>=0.17.0, <1.0.0", # HuggingFace models
            "transformers>=4.21.0, <5.0.0",    # Transformers for speech processing
            "speechrecognition>=3.10.0, <4.0.0",  # Speech-to-text
            "pydub>=0.25.0, <1.0.0",           # Audio processing
            "torch>=1.13.0, <3.0.0",           # PyTorch for local AI models
            "soundfile>=0.12.0, <1.0.0",       # Audio file handling
        ],
        "collaborative": [
            "redis>=4.5.0, <6.0.0",            # Redis for real-time features
            "flask-socketio>=5.3.0, <6.0.0",   # WebSocket support
            "python-socketio>=5.8.0, <6.0.0",  # SocketIO client/server
            "python-engineio>=4.7.0, <5.0.0",  # Engine.IO transport
            "eventlet>=0.33.0, <1.0.0",        # Async networking for SocketIO
        ],
        "dev": [
            "nose2==0.14.0",                   # Testing framework
            "mockldap>=0.3.0",                 # LDAP testing
            "hiro>=0.5.1",                     # Time mocking for tests
            "flake8>=6.0.0, <7.0.0",          # Code linting
            "black>=23.0.0, <24.0.0",         # Code formatting
            "mypy>=1.0.0, <2.0.0",            # Type checking
            "pytest>=7.0.0, <8.0.0",          # Alternative testing framework
            "pytest-cov>=4.0.0, <5.0.0",      # Coverage reporting
            "pre-commit>=3.0.0, <4.0.0",      # Git hooks
        ],
    },
    tests_require=["nose2==0.14.0", "mockldap>=0.3.0", "hiro>=0.5.1"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.12",
    test_suite="nose.collector",
)
