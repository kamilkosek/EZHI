# APsystems EZHI – Home-Assistant-Integration

*[English version](README.md)*

## Überblick

Diese Integration bindet einen APsystems-EZHI-Wechselrichter über dessen lokale
API in Home Assistant ein: Sensoren für die Live-Werte, zwanzig Alarm-Sensoren
und die Leistungsvorgabe. Optional kommen drei Steuerwege dazu — Hersteller-Cloud,
Bluetooth oder ein lokaler MQTT-Broker.

Entitäts- und Feldnamen stehen hier absichtlich auf Englisch: so heißen sie in
Home Assistant und in der API des Geräts. Die weiterführenden Dokumente unter
`docs/` sind bislang nur auf Englisch.

## Funktionen

- **PV-Leistung und -Ertrag**: aktuelle Erzeugung und Gesamtertrag.
- **Batterie**: Zustand, Lade-/Entladeleistung, Temperatur, SOC und SOH.
- **Netz**: Leistungsfluss zum und vom Netz.
- **Alarme**: zwanzig Binärsensoren für Fehler und Warnungen.
- **Leistungssteuerung**: Sollwert für die Ausgangsleistung.
- **Getrennte Abfrageintervalle**: schnell für Leistungsdaten, langsamer für
  Alarme und Geräteinfos.
- **Zweisprachig**: englische und deutsche Übersetzungen enthalten.
- **Cloud-Steuerung (optional)**: An/Aus, Systemmodus, Notstrom (EPS), ECO,
  SOC-Grenzen — nichts davon existiert in der lokalen API. Wirklich optional:
  ohne Zugangsdaten wird der gesamte Steuerungs-Layer übersprungen und der volle
  lokale Funktionsumfang bleibt. Genau das bekommt auch eine bestehende
  Installation beim Update, ohne eine einzige Einstellung anzufassen.

## Voraussetzungen

1. Der Wechselrichter ist im lokalen Netz erreichbar.
2. Der lokale Modus ist in der APsystems-App aktiviert. Das Handbuch bindet
   ausschließlich den einen Schreibbefehl daran: *„This command only takes effect
   after enabling local mode in the APP"*. Das **Lesen** funktioniert gemessen in
   jedem Systemmodus — ein Wechselrichter in einem anderen Szenario füllt also
   trotzdem alle Sensoren. Ungetestet ist ein Gerät, das nie im lokalen Modus war.
3. Feste IP-Adresse für den Wechselrichter im Router (empfohlen).

## Installation

### HACS (empfohlen)

1. Dieses Repository in HACS als benutzerdefiniertes Repository hinzufügen
2. Integration über HACS installieren
3. Home Assistant neu starten
4. Integration über *Einstellungen → Geräte & Dienste* hinzufügen

### Manuell

1. Aktuelles Release herunterladen
2. Ordner `apsystems_ezhi_local` nach `custom_components` entpacken
3. Home Assistant neu starten
4. Integration über die Oberfläche hinzufügen

## Einrichtung

1. *Einstellungen → Geräte & Dienste*
2. Unten rechts auf „Integration hinzufügen"
3. Nach „APsystems EZHI Local API" suchen
4. IP-Adresse und Namen des Wechselrichters eintragen
5. Absenden

### Abfrageintervall ändern

Ohne Neueinrichtung über *Konfigurieren*:

- **Leistungsdaten**: schnelle Aktualisierung für `ogP`, `pvP`, `batP` (Vorgabe 5 s)
- **Alarme und Geräteinfos**: langsamer (Vorgabe 60 s)

Nach dem Absenden lädt die Integration selbstständig neu.

## Entitäten

### Sensoren

| Entität | Beschreibung | Einheit |
|---|---|---|
| Battery Status | Batteriezustand (Idle/Charging/Discharging/Fault/Shutdown/No Communication) | – |
| Photovoltaic Power | aktuelle PV-Erzeugung | W |
| Photovoltaic Energy | PV-Gesamtertrag | kWh |
| Battery Power | Lade-/Entladeleistung | W |
| Battery State of Charge | Ladezustand | % |
| Battery State of Health | Batteriegesundheit | % |
| Battery Temperature | Batterietemperatur | °C |
| Battery Total Charge Energy | insgesamt geladene Energie | kWh |
| Battery Total Discharge Energy | insgesamt entladene Energie | kWh |
| Battery Capacity | Batteriekapazität | kWh |
| On-Grid Power | Leistungsfluss zum/vom Netz | W |
| On-Grid Output Energy | ins Netz eingespeiste Energie | kWh |
| On-Grid Input Energy | aus dem Netz bezogene Energie | kWh |
| Off-Grid Power | Leistungsfluss im Off-Grid-Zweig | W |
| Off-Grid Output Energy | an Off-Grid-Lasten abgegebene Energie | kWh |
| Off-Grid Input Energy | aus Off-Grid-Quellen aufgenommene Energie | kWh |
| Device Temperature | Gerätetemperatur | °C |

### `outputData`-Sensoren (Bluetooth und lokales MQTT)

Auf den Transporten **Bluetooth** und **lokales MQTT** (siehe *Cloud-Steuerung →
Steuerungs-Transport*) liefert die `outputData`-Antwort Werte, die die lokale
HTTP-API nicht kennt: die DC-Batterie, die Netzqualität, die einzelnen PV-Strings,
den Off-Grid-Zweig und die Laufzeit seit dem letzten Neustart. Sie entstehen nur
auf diesen beiden Transporten — der Cloud-Transport hat keinen Lesebefehl dafür,
dort werden sie also gar nicht erst angelegt statt dauerhaft `unavailable` zu sein.

| Entität | Beschreibung | Einheit |
|---|---|---|
| Battery Voltage | DC-Batteriespannung | V |
| Battery Current | DC-Batteriestrom, vorzeichenbehaftet. Welches Vorzeichen Laden bedeutet, ist **nicht** verifiziert und wird roh übernommen, damit keine Vermutung in die Historie einwandert | A |
| PV1–PV3 Voltage / Current | Spannung und Strom je String | V / A |
| PV1 / PV2 Power | Leistung je String — die Antwort kennt kein `pv3P` | W |
| PV1–PV3 Total Energy | Gesamtertrag je String (`total_increasing`) | kWh |
| Device Temperature 2 / 3 | zwei weitere Innentemperaturen neben `devTemp` | °C |
| Grid Voltage | Netzspannung | V |
| Grid Frequency | Netzfrequenz | Hz |
| Off-Grid Voltage / Current | der Off-Grid-Zweig, von dem es bisher nur die Leistung gab | V / A |
| Uptime | Sekunden seit dem letzten Neustart — der einzige Weg zu bemerken, dass es einen gab | s |

Alle drei Strings werden angelegt. Ein String ohne Modul liest 0 — ein echter
Wert, kein „fehlt". Ob man solche Zeilen im Dashboard ausblendet, ist eine
Dashboard-Entscheidung und nicht in der Integration verdrahtet.

`outputData` hat insgesamt 50 Felder. Zehn weitere davon liegen als
**Diagnose-Sensoren** unter ihren Rohnamen bereit: `batCT`, `cMode`, `rS`, `mode`,
`reUpdate`, `metL1`, `metL2`, `metL3`, `metDC`, `freeRam`. Neun sind
standardmäßig deaktiviert; `freeRam` ist an, weil freier Heap als einziger davon
sich bewegt und ein über Tage fallender Verlauf die Frühwarnung für ein
Speicherleck der Firmware ist. Sie tragen **keine** Einheit, Geräteklasse oder
Zustandsklasse, weil ihre Bedeutung nicht feststeht — ein Sensor namens „Battery
Cycles" wäre eine Vermutung im Gewand einer Tatsache, `batCT` behauptet dagegen
nichts. Wer eines davon beobachten will, aktiviert es in den Entitäts-Einstellungen.

`apsystems_ezhi_local.ble_raw_get` ist eine Diagnose-Aktion: sie holt einen
Rohblock (Vorgabe `outputData`) und protokolliert die vollständige Antwort auf
WARNING — für Felder, die keine Sensoren sind, und für das Reverse Engineering der
Rohframes. Funktioniert über Bluetooth und über lokales MQTT.

### Gerätediagnose (lokale Transporte)

`deviceInfo` wird bei jeder Steuerungsabfrage ohnehin gelesen — der
WLAN-Signalsensor braucht es — und vierundzwanzig seiner Felder hatten bis v0.9.0
keine Entität. Jetzt sind es **Diagnose-Entitäten**: Firmware-Versionen, die
Netzwerkadresse, die Ländereinstellungen, die Hersteller-Codes unter ihren
Rohnamen und vier Verbindungs-Flags.

Sechs sind standardmäßig aktiv: **Firmware Version**, **Battery Firmware
Version**, **IP Address**, **Cloud Connected**, **WiFi Connected** und **Bluetooth
Enabled**. Die letzten beiden beantworten in einem Blick die Frage, die am meisten
Zeit kostet, wenn ein Transport ausfällt: *ist das Funkmodul überhaupt an?*

Der Rest ist aus, vier davon mit Absicht: `deviceId`, `ssid`, `bluetoothMac` und
`wifiMac` identifizieren dein Gerät und dein Netz — ein Update sollte sie nicht
ungefragt in deinen Recorder schreiben.

### Zusätzliche Diagnose-Abfragen (nur lokales MQTT)

Sechs Identifier beantworten ein `get` und werden sonst nirgends gelesen. Alle
einundzwanzig Entitäten daraus sind **standardmäßig deaktiviert** — sie erklären
Ausnahmefälle, und niemand sollte durch ein Update einundzwanzig Entitäten
geschenkt bekommen.

| Abfrage | Inhalt |
|---|---|
| `light` | die vier LED-Zustandscodes (`sys`, `ofg`, `bat`, `wifi`) |
| `alarm` | die rohen Bitmasken `dsp` / `battery` / `pv` |
| `supportFunction` | welche Funktionen die Firmware zugibt |
| `meterStatus` | der externe Zähler: Leistung, Signal, Kanal, Verbindungszähler |
| `btLock` | ob die Bluetooth-Kopplungssperre gesetzt ist |
| `bindDevice` | wie viele Geräte gekoppelt sind |

Das ist MQTT-exklusiv aus Konstruktion, nicht aus Vergesslichkeit: der
MQTT-Transport ordnet Antworten über eine Korrelations-ID zu, deshalb gehen alle
neun Abfragen eines Zyklus **gemeinsam** raus und werden innerhalb eines
Firmware-Takts beantwortet. Gemessen: zehn gleichzeitig abgefeuerte Identifier
sind nach 2,5–3,0 s zurück, eine einzelne sequenzielle Abfrage dauert 5,05 s.
Bluetooth ist eine serielle Strecke, dort wären dieselben Abfragen sechs weitere
Umläufe je Zyklus — deshalb entstehen diese Entitäten dort nicht.

Genau das lässt dreimal so viele Abfragen keine zusätzliche Wanduhr kosten: ein
Sammelaufruf ist ein Takt, egal wie viele Identifier darin stecken.

Die `alarm`-Bitmasken bleiben, obwohl die zwanzig dekodierten Schutzflags eigene
Binärsensoren haben. Die Masken tragen mehr: `pv` liest `…01100000…`, während
`PvHV` und `PVWE` im selben Moment beide 0 sind. Welches Bit was bedeutet, steht
nicht fest — deshalb gibt es die Rohzeichenkette.

**Nicht angelegt, jeweils aus geprüftem Grund:** `si` (alle zwanzig Flags haben
schon Binärsensoren), `wifiStatus`, `caTz` und `combineVersion` (jedes Feld steckt
bereits in `deviceInfo`), sowie `batteryCellData` — das auf keinem Transport ein
`get` beantwortet und dessen Push-Antwort leer ist (`{"cell": [], "cellStatus":
0}`). Dahinter liegen keine Zellspannungen, die man finden könnte.

### Binärsensoren (Alarme)

| Entität | Beschreibung | API-Feld |
|---|---|---|
| Battery Overtemperature | Batterie-Übertemperaturschutz aktiv | BatHTP |
| Battery Undertemperature | Batterie-Untertemperaturschutz aktiv | BatLTP |
| Battery Communication Error | Kommunikationsfehler zur Batterie | BatCE |
| Battery Overvoltage | Batterie-Überspannungsschutz aktiv | BatHV |
| Battery Undervoltage | Batterie-Unterspannungsschutz aktiv | BatLV |
| Battery Overcurrent | Batterie-Überstromschutz aktiv | BatHI |
| Battery Error | allgemeiner Batteriefehler | BatE |
| Battery Shutdown | Batterie abgeschaltet | SBS |
| Device Overtemperature | Geräte-Übertemperaturschutz aktiv | DTP |
| Device Error | allgemeiner Gerätefehler | EE |
| AC Abnormal | Netzanomalie erkannt | ACA |
| Off-Grid Overcurrent | Off-Grid-Überstromschutz aktiv | OfOI |
| Off-Grid Short Circuit | Off-Grid-Kurzschlussschutz aktiv | OfGS |
| PV Overvoltage | PV-Überspannungsschutz aktiv | PvHV |
| PV Overcurrent | PV-Überstromschutz aktiv | PvOC |
| PV Wiring Error | PV-Verdrahtungsfehler | PVWE |
| IRD Error | Fehler der Isolationswiderstandsmessung | IRDE |
| SOC Calibration Needed | SOC-Anzeige weicht ab — auf 100 % laden zum Kalibrieren | BCC |
| Battery Access Conflict | Batterie angeschlossen, während das Gerät batterielos läuft | BCI |
| Voltage Reset Protection | PV-Eingang zu niedrig oder Schutz nach Netzanomalie — Neustart nötig, kann mehrere Minuten dauern | VRP |

Die letzten drei meldet `getAlarm` auf aktueller Firmware. Auf Firmware, die sie
nicht sendet, lesen sie `unknown` statt „kein Problem".

Jeder Alarmsensor trägt den Herstellertext als Attribute — `cause` und
`suggested_action`, dazu `vendor_name` und `alarm_code`. Ein Sensor, der auf
*Problem* geht, sagt also auch, was die App dir gesagt hätte. Deutsch, wenn Home
Assistant auf Deutsch steht, sonst Englisch. Vom Recorder ausgenommen, weil statisch.

→ **[docs/alarms.md](docs/alarms.md)** hat alle zwanzig Codes vollständig, dazu
zwei Dinge, die man vor einer Automation darauf wissen sollte: manche Alarme sind
Transienten, die die 60-Sekunden-Abfrage verpasst, und manche erwarteten Alarme
kommen überhaupt nie.

### Steuerungen

- **Max Output Power**: der On-Grid-Sollwert, −1200 W bis +1200 W. **Positiv
  entlädt ins Netz, negativ lädt daraus** — gemessen, und das Gegenteil dessen,
  was diese Datei bis v0.5.2 behauptete.

> **Das wirkt nur im Systemmodus „Local".** Das Handbuch sagt es in einer Zeile
> unter `setPower`, und es ist leicht zu überlesen. Gemessen über alle vier Modi
> mit Sollwert −300 W: in Local folgte der Wechselrichter (Netzfluss von −146 W
> auf +272 W), in Balcony Storage, Portable und AI ignorierte er ihn und fuhr
> seine eigene Strategie. `setPower` antwortet in **jedem** Modus mit `SUCCESS` —
> ein wirkungsloser Schreibvorgang sieht also genauso aus wie ein wirksamer.
> Deshalb protokolliert die Integration eine Warnung, wenn außerhalb von Local
> geschrieben wird.

## Cloud-Steuerung (optional)

Die lokale API ist bis auf `setPower` nur lesend. An/Aus, Systemmodus und
**Notstrom (EPS)** gibt es dort gar nicht — sie existieren nur in der APsystems-
EMA-Cloud. Diese Integration kann mit ihr als zweiter, vollständig getrennter
Schicht sprechen.

**Die lokale Seite hängt nie davon ab.** Die Cloud läuft auf einem eigenen
Koordinator: tote Zugangsdaten, eine unerreichbare Cloud oder eine hängende
Anfrage betreffen ausschließlich die Cloud-Entitäten. Gegen eine laufende
Installation geprüft: mit absichtlich zerstörtem Token gingen alle vier
Cloud-Entitäten auf `unavailable`, und alle 130 lokalen Entitäten behielten ihre
Werte.

### Ohne Zugangsdaten

**Lässt du die Felder leer, bekommst du die Integration so, wie sie vor all dem
war.** Der gesamte Steuerungs-Layer wird übersprungen, es entsteht **keine**
einzige Cloud-, Bluetooth- oder MQTT-Entität — abwesend, nicht dauerhaft
`unavailable`. Übrig bleibt der vollständige Satz der lokalen HTTP-API: alle
Sensoren aus der Tabelle oben, die zwanzig Alarm-Binärsensoren und `setPower`.

Das ist auch der Normalfall. Ein Eintrag, der nie einen Transport gewählt hat,
löst zu **Cloud** auf, und Cloud ohne Zugangsdaten heißt: kein Steuerungs-Layer.
Eine Installation, die auf diese Version aktualisiert, verhält sich also exakt
wie vorher, ohne dass man etwas anfasst.

Zwei Folgerungen, weil beide nicht offensichtlich sind:

- **Bluetooth ohne Zugangsdaten bleibt ebenfalls aus.** Es ist kein cloud-freier
  Modus: das Funkmodul schaltet sich nach 15 Minuten Ruhe ab, und der einzige
  unbeaufsichtigte Weg, es wieder zu öffnen, ist der Cloud-Aufruf `btOnOff`. Ein
  Bluetooth-Transport ohne Konto wäre einer, der sich nicht selbst erholen kann.
- **Lokales MQTT ist die bewusste Ausnahme.** Es ist der einzige Transport ohne
  Hersteller-Konto, deshalb öffnet seine Wahl den Layer von selbst. Ihn zu wählen
  ist ein ausdrücklicher Akt — nichts fällt automatisch darauf zurück.

Das ist durch Tests festgenagelt (`tests/test_transport_choice.py`) statt der
Sorgfalt überlassen: es ist die häufigste Installation und genau die Art Zusage,
die ein späterer Umbau bricht, ohne dass es jemand merkt, bis Entitäten fehlen.

### Einrichtung der Cloud

*Einstellungen → Geräte & Dienste → APsystems EZHI → Konfigurieren*, dann
**Benutzernamen** und Passwort des EMA-Kontos eintragen. Die Integration führt
dieselbe Anmeldung durch wie die App und speichert das Token-Paar.

> Der **Benutzername**, nicht die E-Mail-Adresse, mit der man sich ebenfalls
> anmelden kann — `loginEncrypt` weist die Adresse ab. Gegen ein echtes Konto
> verifiziert.

**Das Passwort wird einmal verwendet und nie gespeichert** — nur die Tokens landen
im Konfigurationseintrag, und der `refresh_token` rotiert nicht, die Anmeldung
muss also nur einmal gelingen. Deshalb bleiben die Kontofelder danach leer; zum
Kontowechsel füllt man sie erneut aus.

### Steuerungs-Transport: Cloud, Bluetooth oder lokales MQTT

*Konfigurieren → Control transport* entscheidet, über welche Leitung die
Steuerbefehle gehen. Vorgabe ist **Cloud**, und eine bestehende Installation
behält das beim Update.

| Transport | Was er braucht | Was er bringt |
|---|---|---|
| **Cloud** | ein Hersteller-Konto | An/Aus, Systemmodus, Notstrom, ECO, SOC-Grenzen |
| **Bluetooth** | einen Adapter oder ESPHome-Proxy in Reichweite — **und** die Cloud-Zugangsdaten, die zum Öffnen des Funkfensters weiter gebraucht werden | dieselben Befehle ohne Umweg über einen Hersteller-Server, dazu die `outputData`-Sensoren |
| **Lokales MQTT** | gar kein Hersteller-Konto — dafür muss der Wechselrichter auf einen eigenen Broker umgeleitet werden | alles von Bluetooth und mehr: der ganze Abfragezyklus in einem Umlauf, plus die Diagnose-Abfragen |

**Lokales MQTT ist der einzige Transport ohne Hersteller-Konto.** Die Verbindung
des Wechselrichters zu seiner Cloud *ist* MQTT, und er prüft nichts an dem Broker,
auf dem er landet — kein Certificate Pinning, kein gegenseitiges TLS. Lenkt man
seinen Verkehr auf einen Broker im eigenen Netz, hat man den Steuerkanal des
Herstellers selbst, ohne Hersteller-Server dazwischen.

Der Haken lässt sich nicht wegkonstruieren: **der Wechselrichter hat kein
Adressfeld für seinen Broker.** Der Hostname steckt fest in der Firmware, die
Umleitung muss also im Netz passieren — am Namen (DNS) oder am Paket (Routing).

> **[ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute)** ist ein
> Home-Assistant-Add-on, das die Routing-Variante übernimmt. Es findet den
> Wechselrichter, löst den Hersteller-Endpunkt selbst auf — die Adresse ist
> regional, eine fest eingetragene wäre also nur in genau einem Teil der Welt
> richtig —, nennt dir die exakte statische Route für deinen Router und meldet
> anschließend am Paketzähler, ob dein Router tatsächlich weiterleitet.

→ **[docs/local-control.md](docs/local-control.md)** behandelt die vier
Umleitungs-Mechanismen und für jeden die Frage, ob du ihn von unterwegs wieder
zurücknehmen kannst — das ist ein Auswahlkriterium, kein Detail. Dort stehen auch
die Anforderungen an den Broker und die Bridge-Variante, mit der die
Hersteller-App weiterläuft.

### Entitäten der Steuerung

| Entität | Typ | Anmerkung |
|---|---|---|
| Inverter On | `switch` | **Einwegschalter.** Einmal aus, fällt der Wechselrichter von der MQTT-Verbindung der Cloud und lässt sich nicht mehr aus der Ferne einschalten — er braucht PV-/DC-Eingang oder 3 s Druck auf die Batterietaste. |
| System Mode | `select` | Balcony Storage, Portable, AI, Local, No Battery. Betriebsszenarien, nicht der Local-API-Schalter: die lokale API antwortete in jedem davon. |
| Backup Power (EPS) | `switch` | Schließt ECO aus — eines einzuschalten löscht das andere in einem Schreibvorgang. |
| ECO Mode | `switch` | Die Gegenpolitik zu EPS für dieselbe Ausgangsstufe: EPS hält den Off-Grid-Ausgang scharf, ECO lässt ihn nach einer Stunde ohne Last fallen. |
| Smart Linking | `switch` | Der `thirdLink`-Hauptschalter, an dem ein Smart Meter hängt. Verweigert im Modus Local. |
| SOC Minimum / Maximum | `number` | Prozent. |
| Discharge Protection | `number` | Verweigert unterhalb *SOC-Minimum + 2 %* — dieselbe Regel wie in der App. |
| Preset Output Power | `number` | Watt. |
| Power Limit | `sensor` | Nur lesend. |

### Smart Linking (`thirdLink`)

Der Hauptschalter für das „Smart Linking" der Hersteller-App — daran hängt ein
Smart Meter (Shelly, EcoTracker). Hier deshalb nützlich, weil **die App beides
koppelt**: schaltet man Linking dort ein, lässt sie nur noch Nulleinspeisung zu,
nie Überschusseinspeisung mit bedarfsgeführter Entladung. Den Hauptschalter aus
Home Assistant zu bedienen lässt dir diese Wahl.

**Mit dem Modus Local nicht kombinierbar.** Linking einzuschalten schiebt das
Gerät nach Balcony, und Local ist der einzige Modus, in dem ein lokaler
`setPower`-Sollwert befolgt wird — der Schalter verweigert also, statt das still
geschehen zu lassen.

→ **[docs/local-control.md](docs/local-control.md#smart-linking-thirdlink-in-full)**
für die drei Werte des Feldes (es ist kein Boolean) und was noch ungetestet ist.

### High-Power-Modus

Die Ausgangsgrenze liegt bei 800 W und lässt sich auf 1200 W anheben. Die App
stellt einen Warnhinweis davor: das könne „dazu führen, dass die Geräteausgabe die
regulatorischen Grenzen für den Netzanschluss überschreitet", mit dem rechtlichen
Risiko beim Betreiber.

Home Assistant kennt für Entitäten keinen Bestätigungsdialog — ein Schalter ist
immer nur ein Tippen — deshalb ist das eine Aktion:

```yaml
action: apsystems_ezhi_local.set_high_power_mode
data:
  enable: true
  acknowledge_regulatory_risk: true   # nur beim Einschalten nötig
```

Das Absenken wird verweigert, solange der Wochenplan noch Einträge oberhalb der
neuen Grenze hat. Die App schreibt die still um; diese Integration nennt dir die
störenden Einträge und lässt deinen Plan in Ruhe.

### Sicherheitsverhalten

Zwei Schreibvorgänge werden verweigert statt durchgereicht:

- **„No Battery"-Modus bei angeschlossener Batterie** — der „Battery Access
  Conflict", vor dem auch die App warnt. Die Sperre hebt sich selbst auf, sobald
  die Cloud keine Batterie mehr meldet.
- **Entladeschutz unterhalb SOC-Minimum + 2 %** — sonst klemmt das Gerät den Wert
  still ab.

### Bekannte Grenzen

**Was ECO tatsächlich spart, ist ungemessen.** Seine dokumentierte Aufgabe ist es,
die Off-Grid-Ausgangsstufe abzuschalten, wenn eine Stunde lang nichts daran
gezogen hat — das Gegenteil dessen, was EPS mit derselben Stufe tut, weshalb die
Firmware beide als exklusiv behandelt. Ein A/B auf der Entwicklungsinstallation
zeigte in beiden Stellungen rund 17 W Standby, was die Frage nicht klärt: eine
Ersparnis kann erst auftreten, wenn der Off-Grid-Ausgang steht, nichts daran
zieht und die Stunde um ist.

Zwei weitere geräteseitige Einstellungen sind in der Cloud-Konfiguration lesbar,
haben aber keinen bekannten Schreibweg:

- **`winter`** — ein Feld unklarer Wirkung, das hier nichts schreibt. Die App
  bringt Übersetzungen für einen „Winter Adaptive Button" mit, der den SOC-Boden
  auf 50 % und den Entladeschutz auf 65 % anheben soll, aber **kein Bildschirm der
  App verwendet sie**. Auf der Entwicklungsinstallation liest `winter` „1",
  während die Batterie auf 52 % gefallen ist — deutlich unter den beschriebenen
  65 %. Das Flag ist also entweder wirkungslos oder in dieser Firmware nicht
  umgesetzt. Dokumentiert, damit es niemand neu herleitet und, wie ich zuerst,
  eine schlicht nicht weiter entladene Batterie für einen durchgesetzten Boden hält.
- **Der Wochenplan** (`outputPowerStrategyWeekly`) wird gelesen, um die
  Leistungsgrenze zu prüfen, und nie geschrieben. `isOPStrategy: 1` heißt nicht,
  dass er wirkt — im Modus Local ist er untätig: gemessen 1125 W Ausgang innerhalb
  eines Fensters, das der Plan auf 50 W begrenzt.

## Beispiel-Dashboard

→ **[docs/dashboard.md](docs/dashboard.md)** — eine Lovelace-Ansicht für die
gängigen Entitäten, zum Einfügen.

## API-Endpunkte

→ **[docs/api.md](docs/api.md)** — die Endpunkte der lokalen HTTP-API, um den
Wechselrichter auch außerhalb dieser Integration auszulesen.

## Fehlersuche

- **Keine Verbindung**: prüfen, ob der Wechselrichter im Netz erreichbar ist. Der
  Systemmodus ist nicht die Ursache — die lokale API antwortete im Test in allen
  vier Modi, ein anderer Modus als Local erklärt also keine fehlenden Sensordaten.
- **Der Sollwert bewirkt nichts**: Systemmodus prüfen. `setPower` wird in jedem
  Modus angenommen und mit `SUCCESS` beantwortet, befolgt aber nur in Local.
- **Bei einem Stromausfall** antwortet der Wechselrichter weiter: er läuft auf der
  Batterie, bleibt im WLAN und bedient alle vier Endpunkte, `getAlarm` inklusive.
  Über drei Ausfälle gemessen, ohne eine verlorene Anfrage. Ausfallende Sensoren
  sehen also **nicht** nach Stromausfall aus — das ist ein Netzwerkproblem.
- **Entitäten `unavailable`**: prüfen, ob das Gerät läuft.
- **Alte Werte**: Abfrageintervall in den Optionen verkürzen.

## Änderungsverlauf

→ **[CHANGELOG.md](CHANGELOG.md)** — jedes Release seit v0.1.2, mit dem, was
gemessen wurde, und der Begründung jeder Änderung.

## Lizenz

MIT.

---

*Diese Integration basiert auf der [APsystems EZ1 API Home Assistant Integration](https://github.com/SonnenladenGmbH/APsystems-EZ1-API-HomeAssistant) von Sonnenladen GmbH.*
