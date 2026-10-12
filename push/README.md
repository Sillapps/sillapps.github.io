# Push (Firebase Cloud Messaging, 0 $)

Server side of the push alerts of the simple Sillapps apps. No server and no
user database: an app subscribes to a **topic** while its alert is on, and a
scheduled workflow of this public repo sends one message to the topic when the
data is out. Cost: 0 $ (FCM is free, Actions minutes are free on a public repo).

- Firebase project **sillapps-push** (account sillapps.pro@gmail.com), shared by
  the simple apps, like their shared upload key. Before selling an app, move it
  to its own Firebase project (new config files, new topic, one app release).
- Sending: `fcm.py` (FCM HTTP v1). The workflow gets a short-lived Google token
  through Workload Identity Federation (`setup_wif.sh`, run once): no key file,
  and only this repo can act as the `fcm-sender` service account.
- Topics say nothing about the user (no suburb, no fuel): the app makes its own
  message from its own settings (Android) or shows a generic one (iOS).
- iOS needs the APNs key of the Apple Developer account uploaded in the
  Firebase project (Project settings, Cloud Messaging). Until then, Android only.

| App | Script | Workflow | Topic (debug builds) | When |
|---|---|---|---|---|
| Fuel Tomorrow WA | `fuel_wa.py` | `push-fuel-wa.yml` | `fuelwa-tomorrow` (`fuelwa-test`) | FuelWatch publishes tomorrow's prices, 2:30pm Perth |
| Placa Hoy | `placa_hoy.py` | `push-placa-hoy.yml` | `placahoy-contingency` (`placahoy-test`) | Each new contingency communiqué on aire.cdmx.gob.mx, checked every 10 min, 10:00-22:30 Mexico City |
| Scioperi Oggi | `scioperi.py` | `push-scioperi.yml` | `scioperi-list` (`scioperi-test`) | A strike added, revoked or removed from the MIT list, checked every 30 min, about 7:00-21:30 Rome. The push only wakes the app (Android data, iOS background): the app decides what to tell |
| Dia do Pagamento | `beneficios.py` | `push-beneficios.yml` | `beneficios-<program id>` (`beneficios-test-<program id>`) | Each publication of `beneficios/calendars.json` that adds payment dates to a program; test: `gh workflow run push-beneficios.yml -f program=br_bolsa_familia` |

Test without touching users: `gh workflow run push-fuel-wa.yml -f topic=fuelwa-test -f force=true`
(or `push-placa-hoy.yml -f topic=placahoy-test -f force=true`, `push-scioperi.yml -f topic=scioperi-test -f force=true`) reaches debug builds only. Locally: `python3 push/fuel_wa.py --check`, `python3 push/placa_hoy.py --check`.

A new app: a script next to `fuel_wa.py` (check the source, build the message,
`fcm.send`), a workflow copied from `push-fuel-wa.yml`, its Android and iOS apps
added to sillapps-push (`firebase apps:create … --project sillapps-push`), a line
in the table above.
