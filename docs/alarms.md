# Alarm codes

The 20 fields `getAlarm` returns, with the vendor's own wording for each.
`"1"` means active, `"0"` means clear.

The English and German text comes from the translation bundles inside the
AP EasyPower Android app, so it is what the app itself would show you. The
app builds its alarm screen from whatever keys the response contains rather
than from a fixed list, looking up `<CODE>_name`, `<CODE>_reason` and
`<CODE>_suggest` for every field set to `"1"`. That is why `BCC` displays
in the app although it appears in no version of the vendor's Local API
manual, including the current V1.3 (2026-02-04) — the device sends the
field, and the app does not ask whether it is allowed to know it.

`docs/alarms.json` carries the same content in machine-readable form, for
anyone driving the API from Node-RED or a script rather than from this
integration.

The vendor's own translation is rough in places: `VRP`'s German name
repeated itself, `PvOC` and `IRDE` were left as untranslated labels, `EE`
and `OfOI` were named after a "host" the manual never mentions, and one
suggestion numbered its steps 1 and 3. TheExpert corrected those in
2026-08-07 and filled the gaps; the meanings are the vendor's, the German
now reads like German. Where the app's text was already right it was left
alone.

## `BatHTP` — Battery High Temperature Protection

**Deutsch:** Batterie-Hochtemperaturschutz

Manual: *battery high temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the battery is too high 2. Excessive number of high-power continuous charging and discharging 3. Internal fault of the battery |
| DE | 1. Die Umgebungstemperatur der Batterie ist zu hoch 2. Zu viele kontinuierliche Lade- und Entladevorgänge mit hoher Leistung 3. Interner Fehler der Batterie |

| | Suggested action |
|---|---|
| EN | 1. Check if the ambient temperature is within the allowable operating range. 2. Has high-power charging and discharging been performed multiple times? If so, reduce such operations after the battery cooled down. 3. If the ambient temperature is normal, contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Betriebsbereichs liegt. 2. Wurden mehrmals Hochleistungsaufladungen und -entladungen durchgeführt? Wenn ja, reduzieren Sie solche Vorgänge, nachdem die Batterie abgekühlt ist. 3. Wenn die Umgebungstemperatur normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BatLTP` — Battery Low Temperature Protection

**Deutsch:** Batterie-Niedertemperaturschutz

Manual: *battery low temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the battery is too low 2. Internal fault of the battery |
| DE | 1. Die Umgebungstemperatur der Batterie ist zu niedrig 2. Interner Fehler der Batterie |

| | Suggested action |
|---|---|
| EN | 1. Check if the ambient temperature is within the allowable operating range. 2. If the ambient temperature is normal, contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Betriebsbereichs liegt. 2. Wenn die Umgebungstemperatur normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BatCE` — Battery Communication Error

**Deutsch:** Batteriekommunikationsfehler

Manual: *battery communication error*

| | Cause |
|---|---|
| EN | 1. The battery is not connected to the main unit 2. The cable is damaged 3. The communication function of the battery or the inverter is abnormal |
| DE | 1. Der Akku ist nicht mit dem Hauptgerät verbunden. 2. Das Kabel ist beschädigt. 3. Die Kommunikationsfunktion des Akkus oder des Wechselrichters ist abnormal |

| | Suggested action |
|---|---|
| EN | 1. Check that the cable is connected correctly. 2. Check the cable for damage. 3. If it is normal, please contact the dealer or after-sales service. |
| DE | 1. Überprüfen Sie, ob das Kabel richtig angeschlossen ist. 2. Überprüfen Sie das Kabel auf Beschädigungen. 3. Wenn alles normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `BatHV` — Battery overvoltage

**Deutsch:** Batterieüberspannung

Manual: *battery overvoltage*

| | Cause |
|---|---|
| EN | 1. Battery overcharged 2. Battery failure |
| DE | 1. Batterie überladen 2. Batterieausfall |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery SOC is within the safe range. If not, please perform charging and discharging operations. 2. If the SOC is normal, please contact the dealer or after-sales service. |
| DE | 1. Überprüfen Sie, ob der Ladezustand der Batterie im sicheren Bereich liegt. Wenn nicht, führen Sie bitte Lade- und Entladevorgänge durch. 2. Wenn der SOC normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `BatLV` — Battery undervoltage

**Deutsch:** Unterspannung der Batterie

Manual: *battery undervoltage*

| | Cause |
|---|---|
| EN | 1. Battery discharged 2. Battery failure |
| DE | 1. Batterie entladen 2. Batterieausfall |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery SOC is within the safe range. If not, please perform charging and discharging operations. 2. If the SOC is normal, please contact the dealer or after-sales service. |
| DE | 1. Überprüfen Sie, ob der Ladezustand der Batterie im sicheren Bereich liegt. Wenn nicht, führen Sie bitte Lade- und Entladevorgänge durch. 2. Wenn der SOC normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `BatHI` — Battery High Current

**Deutsch:** Batterie hoher Strom

Manual: *battery over current*

| | Cause |
|---|---|
| EN | 1. The battery output power is too high 2. Short circuit at the output of the battery 3. Host failure |
| DE | 1. Die Ausgangsleistung der Batterie ist zu hoch 2. Kurzschluss am Ausgang der Batterie 3. Host-Fehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the load and grid-connected power are too large. 2. Check whether the battery output is short-circuited. 3. If it is normal, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Last und die an das Netz angeschlossene Leistung zu groß sind. 2. Prüfen Sie, ob der Batterieausgang kurzgeschlossen ist. 3. Wenn alles normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `BatE` — Battery Error

**Deutsch:** Batteriefehler

Manual: *battery error*

| | Cause |
|---|---|
| EN | 1. Battery BMS failure 2. Battery system failure |
| DE | 1. Batterie-BMS-Fehler 2. Batteriesystemfehler |

| | Suggested action |
|---|---|
| EN | Please contact the dealer or after-sales service. |
| DE | Bitte kontaktieren Sie den Händler oder den Kundendienst. |

## `DTP` — Device Temperature Protection

**Deutsch:** Gerätetemperaturschutz

Manual: *device temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the inverter is too high or too low 2. Internal failure of the inverter |
| DE | 1. Die Umgebungstemperatur des Wechselrichters ist zu hoch oder zu niedrig 2. Interner Fehler des Wechselrichters |

| | Suggested action |
|---|---|
| EN | 1. Check whether the ambient temperature is within the allowable use range. 2. If the ambient temperature is normal, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Nutzungsbereichs liegt. 2. Wenn die Umgebungstemperatur normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `EE` — Device Error

**Deutsch:** Gerätefehler

Manual: *device error*

| | Cause |
|---|---|
| EN | Host internal fault  |
| DE | Interner Fehler |

| | Suggested action |
|---|---|
| EN | 1. Please turn off the battery, grid, PV, and restart the device. 2. If the system does not recover after restarting, please contact your dealer or after-sales service. |
| DE | 1. Bitte schalten Sie die Batterie, das Stromnetz und die PV aus und starten Sie das Gerät neu. 2. Wenn das Problem nach dem Neustart nicht behoben wird, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `SBS` — Battery shutdown

**Deutsch:** Batterieabschaltung

Manual: *battery shutdown*

| | Cause |
|---|---|
| EN | 1. Battery physical button shutdown 2. APP device switch button to shut down |
| DE | 1. Abschaltung über die physikalische Batterietaste 2. Abschaltung über die Geräteschaltfläche in der APP |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery physical button and APP device power button are turned off 2. If the system does not recover after turning on the battery, please contact your dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die physikalische Batterie-Taste und die Geräte-Ein/Aus-Taste in der APP ausgeschaltet sind. 2. Wenn das Problem auch nach dem Einschalten der Batterie weiterhin besteht, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `ACA` — AC Abnormal

**Deutsch:** On-Grid Strom fehlerhaft

Manual: *ac abnormal*

| | Cause |
|---|---|
| EN | 1. On Grid overvoltage, undervoltage or no grid 2. On Grid overfrequency or underfrequency |
| DE | 1. Das Netz ist über-, unter- oder gar nicht mit Strom versorgt 2. Über- oder Unterfrequenz des Stromnetzes |

| | Suggested action |
|---|---|
| EN | 1. Check the status of the power grid and the wiring. If it happens occasionally, you can wait for the power grid to return to normal. 2. If it is triggered for a long time, please contact the electricity operator. |
| DE | 1. Überprüfen Sie den Status des Stromnetzes und der Verkabelung. Wenn es gelegentlich vorkommt, können Sie warten, bis das Stromnetz wieder normal ist. 2. Wenn das Problem über einen längeren Zeitraum auftritt, wenden Sie sich bitte an den Stromanbieter. |

## `OfOI` — Off Grid Over Current

**Deutsch:** Off-Grid Strom zu hoch

Manual: *off grid over current alarm*

| | Cause |
|---|---|
| EN | 1. The power of the off-grid access load exceeds the usage limit 2. Not connected to the grid 3. Inverter failure |
| DE | 1. Die Leistung der netzunabhängigen Zugangslast überschreitet das Nutzungslimit 2. Nicht mit dem Netz verbunden 3. Wechselrichterfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the off-grid load exceeds the allowable power range. 2. Check whether the inverter is connected to the grid. 3. If it is normal, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die netzunabhängige Last den zulässigen Leistungsbereich überschreitet. 2. Prüfen Sie, ob der Wechselrichter mit dem Netz verbunden ist. 3. Wenn alles normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `PvHV` — PV High Voltage

**Deutsch:** PV-Spannung zu hoch

Manual: *pv high voltage*

| | Cause |
|---|---|
| EN | 1. The component configuration is inappropriate 2. The component is not properly connected to the inverter 3. Component failure 4. Inverter failure |
| DE | 1. Die Komponentenkonfiguration ist ungeeignet 2. Die Komponente ist nicht ordnungsgemäß mit dem Host verbunden 3. Komponentenfehler 4. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the PV is connected to the inverter normally. 2. Check whether the PV output voltage exceeds the allowable range of the inverter. 3. Check if the component is working properly. 4. If it is normal, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die PV normal an den Wechselrichter angeschlossen ist. 2. Prüfen Sie, ob die PV-Ausgangsspannung den zulässigen Bereich des Wechselrichters überschreitet. 3. Prüfen Sie, ob die Komponente ordnungsgemäß funktioniert. 4. Wenn alles normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `PvOC` — PV Over Current

**Deutsch:** PV-Strom zu hoch

Manual: *pv over current*

| | Cause |
|---|---|
| EN | 1. The component configuration is inappropriate 2. Component failure 3. Host failure |
| DE | 1. Die Komponentenkonfiguration ist ungeeignet 2. Komponentenfehler 3. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the PV output current exceeds the allowable use range. 2. Check if the component is working properly. 3. If it is within the scope, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob der PV-Ausgangsstrom den zulässigen Anwendungsbereich überschreitet. 2. Prüfen Sie, ob die Komponente richtig funktioniert. 3. Wenn es innerhalb des Bereichs liegt, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `IRDE` — Isolation Restistance Detection Error

**Deutsch:** Isolation Restistance Detection Fehler: Isolationswiederstand DC zu gering

Manual: *IRD error*

| | Cause |
|---|---|
| EN | 1. PV input impedance is abnormal 2. Host failure |
| DE | 1. PV-Eingangsimpedanz ist abnormal 2. Host-Fehler |

| | Suggested action |
|---|---|
| EN | 1. Please turn off the battery, grid, PV, and restart the device. If the system does not recover after restarting, please contact your dealer or after-sales service. |
| DE | 1. Bitte schalten Sie die Batterie, das Stromnetz und die PV aus und starten Sie das Gerät neu. Wenn das Problem nach dem Neustart nicht behoben wird, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `PVWE` — PV Connection Error

**Deutsch:** PV-Verbindungsfehler

Manual: *pv wiring error*

| | Cause |
|---|---|
| EN | 1. Positive and negative poles of different components are mixed and connected to the same input circuit 2. Two input circuits are connected in parallel to the same photovoltaic source 3. The main unit has a malfunction |
| DE | 1.Die positive und negative Pole verschiedener Komponenten werden in der gleichen Eingangsleitung gemischt angeschlossen 2. Zwei Eingänge werden parallel an die gleiche PV-Anlage angeschlossen 3. Der Wechselrichter ist defekt |

| | Suggested action |
|---|---|
| EN | 1. Please turn off the battery and the power grid, connect the photovoltaic source correctly and then restart the device. If the system does not recover after restarting, please contact the dealer or after-sales service. |
| DE | 1.Bitte trennen Sie die Batterie und das Stromnetz, verbinden Sie die PV-Anlage richtig und starten Sie das Gerät neu. Wenn das Problem nach dem Neustart nicht behoben wird, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `OfGS` — Off Grid Short Circuit

**Deutsch:** Kurzschluss auf der netzunabhängigen Seite

Manual: *off grid short circuit*

| | Cause |
|---|---|
| EN | 1. The off-grid side connection line is damaged 2. Electrical appliances on the off-grid side are damaged 3. Host failure |
| DE | 1. Das netzunabhängige Verbindungskabel ist beschädigt 2. Elektrogeräte auf der Off-Grid-Seite sind beschädigt 3. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check if the off-grid side connection line is short-circuited. 2. Check whether the off-grid appliances are short-circuited. 3. If it is normal, please contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Verbindungskabel zur Off-Grid-Seite kurzgeschlossen sind. 2. Prüfen Sie, ob die Off-Grid-Geräte kurzgeschlossen sind. 3. Wenn alles normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BCI` — Battery Access Conflict

**Deutsch:** Batterieanschluss Konflikt

Manual: *Battery_Connection_Issue*

| | Cause |
|---|---|
| EN | Battery is connected in battery-free mode |
| DE | Batterie im batterielosen Modus angeschlossen |

| | Suggested action |
|---|---|
| EN | 1. Ensure that EZHI is not connected to a battery. 2. Set other working modes besides the battery-free mode. |
| DE | 1. Stellen Sie sicher, dass EZHI nicht an eine Batterie angeschlossen ist. 2. Stellen Sie andere Arbeitsmodi als den batterielosen Modus ein. |

## `VRP` — Voltage Reset Protection

**Deutsch:** Spannungsrücksetzschutz

Manual: *Voltage_Reset Protection*

| | Cause |
|---|---|
| EN | 1. PV terminal power is too low. 2. Protection against grid anomalies or overloads. |
| DE | 1. PV-Anschlussleistung zu niedrig. 2. Schutz vor Netzstörungen oder Überlastungen. |

| | Suggested action |
|---|---|
| EN | 1. PV power must be greater than 100 W. 2. In the event of grid anomalies or overloads, a restart is required, which may take several minutes. |
| DE | 1. PV-Leistung muss über 100 W betragen. 2. Bei Netzstörungen oder Überlastungen ist ein Neustart erforderlich, der einige Minuten dauern kann. |

## `BCC` — SOC Calibration

**Deutsch:** SOC-Kalibrierung

Not in any version of the manual.

| | Cause |
|---|---|
| EN | Error in the battery SOC |
| DE | Fehler im Batterie-SOC |

| | Suggested action |
|---|---|
| EN | Please charge the battery to 100%. |
| DE | Bitte laden Sie die Batterie zu 100 % auf. |

---

# What these sensors can and cannot tell you

Moved here from the README, which had grown past the point where anyone read it.
The entity table stays there; this is the part you look up once and then need
again the day something behaves oddly.


> **Some alarms are transients, and the poll will miss them.** `ACA` was
> measured lasting about two seconds after a grid outage — it marks the moment
> the grid goes away and clears again once the inverter has settled into island
> operation. The alarm endpoint is polled every 60 s by default, so a sensor
> here catches an event like that roughly one time in thirty. Do not build an
> outage detector on `AC Abnormal`; use `On-Grid Power` at zero together with a
> negative `Battery Power`, which means the battery is carrying the off-grid
> load alone. Shortening the alarm interval helps a little and costs a request
> per second — it does not make a two-second event reliable.
>
> How much of this generalises to the other nineteen codes is untested. `ACA`
> hangs off the grid monitor, which can only run while the inverter is
> grid-following, so it may well be the exception rather than the rule.

> **And some expected alarms simply never appear.** A user polled `getAlarm`
> once a second from Node-RED — fast enough that the two-second `ACA` above
> should have been caught — and ran three deliberate provocations on his own
> inverter:
>
> | What was done | Alarm expected | Alarm seen |
> |---|---|---|
> | Charged the battery to 100 % (APsystems support says an overvoltage warning is raised at 99 %) | `BatHV`, `BatE` | none |
> | Cut the on-grid supply all-poles at a smart plug — the app showed the outage in its own chart | `ACA` | none |
> | Battery whose SOC reading is visibly off | `BCC` | none |
>
> So a flag staying clear is not evidence that the condition did not occur.
> Treat these sensors as "the inverter said something", never as "nothing is
> wrong" — the same measurements that reach the app do not necessarily reach
> `getAlarm`. One user, one device, firmware of early August 2026; if your
> inverter does raise one of these, that is worth reporting.

Each alarm sensor carries that text as attributes — `cause` and
`suggested_action`, plus the vendor's own `vendor_name` and the `alarm_code` —
so a sensor that goes to *Problem* also tells you what the app would have told
you. German if Home Assistant is set to German, otherwise English. They are
excluded from the recorder, being static.

[alarms.json](alarms.json) is the machine-readable copy of the same texts, for
anyone reading `getAlarm` from Node-RED or a script instead of from this
integration.

`BCI` and `VRP` were added to the vendor's Local API manual in V1.3 (2026-02-04).
`BCC` is in none of its versions, so do not expect to find it there: it is
undocumented but present in the `getAlarm` response (verified on firmware
1.9.0.16, 20 fields) and carried by the app, which builds its alarm screen from
whatever keys the response contains — for every field set to `"1"` it looks up
`<FIELD>_name` and `<FIELD>_reason` in its translations, and those exist for
`BCC` in all twelve shipped languages ("SOC Calibration" / "There is an error in
the battery SOC. Please charge the battery to 100%."). The integration maps it
for the same reason: the device sends the field, whether or not the manual
lists it.

