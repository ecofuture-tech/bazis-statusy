# bazis-statusy — guide for AI agents

Statuses of objects and transitions between them (workflows): transitions (`Transit`) are
configured per model as data, run validators and actions that are methods of the model, and
are permissions of bazis-permit. Needs bazis-permit (and so bazis-users).

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
- The initial status of new objects is `BAZIS_STATUS_INITIAL` (default `["draft", "Draft"]`,
  `BS_BAZIS_STATUS_INITIAL='["new", "New"]'`); its `Status` row is created on first use.
- Statuses and transitions are data (`bazis.contrib.statusy.models`): create `Status`
  (string `id`) and `Transit` (`id`, `model` =
  `StatusyContentType.objects.get_for_model(Order)`, `status_src`, `status_dst`, lists of
  method names `validators`, `actions_before`, `actions_after`) in code or in the admin
  (Statusy > Status models: the transitions inline offers the decorated methods). Their
  names are the columns `name_en` and `name_ru` (as the roles of bazis-permit), whatever
  the languages of the project: a data migration sets both.
- Optionally `router.register('bazis.contrib.statusy.router')` (read-only statuses, transits).

## API of a StatusyRouteSetBase route

- `POST /{item_id}/transit/` with `{"transit": "<transit id>", "payload": {...}}`: 200 with
  the item (204 if the user can no longer view it); 403 if the user has no permission for
  the transit or it does not start from the current status (from bazis-permit 2.8.0, 404
  for an item the user cannot view, as for a missing one); 400 without a required
  payload; 422 with the errors of the payload and the validators.
- `GET /{item_id}/schema_transit/`: the schema the object must satisfy before a transit with
  `is_schema_validate` (default true).
- Meta: `state_actions` (retrieve: allowed transits, their body and `restricts` = the
  validator errors), `status_aggs` (list: the counts by status of the visible objects with
  the filter of the request without `status` and the search, applied by the services of
  the route as the list does, so restricted to what the route shows) and `status_allowed`
  (list).

**Permissions.** On a statusy model the item permissions take the status of the object after the selector
(`all` or a status id); a transit is the operation `transit` with the transit id last:

```
shop.order.item.view.all.all
shop.order.item.change.author.draft              # change only in `draft`
shop.order.item.transit.author.draft.to_paid     # transit `to_paid` from `draft`
```

## Rules

- The status changes only through `POST /{item_id}/transit/`: the UPDATE schema of
  `StatusyRouteSetBase` has no `status`, `status_dt`, `status_author` (a `PATCH` with them
  is ignored), the CREATE schema no `status_dt`, `status_author`; the `fields` of a route
  add up with them, do not exclude them again. The CREATE schema accepts an initial
  `status` (`BAZIS_STATUS_INITIAL` if omitted): restrict it with `add` permissions by
  status, or exclude it (`CrudApiAction.CREATE: SchemaFields(exclude={'status': None})`).
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
- A child object whose status is the parent's: `StatusyChildMixin` with
  `get_status_field()` returning the path (`'order__status_id'`); list its route in
  `routes_child` of the parent route to validate the children with it on a transit.
  `StatusyChildMixin` is a `PermitModelMixin` (as `StatusyMixin`): its objects are
  restricted by the permissions of the user, with selectors (`author`) and the status of
  the parent (`entity.order_item.item.view.author.draft`), on its route and through the
  relations (`included`, filters) of the other routes.
- A transit validates the item once with `JsonApiMixin.validate_item` (bazis 2.10.0):
  `changes.source == 'transit'`, `changes.fields` with `status`, `status_dt`,
  `status_author` and the fields the actions set, `changes.user` the user of the transit;
  a failure rolls the transit back (422 `ERR_ITEM_INVALID` on the transit endpoint). The
  source and the user come from the outermost block: a transit inside a write of a route
  (`hook_after_create`) is validated with that write, once, as `create` with the user of
  the route. Keep the invariants of the item there (a validator of a transit checks only
  that transit).
- `item.transit_apply(transit, user, payload)` in code validates but does not check
  permissions; `@transit_link` returns it bound to the transit whose `source_link` is the
  method.

## Transits in code and the history

- `item.get_transit('<transit id>')` is the transit of the model with that id that starts
  from the current status of the item, else None (check it); `item.instance_transits`
  are all of them. Take the transit of `transit_apply` with it.
- `item.transit_apply(transit, user, payload=None)` makes only a transit of the model of
  the item (its content type) that starts from the current status of the item, a transit
  `get_transit` gives: another one fails with 400 `ERR_TRANSIT`
  (`JsonApiBazisException`) before its validators, nothing written. It runs the
  validators (with `user`), writes the history record, runs the actions before, sets
  `status`, `status_dt`, `status_author`, runs the actions after and returns the item
  read again. It checks
  neither the permissions of `user` nor `is_schema_validate` (the transit endpoint does).
- The actor: `user` is the `author` of the history record and the `status_author`. A
  transit the system makes (an automatic confirmation, a task) passes `None`: the record
  has no author. Do not pass the user of the request for it: the history would say that
  he made a transit his permissions may not allow. A project that names its system actor
  passes a user of its own for it.
- An automatic transit on create, in `hook_after_create` of the route: by itself the
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
    ]),
]
```

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
  that is a transit of another model in the database stops `migrate`.
- Names: English msgids (`gettext_lazy`) translated into `name_en`/`name_ru` by the
  catalogs of the project (`statusy.W002` lists the untranslated ones).
- Tests: the test database is migrated, so the workflows are there, also after the flush
  of a test with `transaction=True`; `bazis_test_utils` gives `apply_declarations()` and
  the fixture `bazis_declared`.
- `bazis.contrib.statusy.declare.apply_declarations(using, workflows=None, dry_run=False)`
  returns the changes; `dry_run` only lists them.
- Checks: `statusy.E001` (the model is a `StatusyMixin`, one workflow per model, the ids,
  a transit between statuses of its workflow, a transit id unique among the models, one
  name per status), `statusy.E002` (a validator or action that is not a method of the
  model), `statusy.E003` (a permission of `roles.py` names a transit that is not declared
  for its model, or a status the transit does not start from), `statusy.W002`; with a
  database (`manage.py check --database default`, not `bazis_doctor`) `statusy.W003` (the
  database differs: migrate) and `statusy.W004`.
