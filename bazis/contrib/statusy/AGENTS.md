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
  (Statusy > Status models: the transitions inline offers the decorated methods).
- Optionally `router.register('bazis.contrib.statusy.router')` (read-only statuses, transits).

## API of a StatusyRouteSetBase route

- `POST /{item_id}/transit/` with `{"transit": "<transit id>", "payload": {...}}`: 200 with
  the item (204 if the user can no longer view it); 403 if the user has no permission for
  the transit or it does not start from the current status; 400 without a required
  payload; 422 with the errors of the payload and the validators.
- `GET /{item_id}/schema_transit/`: the schema the object must satisfy before a transit with
  `is_schema_validate` (default true).
- Meta: `state_actions` (retrieve: allowed transits, their body and `restricts` = the
  validator errors), `status_aggs` and `status_allowed` (list).

**Permissions.** On a statusy model the item permissions take the status of the object after the selector
(`all` or a status id); a transit is the operation `transit` with the transit id last:

```
shop.order.item.view.all.all
shop.order.item.change.author.draft              # change only in `draft`
shop.order.item.transit.author.draft.to_paid     # transit `to_paid` from `draft`
```

## Rules

- The status changes only through `POST /{item_id}/transit/`: the UPDATE schema of
  `StatusyRouteSetBase` has no `status` (a `PATCH` with it is ignored), and neither schema
  has `status_author`. The CREATE schema accepts an initial `status`
  (`BAZIS_STATUS_INITIAL` if omitted): restrict it with `add` permissions by status, or
  exclude it (`CrudApiAction.CREATE: SchemaFields(exclude={'status': None})`).
- Every JSON:API route that changes a statusy model inherits `StatusyRouteSetBase` (`statusy.W001`);
  the routes of `StatusyChildMixin` models inherit `StatusySimpleRouteSetBase`.
- Validators are also called with `payload is payload_validate_none` (to build
  `state_actions`): check it before reading the payload.
- Decorated methods are defined directly in a model class (or its mixin); `Transit` lists
  their method names. A transit runs in a transaction.
- A child object whose status is the parent's: `StatusyChildMixin` with
  `get_status_field()` returning the path (`'order__status_id'`); list its route in
  `routes_child` of the parent route to validate the children with it on a transit.
- A transit validates the item once with `JsonApiMixin.validate_item` (bazis 2.9.0):
  `changes.source == 'transit'`, `changes.fields` with `status`, `status_dt`,
  `status_author` and the fields the actions set, `changes.user` the user of the transit;
  a failure rolls the transit back (422 `ERR_ITEM_INVALID` on the transit endpoint). Keep
  the invariants of the item there (a validator of a transit checks only that transit).
- `item.transit_apply(transit, user, payload)` in code validates but does not check
  permissions; `@transit_link` returns it bound to the transit whose `source_link` is the
  method.
