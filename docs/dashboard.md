# Example dashboard

The integration creates 47 entities. `examples/` has a dashboard that sorts
them into something usable — power right now, battery, controls, energy
totals, alarms, history:

| File | Needs |
|------|-------|
| [`examples/dashboard.yaml`](../examples/dashboard.yaml) | [Mushroom](https://github.com/piitaya/lovelace-mushroom) and [fold-entity-row](https://github.com/thomasloven/lovelace-fold-entity-row) from HACS |
| [`examples/dashboard-core.yaml`](../examples/dashboard-core.yaml) | nothing — built only from cards Home Assistant ships with |

Same layout either way. Without the two custom cards installed, the first file
renders "Custom element doesn't exist" where they would be, so take the second
one if you would rather not install anything.

Settings → Dashboards → Add dashboard → New dashboard from scratch, then paste
the file into the raw configuration editor (pencil → three dots → Raw
configuration editor).

**Both files assume the integration was added with the name `ezhi`.** Replace
that throughout if you used something else. Upgrading from 0.4.0 or earlier?
Entity ids are handed out once, at first registration, so an existing install
keeps the ones it already has — and there the cloud entities and the local
power number carry an extra `apsystems_` (`switch.apsystems_ezhi_backup_power`).
The exact ids for your install are on the device page.

The control section is marked for deletion if you do not use cloud control. It
is not hidden by a conditional card on purpose: the frontend's condition check
reads `hass.states[entity]?.state`, so for an entity that does not exist at all
a `state_not: unavailable` condition evaluates true — the card would appear
exactly when it should not.

