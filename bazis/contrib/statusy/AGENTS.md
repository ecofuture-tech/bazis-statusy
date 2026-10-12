# bazis-statusy — guide for AI agents

Statuses of objects and transitions between them (workflows): transitions (`Transit`) are
configured per model as data, run validators and actions that are methods of the model, and
are permissions of bazis-permit. Needs bazis-permit (and so bazis-users).

### The sections

Read a section with `package_guide("bazis-statusy", "<section>")` when the step at hand
needs it; `guide_search` finds the part of a section that answers a question. A model with
a workflow needs Setup, Workflows in the code, Validators, actions and the payload, and
Rules.

| Section | Read it when |
|---|---|
| Setup | you give a model statuses: `StatusyMixin`, `StatusyRouteSetBase`, the migrations, the initial status, the public catalog router, the permissions by status, the status of a create (`statusy.W005`, `W006`) |
| Workflows in the code (`workflow.py`) | you declare the statuses and transits of a model: `Workflow`, `Status`, `Transit`, `initial=`, what `migrate` applies, the checks `statusy.E001`–`E004`, `W003`, `W004` |
| Validators, actions and the payload | you write the methods of a transit: `transit_validator`, `transit_before`, `transit_after`, `TransitError`, the payload type, a required text, the titles of its fields |
| API of a StatusyRouteSetBase route | a client makes a transit: `POST /{item_id}/transit/` and its answers, `schema_transit`, a transit for anonymous users, the meta `state_actions`, `status_aggs` |
| Transits in code and the history | the code makes a transit: `get_transit`, `transit_apply` and its payload, the actor of a system transit, an automatic transit on create, the history and `status_history` |
| Rules | before you write the code, once: the status changes only by transits, the routes, `StatusyChildMixin` and the validation of the children, `validate_item` on a transit |
| Statuses and transits as data | the statuses and transits are rows made in the admin or a data migration: `Status`, `Transit`, `StatusyContentType` |

## Setup

```python
from bazis.contrib.statusy import TransitError, transit_after, transit_before, transit_validator
from bazis.contrib.statusy.models_abstract import StatusyMixin, StatusyTransit, TransitBase
from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase
from bazis.contrib.statusy.schemas import payload_validate_none
from bazis.core.schemas import CrudApiAction, SchemaFields

class Order(StatusyMixin, DtMixin, UuidMixin, JsonApiMixin):
    is_paid = models.BooleanField(default=False)

    @transit_validator('Order is paid')            # the label shown in the admin
    def validator_paid(self, transit: TransitBase, user, payload):
        if not self.is_paid:
            raise TransitError('The order is not paid')

    @transit_before('Set the date')    # ClosePayload: a Pydantic model, the payload is required
    def before_date(self, statusy_transit: StatusyTransit, payload: ClosePayload):
        self.dt_closed = payload.dt_closed
        self.save()

class OrderRouteSet(StatusyRouteSetBase):
    model = apps.get_model('shop.Order')
```

- `BS_INSTALLED_APPS` includes `bazis.contrib.permit`, `bazis.contrib.statusy` and
  `translated_fields`. Run `makemigrations`: `StatusyMixin` adds `status`, `status_dt`,
  `status_author` and a history model `<Model>StatusyTransit` in the same app
  (`item.statusy_transits`).
- The initial status of new objects is `Workflow(initial=...)` of the model (see Workflows
  in the code), else `BAZIS_STATUS_INITIAL` (default `["draft", "Draft"]`,
  `BS_BAZIS_STATUS_INITIAL='["new", "New"]'`, for all the models); its `Status` row is
  created on first use.
- The statuses and transits of a model are declared in `workflow.py` (see Workflows in the
  code); rows made in the admin or a data migration: see Statuses and transits as data.
- Optionally `router.register('bazis.contrib.statusy.router')`: the read-only statuses and
  transits of every workflow, a public catalog (`permit_public = True`, no `permit.W002`
  since 2.12.0). Registering it publishes the workflow of all the models with statuses to
  every user, anonymous ones included: `statusy/status/` (`id`, `name`) and
  `statusy/transit/` (`id`, `name`, `hint`, `hint_title`, `hint_action`, `model`,
  `status_src`, `status_dst`; not the methods, `source_link`, `is_schema_validate` or
  `transits_related`). Register it if a client names the statuses and transits by their
  ids; leave it out if the workflow must not be public.
- **Permissions by status.** On a statusy model the item permissions take the status of
  the object after the selector (`all` or a status id); a transit is the operation
  `transit` with the transit id last:

  ```
  shop.order.item.view.all.all
  shop.order.item.add.all.draft                    # create only in `draft`
  shop.order.item.change.author.draft              # change only in `draft`
  shop.order.item.transit.author.draft.to_paid     # transit `to_paid` from `draft`
  ```

- **The status of a create.** The CREATE schema accepts an initial `status` (omitted: the
  initial status of the model), and bazis-permit (2.11) checks the created item against
  the `item.add` permissions of the user, the status segment literally: with
  `item.add.all.draft` a create without `status`, or with `draft`, is allowed, one with
  `paid` is 403 `ERR_FORBIDDEN` (nothing written); `item.add.all.paid` creates only with
  `paid` sent, a create without `status` (`draft`) is 403; `item.add.all.all` creates in any
  status the client sends, skipping the transits, their validators, actions and
  permissions. Name the statuses a role creates in. To take the choice away from every
  client, exclude the field: `CrudApiAction.CREATE: SchemaFields(exclude={'status': None})`
  on the route; every create then gets the initial status, which the add permissions must
  name (or `all`). `bazis_doctor` warns of a role whose add permissions on a model name
  neither its initial status nor `all` (`statusy.W005`: every create without `status` is
  refused) and of `item.add.<selector>.all` while a route of the model accepts `status`
  on a create and the role does not hide it (`statusy.W006`), for the roles of `roles.py`
  and those of the database (with the database checks). To take the choice away from one
  role only, hide the field from its creates: `shop.order.field.add.all.all.status.disable`
  (a create with it is 422) or `readonly` (a create ignores it). A status that is not one of the workflow of the model is
  not refused by the permission `all`; a status that does not exist is 422 `ERR_VALIDATE`
  at `/data/relationships/status/data/id` (bazis 2.16; a 500 before).

## Workflows in the code (`workflow.py`)

The statuses and transits of a product are declared in the `workflow.py` module of an
application (needs bazis-permit 2.9: its roles are declared the same way in `roles.py`),
not in data migrations:

```python
# shop/workflow.py
from django.utils.translation import gettext_lazy as _
from bazis.contrib.statusy.declare import Status, Transit, Workflow

DRAFT, PAID = Status('draft', _('Draft')), Status('paid', _('Paid'))
WORKFLOWS = [
    Workflow('shop.Order', [DRAFT, PAID], [
        Transit('to_paid', _('Pay'), DRAFT, PAID,
                validators=['validator_paid'], actions_before=['before_date']),
    ], initial=DRAFT),
]
```

- `initial=` (a status of the workflow or its id) is the status of a new object of the
  model that is created without one (the API, `Order()`, `Order.objects.create()`; a loaded
  object or an explicit `status` is kept), instead of the global `BAZIS_STATUS_INITIAL`
  (bazis-statusy 2.12). The admin form of a new object still starts with the global
  default: pick the status there. An initial status that is not a status of the workflow
  is `statusy.E001`. `initial_status(Model)` of `bazis.contrib.statusy.declare` reads it
  (None without one), as the contract of bazis-front does.

- `migrate` applies them (`post_migrate`, also sent by `flush`) once all the migrations
  of the project are applied, in one transaction; applied again it writes nothing. The
  statuses are shared by the models (one name per id); the transits of a declared model
  get the declared name, statuses and methods (the other fields, `hint`,
  `is_schema_validate`, `transits_related`, stay as the admin set them). The cached
  content types (`ContentType`, `StatusyContentType`) are forgotten first: `flush` makes
  them again with other ids.
- Nothing is deleted: a status (its objects would be deleted, `on_delete=CASCADE`) nor a
  transit of a declared model that is not declared (its history, the transit facts of the
  objects, would be deleted): `statusy.W004` lists such transits. A declared transit id
  that is a transit of another model in the database stops `migrate` (`statusy.E004`).
- A data migration of the product runs before the declarations are applied (they are
  applied after the last migration): on a fresh database it cannot rely on the declared
  statuses or transits.
- Names: English msgids (`gettext_lazy`) translated into `name_en`/`name_ru` by the
  catalogs of the project (`manage.py bazis_messages status` lists the untranslated ones;
  `statusy.W002` is removed in bazis-statusy 2.12).
- Tests: the test database is migrated, so the workflows are there, also after the flush
  of a test with `transaction=True`; `bazis_test_utils` gives `apply_declarations()` and
  the fixture `bazis_declared`.
- `bazis.contrib.statusy.declare.apply_declarations(using, workflows=None, dry_run=False)`
  returns the changes; `dry_run` only lists them.
- Checks: `statusy.E001` (the model is a `StatusyMixin`, one workflow per model, the ids,
  a transit between statuses of its workflow, a transit id unique among the models, one
  name per status, the initial status is one of the workflow), `statusy.E002` (a validator or action that is not a method of the
  model), `statusy.E003` (a permission of `roles.py` of a model with a declared workflow
  names a status that is not one of the workflow, a transit that is not declared for the
  model, or a status the transit does not start from); with a database
  (`bazis_doctor` from bazis 2.13, against the database it reaches; with an older core
  only `manage.py check --database default`) `statusy.W003` (the database differs:
  migrate), `statusy.W004` and `statusy.E004` (a declared transit id is a transit of
  another model).

## Validators, actions and the payload

The methods are listed by name in the `Transit`; `transit_apply` (and so the endpoint)
calls them with these signatures:

```python
@transit_validator('Label')   # (self, transit, user, payload): raise to refuse
def validator_x(self, transit: TransitBase, user, payload: XPayload): ...

@transit_before('Label')      # (self, statusy_transit, payload): before the status is set
def before_x(self, statusy_transit: StatusyTransit, payload: XPayload): ...

@transit_after('Label')       # (self, statusy_transit, payload): after the status is set
def after_x(self, statusy_transit: StatusyTransit, payload): ...
```

- A validator raises `TransitError('...')` (or `JsonApiBazisException`, a pydantic
  `ValidationError`): the errors of all the validators are collected and answered together
  with 422 (`TransitError` is `ERR_TRANSIT`).
  `user` is the user of the transit (None for a system transit). A validator is also called
  with `payload is payload_validate_none` to build the `restricts` of `state_actions`:
  return early then, before reading the payload.
- An action gets the history record `statusy_transit` (its `transit`, `author`, `extra`;
  saved, the status not yet set for a before action) and the payload object. A before
  action saves the changes of the item itself (`self.save()`); if it returns an object, the
  next actions run on it and `transit_apply` returns it (read again). The return of an after
  action is ignored. All
  of it runs in one transaction with the history record.
- **The payload type** comes from the annotations of the parameter `payload` of the
  validators and the actions of the transit: each annotation is a pydantic model, and the
  transit's payload type is one model inheriting all of them (`item.transit_payload_type
  (transit)`): the client sends one `payload` object with the fields of all the models, it
  is validated as a whole (422 with an error per invalid field, 400 `This transition
  requires a payload` when it is missing), and every method receives that
  same object. A `payload` without an annotation adds nothing; a transit whose methods have
  no annotated `payload` has no payload type, the methods receive None. A model with a
  classmethod `schema_build(transit)` returns the model to use for each transit.
- **A required text of the payload** (a reason of a rejection): `reason: str =
  Field(title=_('Reason'), min_length=1, max_length=2000)`. The payload type strips the
  texts of its fields before their length is checked (bazis-statusy 2.12): a reason of
  only spaces is refused (422 at `/payload/reason`) and the methods receive the stripped
  text; do not strip it again in an action. A model nested in the payload keeps its own
  configuration (`model_config = ConfigDict(str_strip_whitespace=True)` to strip its
  texts). Test the transit with a text of only spaces.
- **The titles of the payload fields**: `Field(title=_('Reason'))` with `gettext_lazy`,
  kept lazy: the JSON schemas of the payload (the body of the transit in `state_actions`,
  the contract of bazis-front) are generated in the language of the request (of the export)
  by `TranslatedJsonSchema` of the core (`bazis.core.utils.schemas`, bazis 2.14: the
  payload type and the transit body are `TranslatedSchemaModel`).
  Do not wrap it in `str()`: the title would keep the language of the process start.
  Without a title, pydantic derives it from the field name (`must_active` → `Must Active`).

## API of a StatusyRouteSetBase route

- `POST /{item_id}/transit/` with the plain JSON body (not a JSON:API document)
  `{"transit": "<transit id>", "payload": {...}}` (`payload` omitted or null for a transit
  without a payload type, see below): 200 with the item (204 if the user can no longer view it); 403 if the user has no permission for
  the transit or it does not start from the current status (from bazis-permit 2.8.0, 404
  for an item the user cannot view, as for a missing one); 400 without a required
  payload; 422 with the errors of the payload and the validators. An action of bazis-permit
  declared `public=False` (bazis-statusy 2.12): authenticated users only, an anonymous user
  gets 403 even with a transit permission of a role for anonymous users, unless a route
  declares it again with `public=True` (below).
- `GET /{item_id}/schema_transit/`: the schema the object must satisfy before a transit with
  `is_schema_validate` (default true); kind `schema` in `x-bazis` (bazis-statusy 2.12).
- A transit for anonymous users (a guest request, a public form): a route of its own that
  declares the transit again with `public=True` (`route_declare` of the core; limited by
  `BAZIS_THROTTLE_PUBLIC` per user or IP address, or by
  `route_declare(..., public=True, dependencies=[throttle(...)])`); the transit permissions
  of the roles for anonymous users (`Role(for_anonymous=True)`, selector `all`) still
  decide which transits they make, and the transit has no author:

  ```python
  from bazis.core.routes_abstract.initial import route_declare

  class RequestGuestRouteSet(StatusyRouteSetBase):
      model = apps.get_model('service.Request')
      actions = ['action_transit']

      @classmethod
      def get_url_prefix(cls) -> str:
          return '/service/request_guest'

      action_transit = route_declare(StatusyRouteSetBase.action_transit, public=True)
  ```

  Declare `default_route = True` on the main route of the model (a second route set of a
  model, see the guide of the core).
- Meta: `state_actions` (retrieve: allowed transits, their body and `restricts` = the
  validator errors), `status_aggs` (list: the counts by status of the visible objects with
  the filter of the request without `status` and the search, applied by the services of
  the route as the list does, so restricted to what the route shows) and `status_allowed`
  (list).

## Transits in code and the history

- `item.get_transit('<transit id>')` is the transit of the model with that id that starts
  from the current status of the item, else None (check it); `item.instance_transits`
  are all of them. Take the transit of `transit_apply` with it.
- `item.transit_apply(transit, user, payload=None)` makes only a transit of the model of
  the item (its content type) that starts from the current status of the item, a transit
  `get_transit` gives: another one fails with 400 `ERR_TRANSIT`
  (`JsonApiBazisException`) before its validators, nothing written.
  `payload` is the dict of the body of the transit endpoint (`{'dt_closed': '2026-...'}`)
  or an instance of a payload model (`ClosePayload(dt_closed=...)`, bazis-statusy 2.12),
  validated as its data with the payload type of the transit: a transit whose methods
  annotate several payload models takes the fields of all of them, so pass the dict, or
  an instance of `item.transit_payload_type(transit)`; missing fields are 422
  (`JsonApiBazisException`), as on the endpoint. The methods receive the instance of the
  payload type, not the object passed. It runs the
  validators (with `user`), writes the history record, runs the actions before, sets
  `status`, `status_dt`, `status_author`, runs the actions after and returns the item
  read again. It checks
  neither the permissions of `user` nor `is_schema_validate` (the transit endpoint does).
- The actor: `user` is the `author` of the history record and the `status_author`. A
  transit the system makes (an automatic confirmation, a task) passes `None`: the record
  has no author. Do not pass the user of the request for it: the history would say that
  he made a transit his permissions may not allow. A project that names its system actor
  passes a user of its own for it.
- An automatic transit on create, in `hook_after_create` of the route, after `super()`:
  bazis-permit checks the item against the `item.add` permissions of the user there, with
  the status of creation, so the transit (the server's, not the user's) comes after the
  check and the role needs `item.add` of the initial status only. By itself the
  transit is validated with the create, once, as `create` with the user of the route
  (`changes.user`, also for a transit without a user), but its validators run before that
  validation. Validate the new item first, so that an invalid one answers with the errors
  of its fields (422 `ERR_ITEM_INVALID`), not with the error of the transit
  (`ERR_TRANSIT`); then the item is validated twice, `('create', user)` before the
  transit and `('transit', user)` after it (keep `validate_item` cheap or check
  `changes.source`):

  ```python
  from bazis.core.item_validation import defer_validate_item

  class BookingRouteSet(StatusyRouteSetBase):
      def hook_after_create(self, item):
          super().hook_after_create(item)
          if not item.room.requires_approval:
              with defer_validate_item() as scope:
                  scope.validate()
              # None if the transit does not start from the status of the new item
              if transit := item.get_transit('confirm'):
                  item.transit_apply(transit, None)
  ```

- The history: `item.statusy_transits` (the model `<Model>StatusyTransit` of the app), one
  record per transit with `transit`, `status` (the new one), `dt`, `author` and `extra`
  (JSON, `{}`); order it by `dt`. `StatusyAdminMixin` shows it in the admin. A status
  written without a transit (`QuerySet.update(status=...)` in test data) has no record.

### The history in the API: `status_history`

The history model is not a JSON:API resource and has no route. `StatusyMixin` has the
calculated field `status_history` (bazis-statusy 2.12): the transits of the item, the
oldest first, each `{"transit": "<transit id>", "status": "<status id>", "dt": "<ISO
time>", "author": "<user id>" | null}` (null for a transit of the system). A route shows it
with `include` (fetched in the query of the route, one subquery, for a list too):

```python
class OrderRouteSet(StatusyRouteSetBase):
    model = apps.get_model('shop.Order')
    fields = {None: SchemaFields(include={'status_history': None})}
```

It is a read-only field of the item: whoever views the item reads its history (the
`view` permissions by status and selector), nobody else; a field permission hides it
(`shop.order.field.view.all.all.status_history.disable`). A client names the transits
and statuses by their ids (the read-only routes `statusy/transit/` and `statusy/status/`
under the prefix of the API router, registered with `bazis.contrib.statusy.router`) and the authors by the users it may read. A history with
other data (the `extra` of the records, the names of the authors) is a `calc_property` of
the model of its own over `statusy_transits` (see the guide of the core).

## Rules

- The status changes only through `POST /{item_id}/transit/`: the UPDATE schema of
  `StatusyRouteSetBase` has no `status`, `status_dt`, `status_author`, the CREATE schema no
  `status_dt`, `status_author` (a write with them is 422 `ERR_VALIDATE` `extra_forbidden`
  from bazis 2.12, at `/data/relationships/<f>` or `/data/attributes/status_dt`; before it
  they were ignored); the `fields` of a route add up with them, do not exclude them again.
  The CREATE schema accepts an initial `status` (the initial status if omitted): the
  `add` permissions by status restrict it (`item.add.all.draft`: only `draft`; checked on
  the created item by bazis-permit 2.11, see Setup), or exclude it
  (`CrudApiAction.CREATE: SchemaFields(exclude={'status': None})`: always the initial
  status).
  `StatusyRouteSetBase` adds the actions `action_transit` and `action_schema_transit` and
  no hooks (those of bazis-permit apply).
- Every JSON:API route that changes a statusy model inherits `StatusyRouteSetBase` (`statusy.W001`);
  the routes of `StatusyChildMixin` models inherit `StatusySimpleRouteSetBase`. A read-only
  route of the model (a projection that lists its `actions` without the create, update and
  relationships actions) needs neither and is not reported; it does not apply the
  permissions by status either: it is a route without permissions (see "another route of
  a protected model" in the guide of bazis-permit, `permit.W002`), its `get_queryset`
  decides what it shows. To keep the permissions by status on a read-only route, inherit
  `StatusyRouteSetBase` and list its `actions`; a plain `PermitRouteBase` does not apply the
  status segment of the permissions (only `PermitStatusyHandler` does).
- Validators are also called with `payload is payload_validate_none` (to build
  `state_actions`): check it before reading the payload.
- Decorated methods are defined directly in a model class (or its mixin); `Transit` lists
  their method names. A transit runs in a transaction.
- A child object whose status is the parent's: `StatusyChildMixin` with the
  classmethod `get_status_field()` returning the path to the status of the parent; list
  its route in `routes_child` of the parent route to validate the children with it on a
  transit (else the default route of the child model):

  ```python
  class OrderItem(StatusyChildMixin, DtMixin, UuidMixin, JsonApiMixin):
      order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')

      @classmethod                 # a classmethod: read on the class when the models load
      def get_status_field(cls):
          return 'order__status_id'

  class OrderItemRouteSet(StatusySimpleRouteSetBase):
      model = apps.get_model('shop.OrderItem')
  ```
 `StatusyChildMixin` is a
  `PermitModelMixin` (as `StatusyMixin`): its objects are restricted by the permissions
  of the user, with selectors (`author`) and the status of the parent
  (`entity.order_item.item.view.author.draft`), on its route and through the relations
  (`included`, filters) of the other routes.
- A transit of the parent with `is_schema_validate` validates the parent with its transit
  schema and every child (all of them, also those the user does not view) with the
  transit schema of its route, read as that route reads its objects (with the
  `calc_property` fields of the schema, since 2.12.0): the fields with the restrictions of the field permissions
  of the user for the transits of the child model
  (`shop.order_item.field.transit.all.all.price.notnull`), a failure is 422: the errors of
  the fields of a child the user views (`source` with its `id`, `type` and `pointer`);
  for the children he does not view one error that names none of them,
  `ERR_TRANSIT_CHILDREN_INVALID` `Some related items are not valid for this transit`
  (only when no child he views is invalid). The permission of the transit is the one of the parent
  (`shop.order.item.transit.author.draft.submit`): grant no `transit` item permission of
  the child models for it (since 2.10.0; before it the transit was 403 without them). Such
  a permission only opens `GET /{item_id}/schema_transit/` of the child route.
- A transit validates the item once with `JsonApiMixin.validate_item` (bazis 2.10.0):
  `changes.source == 'transit'`, `changes.fields` with `status`, `status_dt`,
  `status_author` and the fields the actions set, `changes.user` the user of the transit;
  a failure rolls the transit back (422 `ERR_ITEM_INVALID` on the transit endpoint). The
  source and the user come from the outermost block: a transit inside a write of a route
  (`hook_after_create`) is validated with that write, once, as `create` with the user of
  the route. Keep the invariants of the item there (a validator of a transit checks only
  that transit).
- `item.transit_apply(transit, user, payload)` in code validates but does not check
  permissions (the payload: see Transits in code); `@transit_link` returns it bound to the
  transit whose `source_link` is the method.

## Statuses and transits as data

Without `workflow.py` (or besides it, for what the admin changes), the statuses and
transits are rows:

- Statuses and transitions are data (`bazis.contrib.statusy.models`): create `Status`
  (string `id`) and `Transit` (`id`, `model` =
  `StatusyContentType.objects.get_for_model(Order)`, `status_src`, `status_dst`, lists of
  method names `validators`, `actions_before`, `actions_after`) in code or in the admin
  (Statusy > Status models: the transitions inline offers the decorated methods). Their
  names are the columns `name_en` and `name_ru` (as the roles of bazis-permit), whatever
  the languages of the project: a data migration sets both.
- `StatusyContentType` is a proxy of the `ContentType` of Django limited to the statusy
  models (its manager caches them: `StatusyContentType.objects.clear_cache()` in a test that
  creates the transits). A data migration has no proxy managers and runs before the content
  types are created: take the content type itself and set `model_id`:

  ```python
  def create_workflow(apps, schema_editor):
      content_type = apps.get_model('contenttypes', 'ContentType').objects.get_or_create(
          app_label='shop', model='order'
      )[0]
      status = apps.get_model('statusy', 'Status').objects
      draft = status.update_or_create(id='draft', defaults={'name_en': 'Draft', 'name_ru': 'Черновик'})[0]
      paid = status.update_or_create(id='paid', defaults={'name_en': 'Paid', 'name_ru': 'Оплачен'})[0]
      apps.get_model('statusy', 'Transit').objects.update_or_create(
          id='to_paid',
          defaults={
              'name_en': 'Pay', 'name_ru': 'Оплатить', 'model_id': content_type.pk,
              'status_src': draft, 'status_dst': paid,
              'validators': ['validator_paid'], 'actions_before': ['before_date'],
          },
      )
  ```

  Depend on `('contenttypes', '0002_remove_content_type_name')`, the latest migration of
  `statusy` and of the app of the model.
