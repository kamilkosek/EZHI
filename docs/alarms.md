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

Not every code has all three texts; `BCC` has no suggestion.

`docs/alarms.json` carries the same content in machine-readable form, for
anyone driving the API from Node-RED or a script rather than from this
integration.

The wording is reproduced as the app ships it, including its quirks — the
German name for `VRP` really does repeat itself, and `ACA`, `PvOC` and
`IRDE` are left untranslated as labels even though their explanations are
translated. Nothing here was cleaned up, so that what you read matches what
the app would show.

## `BatHTP` — Battery High Temperature Protection

**Deutsch:** Batterie-Hochtemperaturschutz

Manual: *battery high temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the battery is too high 2. Excessive number of high-power continuous charging and discharging 3. Internal fault of the battery |
| DE | 1. Die Umgebungstemperatur des Akkus ist zu hoch. 2. Zu viele kontinuierliche Lade- und Entladevorgänge mit hoher Leistung. 3. Interner Fehler des Akkus |

| | Suggested action |
|---|---|
| EN | 1. Check if the ambient temperature is within the allowable operating range. 2. Has high-power charging and discharging been performed multiple times? If so, reduce such operations after the battery cools down. 3. If the ambient temperature is normal, contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Betriebsbereichs liegt. 2. Wurde mehrmals Hochleistungsaufladung und -entladung durchgeführt? Wenn ja, reduzieren Sie solche Vorgänge, nachdem die Batterie abgekühlt ist. 3. Wenn die Umgebungstemperatur normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BatLTP` — Battery Low Temperature Protection

**Deutsch:** Batterie-Niedertemperaturschutz

Manual: *battery low temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the battery is too low 2. Internal fault of the battery |
| DE | 1. Die Umgebungstemperatur des Akkus ist zu niedrig. 2. Interner Fehler des Akkus |

| | Suggested action |
|---|---|
| EN | 1. Check if the ambient temperature is within the allowable operating range. 3. If the ambient temperature is normal, contact the dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Betriebsbereichs liegt. 2. Wenn die Umgebungstemperatur normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BatCE` — Battery Communication Error

**Deutsch:** Batteriekommunikationsfehler

Manual: *battery communication error*

| | Cause |
|---|---|
| EN | 1. The battery is not connected to the main unit 2. The cable is damaged 3. The communication function of the battery or the host is abnormal |
| DE | 1. Der Akku ist nicht mit dem Hauptgerät verbunden. 2. Das Kabel ist beschädigt. 3. Die Kommunikationsfunktion des Akkus oder des Hosts ist abnormal. |

| | Suggested action |
|---|---|
| EN | 1. Check that the cable is connected correctly  2. Check the cable for damage 3. If it is normal, please contact the dealer or after-sales service |
| DE | 1. Überprüfen Sie, ob das Kabel richtig angeschlossen ist  2. Überprüfen Sie das Kabel auf Beschädigungen 3. Wenn es normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `BatHV` — Battery overvoltage

**Deutsch:** Batterieüberspannung

Manual: *battery overvoltage*

| | Cause |
|---|---|
| EN | 1. Overcharged battery 2. Battery failure |
| DE | 1. Batterie überladen 2. Batterieausfall |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery SOC is within the safe range. If not, please perform charging and discharging operations. 2. If the SOC is normal, please contact the dealer or after-sales |
| DE | 1. Überprüfen Sie, ob der Ladezustand der Batterie im sicheren Bereich liegt. Wenn nicht, führen Sie bitte Lade- und Entladevorgänge durch. 2. Wenn der SOC normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `BatLV` — Battery undervoltage

**Deutsch:** Unterspannung der Batterie

Manual: *battery undervoltage*

| | Cause |
|---|---|
| EN | 1. Battery power failure 2. Battery failure |
| DE | 1. Batterieentladung 2. Batterieausfall |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery SOC is within the safe range. If not, please perform charging and discharging operations. 2. If the SOC is normal, please contact the dealer or after-sales |
| DE | 1. Überprüfen Sie, ob der Ladezustand der Batterie im sicheren Bereich liegt. Wenn nicht, führen Sie bitte Lade- und Entladevorgänge durch. 2. Wenn der SOC normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `BatHI` — Battery High Current

**Deutsch:** Batterie hoher Strom

Manual: *battery overcurrent*

| | Cause |
|---|---|
| EN | 1. The battery output power is too high 2. Short circuit at the output of the battery 3. Host failure |
| DE | 1. Die Ausgangsleistung der Batterie ist zu hoch. 2. Kurzschluss am Ausgang der Batterie. 3. Host-Fehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the load and grid-connected power are too large 2. Check whether the battery output is short-circuited 3. If it is normal, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob die Last und die an das Netz angeschlossene Leistung zu groß sind 2. Prüfen Sie, ob der Batterieausgang kurzgeschlossen ist 3. Wenn es normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

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
| DE | Bitte kontaktieren Sie den Händler oder den Kundendienst |

## `DTP` — Device Temperature Protection

**Deutsch:** Gerätetemperaturschutz

Manual: *device temperature protection*

| | Cause |
|---|---|
| EN | 1. The ambient temperature of the host is too high or too low  2. Internal failure of the host |
| DE | 1. Die Umgebungstemperatur des Hosts ist zu hoch oder zu niedrig  2. Interner Fehler des Hosts |

| | Suggested action |
|---|---|
| EN | 1. Check whether the ambient temperature is within the allowable use range  2. If the ambient temperature is normal, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob die Umgebungstemperatur innerhalb des zulässigen Nutzungsbereichs liegt  2. Wenn die Umgebungstemperatur normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `EE` — System failure

**Deutsch:** Systemfehler

Manual: *device error*

| | Cause |
|---|---|
| EN | 1. Host internal fault |
| DE | 1. Host-Innenfehler |

| | Suggested action |
|---|---|
| EN | 1. Please turn off the battery, grid, PV, and restart the device 2. If the system does not recover after restarting, please contact your dealer or after-sales service. |
| DE | 1. Bitte schalten Sie die Batterie, das Stromnetz und die PV aus und starten Sie das Gerät neu. 2. Wenn das Problem nach dem Neustart nicht behoben wird, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `SBS` — Battery shutdown

**Deutsch:** Batterieabschaltung

Manual: *battery shutdown*

| | Cause |
|---|---|
| EN | 1. Battery physical button shutdown 2. APP device switch button to shut down |
| DE | 1. Abschaltung über die physikalische Batterietaste 2. Abschaltung über die Geräteschaltfläche in der APP |

| | Suggested action |
|---|---|
| EN | 1. Check whether the battery physical button and APP device power button are turned off 2. If the system does not recover after restarting, please contact your dealer or after-sales service. |
| DE | 1. Prüfen Sie, ob die physikalische Batterie-Taste und die Geräte-Ein/Aus-Taste in der APP ausgeschaltet sind. 2. Wenn das Problem auch nach dem Einschalten weiterhin besteht, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `ACA` — AC Abnormal

**Deutsch:** AC Abnormal

Manual: *ac abnormal*

| | Cause |
|---|---|
| EN | 1. Grid overvoltage, undervoltage or no grid. 2. Grid overfrequency or underfrequency. |
| DE | 1. Das Netz ist über-, unter- oder gar nicht mit Strom versorgt. 2. Über- oder Unterfrequenz des Stromnetzes |

| | Suggested action |
|---|---|
| EN | 1. Check the status of the power grid and the wiring, if it happens occasionally, you can wait for the power grid to return to normal 2. If it is triggered for a long time, please contact the electricity operator |
| DE | 1. Überprüfen Sie den Status des Stromnetzes und der Verkabelung. Wenn es gelegentlich vorkommt, können Sie warten, bis das Stromnetz wieder normal ist. 2. Wenn das Problem über einen längeren Zeitraum auftritt, wenden Sie sich bitte an den Stromanbieter |

## `OfOI` — OFF OverCurrent Alarm

**Deutsch:** AUS Überstromalarm

Manual: *off grid over current alarm*

| | Cause |
|---|---|
| EN | 1. The power of the off-grid access load exceeds the usage limit 2. Not connected to the grid 3. Host failure |
| DE | 1. Die Leistung der netzunabhängigen Zugangslast überschreitet das Nutzungslimit 2. Nicht mit dem Netz verbunden 3. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the off-grid load exceeds the allowable power range 2. Check whether the host is connected to the grid 3. If it is normal, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob die netzunabhängige Last den zulässigen Leistungsbereich überschreitet 2. Prüfen Sie, ob der Host mit dem Netz verbunden ist 3. Wenn es normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `PvHV` — PV High Voltage

**Deutsch:** PV-Hochspannung

Manual: *pv high voltage*

| | Cause |
|---|---|
| EN | 1. The component configuration is inappropriate 2. The component is not properly connected to the host 3. Component failure 4. Host failure |
| DE | 1. Die Komponentenkonfiguration ist ungeeignet. 2. Die Komponente ist nicht ordnungsgemäß mit dem Host verbunden. 3. Komponentenfehler. 4. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the PV is connected to the host normally 2. Check whether the PV output voltage exceeds the allowable range of the main engine  3. Check if the component is working properly 4. If it is normal, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob die PV normal an den Host angeschlossen ist. 2. Prüfen Sie, ob die PV-Ausgangsspannung den zulässigen Bereich der Hauptmaschine überschreitet. 3. Prüfen Sie, ob die Komponente ordnungsgemäß funktioniert. 4. Wenn alles normal ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `PvOC` — PV_Over_Cur

**Deutsch:** PV_Over_Cur

Manual: *pv over current*

| | Cause |
|---|---|
| EN | 1. The component configuration is inappropriate 2. Component failure 3. Host failure |
| DE | 1. Die Komponentenkonfiguration ist ungeeignet 2. Komponentenfehler 3. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check whether the PV output current exceeds the allowable use range 2. Check if the component is working properly 3. If it is within the scope, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob der PV-Ausgangsstrom den zulässigen Anwendungsbereich überschreitet. 2. Prüfen Sie, ob die Komponente richtig funktioniert. 3. Wenn es innerhalb des Bereichs liegt, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `IRDE` — IRD

**Deutsch:** IRD

Manual: *IRD error*

| | Cause |
|---|---|
| EN | 1. PV input impedance is abnormal 2. Host failure |
| DE | 1. PV-Eingangsimpedanz ist anormal 2. Host-Fehler |

| | Suggested action |
|---|---|
| EN | 1. Please turn off the battery, grid, PV, and restart the device 2. If the system does not recover after restarting, please contact your dealer or after-sales service. |
| DE | 1. Bitte schalten Sie die Batterie, das Stromnetz und die PV aus und starten Sie das Gerät neu. 2. Wenn das Problem nach dem Neustart nicht behoben wird, wenden Sie sich bitte an den Händler oder den Kundendienst |

## `PVWE` — PV Connection Error

**Deutsch:** PV-Verbindungsfehler

Manual: *pv wiring error*

| | Cause |
|---|---|
| EN | 1.The positive and negative poles of different components are mixed and connected to the same input circuit. 2. Two input circuits are connected in parallel to the same PV (Photovoltaic) source. 3. The main unit has a malfunction. |
| DE | 1.Die positive und negative Pole verschiedener Komponenten werden in der gleichen Eingangsleitung gemischt angeschlossen. 2. Zwei Eingänge werden parallel an die gleiche PV-Anlage angeschlossen. 3. Der Hauptcomputer ist defekt. |

| | Suggested action |
|---|---|
| EN | 1.Please turn off the battery and the power grid, connect the PV correctly, and then restart the device; 2.if it does not recover after restarting, please contact the dealer or after-sales service. |
| DE | 1.Bitte schließen Sie die Batterie und das Stromnetz ab, verbinden Sie die PV richtig, und starten Sie das Gerät neu; 2. wenn es nach dem Neustart nicht wiederhergestellt ist, wenden Sie sich bitte an den Händler oder den Kundendienst. |

## `OfGS` — Off Grid Short Circuit

**Deutsch:** Kurzschluss auf der netzunabhängigen Seite

Manual: *off grid short circuit*

| | Cause |
|---|---|
| EN | 1. The off-grid side connection line is damaged. 2. Electrical appliances on the off-grid side are damaged. 3. Host failure |
| DE | 1. Das netzunabhängige Verbindungskabel ist beschädigt 2. Elektrogeräte auf der Off-Grid-Seite sind beschädigt 3. Hostfehler |

| | Suggested action |
|---|---|
| EN | 1. Check if the off-grid side connection line is short-circuited. 2. Check whether the off-grid appliances are short-circuited. 3. If it is normal, please contact the dealer or after-sales service |
| DE | 1. Prüfen Sie, ob die Verbindungskabel zur Off-Grid-Seite kurzgeschlossen sind. 2. Prüfen Sie, ob die Off-Grid-Geräte kurzgeschlossen sind. 3. Wenn alles normal ist, wenden Sie sich an den Händler oder den Kundendienst. |

## `BCI` — Battery Access Conflict

**Deutsch:** Batterieanschluss konflikt

Manual: *Battery_Connection_Issue*

| | Cause |
|---|---|
| EN | 1. Connect a battery in battery-free mode |
| DE | 1. Batterie im batterielosen Modus anschließen |

| | Suggested action |
|---|---|
| EN | 1. Ensure that EZHI is not connected to a battery. 2. Set other working modes besides the battery-free mode |
| DE | 1. Stellen Sie sicher, dass EZHI nicht an eine Batterie angeschlossen ist. 2. Stellen Sie andere Arbeitsmodi als den batterielosen Modus ein |

## `VRP` — Voltage Reset Protection

**Deutsch:** Spannungsrücksetz Spannungsrücksetzschutz

Manual: *Voltage_Reset Protection*

| | Cause |
|---|---|
| EN | 1. PV terminal power is too low. 2. Protection against grid anomalies or overloads |
| DE | 1. PV-Anschlussleistung zu niedrig. 2. Schutz vor Netzstörungen oder Überlastungen |

| | Suggested action |
|---|---|
| EN | 1. PV power is greater than 100W. 2. In the event of grid anomalies or overloads, a restart is required, which may take several minutes |
| DE | 1. PV-Leistung über 100W. 2. Bei Netzstörungen oder Überlastungen ist ein Neustart erforderlich, der einige Minuten dauern kann |

## `BCC` — SOC Calibration

**Deutsch:** SOC-Kalibrierung

Manual: not listed in any version, including V1.3 (2026-02-04).

| | Cause |
|---|---|
| EN | 1. There is an error in the battery SOC. Please charge the battery to 100%. |
| DE | 1. Es gibt einen Fehler im Batterie-SOC. Bitte laden Sie die Batterie bis zu 100 % auf. |
