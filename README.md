# KWB Comfort 4 (Modbus TCP) für Home Assistant

Custom Integration für KWB-Heizkessel mit der Regelung **Comfort 4** (Easyfire,
Multifire, Pelletfire Plus, Combifire, Classicfire CF 1 / 1.5 / 2 und das
autonome Wärmemanagementmodul). Die Integration spricht direkt Modbus TCP mit
der Regelung. Es ist kein YAML nötig, alles wird über die Oberfläche eingerichtet.

*English below.*

## Funktionen

- Einrichtung über die Oberfläche mit automatischer Erkennung von
  Heizkreisen, Pufferspeichern, Brauchwasserspeichern, Solar, Zirkulation und
  Kesselfolgeschaltung
- Ein Gerät pro Kessel, Heizkreis, Speicher usw. mit deutschen und englischen
  Namen aus der offiziellen KWB-Registerliste (ModbusInfo V21.9.0)
- Rund 1.300 Werte verfügbar, die wichtigsten sind voreingestellt aktiv, der Rest
  lässt sich bei Bedarf in der Entitätenliste aktivieren
- Status-Klartexte (z. B. Kesselstatus „Zünden Start Saugzug“) als
  Enum-Sensoren, ohne Template-Sensoren
- Schreibbare Werte je nach Modbus-Ebene der Regelung („Benutzer“ oder
  „Experte“): Kessel Ein/Aus, Heizkreisprogramm, Komfort- und
  Absenktemperatur, Puffer- und Warmwasserprogramme, Brauchwasser 1x
  erhitzen, Restmenge Pelletlager und mehr
- Aktive Alarme im Klartext (Sensor „Aktive Alarme“ mit Liste als Attribut)
  und Taste „Alarme beheben“
- Sensoren werden nur dann ungültig gemeldet, wenn die Regelung den Fühler
  als defekt oder fehlend meldet
- Schonend für die Regelung: eine dauerhafte Verbindung, Blockabfragen,
  einstellbare Pause zwischen Anfragen (KWB empfiehlt 0,5 bis 1 s). Es
  werden nur die Register abgefragt, deren Entitäten aktiv sind
- Optional Lifetick für die externe Leistungs-/Temperaturvorgabe über Modbus
- Diagnosedaten zum Download

## Voraussetzungen

- KWB Comfort 4 mit Software ab V21.4.0 (Registerliste V21.9.0 enthalten)
- Modbus aktiviert: Expertenebene » Zusatzfunktionen » Modbus » „Modbus aktiv“
  = Ein, danach Regelung neu starten
- Feste IP-Adresse der Regelung (Zusatzfunktionen » Ethernet-Einstellungen)
- Die Regelung erlaubt höchstens **drei** gleichzeitige Modbus-Verbindungen.
  Wenn parallel noch die Modbus-YAML-Konfiguration läuft, belegt sie eine davon.

## Installation

### Über den Marketplace (Home Assistant 2026.11 und neuer)

1. Einstellungen » Marketplace » ⋮ » Benutzerdefinierte Repositories
2. `https://github.com/amrheing/ha-kwb-comfort4`, Typ „Integration“
3. „KWB Comfort 4“ installieren und Home Assistant neu starten

Ältere Versionen mit HACS: genauso über HACS » Benutzerdefinierte Repositories.

### Manuell

Ordner `custom_components/kwb_comfort4` nach `config/custom_components/`
kopieren und neu starten.

## Einrichtung

Einstellungen » Geräte & Dienste » Integration hinzufügen » „KWB Comfort 4“.

1. IP-Adresse, Port (502) und Slave-Adresse (1) eingeben. Die Integration
   prüft die Verbindung und liest die Softwareversion.
2. Kesseltyp und Modbus-Ebene wählen. Erkannte Module sind vorausgewählt.

Später änderbar über „Konfigurieren“: Module, Ebene, Abfrageintervall, Pause
zwischen Anfragen, Lifetick. Die IP-Adresse ändert man über „Neu konfigurieren“.

## Pellets: Verbrauch, Preis und Käufe

Bei Kesseln mit Brennstoffzähler (Easyfire, Multifire, Pelletfire Plus, Combifire)
legt die Integration zusätzlich an:

- **Brennstoffverbrauch** heute, gestern, Monat, Vormonat, Jahr, Vorjahr (kg),
  berechnet aus dem Zähler der Regelung und über Neustarts gespeichert
- **Pelletpreis** (€/t) als Eingabefeld. Jede Änderung wird mit Datum gemerkt.
- **Brennstoffkosten** heute, Monat, Jahr, Vorjahr (Verbrauch × aktueller Preis)
- **Pelletkäufe**: Anzahl als Zustand, alle Käufe als Attribut `purchases`
- **Preisverlauf** als Langzeitstatistik `kwb_comfort4:pellet_price_…` (die genaue
  ID steht im Attribut `price_statistic_id` des Sensors Pelletkäufe). Sie enthält
  jeden Kauf und jede Preisänderung, auch rückwirkend eingetragene.

### Käufe eintragen, auch rückwirkend

Aktion `kwb_comfort4.add_purchase` (Entwicklerwerkzeuge » Aktionen oder in einem Skript):

```yaml
action: kwb_comfort4.add_purchase
data:
  date: "2024-06-15"
  amount_kg: 6000
  price_per_t: 349.50   # oder total_price: 2097
  note: Lieferant XY
  add_to_stock: false   # true zählt die Menge zur Restmenge in der Regelung dazu
```

Dazu gibt es `kwb_comfort4.delete_purchase` (Datum) und `kwb_comfort4.list_purchases`
(liefert Käufe und Preisverlauf zurück).

Skript als Eingabemaske fürs Dashboard (in der Skript-Ansicht erscheinen die
Felder als Formular):

```yaml
alias: Pelletkauf eintragen
fields:
  datum: {name: Datum, required: true, selector: {date: {}}}
  menge: {name: Menge (kg), required: true, selector: {number: {min: 1, max: 100000, mode: box, unit_of_measurement: kg}}}
  preis: {name: Preis pro Tonne, required: true, selector: {number: {min: 0, max: 2000, step: 0.01, mode: box, unit_of_measurement: €/t}}}
  auf_restmenge: {name: Auf Restmenge buchen, default: false, selector: {boolean: {}}}
sequence:
  - action: kwb_comfort4.add_purchase
    data:
      date: "{{ datum }}"
      amount_kg: "{{ menge }}"
      price_per_t: "{{ preis }}"
      add_to_stock: "{{ auf_restmenge }}"
```

### Beispielkarte

Entitäts-IDs an die eigene Installation anpassen:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Pellets
    entities:
      - entity: number.kwb_easyfire_restmenge_brennstofflager
      - entity: number.kwb_easyfire_pelletpreis
      - type: section
      - entity: sensor.kwb_easyfire_brennstoffverbrauch_heute
      - entity: sensor.kwb_easyfire_brennstoffverbrauch_gestern
      - entity: sensor.kwb_easyfire_brennstoffverbrauch_monat
      - entity: sensor.kwb_easyfire_brennstoffverbrauch_vormonat
      - entity: sensor.kwb_easyfire_brennstoffverbrauch_jahr
      - entity: sensor.kwb_easyfire_brennstoffkosten_monat
      - entity: sensor.kwb_easyfire_brennstoffkosten_jahr
  - type: statistics-graph
    title: Pelletpreis
    chart_type: line
    period: month
    days_to_show: 1825
    stat_types: [mean]
    entities:
      - kwb_comfort4:pellet_price_192_168_1_50_1
  - type: markdown
    title: Käufe
    content: >
      | Datum | Menge | €/t | Summe |
      |---|---:|---:|---:|
      {% for p in state_attr('sensor.kwb_easyfire_pelletkaufe', 'purchases') | reverse %}
      | {{ p.date }} | {{ p.amount_kg }} kg | {{ p.price_per_t }} | {{ p.total }} € |
      {% endfor %}
```

## Umstieg von der Modbus-YAML-Konfiguration

Damit Verlauf und Statistiken erhalten bleiben:

1. Integration einrichten, die neuen Entitäten prüfen.
2. Die KWB-Einträge aus der `modbus:`-YAML-Konfiguration entfernen und neu starten.
3. Die neuen Entitäten auf die alten Entitäts-IDs umbenennen
   (Entität » Einstellungen » Entitäts-ID). Automationen, Dashboards und
   Verbrauchszähler laufen dann unverändert weiter.

## Hinweise

- Die Registerliste wird aus den KWB-Dateien `ModbusInfo-de/en-Vxx.xlsx`
  erzeugt (`tools/generate_registers.py`). Die Dateien selbst liegen nicht im
  Repository. Sie sind auf der SD-Karte der Regelung oder bei KWB erhältlich.
- 32-Bit-Werte (z. B. Brennstoffverbrauch) kommen bei aktuellen Regelungen
  (Software 24.x) mit dem höherwertigen Wort zuerst, anders als im
  KWB-Handbuch beschrieben. Falls Zähler riesige Werte zeigen: Konfigurieren »
  Wortreihenfolge umstellen.
- Ob die Regelung die Adressen 1-basiert erwartet, erkennt die Integration
  beim Einrichten selbst.

Dies ist kein offizielles Produkt der KWB GmbH. Schreibzugriffe ändern
Einstellungen an der Heizung, Nutzung auf eigene Verantwortung.

---

## English

Custom integration for KWB boilers with the **Comfort 4** controller using
Modbus TCP. It is set up in the UI, auto-detects heating circuits, buffer
tanks, DHW tanks, solar, circulation and boiler cascade, and creates one
device per unit. Names come from the official KWB register list (V21.9.0)
in English and German. It provides enum sensors for status values, writable
setpoints and programs according to the Modbus level set on the controller
(user or expert), active alarms as plain text, and an optional lifetick for
external output/temperature specification. It keeps a single connection,
reads in blocks and only polls registers of enabled entities.

Install via Marketplace/HACS as custom repository
`https://github.com/amrheing/ha-kwb-comfort4` (category integration), restart,
then add the integration “KWB Comfort 4”. Enable Modbus on the controller
first (expert level » Add-ons » Modbus) and give it a fixed IP address. The
controller accepts at most three Modbus clients at the same time.

Not affiliated with KWB GmbH.
