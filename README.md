# Bazis Statusy

[![PyPI version](https://img.shields.io/pypi/v/bazis-statusy.svg)](https://pypi.org/project/bazis-statusy/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bazis-statusy.svg)](https://pypi.org/project/bazis-statusy/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An extension for the Bazis framework that implements a status system and transitions between them for Django models.

## Description

**Bazis Statusy** is an extension package for the Bazis framework that adds a powerful status management and transition system. The package enables you to:

- Define statuses for models
- Configure transitions between statuses with validation
- Execute actions before and after transitions
- Manage related (child) objects during transitions
- Control access rights for executing transitions
- Track the history of status changes

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Usage](#usage)
  - [Creating Models](#creating-models)
  - [Configuring Transitions](#configuring-transitions)
  - [Creating Routes](#creating-routes)
  - [Working with Admin Panel](#working-with-admin-panel)
- [API](#api)
- [Examples](#examples)
- [Architecture](#architecture)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Status System**: Define and manage statuses for any models
- **Transits**: Customizable transitions between statuses with validation
- **Validators**: Check conditions before executing a transition
- **Actions**: Execute code before and after transitions
- **Child Objects**: Automatic handling of related objects during transitions
- **Transition History**: Complete tracking of all status changes
- **Access Control Integration**: Control permissions for executing transitions
- **Validation Schemas**: Validate object data before transitions
- **Payload**: Pass additional data during transitions
- **Multi-level Relations**: Support for cascading transitions for related objects

## Requirements

- **bazis**: Bazis framework core package
- **bazis-permit**: Access control system (for transition control)
- **translated-fields**: Translated field support used by status/transit names
- **Python**: 3.12+
- **PostgreSQL**: 12+
- **Django**: 4.2+
- **FastAPI**: 0.100+

## Installation

### Using uv (recommended)

```bash
uv add bazis-statusy
```

### Using pip

```bash
pip install bazis-statusy
```

### For Development

```bash
git clone <repository-url>
cd bazis-statusy
uv sync --dev
```

## Quick Start

### 1. Add the applications to settings

```python
INSTALLED_APPS = [
    # ...
    'translated_fields',
    'bazis.contrib.permit',
    'bazis.contrib.statusy',
    # ...
]
```

### 2. Configure parameters in settings.py

```python
# Default initial status
BAZIS_STATUS_INITIAL = ('draft', 'Draft')

# Status system models
BAZIS_STATUSY_STATUS_MODEL = 'statusy.Status'
BAZIS_STATUSY_TRANSIT_MODEL = 'statusy.Transit'
BAZIS_STATUSY_TRANSIT_RELATION_MODEL = 'statusy.TransitRelation'
BAZIS_STATUSY_TRANSIT_MIDDLE_ABSTRACT_MODEL = 'statusy.StatusyTransit'
```

### 3. Create a model with statuses

```python
from django.db import models
from bazis.contrib.statusy.models_abstract import StatusyMixin
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin

class Order(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Order"""
    number = models.CharField('Number', max_length=50)
    description = models.TextField('Description', blank=True)
    
    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
```

### 4. Create a route

```python
from django.apps import apps
from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase

class OrderRouteSet(StatusyRouteSetBase):
    model = apps.get_model('myapp.Order')
```

### 5. Configure transitions via admin panel

1. Create statuses: draft, processing, completed
2. Create transitions between them
3. Configure validators and actions if necessary

## Core Concepts

### Statuses (Status)

A status is a state in which an object can exist. Each status has:
- `id` - unique identifier (string)
- `name` - human-readable name (supports translations)

### Transits (Transit)

A transit defines the possibility of changing an object's status from one to another. Each transit includes:
- `status_src` - source status
- `status_dst` - destination status
- `validators` - list of validators to check conditions
- `actions_before` - actions executed before status change
- `actions_after` - actions executed after status change
- `is_schema_validate` - flag for object schema validation before transition

### StatusyMixin

Base mixin for models requiring a status system. Adds:
- `status` field - current object status
- `status_dt` field - date and time of last status change
- `status_author` field - user who changed the status
- Methods for working with transitions

### StatusyChildMixin

Mixin for child objects whose status depends on the parent object. Enables:
- Defining path to parent status
- Automatic participation in validation during parent transitions

### Decorators for Configuring Transitions

The package provides special decorators for defining business logic of transitions:

#### @transit_validator

Creates a transition validator that is called before the transaction:

```python
@transit_validator('Validator description')
def validator_name(self, transit: TransitBase, user, payload):
    # Check conditions
    if not self.is_valid:
        raise TransitError('Condition not met')
```

**Parameters:**
- `transit` - transition object
- `user` - current user (or None)
- `payload` - additional data (or `payload_validate_none` during pre-validation)

**Important:** Always check `payload is not payload_validate_none` before using payload.

#### @transit_before

Creates an action executed **before** status change:

```python
@transit_before('Action description')
def before_action(self, statusy_transit: StatusyTransit, payload):
    # Logic before status change
    self.prepared_at = now()
    self.save()
```

#### @transit_after

Creates an action executed **after** status change:

```python
@transit_after('Action description')
def after_action(self, statusy_transit: StatusyTransit, payload):
    # Logic after status change
    # Can now work with new status
    self.send_notification()
```

**Action parameters:**
- `statusy_transit` - transition fact object (contains transit, status, dt, author)
- `payload` - additional transition data

#### @transit_link

Creates a link to a transition for programmatic invocation:

```python
@transit_link('Auto-transition on payment')
def get_transit_payment(self):
    # Additional checks (optional)
    return self.is_paid

def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    
    # Programmatic transition call
    if transit := self.get_transit_payment():
        transit(user=some_user, payload=some_data)
```

**Features:**
- Returns `transit_apply` method with preset transition
- Can return `None` if transition is not assigned or conditions not met
- Useful for automatic transitions in code

## Usage

### Creating Models

#### Model with Own Statuses

```python
from django.db import models
from bazis.contrib.statusy.models_abstract import StatusyMixin, TransitBase, StatusyTransit
from bazis.contrib.statusy import transit_validator, transit_before, transit_after, TransitError
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin

class Order(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    number = models.CharField('Number', max_length=50)
    total_amount = models.DecimalField('Total Amount', max_digits=10, decimal_places=2)
    is_paid = models.BooleanField('Paid', default=False)
    completed_at = models.DateTimeField('Completion Date', null=True, blank=True)
    
    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
    
    @transit_validator('Payment Check')
    def validator_check_payment(self, transit: TransitBase, user, payload):
        """Validator to check payment before order completion"""
        if not self.is_paid:
            raise TransitError('Order must be paid before completion')
    
    @transit_validator('Order Amount Check')
    def validator_check_amount(self, transit: TransitBase, user, payload):
        """Example validator using payload"""
        from bazis.contrib.statusy.schemas import payload_validate_none
        
        # Important: always check payload before use
        if payload is not payload_validate_none:
            if hasattr(payload, 'min_amount'):
                if self.total_amount < payload.min_amount:
                    raise TransitError('Order amount is less than minimum')
    
    @transit_before('Set Completion Date')
    def before_set_completed(self, statusy_transit: StatusyTransit, payload):
        """Action before transition - set completion date"""
        from django.utils.timezone import now
        self.completed_at = now()
        self.save()
    
    @transit_after('Send Notification')
    def after_send_notification(self, statusy_transit: StatusyTransit, payload):
        """Action after transition - send notification"""
        # Notification sending logic
        pass
```

#### Child Model

```python
from bazis.contrib.statusy.models_abstract import StatusyChildMixin

class OrderItem(StatusyChildMixin, DtMixin, UuidMixin, JsonApiMixin):
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product_name = models.CharField('Product Name', max_length=255)
    quantity = models.IntegerField('Quantity')
    price = models.DecimalField('Price', max_digits=10, decimal_places=2)
    
    @classmethod
    def get_status_field(cls):
        """Path to parent object status"""
        return 'order__status_id'
    
    class Meta:
        verbose_name = 'Order Item'
        verbose_name_plural = 'Order Items'
```

**Important:** The `get_status_field()` method must return a Django string path to the parent's status field. This allows the child model to automatically participate in validation during parent object transitions.

#### Model with Payload for Transition

```python
from pydantic import BaseModel, Field
from datetime import datetime

class CompleteOrderPayload(BaseModel):
    """Schema for order completion data"""
    completion_note: str = Field(..., description='Completion note')
    completed_by: str = Field(..., description='Completed by')

class Order(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    # ... model fields ...
    
    @transit_before('Save Completion Data')
    def before_save_completion(
        self, 
        statusy_transit: StatusyTransit, 
        payload: CompleteOrderPayload
    ):
        """Save additional data from payload"""
        statusy_transit.extra = {
            'completion_note': payload.completion_note,
            'completed_by': payload.completed_by,
        }
        statusy_transit.save()
```

### Configuring Transitions

Transitions are configured through Django admin panel:

1. Go to "Statusy" → "Transits" section
2. Create a new transit
3. Specify:
   - Model
   - Source status
   - Destination status
   - Validators (optional)
   - Actions before transition (optional)
   - Actions after transition (optional)

#### Example of Configuring "To Processing" Transition

- **Model**: Order
- **Source Status**: draft
- **Destination Status**: processing
- **Validators**: validator_check_items (check for items presence)
- **Actions Before**: before_calculate_total (calculate total)
- **Validate Schema**: Yes

### Creating Routes

#### Basic Route with Statuses

```python
from django.apps import apps
from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase
from bazis.core.schemas import SchemaFields

class OrderRouteSet(StatusyRouteSetBase):
    model = apps.get_model('myapp.Order')
    
    fields = {
        None: SchemaFields(
            include={
                'items': None,  # Include related items
            },
        ),
    }
```

#### Route for Child Object

```python
from bazis.contrib.statusy.routes_abstract import StatusySimpleRouteSetBase

class OrderItemRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('myapp.OrderItem')
    
    fields = {
        None: SchemaFields(
            include={
                'order': None,  # Include parent order
            },
        ),
    }
```

#### Route with Child Routes Specification

```python
class OrderRouteSet(StatusyRouteSetBase):
    model = apps.get_model('myapp.Order')
    
    # Specify child object routes
    routes_child = [
        'myapp.routes.OrderItemRouteSet',
    ]
    
    fields = {
        None: SchemaFields(
            include={
                'items': None,
            },
        ),
    }
```

**Why routes_child is needed:**

The `routes_child` attribute defines a list of child routes for correct validation during transitions. When a parent object transition is executed, the system automatically:

1. Validates all child objects through their routes
2. Checks child objects' compliance with their schemas
3. Considers user's access rights to child objects

**Example with multiple child routes:**

```python
class FacilityRouteSet(StatusyRouteSetBase):
    model = apps.get_model('facility.Facility')
    
    routes_child = [
        'facility.routes.FacilityOperationRouteSet',
        'facility.routes.FacilityEquipmentRouteSet',
        'facility.routes.FacilityPersonnelRouteSet',
    ]
```

**Important:** Each child route must inherit from `StatusySimpleRouteSetBase`, and its model must contain `StatusyChildMixin` with correctly defined `get_status_field()`.

### Working with Admin Panel

#### Admin Setup for Model with Statuses

```python
from django.contrib import admin
from bazis.contrib.statusy.admin_abstract import StatusyAdminMixin
from bazis.core.admin_abstract import DtAdminMixin

@admin.register(Order)
class OrderAdmin(StatusyAdminMixin, DtAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'number', 'status_id', 'total_amount', 'is_paid')
    list_filter = ('status', 'is_paid')
    search_fields = ('number',)
    readonly_fields = ('status', 'status_dt', 'status_author')
```

`StatusyAdminMixin` adds:
- Current status display in list
- Status search
- Inline with transition history (read-only)
- Readonly fields for status fields

#### Status System Models Setup

```python
from django.contrib import admin
from bazis.contrib.statusy.admin_abstract import (
    StatusAdminBase, 
    TransitAdminBase, 
    StatusyContentTypeAdminBase,
    TransitInlineBase,
    TransitRelationInlineBase,
)
from .models import Status, Transit, StatusyContentType, TransitRelation

@admin.register(Status)
class StatusAdmin(StatusAdminBase):
    pass

@admin.register(Transit)
class TransitAdmin(TransitAdminBase):
    pass

@admin.register(StatusyContentType)
class StatusyContentTypeAdmin(StatusyContentTypeAdminBase):
    inlines = [TransitInlineBase]
```

## API

### Endpoints

#### Get Transition Schema

```
GET /api/v1/{model}/{item_id}/schema_transit/
```

Returns validation schema for transition, including available transitions and their parameters.

#### Execute Transition

```
POST /api/v1/{model}/{item_id}/transit/
```

**Request Body:**
```json
{
  "transit": "to_processing",
  "payload": {
    "note": "Starting order execution"
  }
}
```

**Success Response (200):**
```json
{
  "data": {
    "id": "uuid",
    "type": "myapp.order",
    "attributes": {
      "number": "ORD-001",
      "total_amount": "1500.00"
    },
    "relationships": {
      "status": {
        "data": {
          "id": "processing",
          "type": "statusy.status"
        }
      }
    }
  }
}
```

**Validation Error (422):**
```json
{
  "errors": [
    {
      "status": 422,
      "title": "Transit Error",
      "code": "ERR_TRANSIT",
      "detail": "Order must be paid before completion"
    }
  ]
}
```

### Meta Fields

When retrieving an object with statuses, the API returns additional meta fields:

#### state_actions

List of available actions (transitions) for the current object. Actions can be represented as individual objects or as packages (arrays) for execution through bulk API:

```json
{
  "data": {
    "id": "uuid",
    "type": "myapp.order",
    "meta": {
      "state_actions": [
        {
          "hint": "Move order to processing",
          "hint_title": "To Processing",
          "hint_action": "Start order execution",
          "endpoint": {
            "url": "/api/v1/myapp/order/uuid/transit/",
            "method": "POST",
            "body": {
              "type": "object",
              "properties": {
                "transit": {
                  "type": "string",
                  "const": "to_processing"
                },
                "payload": {
                  "type": "object",
                  "properties": {
                    "note": {"type": "string"}
                  }
                }
              }
            }
          },
          "resource": {
            "id": "uuid",
            "type": "myapp.order"
          }
        }
      ]
    }
  }
}
```

**Batch Transitions:**

If a `state_actions` element is represented as an array (not an object), this means a set of related actions that should be executed as a single package via `/api/web/v1/bulk/`:

```json
{
  "meta": {
    "state_actions": [
      [
        {
          "hint": "Sign document",
          "endpoint": {
            "url": "/api/v1/document/uuid1/transit/",
            "method": "POST"
          }
        },
        {
          "hint": "Approve application",
          "endpoint": {
            "url": "/api/v1/application/uuid2/transit/",
            "method": "POST"
          }
        }
      ]
    ]
  }
}
```

**Important:**
- Order of actions in package matters - send requests in the same order
- When requesting an entity, only actions directly related to it are returned
- To get information about related objects, request their endpoints separately

#### status_aggs (list only)

Aggregation of object count by statuses:

```json
{
  "meta": {
    "status_aggs": {
      "draft": 15,
      "processing": 8,
      "completed": 42
    }
  }
}
```

#### status_allowed (list only)

List of all allowed statuses for the model:

```json
{
  "meta": {
    "status_allowed": ["draft", "processing", "completed", "cancelled"]
  }
}
```

## Examples

### Simple Transition

```python
# Model
class Article(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    title = models.CharField('Title', max_length=255)
    content = models.TextField('Content')
    
    class Meta:
        verbose_name = 'Article'
        verbose_name_plural = 'Articles'

# Route
class ArticleRouteSet(StatusyRouteSetBase):
    model = apps.get_model('blog.Article')
```

**API Request:**
```bash
curl -X POST http://api.example.com/api/v1/blog/article/{id}/transit/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {token}" \
  -d '{"transit": "publish"}'
```

### Transition with Validation

```python
class Article(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    title = models.CharField('Title', max_length=255)
    content = models.TextField('Content')
    reviewed_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL
    )
    
    @transit_validator('Review Check')
    def validator_check_review(self, transit, user, payload):
        if not self.reviewed_by:
            raise TransitError('Article must be reviewed')
```

### Transition with Payload

```python
from pydantic import BaseModel
from datetime import datetime

class PublishPayload(BaseModel):
    publish_date: datetime
    featured: bool = False

class Article(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    # ... fields ...
    published_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    
    @transit_before('Set Publishing Parameters')
    def before_publish(
        self, 
        statusy_transit: StatusyTransit, 
        payload: PublishPayload
    ):
        self.published_at = payload.publish_date
        self.is_featured = payload.featured
        self.save()
```

**API Request:**
```bash
curl -X POST http://api.example.com/api/v1/blog/article/{id}/transit/ \
  -H "Content-Type: application/json" \
  -d '{
    "transit": "publish",
    "payload": {
      "publish_date": "2024-03-15T10:00:00Z",
      "featured": true
    }
  }'
```

### Programmatic Transition Call via @transit_link

```python
from django.utils.timezone import now

class Order(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    number = models.CharField('Number', max_length=50)
    is_paid = models.BooleanField('Paid', default=False)
    payment_received_at = models.DateTimeField(null=True, blank=True)
    
    @transit_link('Auto-transition on payment receipt')
    def get_transit_payment(self):
        """Link to transition executed on payment"""
        # Additional condition check (optional)
        return self.is_paid and not self.payment_received_at
    
    def process_payment(self, payment_data):
        """Payment processing"""
        self.is_paid = True
        self.payment_received_at = now()
        self.save()
        
        # Automatic transition after successful payment
        if transit := self.get_transit_payment():
            # transit() returns transit_apply method with preset transition
            transit(user=payment_data.get('user'))
```

**Usage in Code:**
```python
order = Order.objects.get(id=order_id)
order.process_payment({'user': request.user})
# Status will automatically change after payment
```

### Cascading Transitions (parent-child)

```python
# Parent model
class ParentEntity(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)
    dt_approved = models.DateTimeField(null=True, blank=True)
    
    @transit_after('Update Child Objects')
    def after_update_children(self, statusy_transit: StatusyTransit, payload):
        """Update all child objects on transition"""
        self.child_entities.all().update(
            child_dt_approved=self.dt_approved,
            child_is_active=self.is_active
        )

# Child model
class ChildEntity(StatusyChildMixin, DtMixin, UuidMixin, JsonApiMixin):
    parent_entities = models.ManyToManyField(
        ParentEntity,
        related_name='child_entities'
    )
    child_name = models.CharField(max_length=255)
    child_is_active = models.BooleanField(default=False)
    child_dt_approved = models.DateTimeField(null=True, blank=True)
    
    @classmethod
    def get_status_field(cls):
        return 'parent_entities__status_id'

# Routes
class ParentEntityRouteSet(StatusyRouteSetBase):
    model = apps.get_model('myapp.ParentEntity')
    routes_child = ['myapp.routes.ChildEntityRouteSet']
    
    fields = {
        None: SchemaFields(
            include={'child_entities': None},
        ),
    }

class ChildEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('myapp.ChildEntity')
    
    fields = {
        None: SchemaFields(
            include={'parent_entities': None},
        ),
    }
```

## Architecture

### Package Structure

```
bazis.contrib.statusy/
├── __init__.py              # Export of main classes
├── models_abstract.py       # Abstract models
├── models.py                # Concrete models
├── admin_abstract.py        # Abstract admin classes
├── admin.py                 # Admin registration
├── routes_abstract.py       # Abstract routes
├── routes.py                # Concrete routes
├── schemas.py               # Pydantic schemas
├── services.py              # Services
└── apps.py                  # Application configuration
```

### Main Components

#### StatusyMixin

Main mixin adding status functionality to a model. Provides:
- Status fields
- Methods for working with transitions
- Schema validation
- Child object management

#### StatusyChildMixin

Mixin for child objects. Features:
- Automatic registration in parent model
- Participation in validation during parent transitions
- Definition of path to parent status

#### Transit (Transition)

Model describing a transition between statuses:
- Model connection via ContentType
- Source and destination statuses
- Lists of validators and actions
- Relations with other transitions

#### StatusyTransit (Transition Fact)

Model for storing transition history:
- Link to specific transition
- Set status
- Author and transition time
- Additional data (extra)

### Transition Lifecycle

1. **Initiation**: Request to execute transition via API
2. **Access Check**: Check user's permissions for transition
3. **Transit Search**: Determine specific transition by label
4. **Payload Validation**: Validate data passed with transition
5. **Validator Execution**: Run all configured validators
6. **Schema Validation**: Check object's compliance with schema (if enabled)
7. **Transition Fact Creation**: Create StatusyTransit record
8. **Actions Before Transition**: Execute actions_before
9. **Status Setting**: Change object status
10. **Actions After Transition**: Execute actions_after
11. **Save**: Save all changes

### Integration with bazis-permit

The package is tightly integrated with the access control system:

- `StatusyAccessAction.TRANSIT` - special action for transitions
- Permissions checked at specific transition level
- Permission format: `{app}.{model}.item.transit.{scope}.{status_from}.{transit_label}`

Example permission:
```
entity.order.item.transit.author.draft.to_processing
```

Means: author can move their order from "draft" status via "to_processing" transition

## Development

### Setting Up Development Environment

```bash
# Clone repository
git clone <repository-url>
cd bazis-statusy

# Install dependencies
uv sync --dev

# Run tests (requires local PostgreSQL)
cd sample
uv run pytest ../tests

# Code check
ruff check .

# Code formatting
ruff format .
```

### Running Tests

```bash
# All tests
uv run pytest ../tests

# Specific test
uv run pytest ../tests/test_transit.py::test_transit

# With coverage
uv run pytest ../tests --cov=bazis.contrib.statusy
```

## Contributing

We welcome contributions to the project! Here's how you can help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make changes
4. Run tests (`cd sample && pytest ../tests`)
5. Commit changes (`git commit -m 'Add amazing feature'`)
6. Push to branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

Please ensure that:
- Tests are written for new functionality
- Documentation is updated when necessary
- Code follows existing style
- Changes are added to changelog

## License

Apache License 2.0

See [LICENSE](LICENSE) file for details.

## Links

- [Bazis Core](https://github.com/ecofuture-tech/bazis) — framework core
- [Issue Tracker](https://github.com/ecofuture-tech/bazis/issues) — report a bug or suggest improvement
- [Bazis Documentation](https://github.com/ecofuture-tech/bazis) — complete framework documentation

## Support

If you have questions or problems:
- Check the [documentation](https://github.com/ecofuture-tech/bazis)
- Search [existing issues](https://github.com/ecofuture-tech/bazis/issues)
- Create a [new issue](https://github.com/ecofuture-tech/bazis/issues/new) with detailed description

---

Made with ❤️ by the Bazis team
