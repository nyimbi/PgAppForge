# 🚀 QuickStart Tutorial: Build Your First Workflow in 10 Minutes

Welcome to the JHipster-inspired Flask-AppBuilder Workflow System! This tutorial will guide you through creating your first complete workflow application in just 10 minutes.

## 🎯 What We'll Build

We'll create a **Product Review Workflow** that demonstrates:
- ✅ Multi-step form workflow
- ✅ Role-based permissions
- ✅ File uploads
- ✅ Approval process
- ✅ Complete CRUD operations

## 📋 Prerequisites

- Python 3.8+ installed
- Flask-AppBuilder knowledge (basic)
- 10 minutes of your time!

## 🏃‍♂️ Step 1: Setup (2 minutes)

### Install Flask-AppBuilder

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Flask-AppBuilder (includes workflow system)
pip install flask-appbuilder
```

### Verify Installation

```bash
# Check if workflow commands are available
flask fab workflow --help
```

You should see workflow generation commands available.

## 🎨 Step 2: Create Workflow Definition (3 minutes)

Create a file called `product_review.yaml`:

```yaml
ProductReview:
  version: "1.0.0"
  description: "Product review and approval workflow"
  
  # Define our data models
  entities:
    Product: existing  # Reference existing Product model
    Review:           # New Review model we'll generate
      fields:
        - title: {type: string, required: true, validation: {minLength: 5, maxLength: 100}}
        - content: {type: textarea, required: true, validation: {minLength: 20}}
        - rating: {type: select, required: true, choices: [["1", "⭐"], ["2", "⭐⭐"], ["3", "⭐⭐⭐"], ["4", "⭐⭐⭐⭐"], ["5", "⭐⭐⭐⭐⭐"]]}
        - reviewer_email: {type: email, required: true}
        - images: {type: file, required: false, accept: [".jpg", ".png", ".gif"]}
        - status: {type: select, choices: [["draft", "Draft"], ["submitted", "Submitted"], ["approved", "Approved"], ["rejected", "Rejected"]], default: "draft"}
        - submitted_at: {type: datetime, default: now}
  
  # Define workflow steps
  steps:
    WriteReview:
      title: "Write Review"
      description: "Share your experience with this product"
      icon: "edit"
      estimatedTime: "5 minutes"
      fields:
        - title: {type: string, required: true, placeholder: "Brief review title"}
        - content: {type: textarea, required: true, rows: 5, placeholder: "Tell us about your experience..."}
        - rating: {type: select, required: true}
        - reviewer_email: {type: email, required: true, placeholder: "your@email.com"}
        - images: {type: file, required: false, description: "Upload product photos (optional)"}
    
    ModerateReview:
      title: "Review Moderation"
      description: "Moderate submitted reviews for approval"
      icon: "check-circle"
      estimatedTime: "2 minutes"
      permissions:
        view: ["moderator", "admin"]
        edit: ["moderator", "admin"]
      fields:
        - moderation_notes: {type: textarea, required: false, rows: 3, placeholder: "Internal moderation notes..."}
        - approval_decision: {type: select, required: true, choices: [["approve", "✅ Approve"], ["reject", "❌ Reject"], ["needs_changes", "📝 Needs Changes"]]}
        - feedback_to_reviewer: {type: textarea, required: false, rows: 2, placeholder: "Feedback for the reviewer (optional)"}
  
  # Define permissions
  permissions:
    WriteReview:
      view: ["public", "user", "moderator", "admin"]
      edit: ["user", "moderator", "admin"]
    ModerateReview:
      view: ["moderator", "admin"]
      edit: ["moderator", "admin"]
  
  # Configure features
  features:
    auto_save: true
    auto_save_interval: 30
    file_upload: true
    max_file_size: 5242880  # 5MB
    allowed_extensions: ["jpg", "jpeg", "png", "gif"]
    comments: true
  
  # Email notifications
  notifications:
    email:
      enabled: true
      templates:
        step_completed: "Review '{review.title}' has been {step.title}"
        approval_needed: "Review moderation needed for '{review.title}'"
        workflow_completed: "Review '{review.title}' has been published"
  
  # Security settings
  security:
    auth_type: "AUTH_DB"
    audit: true
    admin_role: "Admin"
    public_role: "Public"
```

## ⚡ Step 3: Generate Application Code (1 minute)

Now let's generate our complete Flask-AppBuilder application:

```bash
# Validate our workflow first
flask fab workflow validate product_review.yaml

# Generate the complete application
flask fab workflow generate product_review.yaml --app-name review_app --verbose
```

You should see output like:
```
🚀 JHipster-inspired Flask-AppBuilder Workflow Generation
============================================================
📋 Workflow: Product review and approval workflow
📦 Version: 1.0.0

📋 Generation Plan:
   • Models: 1
   • Views: 2
   • Forms: 2
   • Templates: 2
   • API endpoints: 1
   • Tests: 1
   • Migrations: 1

🏗️  Generating Flask-AppBuilder application...

✅ Generation completed successfully!
📁 Generated 14 files:
   📂 models:
      • review_model.py
   📂 views:
      • writereview_view.py
      • moderatereview_view.py
   📂 forms:
      • writereview_form.py
      • moderatereview_form.py
   📂 templates:
      • writereview.html
      • moderatereview.html
   📂 api:
      • workflow_api.py
   📂 tests:
      • test_product_review.py
   📂 migrations:
      • 001_product_review.py
```

## 🔧 Step 4: Integration with Flask-AppBuilder (2 minutes)

Now let's create a simple Flask-AppBuilder application and integrate our generated workflow:

### Create Basic App Structure

```bash
# Create app directory
mkdir review_app
cd review_app

# Create basic Flask-AppBuilder structure
mkdir app
mkdir app/static
mkdir app/templates
```

### Create `config.py`:

```python
import os
from flask_appbuilder.security.manager import AUTH_DB

basedir = os.path.abspath(os.path.dirname(__file__))

# Database configuration
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'app.db')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Security configuration
SECRET_KEY = 'your-secret-key-here-change-in-production'
AUTH_TYPE = AUTH_DB

# File upload configuration
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

# Workflow configuration
WTF_CSRF_ENABLED = True
```

### Create `app/__init__.py`:

```python
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA
from flask_appbuilder.menu import Menu

# Import generated models
from .models.review_model import Review

# Import generated views
from .views.writereview_view import WriteReviewView
from .views.moderatereview_view import ModerateReviewView

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Initialize AppBuilder
appbuilder = AppBuilder(app, db.session)

# Register generated views
appbuilder.add_view(
    WriteReviewView,
    "Write Review",
    icon="fa-edit",
    category="Product Reviews"
)

appbuilder.add_view(
    ModerateReviewView,
    "Moderate Reviews", 
    icon="fa-check-circle",
    category="Product Reviews"
)

from . import views
```

### Create `app/views.py`:

```python
from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface
from . import appbuilder, db
from .models.review_model import Review

# Basic view for all reviews (optional)
class ReviewView(ModelView):
    datamodel = SQLAInterface(Review)
    list_columns = ['title', 'rating', 'status', 'submitted_at', 'reviewer_email']
    show_columns = ['title', 'content', 'rating', 'reviewer_email', 'status', 'submitted_at']
    search_columns = ['title', 'content', 'reviewer_email']

# Register the basic review view (optional)
appbuilder.add_view(
    ReviewView,
    "All Reviews",
    icon="fa-list",
    category="Product Reviews"
)
```

### Create `run.py`:

```python
from app import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
```

## 🚀 Step 5: Run Your Application (2 minutes)

### Initialize Database and Create Admin User

```bash
# Set Flask app
export FLASK_APP=run.py  # On Windows: set FLASK_APP=run.py

# Initialize database
flask db upgrade

# Create admin user
flask fab create-admin
# Follow prompts to create your admin user
```

### Run the Application

```bash
python run.py
```

Visit `http://localhost:8080` and login with your admin credentials!

## 🎉 Step 6: Test Your Workflow

### 1. **Write a Review**
- Navigate to "Product Reviews" → "Write Review"
- Fill out the form with a sample review
- Upload an image (optional)
- Submit the review

### 2. **Moderate the Review**
- Navigate to "Product Reviews" → "Moderate Reviews"
- Find your submitted review
- Add moderation notes
- Approve or reject the review

### 3. **View All Reviews**
- Navigate to "Product Reviews" → "All Reviews"
- See all reviews with their current status

## 🔍 What You Just Built

In just 10 minutes, you created a complete workflow application with:

### ✅ **Generated Components**

1. **📋 SQLAlchemy Model** (`models/review_model.py`):
   - Complete `Review` model with all fields
   - Validation and constraints
   - Relationships and indexes

2. **📊 Flask-AppBuilder Views** (`views/`):
   - `WriteReviewView`: Form for submitting reviews
   - `ModerateReviewView`: Interface for moderating reviews
   - Complete CRUD operations
   - Permission-based access control

3. **📝 WTForms** (`forms/`):
   - Form validation and field types
   - File upload handling
   - Custom validators

4. **🎨 Bootstrap Templates** (`templates/`):
   - Responsive design
   - Form layouts
   - Progress indicators

5. **🌐 RESTful API** (`api/workflow_api.py`):
   - Complete CRUD endpoints
   - JSON serialization
   - OpenAPI documentation

6. **🧪 Test Suite** (`tests/test_product_review.py`):
   - Model tests
   - View tests
   - API tests
   - Form validation tests

7. **🗄️ Database Migration** (`migrations/001_product_review.py`):
   - Alembic migration script
   - Table creation
   - Index definitions

### ✅ **Key Features**

- **🔐 Role-based Security**: Different permissions for users and moderators
- **📁 File Upload**: Image upload with validation
- **📧 Notifications**: Email alerts for workflow events
- **💾 Auto-save**: Automatic form saving
- **🔍 Validation**: Comprehensive form and data validation
- **📱 Responsive UI**: Mobile-friendly Bootstrap interface
- **🔄 Workflow State**: Complete workflow state management

## 🎯 Next Steps

### Customize Your Workflow

1. **Add More Steps**:
   ```yaml
   steps:
     PublishReview:
       title: "Publish Review"
       description: "Publish approved reviews"
       permissions:
         edit: ["admin"]
   ```

2. **Add Custom Validation**:
   ```yaml
   fields:
     - product_code: {type: string, validation: {pattern: "^PRD-[0-9]{4}$"}}
   ```

3. **Enable More Features**:
   ```yaml
   features:
     real_time: true
     collaboration: true
     versioning: true
   ```

### Extend Generated Code

1. **Custom View Methods**:
   ```python
   class CustomWriteReviewView(WriteReviewView):
       def pre_add(self, item):
           # Custom logic before saving
           item.ip_address = request.remote_addr
           return super().pre_add(item)
   ```

2. **Custom Validators**:
   ```python
   def validate_profanity(form, field):
       if contains_profanity(field.data):
           raise ValidationError('Review contains inappropriate content')
   ```

3. **Custom Templates**:
   - Override generated templates
   - Add custom CSS/JavaScript
   - Implement custom widgets

### Deploy to Production

1. **Use PostgreSQL**:
   ```python
   SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/reviewdb'
   ```

2. **Configure Email**:
   ```python
   MAIL_SERVER = 'smtp.gmail.com'
   MAIL_PORT = 587
   MAIL_USE_TLS = True
   MAIL_USERNAME = 'your-email@gmail.com'
   MAIL_PASSWORD = 'your-app-password'
   ```

3. **Add Security Headers**:
   ```python
   from flask_talisman import Talisman
   Talisman(app)
   ```

## 🆘 Troubleshooting

### Common Issues

1. **Import Errors**:
   ```bash
   # Ensure you're in the right directory
   cd review_app
   
   # Check Python path
   export PYTHONPATH="${PYTHONPATH}:$(pwd)"
   ```

2. **Database Issues**:
   ```bash
   # Reset database
   rm app.db
   flask db upgrade
   flask fab create-admin
   ```

3. **Permission Errors**:
   ```bash
   # Create roles manually
   flask fab create-user
   # Assign appropriate roles in the web interface
   ```

### Getting Help

- 📖 **Full Documentation**: See `docs/JHIPSTER_WORKFLOW_SYSTEM.md`
- 🔧 **API Reference**: See `docs/API_REFERENCE.md`
- 💡 **Examples**: Check the `examples/` directory
- 🐛 **Issues**: Report on GitHub

## 🎊 Congratulations!

You've successfully built a complete workflow application in just 10 minutes! 

You now have:
- ✅ A working Flask-AppBuilder application
- ✅ Complete workflow with approval process
- ✅ Role-based security
- ✅ File upload capabilities
- ✅ RESTful API
- ✅ Comprehensive test suite
- ✅ Production-ready code structure

### 🚀 What's Next?

Explore more advanced features:
- **Multi-tenant workflows**
- **Complex approval chains**
- **Integration with external systems**
- **Real-time collaboration**
- **Advanced analytics**

**Happy coding with JHipster-inspired Flask-AppBuilder workflows!** 🎉