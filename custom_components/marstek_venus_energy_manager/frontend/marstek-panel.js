/*
 * Marstek Venus Energy Manager — custom sidebar panel.
 *
 * Faithful port of the "MVEM" high-fidelity design handoff (Resumen view).
 * Vanilla custom element, no build step, no external deps. Home Assistant
 * injects `hass`, `panel`, `narrow` and `route`. We read entities from the
 * frontend registry (hass.entities) filtered by this integration's platform,
 * match them by translation_key (language/rename independent), aggregate them
 * into a single state model and render the themed dashboard:
 *
 *   - animated energy-flow diagram (Solar · Red · Casa · Batería + núcleo)
 *   - SOC ring hero ("Estado del sistema")
 *   - Potencia / Balance neto / Energía hoy / SOC mini-histórico / Diagnóstico
 *
 * The flow Grid/Home nodes use the entities the integration was configured
 * with, forwarded through the panel `config` payload (grid_entity / home_entity).
 * Solar uses the configured production sensor (solar_entity, external inverter)
 * when present, else falls back to per-battery MPPT sensors when the model
 * exposes them.
 *
 * Design tokens (OKLCH) are embedded so the look matches the handoff exactly;
 * dark/light follows the user's HA theme (hass.themes.darkMode).
 *
 * Tabs: Resumen (this overview), Baterías (per-device cards + controls) and
 * Control (system-level entities grouped by feature — each capability's on/off
 * switch plus its CONFIG params: PD tuning, limits, thresholds). The DOM is
 * built once and patched in place on every hass update so the SVG particle
 * animation and ring transitions never restart.
 */

const FALLBACK_DOMAIN = "marstek_venus_energy_manager";
const FALLBACK_TITLE = "Marstek Venus";

// --- i18n ------------------------------------------------------------------
// All user-facing panel strings, keyed by a stable id and resolved at render
// time from the HA UI language (hass.locale.language). English is the base/
// fallback; the integration ships de/en/es/fr/nl, mirrored here. `{var}`
// placeholders are filled by _t(key, vars). Terminology matches the entity
// names in translations/*.json so the panel reads consistently with HA.
const I18N = {
  en: {
    subtitle: "Energy Manager",
    live: "Live",
    tabResumen: "Overview", tabBaterias: "Batteries", tabControl: "Control",
    moreInfo: "Show history",
    zoomReset: "All",
    placeholderMsg: "This view is coming in a future phase. For now, use the Overview view.",
    cardFlow: "Energy flow", cardSoc: "System status", cardDaily: "Energy today",
    cardWeekly: "Weekly energy", cardPower: "Power", cardSocToday: "SOC · today",
    grid: "Grid", solar: "Solar", home: "Home", battery: "Battery",
    importing: "Importing", exporting: "Exporting",
    charging: "Charging", discharging: "Discharging", idle: "Idle",
    selfConsumptionSuffix: "% self-consumption", units: "units",
    charge: "Charge", discharge: "Discharge", availOf: "of {value} available",
    charged: "Charged", discharged: "Discharged",
    gridImport: "Grid imported", gridExport: "Grid exported",
    now: "now", noData: "No data", imported: "Imported", exported: "Exported",
    diagTitle: "Integration status",
    diagIntegration: "Integration", diagNetBalance: "Net balance", diagAlarm: "Alarm",
    diagActiveBatteries: "Active batteries", diagNonResponsive: "No response",
    diagDischargeWindow: "Discharge window", diagPredictive: "Predictive charging",
    diagPeak: "Peak shaving", diagWeeklyCharge: "Weekly charge", diagChargeDelay: "Charge delay",
    nResponsive: "{n} no response", none: "None",
    noBatteriesTitle: "No batteries",
    noBatteriesMsg: "No battery devices were detected in this integration.",
    healthCells: "Health & cells",
    mTemp: "Temperature", mVoltage: "Voltage", mCellMax: "Cell max", mCellMin: "Cell min",
    mCellDelta: "Δ cell", mCycles: "Cycles", mEfficiency: "Efficiency", mHysteresis: "Hysteresis",
    solarMppt: "Solar (MPPT)", controls: "Controls", deviceInfo: "Device information",
    offgrid: "Off-grid", infoComm: "Comm module",
    invBackup: "Backup", invUpdating: "Updating", invStandby: "Standby", invBypass: "Bypass",
    active: "Active", inactive: "Inactive",
    ctlEmpty: "No controls enabled. Enable them on the device (Settings → disabled entities).",
    sysEmptyTitle: "No controls available",
    sysEmptyMsg: "This integration exposes no system controls, or they are disabled. Enable them in Settings → entities.",
    bcAllowCharge: "Allow charge", bcAllowDischarge: "Allow discharge",
    bcSocMax: "Max SOC", bcSocMin: "Min SOC", bcWorkMode: "Work mode", bcForceMode: "Force mode",
    bcChargePower: "Charge power", bcDischargePower: "Discharge power",
    bcMaxCharge: "Max charge", bcMaxDischarge: "Max discharge",
    bcChargeToSoc: "Charge to SOC", bcChargeHysteresis: "Charge hysteresis", bcBackup: "Backup function",
    secManual: "Manual mode", itemEnable: "Enable",
    itemMaxContracted: "Max contracted power", itemSolarSafety: "Solar safety margin",
    itemSocThreshold: "SOC threshold", itemPeakLimit: "Peak limit",
    itemDelaySafety: "Safety margin", itemDelaySoc: "Delay target SOC",
    secHourly: "Hourly balance", secWeeklyFull: "Weekly full charge", itemWeeklyDay: "Full charge day",
    secSlots: "Configured slots", itemSlot: "Slot",
    secExcluded: "Excluded devices", itemExcludedDevice: "Excluded device", itemSolarSurplus: "Solar surplus",
    secSysLimits: "System power limits", itemSysMaxCharge: "System max charge", itemSysMaxDischarge: "System max discharge",
    secPd: "PD controller (advanced)",
    itemPdKp: "Proportional gain (Kp)", itemPdKd: "Derivative gain (Kd)", itemPdDeadband: "Deadband",
    itemPdMaxChange: "Max power change", itemPdDirHyst: "Direction hysteresis",
    itemPdMinCharge: "Min charge power", itemPdMinDischarge: "Min discharge power", itemPdTargetGrid: "Target grid power",
    slotSchedule: "Schedule", slotDays: "Days", slotAll: "All", slotMode: "Mode", slotManual: "Manual", slotPd: "PD",
    slotAllows: "Allows", slotChargeWord: "charge", slotDischargeWord: "discharge", slotNothing: "nothing",
    slotSocOverride: "SOC override", slotYes: "yes", slotPowerOverride: "Power override",
    slotStateLabel: "State", slotActiveWord: "active", slotInactiveWord: "inactive",
  },
  es: {
    subtitle: "Energy Manager",
    live: "En vivo",
    tabResumen: "Resumen", tabBaterias: "Baterías", tabControl: "Control",
    moreInfo: "Ver histórico",
    zoomReset: "Todo",
    placeholderMsg: "Esta vista llegará en una próxima fase. Por ahora, usa la vista Resumen.",
    cardFlow: "Flujo de energía", cardSoc: "Estado del sistema", cardDaily: "Energía hoy",
    cardWeekly: "Energía semanal", cardPower: "Potencias", cardSocToday: "SOC · hoy",
    grid: "Red", solar: "Solar", home: "Casa", battery: "Batería",
    importing: "Importando", exporting: "Exportando",
    charging: "Cargando", discharging: "Descargando", idle: "Reposo",
    selfConsumptionSuffix: "% autoconsumo", units: "uds",
    charge: "Carga", discharge: "Descarga", availOf: "de {value} disponibles",
    charged: "Cargada", discharged: "Descargada",
    gridImport: "Red importada", gridExport: "Red exportada",
    now: "ahora", noData: "Sin datos", imported: "Importada", exported: "Exportada",
    diagTitle: "Estado de la integración",
    diagIntegration: "Integración", diagNetBalance: "Balance neto", diagAlarm: "Alarma",
    diagActiveBatteries: "Baterías activas", diagNonResponsive: "Sin respuesta",
    diagDischargeWindow: "Ventana de descarga", diagPredictive: "Carga predictiva",
    diagPeak: "Reducción de picos", diagWeeklyCharge: "Carga semanal", diagChargeDelay: "Retardo de carga",
    nResponsive: "{n} sin respuesta", none: "Ninguna",
    noBatteriesTitle: "Sin baterías",
    noBatteriesMsg: "No se detectaron dispositivos de batería en esta integración.",
    healthCells: "Salud y celdas",
    mTemp: "Temperatura", mVoltage: "Voltaje", mCellMax: "Celda máx", mCellMin: "Celda mín",
    mCellDelta: "Δ celda", mCycles: "Ciclos", mEfficiency: "Eficiencia", mHysteresis: "Histéresis",
    solarMppt: "Solar (MPPT)", controls: "Controles", deviceInfo: "Información del dispositivo",
    offgrid: "Offgrid", infoComm: "Módulo com.",
    invBackup: "Respaldo", invUpdating: "Actualizando", invStandby: "En espera", invBypass: "Bypass",
    active: "Activa", inactive: "Inactiva",
    ctlEmpty: "No hay controles habilitados. Actívalos en el dispositivo (Ajustes → entidades deshabilitadas).",
    sysEmptyTitle: "Sin controles disponibles",
    sysEmptyMsg: "Esta integración no expone controles de sistema, o están deshabilitados. Actívalos en Ajustes → entidades.",
    bcAllowCharge: "Permitir carga", bcAllowDischarge: "Permitir descarga",
    bcSocMax: "SOC máximo", bcSocMin: "SOC mínimo", bcWorkMode: "Modo de trabajo", bcForceMode: "Modo forzado",
    bcChargePower: "Potencia de carga", bcDischargePower: "Potencia de descarga",
    bcMaxCharge: "Máx. carga", bcMaxDischarge: "Máx. descarga",
    bcChargeToSoc: "Cargar hasta SOC", bcChargeHysteresis: "Histéresis de carga", bcBackup: "Función de respaldo",
    secManual: "Modo manual", itemEnable: "Activar",
    itemMaxContracted: "Potencia contratada máx.", itemSolarSafety: "Margen de seguridad solar",
    itemSocThreshold: "Umbral de SOC", itemPeakLimit: "Límite de pico",
    itemDelaySafety: "Margen de seguridad", itemDelaySoc: "SOC objetivo de retardo",
    secHourly: "Balance horario", secWeeklyFull: "Carga semanal completa", itemWeeklyDay: "Día de carga completa",
    secSlots: "Franjas configuradas", itemSlot: "Franja",
    secExcluded: "Dispositivos excluidos", itemExcludedDevice: "Dispositivo excluido", itemSolarSurplus: "Excedente solar",
    secSysLimits: "Límites de potencia del sistema", itemSysMaxCharge: "Máx. carga del sistema", itemSysMaxDischarge: "Máx. descarga del sistema",
    secPd: "Controlador PD (avanzado)",
    itemPdKp: "Ganancia proporcional (Kp)", itemPdKd: "Ganancia derivativa (Kd)", itemPdDeadband: "Banda muerta",
    itemPdMaxChange: "Cambio máx. de potencia", itemPdDirHyst: "Histéresis de dirección",
    itemPdMinCharge: "Potencia mín. de carga", itemPdMinDischarge: "Potencia mín. de descarga", itemPdTargetGrid: "Potencia objetivo de red",
    slotSchedule: "Horario", slotDays: "Días", slotAll: "Todas", slotMode: "Modo", slotManual: "Manual", slotPd: "PD",
    slotAllows: "Permite", slotChargeWord: "carga", slotDischargeWord: "descarga", slotNothing: "nada",
    slotSocOverride: "SOC override", slotYes: "sí", slotPowerOverride: "Potencia override",
    slotStateLabel: "Estado", slotActiveWord: "activa", slotInactiveWord: "inactiva",
  },
  de: {
    subtitle: "Energy Manager",
    live: "Live",
    tabResumen: "Übersicht", tabBaterias: "Batterien", tabControl: "Steuerung",
    moreInfo: "Verlauf anzeigen",
    zoomReset: "Alles",
    placeholderMsg: "Diese Ansicht kommt in einer späteren Phase. Nutze vorerst die Übersicht.",
    cardFlow: "Energiefluss", cardSoc: "Systemstatus", cardDaily: "Energie heute",
    cardWeekly: "Wochenenergie", cardPower: "Leistung", cardSocToday: "SOC · heute",
    grid: "Netz", solar: "Solar", home: "Haus", battery: "Batterie",
    importing: "Bezug", exporting: "Einspeisung",
    charging: "Laden", discharging: "Entladen", idle: "Bereit",
    selfConsumptionSuffix: "% Eigenverbrauch", units: "Einh.",
    charge: "Laden", discharge: "Entladen", availOf: "von {value} verfügbar",
    charged: "Geladen", discharged: "Entladen",
    gridImport: "Netzbezug", gridExport: "Netzeinspeisung",
    now: "jetzt", noData: "Keine Daten", imported: "Bezug", exported: "Einspeisung",
    diagTitle: "Integrationsstatus",
    diagIntegration: "Integration", diagNetBalance: "Netto-Balance", diagAlarm: "Alarm",
    diagActiveBatteries: "Aktive Batterien", diagNonResponsive: "Keine Antwort",
    diagDischargeWindow: "Entladefenster", diagPredictive: "Prädiktives Laden",
    diagPeak: "Spitzenlastkappung", diagWeeklyCharge: "Wöchentliche Ladung", diagChargeDelay: "Ladeverzögerung",
    nResponsive: "{n} ohne Antwort", none: "Keine",
    noBatteriesTitle: "Keine Batterien",
    noBatteriesMsg: "In dieser Integration wurden keine Batteriegeräte erkannt.",
    healthCells: "Zustand & Zellen",
    mTemp: "Temperatur", mVoltage: "Spannung", mCellMax: "Zelle max", mCellMin: "Zelle min",
    mCellDelta: "Δ Zelle", mCycles: "Zyklen", mEfficiency: "Effizienz", mHysteresis: "Hysterese",
    solarMppt: "Solar (MPPT)", controls: "Steuerung", deviceInfo: "Geräteinformationen",
    offgrid: "Inselbetrieb", infoComm: "Komm.-Modul",
    invBackup: "Backup", invUpdating: "Aktualisierung", invStandby: "Standby", invBypass: "Bypass",
    active: "Aktiv", inactive: "Inaktiv",
    ctlEmpty: "Keine Steuerungen aktiviert. Aktiviere sie am Gerät (Einstellungen → deaktivierte Entitäten).",
    sysEmptyTitle: "Keine Steuerungen verfügbar",
    sysEmptyMsg: "Diese Integration stellt keine Systemsteuerungen bereit oder sie sind deaktiviert. Aktiviere sie in Einstellungen → Entitäten.",
    bcAllowCharge: "Laden erlauben", bcAllowDischarge: "Entladen erlauben",
    bcSocMax: "Max. SOC", bcSocMin: "Min. SOC", bcWorkMode: "Arbeitsmodus", bcForceMode: "Betriebsmodus erzwingen",
    bcChargePower: "Ladeleistung", bcDischargePower: "Entladeleistung",
    bcMaxCharge: "Max. Ladeleistung", bcMaxDischarge: "Max. Entladeleistung",
    bcChargeToSoc: "Laden bis SOC", bcChargeHysteresis: "Ladehysterese", bcBackup: "Backup-Funktion",
    secManual: "Manueller Modus", itemEnable: "Aktivieren",
    itemMaxContracted: "Max. Vertragsleistung", itemSolarSafety: "Sicherheitspuffer Solar",
    itemSocThreshold: "SOC-Schwelle", itemPeakLimit: "Spitzenlimit",
    itemDelaySafety: "Sicherheitspuffer", itemDelaySoc: "Verzögerungs-Ziel-SOC",
    secHourly: "Stündliche Balance", secWeeklyFull: "Wöchentliche Vollladung", itemWeeklyDay: "Tag der Vollladung",
    secSlots: "Konfigurierte Zeitfenster", itemSlot: "Zeitfenster",
    secExcluded: "Ausgeschlossene Geräte", itemExcludedDevice: "Ausgeschlossenes Gerät", itemSolarSurplus: "Solarüberschuss",
    secSysLimits: "System-Leistungsgrenzen", itemSysMaxCharge: "System-Max.-Ladeleistung", itemSysMaxDischarge: "System-Max.-Entladeleistung",
    secPd: "PD-Regler (erweitert)",
    itemPdKp: "Proportionalverstärkung (Kp)", itemPdKd: "Differenzialverstärkung (Kd)", itemPdDeadband: "Totband",
    itemPdMaxChange: "Max. Leistungsänderung", itemPdDirHyst: "Richtungshysterese",
    itemPdMinCharge: "Min. Ladeleistung", itemPdMinDischarge: "Min. Entladeleistung", itemPdTargetGrid: "Ziel-Netzleistung",
    slotSchedule: "Zeitplan", slotDays: "Tage", slotAll: "Alle", slotMode: "Modus", slotManual: "Manuell", slotPd: "PD",
    slotAllows: "Erlaubt", slotChargeWord: "Laden", slotDischargeWord: "Entladen", slotNothing: "nichts",
    slotSocOverride: "SOC-Override", slotYes: "ja", slotPowerOverride: "Leistungs-Override",
    slotStateLabel: "Status", slotActiveWord: "aktiv", slotInactiveWord: "inaktiv",
  },
  fr: {
    subtitle: "Energy Manager",
    live: "En direct",
    tabResumen: "Résumé", tabBaterias: "Batteries", tabControl: "Contrôle",
    moreInfo: "Voir l'historique",
    zoomReset: "Tout",
    placeholderMsg: "Cette vue arrivera dans une phase ultérieure. Pour l'instant, utilisez la vue Résumé.",
    cardFlow: "Flux d'énergie", cardSoc: "État du système", cardDaily: "Énergie aujourd'hui",
    cardWeekly: "Énergie hebdomadaire", cardPower: "Puissances", cardSocToday: "SOC · aujourd'hui",
    grid: "Réseau", solar: "Solaire", home: "Maison", battery: "Batterie",
    importing: "Importation", exporting: "Exportation",
    charging: "Charge", discharging: "Décharge", idle: "Repos",
    selfConsumptionSuffix: "% autoconsommation", units: "unités",
    charge: "Charge", discharge: "Décharge", availOf: "sur {value} disponibles",
    charged: "Chargée", discharged: "Déchargée",
    gridImport: "Réseau importé", gridExport: "Réseau exporté",
    now: "maintenant", noData: "Aucune donnée", imported: "Importée", exported: "Exportée",
    diagTitle: "État de l'intégration",
    diagIntegration: "Intégration", diagNetBalance: "Bilan net", diagAlarm: "Alarme",
    diagActiveBatteries: "Batteries actives", diagNonResponsive: "Sans réponse",
    diagDischargeWindow: "Fenêtre de décharge", diagPredictive: "Charge prédictive",
    diagPeak: "Écrêtement de pointe", diagWeeklyCharge: "Charge hebdomadaire", diagChargeDelay: "Délai de charge",
    nResponsive: "{n} sans réponse", none: "Aucune",
    noBatteriesTitle: "Aucune batterie",
    noBatteriesMsg: "Aucun appareil de batterie n'a été détecté dans cette intégration.",
    healthCells: "Santé et cellules",
    mTemp: "Température", mVoltage: "Tension", mCellMax: "Cellule max", mCellMin: "Cellule min",
    mCellDelta: "Δ cellule", mCycles: "Cycles", mEfficiency: "Efficacité", mHysteresis: "Hystérésis",
    solarMppt: "Solaire (MPPT)", controls: "Contrôles", deviceInfo: "Informations sur l'appareil",
    offgrid: "Hors réseau", infoComm: "Module comm.",
    invBackup: "Secours", invUpdating: "Mise à jour", invStandby: "En attente", invBypass: "Bypass",
    active: "Active", inactive: "Inactive",
    ctlEmpty: "Aucun contrôle activé. Activez-les sur l'appareil (Paramètres → entités désactivées).",
    sysEmptyTitle: "Aucun contrôle disponible",
    sysEmptyMsg: "Cette intégration n'expose aucun contrôle système, ou ils sont désactivés. Activez-les dans Paramètres → entités.",
    bcAllowCharge: "Autoriser la charge", bcAllowDischarge: "Autoriser la décharge",
    bcSocMax: "SOC max.", bcSocMin: "SOC min.", bcWorkMode: "Mode de fonctionnement", bcForceMode: "Mode forcé",
    bcChargePower: "Puissance de charge", bcDischargePower: "Puissance de décharge",
    bcMaxCharge: "Charge max.", bcMaxDischarge: "Décharge max.",
    bcChargeToSoc: "Charger jusqu'à SOC", bcChargeHysteresis: "Hystérésis de charge", bcBackup: "Fonction de secours",
    secManual: "Mode manuel", itemEnable: "Activer",
    itemMaxContracted: "Puissance contractuelle max.", itemSolarSafety: "Marge de sécurité solaire",
    itemSocThreshold: "Seuil SOC", itemPeakLimit: "Limite de pointe",
    itemDelaySafety: "Marge de sécurité", itemDelaySoc: "SOC cible du délai",
    secHourly: "Bilan horaire", secWeeklyFull: "Charge complète hebdomadaire", itemWeeklyDay: "Jour de charge complète",
    secSlots: "Créneaux configurés", itemSlot: "Créneau",
    secExcluded: "Appareils exclus", itemExcludedDevice: "Appareil exclu", itemSolarSurplus: "Surplus solaire",
    secSysLimits: "Limites de puissance du système", itemSysMaxCharge: "Charge max. système", itemSysMaxDischarge: "Décharge max. système",
    secPd: "Régulateur PD (avancé)",
    itemPdKp: "Gain proportionnel (Kp)", itemPdKd: "Gain dérivé (Kd)", itemPdDeadband: "Bande morte",
    itemPdMaxChange: "Changement de puissance max.", itemPdDirHyst: "Hystérésis de direction",
    itemPdMinCharge: "Puissance min. de charge", itemPdMinDischarge: "Puissance min. de décharge", itemPdTargetGrid: "Puissance cible réseau",
    slotSchedule: "Horaire", slotDays: "Jours", slotAll: "Toutes", slotMode: "Mode", slotManual: "Manuel", slotPd: "PD",
    slotAllows: "Autorise", slotChargeWord: "charge", slotDischargeWord: "décharge", slotNothing: "rien",
    slotSocOverride: "Surcharge SOC", slotYes: "oui", slotPowerOverride: "Surcharge puissance",
    slotStateLabel: "État", slotActiveWord: "actif", slotInactiveWord: "inactif",
  },
  nl: {
    subtitle: "Energy Manager",
    live: "Live",
    tabResumen: "Overzicht", tabBaterias: "Batterijen", tabControl: "Bediening",
    moreInfo: "Geschiedenis tonen",
    zoomReset: "Alles",
    placeholderMsg: "Deze weergave komt in een latere fase. Gebruik voorlopig het Overzicht.",
    cardFlow: "Energiestroom", cardSoc: "Systeemstatus", cardDaily: "Energie vandaag",
    cardWeekly: "Energie per week", cardPower: "Vermogen", cardSocToday: "SOC · vandaag",
    grid: "Net", solar: "Zon", home: "Huis", battery: "Batterij",
    importing: "Invoer", exporting: "Teruglevering",
    charging: "Laden", discharging: "Ontladen", idle: "Rust",
    selfConsumptionSuffix: "% zelfconsumptie", units: "stuks",
    charge: "Laden", discharge: "Ontladen", availOf: "van {value} beschikbaar",
    charged: "Geladen", discharged: "Ontladen",
    gridImport: "Net ingevoerd", gridExport: "Net teruggeleverd",
    now: "nu", noData: "Geen gegevens", imported: "Ingevoerd", exported: "Teruggeleverd",
    diagTitle: "Integratiestatus",
    diagIntegration: "Integratie", diagNetBalance: "Nettosaldo", diagAlarm: "Alarm",
    diagActiveBatteries: "Actieve batterijen", diagNonResponsive: "Geen reactie",
    diagDischargeWindow: "Ontlaadvenster", diagPredictive: "Voorspellend laden",
    diagPeak: "Piekbegrenzing", diagWeeklyCharge: "Wekelijkse lading", diagChargeDelay: "Laadvertraging",
    nResponsive: "{n} geen reactie", none: "Geen",
    noBatteriesTitle: "Geen batterijen",
    noBatteriesMsg: "Er zijn geen batterijapparaten gedetecteerd in deze integratie.",
    healthCells: "Gezondheid & cellen",
    mTemp: "Temperatuur", mVoltage: "Spanning", mCellMax: "Cel max", mCellMin: "Cel min",
    mCellDelta: "Δ cel", mCycles: "Cycli", mEfficiency: "Efficiëntie", mHysteresis: "Hysterese",
    solarMppt: "Solar (MPPT)", controls: "Bediening", deviceInfo: "Apparaatinformatie",
    offgrid: "Eilandbedrijf", infoComm: "Comm.-module",
    invBackup: "Back-up", invUpdating: "Bijwerken", invStandby: "Stand-by", invBypass: "Bypass",
    active: "Actief", inactive: "Inactief",
    ctlEmpty: "Geen bedieningen ingeschakeld. Schakel ze in op het apparaat (Instellingen → uitgeschakelde entiteiten).",
    sysEmptyTitle: "Geen bedieningen beschikbaar",
    sysEmptyMsg: "Deze integratie biedt geen systeembedieningen, of ze zijn uitgeschakeld. Schakel ze in via Instellingen → entiteiten.",
    bcAllowCharge: "Laden toestaan", bcAllowDischarge: "Ontladen toestaan",
    bcSocMax: "Max. SOC", bcSocMin: "Min. SOC", bcWorkMode: "Werkmodus", bcForceMode: "Geforceerde modus",
    bcChargePower: "Laadvermogen", bcDischargePower: "Ontlaadvermogen",
    bcMaxCharge: "Max. laden", bcMaxDischarge: "Max. ontladen",
    bcChargeToSoc: "Laden tot SOC", bcChargeHysteresis: "Laadhysterese", bcBackup: "Back-upfunctie",
    secManual: "Handmatige modus", itemEnable: "Inschakelen",
    itemMaxContracted: "Max. gecontracteerd vermogen", itemSolarSafety: "Veiligheidsmarge zon",
    itemSocThreshold: "SOC-drempel", itemPeakLimit: "Pieklimiet",
    itemDelaySafety: "Veiligheidsmarge", itemDelaySoc: "Doel-SOC vertraging",
    secHourly: "Uurbalans", secWeeklyFull: "Wekelijkse volledige lading", itemWeeklyDay: "Dag volledige lading",
    secSlots: "Geconfigureerde tijdvakken", itemSlot: "Tijdvak",
    secExcluded: "Uitgesloten apparaten", itemExcludedDevice: "Uitgesloten apparaat", itemSolarSurplus: "Zonne-overschot",
    secSysLimits: "Systeemvermogenslimieten", itemSysMaxCharge: "Max. systeemladen", itemSysMaxDischarge: "Max. systeemontladen",
    secPd: "PD-regelaar (geavanceerd)",
    itemPdKp: "Proportionele versterking (Kp)", itemPdKd: "Differentiële versterking (Kd)", itemPdDeadband: "Dode zone",
    itemPdMaxChange: "Max. vermogenswijziging", itemPdDirHyst: "Richtingshysterese",
    itemPdMinCharge: "Min. laadvermogen", itemPdMinDischarge: "Min. ontlaadvermogen", itemPdTargetGrid: "Doelnetvermogen",
    slotSchedule: "Schema", slotDays: "Dagen", slotAll: "Alle", slotMode: "Modus", slotManual: "Handmatig", slotPd: "PD",
    slotAllows: "Staat toe", slotChargeWord: "laden", slotDischargeWord: "ontladen", slotNothing: "niets",
    slotSocOverride: "SOC-overschrijving", slotYes: "ja", slotPowerOverride: "Vermogensoverschrijving",
    slotStateLabel: "Status", slotActiveWord: "actief", slotInactiveWord: "inactief",
  },
};

// translation_key -> role. These are stable identifiers set by the integration
// (see const.py / *_sensors.py), independent of the user's language or renames.
const K = {
  // per battery
  batterySoc: "battery_soc",
  acPower: "ac_power", // AC-side power. HA sign: - charge / + discharge (W)
  storedEnergy: "stored_energy", // kWh
  batteryTotalEnergy: "battery_total_energy", // capacity kWh
  inverterState: "inverter_state",
  dailyCharge: "total_daily_charging_energy",
  dailyDischarge: "total_daily_discharging_energy",
  maxChargePower: "max_charge_power",
  maxDischargePower: "max_discharge_power",
  batteryVoltage: "battery_voltage",
  internalTemp: "internal_temperature",
  cellMax: "max_cell_voltage",
  cellMin: "min_cell_voltage",
  cellDelta: "cell_delta", // measured imbalance (mV) from the balance monitor
  cycles: "battery_cycle_count",
  cyclesCalc: "battery_cycle_count_calc",
  rte: "round_trip_efficiency_total",
  bmsVersion: "bms_version",
  vmsVersion: "vms_version",
  emsVersion: "ems_version",
  commFw: "comm_module_firmware",
  wifiSignal: "wifi_signal_strength",
  wifiStatus: "wifi_status",
  mac: "mac_address",
  deviceName: "device_name",
  // backup / offgrid + charge hysteresis (per battery)
  acOffgridPower: "ac_offgrid_power", // power delivered to off-grid/backup loads (W)
  backupFunction: "backup_function", // backup/off-grid switch
  chargeHysteresisActive: "charge_hysteresis", // binary: hysteresis blocking charge
  // system aggregates
  sysSoc: "system_soc",
  sysStored: "system_stored_energy",
  sysCapacity: "system_total_energy",
  sysChargePower: "system_charge_power",
  sysDischargePower: "system_discharge_power",
  sysDailyCharge: "system_daily_charging_energy",
  sysDailyDischarge: "system_daily_discharging_energy",
  sysDailySolar: "system_daily_solar_energy", // exact daily PV production (kWh)
  sysDailyHome: "system_daily_home_energy", // exact daily home consumption (kWh)
  sysDailyGridImport: "system_daily_grid_import_energy", // exact daily grid import (kWh)
  sysDailyGridExport: "system_daily_grid_export_energy", // exact daily grid export (kWh)
  sysAlarm: "system_alarm_status",
  // diagnostics / flags
  netBalance: "balance_neto",
  activeBatteries: "active_batteries",
  nonResponsive: "non_responsive_batteries",
  integration: "integration_status",
  dischargeWindow: "discharge_window",
  predictiveSwitch: "predictive_charging",
  peakSwitch: "capacity_protection",
  // diagnostic-category entities of the "Marstek Venus System" device
  predictiveActive: "predictive_charging_active",
  capacityActive: "capacity_protection_active",
  weeklyFullCharge: "weekly_full_charge",
  chargeDelay: "charge_delay_status",
};

const MPPT_KEYS = ["mppt1_power", "mppt2_power", "mppt3_power", "mppt4_power"];

// Diagnostic rows shown in the SOC card's second section (2-column grid).
// One per diagnostic-category entity on the system device, except the hidden
// configuration_summary (support-only) and balance_neto (own dedicated card).
// Values are localized at render time via hass.formatEntityState.
const DIAG_ROWS = [
  { key: K.integration, lk: "diagIntegration" },
  { key: K.netBalance, lk: "diagNetBalance" },
  { key: K.sysAlarm, lk: "diagAlarm" },
  { key: K.activeBatteries, lk: "diagActiveBatteries" },
  { key: K.nonResponsive, lk: "diagNonResponsive" },
  { key: K.dischargeWindow, lk: "diagDischargeWindow" },
  { key: K.predictiveActive, lk: "diagPredictive" },
  { key: K.capacityActive, lk: "diagPeak" },
  { key: K.weeklyFullCharge, lk: "diagWeeklyCharge" },
  { key: K.chargeDelay, lk: "diagChargeDelay" },
];

// Cell-imbalance color thresholds (raw delta, mV). Mirror const.py
// BALANCE_THRESHOLD_YELLOW/ORANGE/RED so the panel tier matches the integration.
const DELTA_MV_YELLOW = 200;
const DELTA_MV_ORANGE = 230;
const DELTA_MV_RED = 250;

// Per-battery control entities, matched by translation_key. A control is only
// rendered when its entity is enabled (has a live state); most default to
// disabled in the integration. `domain` selects the widget + service.
const BAT_CONTROLS = [
  { key: "battery_allow_charge", domain: "switch", lk: "bcAllowCharge", icon: "mdi:battery-arrow-up" },
  { key: "battery_allow_discharge", domain: "switch", lk: "bcAllowDischarge", icon: "mdi:battery-arrow-down" },
  { key: "charging_cutoff_capacity", domain: "number", lk: "bcSocMax", icon: "mdi:battery-high" },
  { key: "discharging_cutoff_capacity", domain: "number", lk: "bcSocMin", icon: "mdi:battery-low" },
  { key: "user_work_mode", domain: "select", lk: "bcWorkMode", icon: "mdi:cog-transfer-outline" },
  { key: "force_mode", domain: "select", lk: "bcForceMode", icon: "mdi:gesture-tap-button" },
  { key: "set_charge_power", domain: "number", lk: "bcChargePower", icon: "mdi:battery-arrow-up-outline" },
  { key: "set_discharge_power", domain: "number", lk: "bcDischargePower", icon: "mdi:battery-arrow-down-outline" },
  { key: "max_charge_power", domain: "number", lk: "bcMaxCharge", icon: "mdi:battery-arrow-up-outline" },
  { key: "max_discharge_power", domain: "number", lk: "bcMaxDischarge", icon: "mdi:battery-arrow-down-outline" },
  { key: "charge_to_soc", domain: "number", lk: "bcChargeToSoc", icon: "mdi:battery-sync-outline" },
  { key: "charge_hysteresis_percent", domain: "number", lk: "bcChargeHysteresis", icon: "mdi:battery-sync" },
  { key: "backup_function", domain: "switch", lk: "bcBackup", icon: "mdi:home-battery-outline" },
];

// Unified Control tab: system-level entities grouped BY FEATURE — each section
// is one capability with its on/off switch first, then its related config
// params (CONFIG number sliders / selects). Entities are matched by
// translation_key on the system device (switch.py/select.py/number.py with
// identifier "marstek_venus_system"). domain defaults to "number". Only entities
// with a live state render; conditional params only exist when their feature is
// configured, so a section collapses to just what's present (and hides if empty).
// `tk`/`lk` are i18n keys resolved at render time (see _t). labelFn/titleFn
// receive the live state and a translator `t` so dynamic text is localized too.
const SYS_SECTIONS = [
  {
    tk: "secManual",
    icon: "mdi:hand-back-right-outline",
    items: [
      { key: "manual_mode", domain: "switch", lk: "secManual", icon: "mdi:hand-back-right-outline" },
    ],
  },
  {
    tk: "secWeeklyFull",
    icon: "mdi:calendar-check",
    items: [
      { key: "weekly_full_charge_day", domain: "select", lk: "itemWeeklyDay", icon: "mdi:calendar-week" },
    ],
  },
  {
    tk: "secSlots",
    icon: "mdi:calendar-clock",
    // time_slot is indexed (one per slot). Label is the short "Slot N"; the
    // slot's details (schedule/days/apply-to-charge/state) go in a hover tooltip.
    items: [
      {
        key: "time_slot",
        domain: "switch",
        lk: "itemSlot",
        icon: "mdi:calendar-clock",
        labelFn: (st, t) => {
          const a = (st && st.attributes) || {};
          const m = String(a.friendly_name || "").match(/(\d+)\s*$/);
          return m ? `${t("itemSlot")} ${m[1]}` : null;
        },
        titleFn: (st, t) => {
          const a = (st && st.attributes) || {};
          const names = a.battery_names || {};
          const lim = a.battery_limits || {};
          const L = [];
          if (a.schedule && a.schedule !== "??-??") L.push(`${t("slotSchedule")}: ${a.schedule}`);
          if (a.days && a.days !== "None") L.push(`${t("slotDays")}: ${a.days}`);
          L.push(`${t("tabBaterias")}: ${a.battery_scope === "all" || !a.battery_scope_name ? t("slotAll") : a.battery_scope_name}`);
          if (a.mode) L.push(`${t("slotMode")}: ${a.mode === "manual" ? t("slotManual") : t("slotPd")}`);
          const allow = [];
          if (a.allow_charge) allow.push(t("slotChargeWord"));
          if (a.allow_discharge) allow.push(t("slotDischargeWord"));
          L.push(`${t("slotAllows")}: ${allow.length ? allow.join(" + ") : t("slotNothing")}`);
          if (a.soc_override_enabled) {
            const p = Object.entries(lim)
              .filter(([, v]) => v && (v.soc_min != null || v.soc_max != null))
              .map(([k, v]) => `${names[k] || k} ${v.soc_min ?? "—"}–${v.soc_max ?? "—"}%`);
            L.push(`${t("slotSocOverride")}: ${p.length ? p.join(", ") : t("slotYes")}`);
          }
          if (a.power_override_enabled) {
            const p = Object.entries(lim)
              .filter(([, v]) => v && (v.max_charge_power_w != null || v.max_discharge_power_w != null))
              .map(([k, v]) => `${names[k] || k} ↑${v.max_charge_power_w ?? "—"}W ↓${v.max_discharge_power_w ?? "—"}W`);
            L.push(`${t("slotPowerOverride")}: ${p.length ? p.join(", ") : t("slotYes")}`);
          }
          L.push(`${t("slotStateLabel")}: ${st && st.state === "on" ? t("slotActiveWord") : t("slotInactiveWord")}`);
          return L.join("\n");
        },
      },
    ],
  },
  {
    tk: "secExcluded",
    icon: "mdi:power-plug-off-outline",
    // Each control is indexed per excluded device; the entity name embeds the
    // device ("{device} – Enabled" / "– Solar Surplus"), so always use it —
    // otherwise a single excluded device would show a generic, unidentifiable row.
    items: [
      { key: "excluded_device_enabled", domain: "switch", lk: "itemExcludedDevice", icon: "mdi:power-plug-off", useName: true },
      { key: "excluded_device_solar_surplus", domain: "switch", lk: "itemSolarSurplus", icon: "mdi:solar-power", useName: true },
    ],
  },
  {
    tk: "secPd",
    icon: "mdi:tune",
    items: [
      { key: "pd_controller_kp", lk: "itemPdKp", icon: "mdi:tune" },
      { key: "pd_controller_kd", lk: "itemPdKd", icon: "mdi:tune" },
      { key: "pd_controller_deadband", lk: "itemPdDeadband", icon: "mdi:arrow-collapse-horizontal" },
      { key: "pd_controller_max_power_change", lk: "itemPdMaxChange", icon: "mdi:delta" },
      { key: "pd_controller_direction_hysteresis", lk: "itemPdDirHyst", icon: "mdi:swap-horizontal" },
      { key: "pd_min_charge_power", lk: "itemPdMinCharge", icon: "mdi:battery-charging-low" },
      { key: "pd_min_discharge_power", lk: "itemPdMinDischarge", icon: "mdi:battery-low" },
      { key: "pd_target_grid_power", lk: "itemPdTargetGrid", icon: "mdi:transmission-tower-export" },
    ],
  },
  {
    tk: "diagPredictive",
    icon: "mdi:brain",
    items: [
      { key: "predictive_charging", domain: "switch", lk: "itemEnable", icon: "mdi:brain" },
      { key: "max_contracted_power", lk: "itemMaxContracted", icon: "mdi:transmission-tower" },
      { key: "predictive_safety_margin_kwh", lk: "itemSolarSafety", icon: "mdi:solar-power-variant" },
    ],
  },
  {
    tk: "diagChargeDelay",
    icon: "mdi:timer-sand",
    items: [
      { key: "charge_delay", domain: "switch", lk: "itemEnable", icon: "mdi:timer-sand" },
      { key: "delay_safety_margin_min", lk: "itemDelaySafety", icon: "mdi:timer-sand-complete" },
      { key: "delay_soc_setpoint", lk: "itemDelaySoc", icon: "mdi:battery-charging-50" },
    ],
  },
  {
    tk: "secHourly",
    icon: "mdi:scale-balance",
    items: [
      { key: "hourly_balance", domain: "switch", lk: "itemEnable", icon: "mdi:scale-balance" },
    ],
  },
  {
    tk: "secSysLimits",
    icon: "mdi:speedometer",
    items: [
      { key: "system_max_charge_power", lk: "itemSysMaxCharge", icon: "mdi:battery-arrow-up-outline" },
      { key: "system_max_discharge_power", lk: "itemSysMaxDischarge", icon: "mdi:battery-arrow-down-outline" },
    ],
  },
  {
    tk: "diagPeak",
    icon: "mdi:flash-alert",
    items: [
      { key: "capacity_protection", domain: "switch", lk: "itemEnable", icon: "mdi:flash-alert" },
      { key: "capacity_protection_soc_threshold", lk: "itemSocThreshold", icon: "mdi:battery-alert-variant-outline" },
      { key: "capacity_protection_limit", lk: "itemPeakLimit", icon: "mdi:flash" },
    ],
  },
];

// Control tab layout, by section `tk`. Sections absent from the live registry
// are skipped; an empty column/row is dropped (no gaps).
//  - `pair`: columns 1 & 2 rendered as a 2-col grid so each row's two cards
//    share a height (Manual≈Semanal, Predictiva≈Retardo, Horario≈Límites). A
//    `null` (or absent) partner leaves an invisible spacer to keep the pairing.
//  - `col`: an independent vertical stack (columns 3-5).
const SYS_LAYOUT = [
  {
    pair: [
      ["secManual", "secWeeklyFull"],
      ["diagPredictive", "diagChargeDelay"],
      ["secHourly", "secSysLimits"],
      ["diagPeak", null],
    ],
  },
  { col: ["secSlots"] },
  { col: ["secExcluded"] },
  { col: ["secPd"] },
];

class MarstekVenusPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panelConfig = {};
    this._built = false;
    this._view = "resumen";
    this._r = {}; // dynamic node refs for patch-in-place
    this._edgeSig = {}; // per flow edge: last dot signature
    this._socSeries = []; // SOC % samples for the sparkline (history seed + live)
    this._socLastPush = 0; // last live-append timestamp (s), to throttle pushes
    this._powerSeries = null; // { t:[...], solar/home/grid/battery:[...] } kW, 24h
    this._weekly = null; // { days:[..7], charge/discharge/import/export:[..7] } kWh
    this._histTimer = null;
  }

  // --- HA-injected properties ------------------------------------------------
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._applyTheme();
    this._update();
    if (first) this._startHistory();
  }
  get hass() {
    return this._hass;
  }
  set panel(panel) {
    this._panelConfig = (panel && panel.config) || {};
  }
  set narrow(v) {
    this._narrow = v;
  }
  set route(_v) {}

  connectedCallback() {
    this._injectFonts();
    this._update();
  }
  disconnectedCallback() {
    if (this._histTimer) clearInterval(this._histTimer);
  }

  // --- config / theme --------------------------------------------------------
  _domain() {
    return this._panelConfig.domain || FALLBACK_DOMAIN;
  }
  _title() {
    return this._panelConfig.title || FALLBACK_TITLE;
  }
  _lang() {
    return (this._hass && this._hass.locale && this._hass.locale.language) || "es-ES";
  }
  /** Two-letter UI language for i18n lookups ("es-ES" -> "es"). */
  _lang2() {
    return String(this._lang()).split("-")[0].toLowerCase();
  }
  /** Localized panel string by key. Falls back es/de/fr/nl -> en -> key.
   *  `vars` fills {name} placeholders. */
  _t(key, vars) {
    const dict = I18N[this._lang2()] || I18N.en;
    let s = dict[key] != null ? dict[key] : I18N.en[key] != null ? I18N.en[key] : key;
    if (vars) for (const k in vars) s = s.replace("{" + k + "}", vars[k]);
    return s;
  }
  _applyTheme() {
    const dark = !this._hass || !this._hass.themes || this._hass.themes.darkMode !== false;
    this.setAttribute("data-theme", dark ? "dark" : "light");
  }
  _injectFonts() {
    if (document.getElementById("mvem-fonts")) return;
    const l = document.createElement("link");
    l.id = "mvem-fonts";
    l.rel = "stylesheet";
    l.href =
      "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap";
    document.head.appendChild(l);
  }

  // --- entity resolution -----------------------------------------------------
  /** Index this integration's entities by translation_key and by device. */
  _index() {
    const hass = this._hass;
    const domain = this._domain();
    const reg = hass.entities || {};
    const byKey = new Map(); // translation_key -> [entity_id]
    const byDevice = new Map(); // device_id -> [entity_id]

    for (const e of Object.values(reg)) {
      if (e.platform !== domain || e.hidden) continue;
      const tk = e.translation_key;
      if (tk) {
        if (!byKey.has(tk)) byKey.set(tk, []);
        byKey.get(tk).push(e.entity_id);
      }
      const dev = e.device_id || "_";
      if (!byDevice.has(dev)) byDevice.set(dev, []);
      byDevice.get(dev).push(e.entity_id);
    }
    return { byKey, byDevice };
  }

  _statesFor(byKey, key) {
    const ids = byKey.get(key) || [];
    return ids.map((id) => this._hass.states[id]).filter(Boolean);
  }
  _stateFor(byKey, key) {
    return this._statesFor(byKey, key)[0] || null;
  }
  /** First system/aggregate entity_id for a translation_key (for more-info). */
  _sysEntityId(key) {
    const { byKey } = this._index();
    return (byKey.get(key) || [])[0] || null;
  }
  _num(stateObj) {
    if (!stateObj) return null;
    const n = Number(stateObj.state);
    return Number.isNaN(n) ? null : n;
  }
  /** Sum numeric states for a key across all batteries. */
  _sum(byKey, key) {
    let total = null;
    for (const s of this._statesFor(byKey, key)) {
      const n = this._num(s);
      if (n != null) total = (total || 0) + n;
    }
    return total;
  }
  /** Convert a power state to Watts regardless of W/kW unit. */
  _watts(stateObj) {
    const n = this._num(stateObj);
    if (n == null) return null;
    const u = (stateObj.attributes.unit_of_measurement || "").toLowerCase();
    return u === "kw" ? n * 1000 : n;
  }

  // --- model builder ---------------------------------------------------------
  /** Build the single source-of-truth model (mirrors the prototype `s`/`agg`). */
  _model() {
    const { byKey, byDevice } = this._index();
    const hass = this._hass;

    // Per-battery list (one device per unit, excluding the "system" virtual one).
    const batteries = [];
    for (const [dev, ids] of byDevice) {
      const socObj = ids.map((id) => hass.states[id]).find((s) => {
        const e = hass.entities[s && s.entity_id];
        return e && e.translation_key === K.batterySoc;
      });
      if (!socObj) continue; // not a battery device
      const get = (key) => {
        const id = ids.find((i) => {
          const e = hass.entities[i];
          return e && e.translation_key === key;
        });
        return id ? hass.states[id] : null;
      };
      const acW = this._watts(get(K.acPower));
      batteries.push({
        dev,
        soc: this._num(socObj),
        // ac_power HA sign is - charge / + discharge; negate to panel's + charge / - discharge
        powerW: acW == null ? null : -acW,
        stored: this._num(get(K.storedEnergy)),
        capacity: this._num(get(K.batteryTotalEnergy)),
        inverter: (get(K.inverterState) || {}).state || null,
      });
    }

    const nBat = batteries.length;
    const socList = batteries.map((b) => b.soc).filter((v) => v != null);
    const capList = batteries.map((b) => b.capacity).filter((v) => v != null);

    // ----- aggregates (prefer system sensors, else derive from batteries) -----
    const capacity =
      this._num(this._stateFor(byKey, K.sysCapacity)) ??
      (capList.length ? capList.reduce((a, b) => a + b, 0) : null);
    let soc = this._num(this._stateFor(byKey, K.sysSoc));
    if (soc == null && socList.length) {
      // capacity-weighted average when possible, else plain mean
      const wsum = batteries.reduce(
        (a, b) => (b.soc != null && b.capacity ? a + b.soc * b.capacity : a),
        0
      );
      const csum = batteries.reduce(
        (a, b) => (b.soc != null && b.capacity ? a + b.capacity : a),
        0
      );
      soc = csum ? wsum / csum : socList.reduce((a, b) => a + b, 0) / socList.length;
    }
    let stored = this._num(this._stateFor(byKey, K.sysStored));
    if (stored == null) {
      const s = this._sum(byKey, K.storedEnergy);
      stored = s != null ? s : capacity != null && soc != null ? (capacity * soc) / 100 : null;
    }
    const dailyCharge =
      this._num(this._stateFor(byKey, K.sysDailyCharge)) ?? this._sum(byKey, K.dailyCharge) ?? 0;
    const dailyDischarge =
      this._num(this._stateFor(byKey, K.sysDailyDischarge)) ??
      this._sum(byKey, K.dailyDischarge) ??
      0;

    // active / offline counts
    const activeNum = this._num(this._stateFor(byKey, K.activeBatteries));
    const active = activeNum != null ? activeNum : nBat;
    const nrObj = this._stateFor(byKey, K.nonResponsive);
    let offline = 0;
    if (nrObj) {
      const v = String(nrObj.state).trim().toLowerCase();
      if (v && v !== "none" && v !== "0" && v !== "unknown" && v !== "unavailable") {
        const n = Number(nrObj.state);
        offline = Number.isNaN(n) ? v.split(",").filter(Boolean).length : n;
      }
    }

    // ----- flow (kW) -----
    // battery net: prefer per-battery signed sum (+charge/-discharge), else system.
    let battW = null;
    const battSum = batteries.reduce(
      (a, b) => (b.powerW != null ? (a || 0) + b.powerW : a),
      null
    );
    if (battSum != null) battW = battSum;
    else {
      const c = this._num(this._stateFor(byKey, K.sysChargePower));
      const d = this._num(this._stateFor(byKey, K.sysDischargePower));
      if (c != null || d != null) battW = (c || 0) - (d || 0);
    }
    const battery = battW != null ? battW / 1000 : 0;

    // solar: explicit production sensor (external inverter) takes priority;
    // else sum per-battery MPPT sensors when the model exposes any.
    let solarW = null;
    const solarObj = this._panelConfig.solar_entity
      ? hass.states[this._panelConfig.solar_entity]
      : null;
    const explicitSolarW = this._watts(solarObj);
    if (explicitSolarW != null) {
      solarW = explicitSolarW;
    } else {
      for (const mk of MPPT_KEYS) {
        const s = this._sum(byKey, mk);
        if (s != null) solarW = (solarW || 0) + s;
      }
    }
    const solar = solarW != null ? Math.max(0, solarW / 1000) : 0;
    const hasSolar = solarW != null;

    // grid from the configured net meter (+import / -export)
    const gridObj = this._panelConfig.grid_entity
      ? hass.states[this._panelConfig.grid_entity]
      : null;
    const gridW = this._watts(gridObj);
    const grid = gridW != null ? gridW / 1000 : null;

    // home: explicit sensor, else derive  home = grid - battery + solar
    const homeObj = this._panelConfig.home_entity
      ? hass.states[this._panelConfig.home_entity]
      : null;
    const homeW = this._watts(homeObj);
    let home;
    if (homeW != null) home = homeW / 1000;
    else if (grid != null) home = Math.max(0, grid - battery + solar);
    else home = 0;

    const netBalance = this._num(this._stateFor(byKey, K.netBalance));

    // total available power for the bar (sum of per-unit max limits, else heuristic)
    const maxCh = this._sum(byKey, K.maxChargePower);
    const maxDis = this._sum(byKey, K.maxDischargePower);

    // ----- diagnostics -----
    // raw state object per diagnostic row, localized later via formatEntityState
    const diagStates = {};
    for (const row of DIAG_ROWS) diagStates[row.key] = this._stateFor(byKey, row.key);
    const alarmObj = diagStates[K.sysAlarm];

    // exact daily solar/home/grid energy (kWh) from the backend accumulator sensors
    const dailySolar = this._num(this._stateFor(byKey, K.sysDailySolar));
    const dailyHome = this._num(this._stateFor(byKey, K.sysDailyHome));
    const dailyGridImport = this._num(this._stateFor(byKey, K.sysDailyGridImport));
    const dailyGridExport = this._num(this._stateFor(byKey, K.sysDailyGridExport));

    return {
      nBat,
      solar,
      hasSolar,
      home,
      grid,
      battery,
      soc,
      capacity,
      stored,
      dailyCharge,
      dailyDischarge,
      dailySolar,
      dailyHome,
      dailyGridImport,
      dailyGridExport,
      active,
      offline,
      netBalance,
      maxCharge: maxCh,
      maxDischarge: maxDis,
      alarm: alarmObj ? alarmObj.state : null,
      diagStates,
    };
  }

  // --- formatting ------------------------------------------------------------
  _nf(n, d = 2) {
    if (n == null || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString(this._lang(), {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  }
  _fmtPower(w) {
    if (w == null || Number.isNaN(w)) return { v: "—", u: "" };
    const a = Math.abs(w);
    if (a < 1000) return { v: Math.round(w).toLocaleString(this._lang()), u: "W" };
    return { v: this._nf(w / 1000, 2), u: "kW" };
  }
  _clamp(x, a, b) {
    return Math.max(a, Math.min(b, x));
  }

  // --- update / render -------------------------------------------------------
  _update() {
    if (!this._hass || !this.isConnected) return;
    if (!this._built) {
      this._renderShell();
      this._built = true;
    }
    if (this._view === "resumen") this._patch(this._model());
    else if (this._view === "baterias") this._patchBatteries(this._batteryModel());
    else if (this._view === "control") this._patchControl();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(this._styleEl());

    const app = document.createElement("div");
    app.className = "app";
    app.appendChild(this._renderAppbar());

    const main = document.createElement("div");
    main.className = "main";
    app.appendChild(main);
    this._main = main;

    this.shadowRoot.appendChild(app);
    this._setView(this._view); // builds the active view
  }

  _renderAppbar() {
    const bar = document.createElement("div");
    bar.className = "appbar";

    const brand = document.createElement("div");
    brand.className = "brand";
    brand.innerHTML = `
      <div class="logo">M</div>
      <div class="btext">
        <div class="bt-name">${this._title()}</div>
        <div class="bt-sub">${this._t("subtitle")}</div>
      </div>`;
    brand.querySelector(".logo").addEventListener("click", () =>
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }))
    );

    const tabs = document.createElement("div");
    tabs.className = "tabs";
    const TABS = [
      ["resumen", "mdi:view-dashboard-outline", this._t("tabResumen")],
      ["baterias", "mdi:battery-high", this._t("tabBaterias")],
      ["control", "mdi:tune-variant", this._t("tabControl")],
    ];
    this._tabEls = {};
    for (const [id, icon, label] of TABS) {
      const t = document.createElement("button");
      t.className = "tab";
      t.innerHTML = `<ha-icon icon="${icon}"></ha-icon><span class="tab-label">${label}</span>`;
      t.addEventListener("click", () => this._setView(id));
      this._tabEls[id] = t;
      tabs.appendChild(t);
    }

    bar.appendChild(brand);
    bar.appendChild(tabs);
    return bar;
  }

  _setView(view) {
    this._view = view;
    for (const [id, el] of Object.entries(this._tabEls || {})) {
      el.classList.toggle("active", id === view);
    }
    if (!this._main) return;
    this._main.innerHTML = "";
    if (view === "resumen") {
      this._main.appendChild(this._renderResumen());
      this._patch(this._model());
    } else if (view === "baterias") {
      this._main.appendChild(this._renderBaterias());
      this._patchBatteries(this._batteryModel());
    } else if (view === "control") {
      this._main.appendChild(this._renderControl());
      this._patchControl();
    } else {
      this._main.appendChild(this._placeholder(view));
    }
  }

  _placeholder(view) {
    const names = { baterias: this._t("tabBaterias"), control: this._t("tabControl") };
    const d = document.createElement("div");
    d.className = "placeholder";
    d.innerHTML = `
      <ha-icon icon="mdi:hammer-wrench"></ha-icon>
      <h3>${names[view] || view}</h3>
      <p>${this._t("placeholderMsg")}</p>`;
    return d;
  }

  // ===== Resumen view ========================================================
  _renderResumen() {
    this._r = {};
    this._edgeSig = {};
    this._buildCards();
    const c = this._cards;
    const wrap = (cls, children) => {
      const d = document.createElement("div");
      d.className = cls;
      children.forEach((ch) => d.appendChild(ch));
      return d;
    };
    // hero (SOC + power + diagnostics) on top; below, Flujo on the left and a
    // 2×2 chart grid on the right (top row auto-fits Energía hoy, bottom fills)
    return wrap("res-stack", [
      c.soc,
      wrap("resumen-lower", [
        c.flow,
        wrap("charts-2x2", [c.daily, c.weekly, c.power, c.mini]),
      ]),
    ]);
  }

  _card(title, icon) {
    const card = document.createElement("div");
    card.className = "card";
    const head = document.createElement("div");
    head.className = "card-head";
    head.innerHTML = `<span class="ic"><ha-icon icon="${icon}"></ha-icon></span><h2>${title}</h2>`;
    card.appendChild(head);
    return { card, head };
  }

  _buildCards() {
    this._cards = {
      flow: this._buildFlowCard(),
      soc: this._buildSocCard(),
      daily: this._buildDailyCard(),
      weekly: this._buildWeeklyCard(),
      power: this._buildPowerHistoryCard(),
      mini: this._buildMiniHistory(),
    };
  }

  // ----- Flow card -----
  _buildFlowCard() {
    const { card, head } = this._card(this._t("cardFlow"), "mdi:transit-connection-variant");
    card.classList.add("flow-card");
    const livePill = document.createElement("span");
    livePill.className = "pill";
    livePill.style.marginLeft = "auto";
    livePill.innerHTML = `<span class="dot live"></span>${this._t("live")}`;
    head.appendChild(livePill);

    const wrap = document.createElement("div");
    wrap.className = "flow-wrap";
    const sq = document.createElement("div");
    sq.className = "scene-stage";

    // 3D-render backdrop + leader-line callouts (Tesla style). Lines are
    // axis-aligned (straight, or an L-elbow), never diagonal, and stop short of
    // the label text. Day/night renders are swapped by sun position.
    const sceneBase = new URL(".", import.meta.url);
    this._sceneDay = new URL("home-scene-day.png", sceneBase).href;
    this._sceneNight = new URL("home-scene-night.png", sceneBase).href;
    const GAP = 5; // % gap so the line ends before the label text

    // ex,ey = point on the render. lx,ly = label position.
    // shape: "v"  straight vertical (lx == ex)
    //        "hv" horizontal from element, then vertical down/up to the label
    //        "vh" vertical from element, then horizontal to the label
    const EDGES = [
      { key: "nGrid",  edge: "grid",  cap: this._t("grid"),    ex: 38, ey: 63, lx: 12, ly: 9,  shape: "hv" },
      { key: "nSolar", edge: "solar", cap: this._t("solar"),   ex: 50, ey: 33, lx: 50, ly: 9,  shape: "v" },
      { key: "nHome",  edge: "home",  cap: this._t("home"),    ex: 66, ey: 48, lx: 88, ly: 9,  shape: "hv" },
      { key: "nBatt",  edge: "batt",  cap: this._t("battery"), ex: 61, ey: 62, lx: 50, ly: 88, shape: "hv" },
    ];
    const leadPts = (e) => {
      if (e.shape === "hv") {
        const y2 = e.ly < e.ey ? e.ly + GAP : e.ly - GAP;
        return `${e.ex},${e.ey} ${e.lx},${e.ey} ${e.lx},${y2}`;
      }
      if (e.shape === "vh") {
        const x2 = e.lx < e.ex ? e.lx + GAP : e.lx - GAP;
        return `${e.ex},${e.ey} ${e.ex},${e.ly} ${x2},${e.ly}`;
      }
      const y2 = e.ly < e.ey ? e.ly + GAP : e.ly - GAP; // "v"
      return `${e.ex},${e.ey} ${e.ex},${y2}`;
    };

    const day = this._isDaytime();
    this._sceneIsDay = day;
    sq.innerHTML =
      `<img class="scene-img" src="${day ? this._sceneDay : this._sceneNight}" alt="" draggable="false">` +
      `<svg class="lead-svg" viewBox="0 0 100 100" preserveAspectRatio="none">` +
      EDGES.map(
        (e) =>
          `<polyline class="lead" data-edge="${e.edge}" points="${leadPts(e)}"/>` +
          `<polyline class="lead-flow" data-edge="${e.edge}" pathLength="100" points="${leadPts(e)}"/>` +
          `<circle class="lead-end" data-edge="${e.edge}" cx="${e.ex}" cy="${e.ey}" r="0.7"/>`
      ).join("") +
      `</svg>`;

    const img = sq.querySelector(".scene-img");
    img.addEventListener("error", () => {
      if (img.dataset.fb) return;
      img.dataset.fb = "1";
      img.src = new URL("home-scene.png", sceneBase).href; // single-image fallback
    });

    const node = (e) => {
      const n = document.createElement("div");
      n.className = "scene-lbl l-" + e.edge;
      n.style.left = e.lx + "%";
      n.style.top = e.ly + "%";
      n.innerHTML =
        `<div class="lbl-val num"><span class="fn-v">—</span><span class="fn-unit"></span></div>` +
        `<div class="lbl-cap pf-label">${e.cap}</div>` +
        `<div class="lbl-badge pf-badge"></div>`;
      sq.appendChild(n);
      this._r[e.key] = {
        node: n,
        val: n.querySelector(".fn-v"),
        unit: n.querySelector(".fn-unit"),
        label: n.querySelector(".pf-label"),
        badge: n.querySelector(".pf-badge"),
      };
    };
    EDGES.forEach(node);
    // click a flow node -> more-info (history graph). Grid/Solar/Home map to the
    // configured sensors. Battery: a single-battery system has a true net-power
    // entity (ac_power); otherwise fall back to System Charge Power.
    const fcfg = this._panelConfig;
    const acIds = (this._index().byKey.get(K.acPower)) || [];
    const battEid = acIds.length === 1 ? acIds[0] : this._sysEntityId(K.sysChargePower);
    this._linkMoreInfo(this._r.nGrid.node, fcfg.grid_entity);
    this._linkMoreInfo(this._r.nSolar.node, fcfg.solar_entity);
    this._linkMoreInfo(this._r.nHome.node, fcfg.home_entity);
    this._linkMoreInfo(this._r.nBatt.node, battEid);

    // self-consumption chip, bottom-centre of the scene
    const self = document.createElement("div");
    self.className = "scene-self";
    self.innerHTML = `<span class="hub-self">—</span>${this._t("selfConsumptionSuffix")}`;
    sq.appendChild(self);

    wrap.appendChild(sq);
    card.appendChild(wrap);

    this._r.flowSvg = sq; // satisfies the "on Resumen" guard in _patch
    this._r.hubSelf = self.querySelector(".hub-self");
    this._r.sceneImg = img;
    this._r.wires = {}; // no animated wires in scene mode
    this._r.dots = {}; // no particles in scene mode
    this._r.leads = {};
    sq.querySelectorAll(".lead, .lead-end").forEach((el) => {
      (this._r.leads[el.dataset.edge] = this._r.leads[el.dataset.edge] || []).push(el);
    });
    this._r.flows = {}; // animated "snake" polyline per edge (color + direction by state)
    sq.querySelectorAll(".lead-flow").forEach((el) => {
      (this._r.flows[el.dataset.edge] = this._r.flows[el.dataset.edge] || []).push(el);
    });
    return card;
  }

  /** Daytime if the sun is up; falls back to a local-hour heuristic. */
  _isDaytime() {
    const sun = this._hass && this._hass.states && this._hass.states["sun.sun"];
    if (sun) return sun.state !== "below_horizon";
    const h = new Date().getHours();
    return h >= 7 && h < 20;
  }

  /** Scene day/night driven by solar production: night once PV stops (< 50 W).
   *  Hysteresis (50 W off / 80 W on) prevents flicker on passing clouds. Falls
   *  back to sun position / local hour when no solar sensor is configured. */
  _sceneDaytime(m) {
    if (m && m.hasSolar && m.solar != null) {
      const w = m.solar * 1000;
      if (this._sceneIsDay && w < 50) return false;
      if (!this._sceneIsDay && w >= 80) return true;
      return this._sceneIsDay;
    }
    return this._isDaytime();
  }

  /** Rebuild the animated particles for one flow edge (only when its bucket/dir changes). */
  _patchEdge(edge, pathId, color, active, reversed, mag) {
    const n = active ? this._clamp(Math.round(Math.abs(mag) * 1.8) + 1, 1, 5) : 0;
    const dur = this._clamp(2.6 - Math.abs(mag) * 0.28, 0.75, 2.6);
    const sig = `${active ? 1 : 0}|${reversed ? 1 : 0}|${n}|${dur.toFixed(2)}`;
    if (this._edgeSig[edge] === sig) return;
    this._edgeSig[edge] = sig;

    const g = this._r.dots[edge];
    if (!g) return; // scene mode: no particle layer
    g.textContent = "";
    if (!active) return;
    const SVG = "http://www.w3.org/2000/svg";
    const XLINK = "http://www.w3.org/1999/xlink";
    for (let i = 0; i < n; i++) {
      const c = document.createElementNS(SVG, "circle");
      c.setAttribute("r", "1.7");
      c.setAttribute("fill", color);
      c.style.filter = `drop-shadow(0 0 3px ${color})`;
      const m = document.createElementNS(SVG, "animateMotion");
      m.setAttribute("dur", dur + "s");
      m.setAttribute("repeatCount", "indefinite");
      m.setAttribute("begin", -(i * dur) / n + "s");
      m.setAttribute("keyPoints", reversed ? "1;0" : "0;1");
      m.setAttribute("keyTimes", "0;1");
      m.setAttribute("calcMode", "linear");
      const mp = document.createElementNS(SVG, "mpath");
      mp.setAttribute("href", "#" + pathId);
      mp.setAttributeNS(XLINK, "xlink:href", "#" + pathId);
      m.appendChild(mp);
      c.appendChild(m);
      g.appendChild(c);
    }
  }

  // ----- SOC hero: ring (SOC + capacity + system power) left, diagnostics right -----
  _buildSocCard() {
    const { card } = this._card(this._t("cardSoc"), "mdi:battery-charging-high");
    card.classList.add("soc-card");
    const size = 224, stroke = 16, pad = 12; // pad leaves room for the glow so it isn't clipped by the svg box
    const r = (size - stroke) / 2 - pad;
    const circ = 2 * Math.PI * r;
    const ring = document.createElement("div");
    ring.className = "ring";
    ring.style.width = size + "px";
    ring.style.height = size + "px";
    ring.innerHTML = `
      <svg width="${size}" height="${size}" style="transform:rotate(-90deg)">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--bg-2)" stroke-width="${stroke}"/>
        <circle class="ring-fg" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--battery)"
          stroke-width="${stroke}" stroke-linecap="round"
          stroke-dasharray="${circ.toFixed(2)}" stroke-dashoffset="${circ.toFixed(2)}"/>
      </svg>
      <div class="ring-center">
        <div class="num ring-val">—<span>%</span></div>
        <div class="dim ring-sub">— / — kWh</div>
      </div>`;

    // System charge / discharge power + available headroom, under the ring.
    const pw = document.createElement("div");
    pw.className = "soc-power";
    pw.innerHTML = `
      <div class="pw-stats">
        <div class="statblock">
          <div class="stat-label"><ha-icon icon="mdi:plus"></ha-icon>${this._t("charge")}</div>
          <div class="stat-value pw-charge" style="color:var(--battery)">—<span class="stat-unit"></span></div>
        </div>
        <div class="statblock" style="text-align:right">
          <div class="stat-label" style="justify-content:flex-end"><ha-icon icon="mdi:minus"></ha-icon>${this._t("discharge")}</div>
          <div class="stat-value pw-disch" style="color:var(--grid)">—<span class="stat-unit"></span></div>
        </div>
      </div>
      <div class="socbar" style="height:6px;margin-top:9px"><span class="pw-bar"></span></div>
      <div class="dim pw-avail">—</div>`;

    // Left — ring (SOC + capacity) and the power block.
    const left = document.createElement("div");
    left.className = "soc-left";
    left.appendChild(ring);
    left.appendChild(pw);

    // Right — diagnostics, two columns, same height as the ring column.
    const inner = document.createElement("div");
    inner.className = "soc-inner";
    inner.appendChild(left);
    inner.appendChild(this._buildDiagBody());
    card.appendChild(inner);

    // click ring / capacity / power blocks -> more-info (history graph)
    this._linkMoreInfo(ring, this._sysEntityId(K.sysSoc));
    this._linkMoreInfo(ring.querySelector(".ring-sub"), this._sysEntityId(K.sysStored));
    const sb = pw.querySelectorAll(".statblock");
    this._linkMoreInfo(sb[0], this._sysEntityId(K.sysChargePower));
    this._linkMoreInfo(sb[1], this._sysEntityId(K.sysDischargePower));

    this._r.ringFg = ring.querySelector(".ring-fg");
    this._r.ringCirc = circ;
    this._r.ringVal = ring.querySelector(".ring-val");
    this._r.ringSub = ring.querySelector(".ring-sub");
    this._r.pwCharge = pw.querySelector(".pw-charge");
    this._r.pwDisch = pw.querySelector(".pw-disch");
    this._r.pwBar = pw.querySelector(".pw-bar");
    this._r.pwAvail = pw.querySelector(".pw-avail");
    return card;
  }

  // ----- Daily energy card -----
  _buildDailyCard() {
    const { card } = this._card(this._t("cardDaily"), "mdi:calendar-today");
    card.classList.add("daily-card");
    const body = document.createElement("div");
    body.className = "daily-body";
    const bar = (cls, label, color) => `
      <div class="daily-row">
        <div class="daily-head"><span class="muted">${label}</span>
          <span class="num daily-${cls}-v">—<span class="dim" style="font-size:11px"> kWh</span></span></div>
        <div class="socbar"><span class="daily-${cls}-bar" style="background:${color}"></span></div>
      </div>`;
    body.innerHTML =
      bar("ch", this._t("charged"), "var(--battery)") +
      bar("dis", this._t("discharged"), "var(--grid)") +
      bar("sol", this._t("solar"), "var(--solar)") +
      bar("home", this._t("home"), "var(--home)") +
      bar("imp", this._t("gridImport"), "var(--flow-purple)") +
      bar("exp", this._t("gridExport"), "var(--flow-orange)");
    card.appendChild(body);
    const rows = body.querySelectorAll(".daily-row");
    // click an energy row -> more-info (history graph)
    this._linkMoreInfo(rows[0], this._sysEntityId(K.sysDailyCharge));
    this._linkMoreInfo(rows[1], this._sysEntityId(K.sysDailyDischarge));
    this._linkMoreInfo(rows[2], this._sysEntityId(K.sysDailySolar));
    this._linkMoreInfo(rows[3], this._sysEntityId(K.sysDailyHome));
    this._linkMoreInfo(rows[4], this._sysEntityId(K.sysDailyGridImport));
    this._linkMoreInfo(rows[5], this._sysEntityId(K.sysDailyGridExport));
    this._r.dChV = body.querySelector(".daily-ch-v");
    this._r.dChBar = body.querySelector(".daily-ch-bar");
    this._r.dDisV = body.querySelector(".daily-dis-v");
    this._r.dDisBar = body.querySelector(".daily-dis-bar");
    this._r.dSolRow = rows[2];
    this._r.dSolV = body.querySelector(".daily-sol-v");
    this._r.dSolBar = body.querySelector(".daily-sol-bar");
    this._r.dHomeRow = rows[3];
    this._r.dHomeV = body.querySelector(".daily-home-v");
    this._r.dHomeBar = body.querySelector(".daily-home-bar");
    this._r.dImpRow = rows[4];
    this._r.dImpV = body.querySelector(".daily-imp-v");
    this._r.dImpBar = body.querySelector(".daily-imp-bar");
    this._r.dExpRow = rows[5];
    this._r.dExpV = body.querySelector(".daily-exp-v");
    this._r.dExpBar = body.querySelector(".daily-exp-bar");
    return card;
  }

  // ----- Mini SOC history -----
  _buildMiniHistory() {
    const { card, head } = this._card(this._t("cardSocToday"), "mdi:chart-areaspline");
    card.classList.add("chart-card");
    const pct = document.createElement("span");
    pct.className = "num dim mini-pct";
    pct.style.marginLeft = "auto";
    pct.style.fontSize = "13px";
    pct.textContent = "—";
    head.appendChild(pct);

    const sparkWrap = document.createElement("div");
    sparkWrap.className = "mini-spark chart-canvas";
    sparkWrap.innerHTML =
      `<div class="chart-yaxis">${this._yAxisHTML({ yMin: 0, yMax: 100, unit: "%", decimals: 0 })}</div>` +
      `<div class="chart-surface"><svg viewBox="0 0 280 68" width="100%" height="100%" preserveAspectRatio="none">
          <defs><linearGradient id="mv-spark" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="var(--accent)" stop-opacity="0.28"/>
            <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
          </linearGradient></defs>
          <line class="chart-grid" x1="0" y1="0" x2="280" y2="0"/>
          <line class="chart-grid" x1="0" y1="17" x2="280" y2="17"/>
          <line class="chart-grid" x1="0" y1="34" x2="280" y2="34"/>
          <line class="chart-grid" x1="0" y1="51" x2="280" y2="51"/>
          <line class="chart-grid" x1="0" y1="68" x2="280" y2="68"/>
          <path class="spark-area" fill="url(#mv-spark)"></path>
          <path class="spark-line" fill="none" stroke="var(--accent)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></path>
        </svg></div>`;
    const axis = document.createElement("div");
    axis.className = "mini-axis dim";
    axis.innerHTML = `<span>00:00</span><span>${this._t("now")}</span>`;

    card.appendChild(sparkWrap);
    card.appendChild(axis);
    card.appendChild(this._buildZoomBar(sparkWrap, "soc"));
    this._r.miniPct = pct;
    this._r.miniSpark = sparkWrap;
    this._r.miniAxis = axis;
    this._r.sparkArea = sparkWrap.querySelector(".spark-area");
    this._r.sparkLine = sparkWrap.querySelector(".spark-line");
    this._attachHover(sparkWrap);
    this._attachBrush(sparkWrap, "soc");
    this._drawSpark();
    return card;
  }

  _drawSpark() {
    if (!this._r.sparkLine) return;
    const host = this._r.miniSpark;
    const full = this._socSeries;
    if (!full || full.length < 2) {
      this._r.sparkLine.setAttribute("d", "");
      this._r.sparkArea.setAttribute("d", "");
      if (host) host.__hv = null;
      this._updateMiniAxis(null);
      return;
    }
    // SOC samples are evenly spaced from 00:00 → now; map an original index → clock.
    const mid = new Date();
    mid.setHours(0, 0, 0, 0);
    const startS = mid.getTime() / 1000;
    const elapsed = Date.now() / 1000 - startS;
    const fullLast = full.length - 1;
    const clockOf = (origIdx) => startS + (fullLast > 0 ? origIdx / fullLast : 0) * elapsed;

    // apply zoom (fraction of the index domain), if set
    const z = host && host.__zoom;
    let data = full, i0 = 0;
    if (z) {
      i0 = Math.round(z.lo * fullLast);
      const i1 = Math.round(z.hi * fullLast);
      if (i1 - i0 >= 1) data = full.slice(i0, i1 + 1);
      else i0 = 0;
    }

    const w = 280, h = 68, lo = 0, hi = 100, rng = hi - lo;
    const pts = data.map((d, i) => [
      (i / (data.length - 1)) * w,
      h - ((this._clamp(d, lo, hi) - lo) / rng) * h,
    ]);
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    this._r.sparkLine.setAttribute("d", line);
    this._r.sparkArea.setAttribute("d", `${line} L${w} ${h} L0 ${h} Z`);
    if (this._r.miniPct) this._r.miniPct.textContent = Math.round(full[full.length - 1]) + "%";
    if (host) {
      host.__hv = {
        kind: "line",
        n: data.length,
        xs: null,
        series: [{ label: "SOC", color: "var(--accent)", data: data.slice() }],
        yMin: 0,
        yMax: 100,
        unit: "%",
        decimals: 0,
        xLabel: (k) => this._fmtClock(clockOf(i0 + k)),
      };
    }
    this._updateMiniAxis(z ? { t0: clockOf(i0), t1: clockOf(i0 + data.length - 1) } : null);
  }

  // ----- Inline SVG chart helpers (ported from the design handoff) -----
  /** Multi-series line chart as an SVG string. Shapes only (no SVG text, so
   *  preserveAspectRatio="none" can stretch it to the card height without
   *  distorting labels); non-scaling-stroke keeps line widths constant. */
  _lineChartSVG({ series, yMin, yMax, xs }) {
    const W = 320, H = 160;
    const n = Math.max(0, ...series.map((s) => (s.data ? s.data.length : 0)));
    if (n < 2) return "";
    const span = yMax - yMin || 1;
    // xs: optional per-sample x positions in [0,1] (e.g. fraction of the day),
    // so a partial day of data sits at its real clock position instead of being
    // stretched across the full width. Falls back to even index spacing.
    const X = (i) => (xs ? this._clamp(xs[i], 0, 1) : i / (n - 1)) * W;
    const Y = (v) => H - ((this._clamp(v, yMin, yMax) - yMin) / span) * H;
    let g = "";
    for (let k = 0; k <= 4; k++) {
      const y = ((k / 4) * H).toFixed(1);
      g += `<line class="chart-grid" x1="0" y1="${y}" x2="${W}" y2="${y}"/>`;
    }
    if (yMin < 0 && yMax > 0) {
      const yz = Y(0).toFixed(1);
      g += `<line class="chart-zero" x1="0" y1="${yz}" x2="${W}" y2="${yz}"/>`;
    }
    let paths = "";
    for (const s of series) {
      if (!s.data || s.data.length < 2) continue;
      const d = s.data
        .map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1))
        .join(" ");
      paths +=
        `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" ` +
        `vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%" height="100%">${g}${paths}</svg>`;
  }

  _axisDecimals(yMin, yMax) {
    const span = Math.abs(yMax - yMin);
    return span < 1 ? 2 : span < 10 ? 1 : 0;
  }

  _yAxisHTML({ yMin, yMax, unit, decimals = this._axisDecimals(yMin, yMax) }) {
    return Array.from({ length: 5 }, (_, i) => {
      const raw = yMax - ((yMax - yMin) * i) / 4;
      const value = Math.abs(raw) < 10 ** -(decimals + 1) ? 0 : raw;
      return `<span>${this._nf(value, decimals)}<small>${unit}</small></span>`;
    }).join("");
  }

  _chartWithYAxis(svg, { yMin, yMax, unit, decimals }) {
    return (
      `<div class="chart-canvas">` +
      `<div class="chart-yaxis">${this._yAxisHTML({ yMin, yMax, unit, decimals })}</div>` +
      `<div class="chart-surface">${svg}</div>` +
      `</div>`
    );
  }

  // ----- Chart hover readout (crosshair + value tooltip) -----------------
  /** Local clock "HH:MM" for an epoch-seconds value. */
  _fmtClock(s) {
    if (s == null) return "";
    return new Date(s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  /** Attach a hover readout to a STABLE element (the .chart-plot or .mini-spark
   *  wrapper). The per-draw model lives on `host.__hv`; the overlay nodes are
   *  (re)created inside the live .chart-surface so they survive the innerHTML
   *  rebuilds that happen on every data refresh. */
  _attachHover(host) {
    if (host.__hoverBound) return;
    host.__hoverBound = true;
    const hide = () => { if (host.__ov) host.__ov.root.style.display = "none"; };
    host.addEventListener("mouseleave", hide);
    host.addEventListener("mousemove", (ev) => {
      if (host.__dragging) return hide();
      const hv = host.__hv;
      const surface = host.querySelector(".chart-surface");
      if (!hv || !surface) return hide();
      const rect = surface.getBoundingClientRect();
      if (rect.width <= 0) return hide();
      const fx = this._clamp((ev.clientX - rect.left) / rect.width, 0, 1);
      let ov = host.__ov;
      if (!ov || ov.surface !== surface || !surface.contains(ov.root)) {
        ov = this._makeHoverOverlay(surface);
        host.__ov = ov;
      }
      ov.root.style.display = "block";
      (hv.kind === "bar" ? this._hoverBar : this._hoverLine).call(this, hv, fx, rect, ov);
    });
  }

  _makeHoverOverlay(surface) {
    const root = document.createElement("div");
    root.className = "chart-hover";
    root.innerHTML = `<div class="hv-line"></div><div class="hv-dots"></div><div class="hv-tip"></div>`;
    surface.appendChild(root);
    return {
      surface, root,
      line: root.querySelector(".hv-line"),
      dots: root.querySelector(".hv-dots"),
      tip: root.querySelector(".hv-tip"),
    };
  }

  _hoverRow(color, label, valueHTML) {
    return (
      `<div class="hv-r"><span class="hv-k"><i style="background:${color}"></i>${label}</span>` +
      `<span class="hv-v">${valueHTML}</span></div>`
    );
  }

  _placeTip(ov, rect, leftPx, headHTML, rows) {
    ov.line.style.left = leftPx.toFixed(1) + "px";
    ov.tip.innerHTML = `<div class="hv-h">${headHTML}</div>` + rows.join("");
    const tw = ov.tip.offsetWidth || 0;
    let tl = leftPx + 12;
    if (tl + tw > rect.width) tl = leftPx - 12 - tw;
    ov.tip.style.left = this._clamp(tl, 0, Math.max(0, rect.width - tw)).toFixed(1) + "px";
  }

  _hoverLine(hv, fx, rect, ov) {
    const n = hv.n;
    if (!n) return;
    const frac = (k) => (hv.xs ? this._clamp(hv.xs[k], 0, 1) : n > 1 ? k / (n - 1) : 0);
    let bi = 0, bd = Infinity;
    for (let k = 0; k < n; k++) { const d = Math.abs(frac(k) - fx); if (d < bd) { bd = d; bi = k; } }
    const leftPx = frac(bi) * rect.width;
    const span = hv.yMax - hv.yMin || 1;
    let dots = "";
    const rows = [];
    for (const s of hv.series) {
      const v = s.data ? s.data[bi] : null;
      if (v == null || Number.isNaN(v)) continue;
      const top = (1 - (this._clamp(v, hv.yMin, hv.yMax) - hv.yMin) / span) * rect.height;
      dots += `<span class="hv-dot" style="left:${leftPx.toFixed(1)}px;top:${top.toFixed(1)}px;background:${s.color}"></span>`;
      rows.push(this._hoverRow(s.color, s.label, `${this._nf(v, hv.decimals)} ${hv.unit}`));
    }
    ov.dots.innerHTML = dots;
    this._placeTip(ov, rect, leftPx, hv.xLabel(bi), rows);
  }

  _hoverBar(hv, fx, rect, ov) {
    const c = hv.count;
    if (!c) return;
    const li = this._clamp(Math.floor(fx * c), 0, c - 1);
    const leftPx = ((li + 0.5) / c) * rect.width;
    ov.dots.innerHTML = "";
    const rows = hv.groups.map((g) =>
      this._hoverRow(g.color, g.label, `${this._nf(g.values[li] || 0, hv.decimals)} ${hv.unit}`)
    );
    this._placeTip(ov, rect, leftPx, hv.xLabel(li), rows);
  }

  /** Grouped bar chart as an SVG string plus its calculated Y maximum. */
  _barChartSVG({ groups, count }) {
    const W = 320, H = 160;
    const all = groups.flatMap((g) => g.values.map((v) => v || 0));
    const yMax = Math.max(0.1, ...all) * 1.12;
    const Y = (v) => H - (Math.max(0, v) / yMax) * H;
    const slot = W / Math.max(1, count);
    const ng = groups.length;
    // thinner bars: cap per-bar width low and keep the cluster compact so 4
    // series per day still read clearly with gaps between them
    const bw = Math.min(slot * 0.18, (slot * 0.66) / ng);
    let grid = "";
    for (let k = 0; k <= 4; k++) {
      const y = ((k / 4) * H).toFixed(1);
      grid += `<line class="chart-grid" x1="0" y1="${y}" x2="${W}" y2="${y}"/>`;
    }
    let rects = "";
    for (let li = 0; li < count; li++) {
      groups.forEach((grp, gi) => {
        const v = grp.values[li] || 0;
        const x = slot * li + slot / 2 - (ng * bw) / 2 + gi * bw;
        const y = Y(v);
        rects +=
          `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 1.5).toFixed(1)}" ` +
          `height="${(H - y).toFixed(1)}" rx="2" fill="${grp.color}"/>`;
      });
    }
    return {
      svg: `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%" height="100%">${grid}${rects}</svg>`,
      yMax,
    };
  }

  _legendHTML(items) {
    return items
      .map(
        (it) =>
          `<span class="legend-item"><span class="legend-dot" style="background:${it.color}"></span>${it.label}</span>`
      )
      .join("");
  }

  // ----- Potencias (24 h, up to 4 series) -----
  _buildPowerHistoryCard() {
    const { card, head } = this._card(this._t("cardPower"), "mdi:flash");
    card.classList.add("chart-card");
    const legend = document.createElement("span");
    legend.className = "chart-legend";
    legend.style.marginLeft = "auto";
    head.appendChild(legend);
    const plot = document.createElement("div");
    plot.className = "chart-plot";
    const xaxis = document.createElement("div");
    xaxis.className = "chart-xaxis dim";
    xaxis.innerHTML = `<span>00</span><span>06</span><span>12</span><span>18</span><span>24</span>`;
    card.appendChild(plot);
    card.appendChild(xaxis);
    card.appendChild(this._buildZoomBar(plot, "power"));
    this._r.powerLegend = legend;
    this._r.powerPlot = plot;
    this._r.powerXaxis = xaxis;
    this._attachHover(plot);
    this._attachBrush(plot, "power");
    this._drawPowerHistory();
    return card;
  }

  _drawPowerHistory() {
    const plot = this._r.powerPlot;
    if (!plot) return;
    const ps = this._powerSeries;
    const defs = [
      { key: "solar", label: this._t("solar"), color: "var(--solar)" },
      { key: "home", label: this._t("home"), color: "var(--home)" },
      { key: "battery", label: this._t("battery"), color: "var(--battery)" },
      { key: "grid", label: this._t("grid"), color: "var(--grid)" },
    ];
    const avail = ps
      ? defs.filter((d) => Array.isArray(ps[d.key]) && ps[d.key].some((v) => v != null))
      : [];
    if (this._r.powerLegend) this._r.powerLegend.innerHTML = this._legendHTML(avail);
    if (!avail.length) {
      plot.innerHTML = `<div class="chart-empty dim">${this._t("noData")}</div>`;
      plot.__hv = null;
      return;
    }
    const fullSeries = avail.map((d) => ({ color: d.color, data: ps[d.key].map((v) => (v == null ? 0 : v)) }));
    // Anchor each sample to its real time-of-day so a partial day (e.g. 03:00)
    // only fills the left of the fixed 00–24 axis instead of stretching across it.
    const dayStart = new Date();
    dayStart.setHours(0, 0, 0, 0);
    const startS = dayStart.getTime() / 1000;
    const t = Array.isArray(ps.t) ? ps.t : null;
    const fullXs = t && t.length ? t.map((ts) => (ts - startS) / 86400) : null;

    // apply the active zoom window (fraction of the 24 h day), if set
    const z = plot.__zoom;
    let series = fullSeries, xs = fullXs, times = t;
    if (z && fullXs) {
      const idx = [];
      for (let i = 0; i < fullXs.length; i++) if (fullXs[i] >= z.lo && fullXs[i] <= z.hi) idx.push(i);
      if (idx.length >= 2) {
        const sp = z.hi - z.lo || 1;
        xs = idx.map((i) => (fullXs[i] - z.lo) / sp);
        series = fullSeries.map((s) => ({ color: s.color, data: idx.map((i) => s.data[i]) }));
        times = t ? idx.map((i) => t[i]) : null;
      }
    }

    let lo = 0, hi = 0;
    for (const s of series) for (const v of s.data) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const pad = (hi - lo) * 0.08 || 0.2;
    const yMin = lo - pad;
    const yMax = hi + pad;
    plot.innerHTML = this._chartWithYAxis(this._lineChartSVG({ series, yMin, yMax, xs }), {
      yMin,
      yMax,
      unit: "kW",
    });
    plot.__hv = {
      kind: "line",
      n: Math.max(0, ...series.map((s) => s.data.length)),
      xs,
      series: avail.map((d, i) => ({ label: d.label, color: d.color, data: series[i].data })),
      yMin,
      yMax,
      unit: "kW",
      decimals: this._axisDecimals(yMin, yMax),
      xLabel: (i) => (times ? this._fmtClock(times[i]) : ""),
    };
    this._updatePowerXaxis(z, startS);
  }

  // ----- Energía semanal (7 días, barras agrupadas) -----
  _buildWeeklyCard() {
    const { card, head } = this._card(this._t("cardWeekly"), "mdi:calendar-week");
    card.classList.add("chart-card");
    const legend = document.createElement("span");
    legend.className = "chart-legend";
    legend.style.marginLeft = "auto";
    head.appendChild(legend);
    const plot = document.createElement("div");
    plot.className = "chart-plot";
    const xaxis = document.createElement("div");
    xaxis.className = "chart-xaxis dim";
    card.appendChild(plot);
    card.appendChild(xaxis);
    this._r.weeklyPlot = plot;
    this._r.weeklyXaxis = xaxis;
    this._r.weeklyLegend = legend;
    this._attachHover(plot);
    this._drawWeekly();
    return card;
  }

  _drawWeekly() {
    const plot = this._r.weeklyPlot;
    if (!plot) return;
    const wk = this._weekly;
    if (!wk || !wk.days || !wk.days.length) {
      plot.innerHTML = `<div class="chart-empty dim">${this._t("noData")}</div>`;
      plot.__hv = null;
      if (this._r.weeklyXaxis) this._r.weeklyXaxis.innerHTML = "";
      if (this._r.weeklyLegend) this._r.weeklyLegend.innerHTML = "";
      return;
    }
    const groups = [
      { label: this._t("charge"), color: "var(--battery)", values: wk.charge },
      { label: this._t("discharge"), color: "var(--grid)", values: wk.discharge },
    ];
    if (wk.import) groups.push({ label: this._t("imported"), color: "var(--flow-purple)", values: wk.import });
    if (wk.export) groups.push({ label: this._t("exported"), color: "var(--flow-orange)", values: wk.export });
    if (this._r.weeklyLegend) this._r.weeklyLegend.innerHTML = this._legendHTML(groups);
    const { svg, yMax } = this._barChartSVG({ groups, count: wk.days.length });
    plot.innerHTML = this._chartWithYAxis(svg, { yMin: 0, yMax, unit: "kWh" });
    plot.__hv = {
      kind: "bar",
      count: wk.days.length,
      groups,
      unit: "kWh",
      decimals: this._axisDecimals(0, yMax),
      xLabel: (i) => wk.days[i] || "",
    };
    if (this._r.weeklyXaxis) this._r.weeklyXaxis.innerHTML = wk.days.map((d) => `<span>${d}</span>`).join("");
  }

  // ----- Chart zoom (drag-to-brush on desktop + range buttons everywhere) -----
  _zoomHostFor(kind) {
    return kind === "power" ? this._r.powerPlot : this._r.miniSpark;
  }
  _redrawChart(kind) {
    if (kind === "power") this._drawPowerHistory();
    else this._drawSpark();
  }
  /** Natural time domain (epoch s) for a chart: Potencias spans the full day,
   *  SOC spans midnight -> now. */
  _chartDomain(kind) {
    const mid = new Date();
    mid.setHours(0, 0, 0, 0);
    const startS = mid.getTime() / 1000;
    const nowS = Date.now() / 1000;
    return { startS, nowS, endS: kind === "power" ? startS + 86400 : nowS };
  }
  /** Range-preset buttons + reset, placed under the chart. */
  _buildZoomBar(host, kind) {
    const bar = document.createElement("div");
    bar.className = "chart-zoom";
    const opts = [["1h", 1], ["6h", 6], ["12h", 12], [this._t("zoomReset"), null]];
    for (const [label, h] of opts) {
      const b = document.createElement("button");
      b.className = "zoom-btn";
      b.textContent = label;
      b.dataset.h = h == null ? "" : String(h);
      b.addEventListener("click", () => this._setRangeHours(host, kind, h));
      bar.appendChild(b);
    }
    host.__zoomBar = bar;
    host.__activeH = null; // full view
    const resetBtn = bar.querySelector('.zoom-btn[data-h=""]');
    if (resetBtn) resetBtn.classList.add("active");
    return bar;
  }
  /** Set the window to the last `hours` ending at now (null = full/reset). */
  _setRangeHours(host, kind, hours) {
    if (hours == null) {
      host.__zoom = null;
      host.__activeH = null;
    } else {
      const { startS, endS, nowS } = this._chartDomain(kind);
      const span = endS - startS || 1;
      const lo = this._clamp((nowS - hours * 3600 - startS) / span, 0, 1);
      const hi = this._clamp((nowS - startS) / span, 0, 1);
      host.__zoom = hi - lo > 0.005 ? { lo, hi } : null;
      host.__activeH = host.__zoom ? hours : null;
    }
    this._redrawChart(kind);
    this._syncZoomBtns(kind);
  }
  _syncZoomBtns(kind) {
    const host = this._zoomHostFor(kind);
    if (!host || !host.__zoomBar) return;
    const active = host.__activeH;
    host.__zoomBar.querySelectorAll(".zoom-btn").forEach((b) => {
      const h = b.dataset.h === "" ? null : Number(b.dataset.h);
      b.classList.toggle("active", h === active);
    });
  }
  _makeBrushBox(surface) {
    const box = document.createElement("div");
    box.className = "brush-box";
    surface.appendChild(box);
    return box;
  }
  /** Compose a brush selection (fraction of the visible width) with the current
   *  zoom to produce the new absolute window. */
  _applyBrush(host, kind, f0, f1) {
    const z = host.__zoom || { lo: 0, hi: 1 };
    const sp = z.hi - z.lo || 1;
    const lo = z.lo + f0 * sp;
    const hi = z.lo + f1 * sp;
    if (hi - lo < 0.01) return;
    host.__zoom = { lo, hi };
    host.__activeH = "custom"; // no preset highlighted
    this._redrawChart(kind);
    this._syncZoomBtns(kind);
  }
  /** Drag-to-zoom with the mouse (pointer). Touch is left to scroll + the range
   *  buttons, so touch pointers are ignored here. */
  _attachBrush(host, kind) {
    if (host.__brushBound) return;
    host.__brushBound = true;
    let startX = null, box = null, rect = null, pid = null;
    const onDown = (ev) => {
      if (ev.pointerType === "touch") return;
      const surface = host.querySelector(".chart-surface");
      if (!surface) return;
      rect = surface.getBoundingClientRect();
      if (rect.width <= 0) return;
      startX = this._clamp((ev.clientX - rect.left) / rect.width, 0, 1);
      host.__dragging = true;
      box = this._makeBrushBox(surface);
      box.style.left = (startX * 100).toFixed(2) + "%";
      box.style.width = "0%";
      pid = ev.pointerId;
      try { host.setPointerCapture(pid); } catch (e) { /* ignore */ }
    };
    const onMove = (ev) => {
      if (startX == null || !box || !rect) return;
      const cx = this._clamp((ev.clientX - rect.left) / rect.width, 0, 1);
      const l = Math.min(startX, cx), r = Math.max(startX, cx);
      box.style.left = (l * 100).toFixed(2) + "%";
      box.style.width = ((r - l) * 100).toFixed(2) + "%";
    };
    const onUp = (ev) => {
      if (startX == null) return;
      const cx = rect ? this._clamp((ev.clientX - rect.left) / rect.width, 0, 1) : startX;
      const f0 = Math.min(startX, cx), f1 = Math.max(startX, cx);
      if (box && box.parentNode) box.parentNode.removeChild(box);
      try { if (pid != null) host.releasePointerCapture(pid); } catch (e) { /* ignore */ }
      box = null; startX = null; pid = null;
      host.__dragging = false;
      if (f1 - f0 > 0.02) this._applyBrush(host, kind, f0, f1);
    };
    host.addEventListener("pointerdown", onDown);
    host.addEventListener("pointermove", onMove);
    host.addEventListener("pointerup", onUp);
    window.addEventListener("pointerup", onUp);
  }
  _updatePowerXaxis(z, startS) {
    const ax = this._r.powerXaxis;
    if (!ax) return;
    if (!z) {
      ax.innerHTML = `<span>00</span><span>06</span><span>12</span><span>18</span><span>24</span>`;
      return;
    }
    const t0 = startS + z.lo * 86400, t1 = startS + z.hi * 86400;
    ax.innerHTML = Array.from({ length: 5 }, (_, i) =>
      `<span>${this._fmtClock(t0 + ((t1 - t0) * i) / 4)}</span>`
    ).join("");
  }
  _updateMiniAxis(win) {
    const ax = this._r.miniAxis;
    if (!ax) return;
    ax.innerHTML = win
      ? `<span>${this._fmtClock(win.t0)}</span><span>${this._fmtClock(win.t1)}</span>`
      : `<span>00:00</span><span>${this._t("now")}</span>`;
  }

  // ----- Diagnostics body (section 2 of the SOC card, two columns) -----
  _buildDiagBody() {
    const wrap = document.createElement("div");
    wrap.className = "soc-diag";
    const title = document.createElement("div");
    title.className = "soc-diag-title";
    title.innerHTML = `<ha-icon icon="mdi:shield-check-outline"></ha-icon><span>${this._t("diagTitle")}</span>`;
    wrap.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "diag-grid";
    this._r.diag = {};
    DIAG_ROWS.forEach((row) => {
      const cell = document.createElement("div");
      cell.className = "diag-cell";
      cell.innerHTML =
        `<span class="muted diag-cell-label">${this._t(row.lk)}</span>` +
        `<span class="chip diag-${row.key}">—</span>`;
      grid.appendChild(cell);
      this._r.diag[row.key] = cell.querySelector(".chip");
      // click a diagnostic -> more-info (history graph)
      this._linkMoreInfo(cell, this._sysEntityId(row.key));
    });
    wrap.appendChild(grid);
    return wrap;
  }

  /** Localized chip text + tone for one diagnostic entity. */
  _diagDisplay(key, so, m) {
    if (key === K.nonResponsive) {
      const off = m.offline || 0;
      return off > 0
        ? { text: this._t("nResponsive", { n: off }), tone: "warn" }
        : { text: this._t("none"), tone: "good" };
    }
    if (!so || so.state == null || so.state === "unknown" || so.state === "unavailable") {
      return { text: "—", tone: "neutral" };
    }
    const raw = String(so.state).toLowerCase();
    const disp =
      typeof this._hass.formatEntityState === "function"
        ? this._hass.formatEntityState(so)
        : so.state;
    switch (key) {
      case K.netBalance: {
        const n = this._num(so);
        if (n == null) return { text: "—", tone: "neutral" };
        return { text: `${n >= 0 ? "+" : ""}${this._nf(n, 2)} kWh`, tone: n >= 0 ? "good" : "warn" };
      }
      case K.sysAlarm:
        return {
          text: disp,
          tone: raw === "ok" ? "good" : raw === "warning" ? "warn" : raw === "fault" ? "bad" : "neutral",
        };
      case K.predictiveActive:
      case K.capacityActive:
        return { text: disp, tone: raw === "on" ? "good" : "neutral" };
      case K.dischargeWindow:
        return { text: disp, tone: raw === "active" ? "good" : "neutral" };
      case K.weeklyFullCharge:
        return { text: disp, tone: raw === "charging" || raw === "complete" ? "good" : "neutral" };
      case K.chargeDelay:
        if (raw === "charging_allowed" || raw === "charging_to_setpoint") return { text: disp, tone: "good" };
        if (raw === "delayed" || raw === "waiting_for_solar") return { text: disp, tone: "warn" };
        return { text: disp, tone: "neutral" };
      case K.activeBatteries:
        if (raw.startsWith("discharging")) return { text: this._t("discharging"), tone: "good" };
        if (raw.startsWith("charging")) return { text: this._t("charging"), tone: "good" };
        if (raw === "idle") return { text: this._t("idle"), tone: "neutral" };
        return { text: disp, tone: "neutral" };
      case K.integration: {
        let tone = "good";
        if (raw.includes("blocked") || raw.includes("pause") || raw.includes("backup")) tone = "warn";
        else if (raw === "initializing") tone = "neutral";
        return { text: disp, tone };
      }
      default:
        return { text: disp, tone: "neutral" };
    }
  }

  // --- patch (data -> DOM) ---------------------------------------------------
  _setChip(el, text, tone) {
    if (!el) return;
    el.className = "chip chip-" + (tone || "neutral");
    el.textContent = text;
  }

  _patch(m) {
    const r = this._r;
    if (!r.flowSvg) return; // not on Resumen
    const p = (kw) => {
      const f = this._fmtPower(Math.abs(kw * 1000));
      return f.v + (f.u ? " " + f.u : "");
    };
    const off = (kw) => Math.abs(kw) > 0.03;

    // ----- flow nodes -----
    const { solar, home, grid, battery } = m;
    // solar
    const solActive = m.hasSolar && solar > 0.05;
    r.nSolar.node.style.display = m.hasSolar ? "" : "none";
    r.nSolar.node.classList.toggle("active", solActive);
    r.nSolar.val.textContent = m.hasSolar ? (solar > 0.03 ? p(solar) : "—") : "—";
    r.nSolar.unit.textContent = "";
    // grid
    const gridKnown = grid != null;
    const gridLabel = !gridKnown ? this._t("grid") : Math.abs(grid) < 0.03 ? this._t("grid") : grid > 0 ? this._t("importing") : this._t("exporting");
    r.nGrid.label.textContent = gridLabel;
    r.nGrid.node.classList.toggle("active", gridKnown && off(grid));
    r.nGrid.val.textContent = gridKnown ? p(grid) : "—";
    // home
    r.nHome.node.classList.toggle("active", home > 0.05);
    r.nHome.val.textContent = home != null ? p(home) : "—";
    // battery
    const battLabel = Math.abs(battery) < 0.03 ? this._t("idle") : battery > 0 ? this._t("charging") : this._t("discharging");
    r.nBatt.label.textContent = battLabel;
    r.nBatt.node.classList.toggle("active", off(battery));
    r.nBatt.val.textContent = p(battery);
    r.nBatt.badge.textContent =
      (m.soc != null ? Math.round(m.soc) : "—") + "% · " + m.active + " " + this._t("units");

    // wires (animated node-graph) — skipped in scene mode
    if (r.wires.solar) {
      r.wires.solar.classList.toggle("on", solActive);
      r.wires.grid.classList.toggle("on", gridKnown && off(grid));
      r.wires.home.classList.toggle("on", home > 0.03);
      r.wires.batt.classList.toggle("on", off(battery));
    }

    // leader lines + element end-dots (scene mode)
    if (r.leads) {
      const lead = (edge, on) =>
        (r.leads[edge] || []).forEach((el) => el.classList.toggle("on", on));
      lead("solar", solActive);
      lead("grid", gridKnown && off(grid));
      lead("home", home > 0.05);
      lead("batt", off(battery));
      (r.leads.solar || []).forEach((el) => (el.style.display = m.hasSolar ? "" : "none"));
    }

    // animated "snake" flow lines: color + travel direction follow the live state
    //   grid   → morado (import) / naranja (export, e.g. solar surplus)
    //   solar  → naranja
    //   batería→ verde (carga) / azul (descarga)
    // `rev` reverses the snake so it travels "into" the consuming node.
    if (r.flows) {
      const flow = (edge, on, color, rev) =>
        (r.flows[edge] || []).forEach((el) => {
          el.classList.toggle("on", on);
          el.classList.toggle("rev", !!rev);
          if (color) el.style.color = color; // stroke + glow inherit currentColor
        });
      flow("solar", solActive, "var(--solar)", false);
      flow(
        "grid",
        gridKnown && off(grid),
        grid > 0 ? "var(--flow-purple)" : "var(--flow-orange)",
        gridKnown && grid < 0
      );
      flow("home", home > 0.05, "var(--home)", true);
      flow(
        "batt",
        off(battery),
        battery > 0 ? "var(--flow-green)" : "var(--flow-blue)",
        battery > 0
      );
      (r.flows.solar || []).forEach((el) => (el.style.display = m.hasSolar ? "" : "none"));
    }

    // day / night backdrop swap
    if (r.sceneImg) {
      const day = this._sceneDaytime(m);
      if (day !== this._sceneIsDay) {
        this._sceneIsDay = day;
        delete r.sceneImg.dataset.fb;
        r.sceneImg.src = day ? this._sceneDay : this._sceneNight;
      }
    }

    // particles
    this._patchEdge("solar", "mv-e-solar", "var(--solar)", solActive, false, solar);
    this._patchEdge("grid", "mv-e-grid", "var(--grid)", gridKnown && Math.abs(grid) > 0.05, gridKnown && grid < 0, grid || 0);
    this._patchEdge("home", "mv-e-home", "var(--home)", home > 0.05, true, home);
    this._patchEdge("batt", "mv-e-batt", "var(--battery)", Math.abs(battery) > 0.05, battery > 0, battery);

    // hub self-consumption
    const self = home > 0.03 ? this._clamp(100 * (1 - Math.max(0, grid || 0) / home), 0, 100) : 100;
    r.hubSelf.textContent = Math.round(self);

    // ----- SOC hero (ring colored by charge level) -----
    const socColor =
      m.soc == null ? "var(--battery)"
      : m.soc < 20 ? "oklch(0.7 0.18 25)"   // low — red
      : m.soc < 50 ? "oklch(0.82 0.14 75)"  // mid — amber
      : "var(--battery)";                    // healthy — accent
    if (m.soc != null) {
      r.ringFg.setAttribute(
        "stroke-dashoffset",
        (r.ringCirc * (1 - this._clamp(m.soc, 0, 100) / 100)).toFixed(2)
      );
      r.ringVal.innerHTML = Math.round(m.soc) + "<span>%</span>";
    }
    r.ringFg.setAttribute("stroke", socColor);
    r.ringFg.style.filter = `drop-shadow(0 0 8px ${socColor})`;
    r.ringSub.textContent = `${this._nf(m.stored, 2)} / ${this._nf(m.capacity, 2)} kWh`;

    // keep the SOC sparkline alive even if recorder history is empty: append the
    // live SOC (throttled to ~60 s, capped) so the line always renders
    if (m.soc != null) {
      const nowS = Date.now() / 1000;
      const v = this._clamp(m.soc, 0, 100);
      if (this._socSeries.length === 0) {
        this._socSeries.push(v, v);
        this._socLastPush = nowS;
        this._drawSpark();
      } else if (nowS - this._socLastPush > 60) {
        this._socSeries.push(v);
        if (this._socSeries.length > 240) this._socSeries.shift();
        this._socLastPush = nowS;
        this._drawSpark();
      }
    }

    // ----- system power (charge / discharge) + available headroom -----
    const ch = Math.max(0, battery) * 1000;
    const dis = Math.max(0, -battery) * 1000;
    const fc = this._fmtPower(ch), fd = this._fmtPower(dis);
    r.pwCharge.innerHTML = `${fc.v}<span class="stat-unit"> ${fc.u}</span>`;
    r.pwDisch.innerHTML = `${fd.v}<span class="stat-unit"> ${fd.u}</span>`;
    let tcap = battery >= 0 ? m.maxCharge : m.maxDischarge;
    if (!tcap) tcap = 2500 * Math.max(1, m.active);
    r.pwBar.style.width = this._clamp((Math.abs(battery) * 1000 / tcap) * 100, 0, 100) + "%";
    r.pwBar.style.background = battery >= 0 ? "var(--battery)" : "var(--grid)";
    const ftc = this._fmtPower(tcap);
    r.pwAvail.textContent = this._t("availOf", { value: `${ftc.v} ${ftc.u}` });

    // ----- daily energy -----
    const sol = m.dailySolar;
    const hm = m.dailyHome;
    const imp = m.dailyGridImport;
    const exp = m.dailyGridExport;
    const u = `<span class="dim" style="font-size:11px"> kWh</span>`;
    const max = Math.max(m.dailyCharge || 0, m.dailyDischarge || 0, sol || 0, hm || 0, imp || 0, exp || 0, 0.1);
    r.dChV.innerHTML = `${this._nf(m.dailyCharge, 2)}${u}`;
    r.dChBar.style.width = ((m.dailyCharge || 0) / max) * 100 + "%";
    r.dDisV.innerHTML = `${this._nf(m.dailyDischarge, 2)}${u}`;
    r.dDisBar.style.width = ((m.dailyDischarge || 0) / max) * 100 + "%";
    // solar / home rows hide entirely when no source sensor is configured
    if (r.dSolRow) r.dSolRow.style.display = sol == null ? "none" : "";
    if (sol != null) {
      r.dSolV.innerHTML = `${this._nf(sol, 2)}${u}`;
      r.dSolBar.style.width = (sol / max) * 100 + "%";
    }
    if (r.dHomeRow) r.dHomeRow.style.display = hm == null ? "none" : "";
    if (hm != null) {
      r.dHomeV.innerHTML = `${this._nf(hm, 2)}${u}`;
      r.dHomeBar.style.width = (hm / max) * 100 + "%";
    }
    // grid import / export — hidden until the integrated history is available
    if (r.dImpRow) r.dImpRow.style.display = imp == null ? "none" : "";
    if (imp != null) {
      r.dImpV.innerHTML = `${this._nf(imp, 2)}${u}`;
      r.dImpBar.style.width = (imp / max) * 100 + "%";
    }
    if (r.dExpRow) r.dExpRow.style.display = exp == null ? "none" : "";
    if (exp != null) {
      r.dExpV.innerHTML = `${this._nf(exp, 2)}${u}`;
      r.dExpBar.style.width = (exp / max) * 100 + "%";
    }

    // ----- diagnostics (section 2, two columns) -----
    const ds = m.diagStates || {};
    for (const row of DIAG_ROWS) {
      const el = r.diag[row.key];
      if (!el) continue;
      const { text, tone } = this._diagDisplay(row.key, ds[row.key], m);
      this._setChip(el, text, tone);
      el.title = `${this._t(row.lk)}: ${text}`; // full value on hover (chips ellipsize)
    }
  }

  // --- history (SOC sparkline + Potencias + Energía semanal) -----------------
  _startHistory() {
    this._refreshHistory();
    if (this._histTimer) clearInterval(this._histTimer);
    this._histTimer = setInterval(() => this._refreshHistory(), 5 * 60 * 1000);
  }

  _refreshHistory() {
    this._fetchHistory();
    this._fetchPowerHistory();
    this._fetchWeeklyEnergy();
  }

  async _fetchHistory() {
    if (!this._hass || !this._hass.callWS) return;
    // resolve a SOC entity: prefer system, else first battery SOC
    const { byKey } = this._index();
    const sysSoc = (byKey.get(K.sysSoc) || [])[0];
    const battSoc = (byKey.get(K.batterySoc) || [])[0];
    const socId = sysSoc || battSoc;
    if (!socId) return;
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: new Date().toISOString(),
        entity_ids: [socId],
        minimal_response: true,
        no_attributes: true,
      });
      const arr = res && res[socId];
      if (!Array.isArray(arr) || !arr.length) return;
      const series = [];
      for (const it of arr) {
        const n = Number(it.s != null ? it.s : it.state);
        if (!Number.isNaN(n)) series.push(n);
      }
      if (!series.length) return;
      // downsample to ~60 points
      const step = Math.max(1, Math.ceil(series.length / 60));
      this._socSeries = series.filter((_, i) => i % step === 0 || i === series.length - 1);
      this._socLastPush = Date.now() / 1000;
      this._drawSpark();
    } catch (e) {
      console.debug("[mvem] SOC history fetch failed", e);
    }
  }

  /** Build a step-hold sampler grid from local midnight to now (N+1 points). */
  _historyGrid(n = 144) {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const startS = start.getTime() / 1000;
    const nowS = Date.now() / 1000;
    const grid = [];
    for (let i = 0; i <= n; i++) grid.push(startS + (nowS - startS) * (i / n));
    return { grid, startISO: start.toISOString() };
  }

  /** Resample one entity's recorder history onto `grid` (step-hold), in kW. */
  _sampleToGrid(res, id, grid) {
    const arr = res && res[id];
    if (!Array.isArray(arr) || !arr.length) return null;
    const so = this._hass.states[id];
    const unit = ((so && so.attributes.unit_of_measurement) || "").toLowerCase();
    const toKw = unit === "kw" ? 1 : 0.001;
    const pts = [];
    for (const it of arr) {
      const v = Number(it.s != null ? it.s : it.state);
      const t =
        it.lu != null ? it.lu
        : it.last_updated ? Date.parse(it.last_updated) / 1000
        : it.last_changed ? Date.parse(it.last_changed) / 1000
        : null;
      if (t == null || Number.isNaN(v)) continue;
      pts.push([t, v * toKw]);
    }
    if (!pts.length) return null;
    pts.sort((a, b) => a[0] - b[0]);
    const out = [];
    let j = 0, cur = null;
    for (const gt of grid) {
      while (j < pts.length && pts[j][0] <= gt) { cur = pts[j][1]; j++; }
      out.push(cur);
    }
    return out;
  }

  /** 24 h power history for the Potencias chart (Solar/Casa/Batería/Red, kW). */
  async _fetchPowerHistory() {
    if (!this._hass || !this._hass.callWS) return;
    const cfg = this._panelConfig;
    const { byKey } = this._index();
    const sysCh = (byKey.get(K.sysChargePower) || [])[0];
    const sysDis = (byKey.get(K.sysDischargePower) || [])[0];
    const acIds = byKey.get(K.acPower) || [];
    const ids = new Set();
    if (cfg.solar_entity) ids.add(cfg.solar_entity);
    if (cfg.home_entity) ids.add(cfg.home_entity);
    if (cfg.grid_entity) ids.add(cfg.grid_entity);
    // Query the system charge/discharge aggregates AND the per-battery AC power.
    // The system sensors are preferred, but they can be `unavailable` (e.g. a
    // single-battery setup where the aggregate stays down); in that case we fall
    // back to per-battery ac_power so the Batería line still renders.
    if (sysCh) ids.add(sysCh);
    if (sysDis) ids.add(sysDis);
    acIds.forEach((x) => x && ids.add(x));
    if (!ids.size) { this._powerSeries = null; this._drawPowerHistory(); return; }
    const { grid, startISO } = this._historyGrid();
    let res;
    try {
      res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: startISO,
        end_time: new Date().toISOString(),
        entity_ids: [...ids],
        minimal_response: true,
        no_attributes: true,
      });
    } catch (e) {
      console.debug("[mvem] power history fetch failed", e);
      return;
    }
    if (!res) return;
    const solar = cfg.solar_entity ? this._sampleToGrid(res, cfg.solar_entity, grid) : null;
    const home = cfg.home_entity ? this._sampleToGrid(res, cfg.home_entity, grid) : null;
    const gridS = cfg.grid_entity ? this._sampleToGrid(res, cfg.grid_entity, grid) : null;
    let battery = null;
    if (sysCh || sysDis) {
      const ch = sysCh ? this._sampleToGrid(res, sysCh, grid) : null;
      const di = sysDis ? this._sampleToGrid(res, sysDis, grid) : null;
      if (ch || di) battery = grid.map((_, i) => ((ch && ch[i]) || 0) - ((di && di[i]) || 0));
    }
    // Fall back to per-battery ac_power when the system aggregate has no history
    // (sign in ac_power is - charge / + discharge, so negate to + charge / - discharge).
    if (battery == null && acIds.length) {
      const samples = acIds.map((id) => this._sampleToGrid(res, id, grid)).filter(Boolean);
      if (samples.length) battery = grid.map((_, i) => -samples.reduce((a, s) => a + (s[i] || 0), 0));
    }
    this._powerSeries = { t: grid, solar, home, grid: gridS, battery };
    this._drawPowerHistory();
  }

  /** Last 7 days of daily charge/discharge for the Energía semanal bars (kWh).
   *  Daily sensors are total_increasing that reset at local midnight, so the
   *  per-day max equals that day's total; sum across batteries when no system
   *  aggregate exists. */
  async _fetchWeeklyEnergy() {
    if (!this._hass || !this._hass.callWS) return;
    const { byKey } = this._index();
    const chSys = (byKey.get(K.sysDailyCharge) || [])[0];
    const diSys = (byKey.get(K.sysDailyDischarge) || [])[0];
    const chIds = chSys ? [chSys] : (byKey.get(K.dailyCharge) || []);
    const diIds = diSys ? [diSys] : (byKey.get(K.dailyDischarge) || []);
    if (!chIds.length && !diIds.length) { this._weekly = null; this._drawWeekly(); return; }
    const impSys = (byKey.get(K.sysDailyGridImport) || [])[0];
    const expSys = (byKey.get(K.sysDailyGridExport) || [])[0];
    const impIds = impSys ? [impSys] : [];
    const expIds = expSys ? [expSys] : [];
    const days = 7;
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() - (days - 1));
    const allIds = [...new Set([...chIds, ...diIds, ...impIds, ...expIds])];
    let res;
    try {
      res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: new Date().toISOString(),
        entity_ids: allIds,
        minimal_response: true,
        no_attributes: true,
      });
    } catch (e) {
      console.debug("[mvem] weekly fetch failed", e);
      return;
    }
    if (!res) return;
    const startMs = start.getTime();
    const dayIndex = (ms) => Math.floor((ms - startMs) / 86400000);
    // per-id daily max, then sum across ids → daily total per day
    const dailyTotals = (entIds) => {
      const total = new Array(days).fill(null);
      for (const id of entIds) {
        const arr = res[id];
        if (!Array.isArray(arr)) continue;
        const perDay = new Array(days).fill(null);
        for (const it of arr) {
          const v = Number(it.s != null ? it.s : it.state);
          const t =
            it.lu != null ? it.lu * 1000
            : it.last_updated ? Date.parse(it.last_updated)
            : it.last_changed ? Date.parse(it.last_changed)
            : null;
          if (t == null || Number.isNaN(v)) continue;
          const k = dayIndex(t);
          if (k < 0 || k >= days) continue;
          if (perDay[k] == null || v > perDay[k]) perDay[k] = v;
        }
        for (let k = 0; k < days; k++) if (perDay[k] != null) total[k] = (total[k] || 0) + perDay[k];
      }
      return total;
    };
    const charge = dailyTotals(chIds);
    const discharge = dailyTotals(diIds);
    // grid import/export: per-day total = daily-reset sensor's max for that day
    const impTot = impIds.length ? dailyTotals(impIds) : null;
    const expTot = expIds.length ? dailyTotals(expIds) : null;
    const labels = [];
    for (let k = 0; k < days; k++) {
      const dd = new Date(startMs + k * 86400000);
      labels.push(dd.toLocaleDateString(this._lang(), { weekday: "short" }));
    }
    this._weekly = {
      days: labels,
      charge: charge.map((v) => v || 0),
      discharge: discharge.map((v) => v || 0),
      import: impTot ? impTot.map((v) => v || 0) : null,
      export: expTot ? expTot.map((v) => v || 0) : null,
    };
    this._drawWeekly();
  }

  // ===== Baterías view =======================================================
  /** SOC-tiered ring color: <20 red, <50 amber, else accent. */
  _socColor(soc) {
    if (soc == null) return "var(--battery)";
    if (soc < 20) return "oklch(0.7 0.18 25)";
    if (soc < 50) return "oklch(0.82 0.14 75)";
    return "var(--battery)";
  }
  /** Trimmed string state, or null when empty/unknown/unavailable. */
  _sval(so) {
    if (!so || so.state == null) return null;
    const s = String(so.state).trim();
    if (!s || s === "unknown" || s === "unavailable") return null;
    return s;
  }
  /** "123 W" / "1.20 kW" as a single string. */
  _fmtPowerStr(w) {
    const f = this._fmtPower(w);
    return f.v + (f.u ? " " + f.u : "");
  }

  /** One model object per battery device (has a battery_soc entity). */
  _batteryModel() {
    const { byDevice } = this._index();
    const hass = this._hass;
    const list = [];
    for (const [dev, ids] of byDevice) {
      const byTk = {};
      const idByTk = {}; // translation_key -> entity_id (for control service calls)
      for (const id of ids) {
        const e = hass.entities[id];
        if (e && e.translation_key) {
          byTk[e.translation_key] = hass.states[id];
          idByTk[e.translation_key] = id;
        }
      }
      const socObj = byTk[K.batterySoc];
      if (!socObj) continue; // not a battery device
      const acW = this._watts(byTk[K.acPower]);
      const cmax = this._num(byTk[K.cellMax]);
      const cmin = this._num(byTk[K.cellMin]);
      const mppt = MPPT_KEYS.map((k) => this._num(byTk[k]));
      const devReg = (hass.devices && hass.devices[dev]) || null;
      const name =
        (devReg && (devReg.name_by_user || devReg.name)) ||
        this._sval(byTk[K.deviceName]) ||
        null;
      list.push({
        dev,
        name,
        soc: this._num(socObj),
        // ac_power HA sign is - charge / + discharge; negate to + charge / - discharge
        powerW: acW == null ? null : -acW,
        offgridW: this._watts(byTk[K.acOffgridPower]),
        backupOn: (byTk[K.backupFunction] || {}).state === "on",
        hysteresisActive: (() => {
          const s = byTk[K.chargeHysteresisActive];
          return s ? (s.state === "on" ? true : s.state === "off" ? false : null) : null;
        })(),
        stored: this._num(byTk[K.storedEnergy]),
        capacity: this._num(byTk[K.batteryTotalEnergy]),
        inverter: byTk[K.inverterState] || null,
        temp: this._num(byTk[K.internalTemp]),
        voltage: this._num(byTk[K.batteryVoltage]),
        cellMax: cmax,
        cellMin: cmin,
        // measured delta (mV) from the cell_delta balance sensor — NOT the live
        // max-min, which swings with load. null until the first balance reading.
        cellDelta: this._num(byTk[K.cellDelta]),
        cycles: this._num(byTk[K.cycles]),
        cyclesCalc: this._num(byTk[K.cyclesCalc]),
        rte: this._num(byTk[K.rte]),
        dailyCharge: this._num(byTk[K.dailyCharge]),
        dailyDischarge: this._num(byTk[K.dailyDischarge]),
        maxCharge: this._num(byTk[K.maxChargePower]),
        maxDischarge: this._num(byTk[K.maxDischargePower]),
        mppt,
        hasMppt: mppt.some((v) => v != null),
        entIds: idByTk,
        info: {
          bms: this._sval(byTk[K.bmsVersion]),
          vms: this._sval(byTk[K.vmsVersion]),
          ems: this._sval(byTk[K.emsVersion]),
          comm: this._sval(byTk[K.commFw]),
          wifiSignal: this._num(byTk[K.wifiSignal]),
          wifiStatus: byTk[K.wifiStatus] || null,
          mac: this._sval(byTk[K.mac]),
        },
      });
    }
    list.sort((a, b) =>
      String(a.name || a.dev).localeCompare(String(b.name || b.dev), this._lang())
    );
    return list;
  }

  _renderBaterias() {
    this._batCards = {};
    const list = this._batteryModel();
    this._batSig = list.map((b) => b.dev).sort().join("|");
    const wrap = document.createElement("div");
    wrap.className = "bat-grid";
    if (!list.length) {
      const e = document.createElement("div");
      e.className = "placeholder";
      e.innerHTML =
        `<ha-icon icon="mdi:battery-off-outline"></ha-icon><h3>${this._t("noBatteriesTitle")}</h3>` +
        `<p>${this._t("noBatteriesMsg")}</p>`;
      wrap.appendChild(e);
      return wrap;
    }
    for (const b of list) wrap.appendChild(this._buildBatteryCard(b));
    return wrap;
  }

  /** Small SOC ring (DOM built once, animated via stroke-dashoffset on patch). */
  _buildBatRing() {
    const size = 116, stroke = 11, pad = 6;
    const r = (size - stroke) / 2 - pad;
    const circ = 2 * Math.PI * r;
    const ring = document.createElement("div");
    ring.className = "ring bat-ring";
    ring.style.width = size + "px";
    ring.style.height = size + "px";
    ring.innerHTML = `
      <svg width="${size}" height="${size}" style="transform:rotate(-90deg)">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--bg-2)" stroke-width="${stroke}"/>
        <circle class="ring-fg" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--battery)"
          stroke-width="${stroke}" stroke-linecap="round"
          stroke-dasharray="${circ.toFixed(2)}" stroke-dashoffset="${circ.toFixed(2)}"/>
      </svg>
      <div class="ring-center"><div class="num ring-val">—<span>%</span></div></div>`;
    return { ring, fg: ring.querySelector(".ring-fg"), circ, val: ring.querySelector(".ring-val") };
  }

  _buildBatteryCard(b) {
    const card = document.createElement("div");
    card.className = "card bat-card";

    const head = document.createElement("div");
    head.className = "bat-head";
    head.innerHTML =
      `<div class="bat-title"><span class="ic"><ha-icon icon="mdi:battery-high"></ha-icon></span>` +
      `<span class="bat-name"></span></div><span class="chip bat-state">—</span>`;
    card.appendChild(head);

    // ----- top: SOC ring + power readout -----
    const top = document.createElement("div");
    top.className = "bat-top";
    const ring = this._buildBatRing();
    const pw = document.createElement("div");
    pw.className = "bat-power";
    pw.innerHTML =
      `<div class="bat-pwr"><span class="num bat-pwr-val">—</span><span class="bat-pwr-unit dim"></span></div>` +
      `<div class="muted bat-pwr-lbl">—</div>` +
      `<div class="socbar bat-pwr-track" style="height:6px;margin-top:8px"><span class="bat-pwr-bar"></span></div>` +
      `<div class="dim bat-cap">— / — kWh</div>` +
      // off-grid power, pinned to the right edge at the AC-power line; shown only
      // when the backup function switch is on (see _patchBatteryCard).
      `<div class="bat-offgrid" style="display:none">` +
        `<div class="bat-pwr"><span class="num bat-og-val">—</span><span class="bat-og-unit dim"></span></div>` +
        `<div class="muted bat-og-lbl">${this._t("offgrid")}</div>` +
      `</div>`;
    top.appendChild(ring.ring);
    top.appendChild(pw);
    // click SOC ring / power / capacity -> more-info (history graph)
    this._linkMoreInfo(ring.ring, b.entIds[K.batterySoc]);
    this._linkMoreInfo(pw.querySelector(".bat-pwr"), b.entIds[K.acPower]);
    this._linkMoreInfo(pw.querySelector(".bat-cap"), b.entIds[K.storedEnergy]);
    card.appendChild(top);

    // ----- salud y celdas -----
    const health = document.createElement("div");
    health.className = "bat-sect";
    health.innerHTML = `<div class="bat-sect-t">${this._t("healthCells")}</div>`;
    const hgrid = document.createElement("div");
    hgrid.className = "bat-metrics";
    const M = {};
    const addMetric = (id, label, tk) => {
      const c = document.createElement("div");
      c.className = "metric";
      c.innerHTML = `<span class="m-k muted">${label}</span><span class="m-v num">—</span>`;
      // click the metric -> open HA's more-info dialog (shows the history graph)
      if (tk) this._linkMoreInfo(c, b.entIds[tk]);
      hgrid.appendChild(c);
      M[id] = c.querySelector(".m-v");
    };
    addMetric("temp", this._t("mTemp"), K.internalTemp);
    addMetric("volt", this._t("mVoltage"), K.batteryVoltage);
    addMetric("cmax", this._t("mCellMax"), K.cellMax);
    addMetric("cmin", this._t("mCellMin"), K.cellMin);
    addMetric("cdelta", this._t("mCellDelta"), K.cellDelta);
    addMetric("cycles", this._t("mCycles"), b.entIds[K.cycles] ? K.cycles : K.cyclesCalc);
    addMetric("rte", this._t("mEfficiency"), K.rte);
    addMetric("hyst", this._t("mHysteresis"), K.chargeHysteresisActive); // col2 row4: right of Efficiency, below Cycles
    health.appendChild(hgrid);
    card.appendChild(health);

    // ----- energía hoy -----
    const en = document.createElement("div");
    en.className = "bat-sect";
    en.innerHTML = `<div class="bat-sect-t">${this._t("cardDaily")}</div>`;
    const ebody = document.createElement("div");
    ebody.className = "daily-body";
    const ebar = (cls, label, color) => `
      <div class="daily-row">
        <div class="daily-head"><span class="muted">${label}</span>
          <span class="num bat-${cls}-v">—<span class="dim" style="font-size:11px"> kWh</span></span></div>
        <div class="socbar"><span class="bat-${cls}-bar" style="background:${color}"></span></div>
      </div>`;
    ebody.innerHTML =
      ebar("ch", this._t("charged"), "var(--battery)") + ebar("dis", this._t("discharged"), "var(--grid)");
    const dRows = ebody.querySelectorAll(".daily-row");
    this._linkMoreInfo(dRows[0], b.entIds[K.dailyCharge]);
    this._linkMoreInfo(dRows[1], b.entIds[K.dailyDischarge]);
    en.appendChild(ebody);
    card.appendChild(en);

    // ----- solar (MPPT) — hidden when the model exposes none -----
    const mppt = document.createElement("div");
    mppt.className = "bat-sect bat-mppt";
    mppt.innerHTML = `<div class="bat-sect-t">${this._t("solarMppt")}</div><div class="bat-mppt-chips"></div>`;
    card.appendChild(mppt);

    // ----- controles (collapsible) -----
    const controls = document.createElement("details");
    controls.className = "bat-info bat-controls";
    controls.innerHTML =
      `<summary><ha-icon icon="mdi:tune-variant"></ha-icon>${this._t("controls")}</summary>` +
      `<div class="bat-ctl-grid"></div>`;
    card.appendChild(controls);

    // ----- info (collapsible) -----
    const info = document.createElement("details");
    info.className = "bat-info";
    info.innerHTML = `<summary><ha-icon icon="mdi:information-outline"></ha-icon>${this._t("deviceInfo")}</summary><div class="bat-info-grid"></div>`;
    card.appendChild(info);

    this._batCards[b.dev] = {
      card,
      name: head.querySelector(".bat-name"),
      state: head.querySelector(".bat-state"),
      ringFg: ring.fg,
      ringCirc: ring.circ,
      ringVal: ring.val,
      pwrVal: pw.querySelector(".bat-pwr-val"),
      pwrUnit: pw.querySelector(".bat-pwr-unit"),
      pwrLbl: pw.querySelector(".bat-pwr-lbl"),
      pwrBar: pw.querySelector(".bat-pwr-bar"),
      cap: pw.querySelector(".bat-cap"),
      ogWrap: pw.querySelector(".bat-offgrid"),
      ogVal: pw.querySelector(".bat-og-val"),
      ogUnit: pw.querySelector(".bat-og-unit"),
      M,
      chV: ebody.querySelector(".bat-ch-v"),
      chBar: ebody.querySelector(".bat-ch-bar"),
      disV: ebody.querySelector(".bat-dis-v"),
      disBar: ebody.querySelector(".bat-dis-bar"),
      mpptSect: mppt,
      mpptChips: mppt.querySelector(".bat-mppt-chips"),
      ctlGrid: controls.querySelector(".bat-ctl-grid"),
      ctlSig: null,
      controls: {},
      infoGrid: info.querySelector(".bat-info-grid"),
    };
    return card;
  }

  _patchBatteries(list) {
    if (!this._batCards) return;
    const sig = list.map((b) => b.dev).sort().join("|");
    if (sig !== this._batSig && this._main) {
      // battery set changed under us: rebuild the whole view, then patch fresh
      this._main.innerHTML = "";
      this._main.appendChild(this._renderBaterias());
      list = this._batteryModel();
    }
    for (const b of list) {
      const r = this._batCards[b.dev];
      if (r) this._patchBatteryCard(r, b);
    }
  }

  _patchBatteryCard(r, b) {
    r.name.textContent = b.name || this._t("battery");

    // inverter-state chip (localized; tone by state)
    const inv = b.inverter;
    const invState = this._sval(inv);
    if (invState) {
      const raw = invState.toLowerCase();
      let tone = "neutral", disp;
      // inverter_state exposes the English label (sensor.py states map); localize
      // here since HA has no state translation for these free-text values.
      if (raw.includes("backup")) { disp = this._t("invBackup"); tone = "warn"; }
      else if (raw.includes("ota") || raw.includes("upgrade")) { disp = this._t("invUpdating"); tone = "warn"; }
      else if (raw.includes("discharge")) { disp = this._t("discharging"); tone = "good"; }
      else if (raw.includes("charge")) { disp = this._t("charging"); tone = "good"; }
      else if (raw.includes("standby")) disp = this._t("invStandby");
      else if (raw.includes("sleep")) disp = this._t("idle");
      else if (raw.includes("bypass")) disp = this._t("invBypass");
      else disp =
        typeof this._hass.formatEntityState === "function"
          ? this._hass.formatEntityState(inv)
          : invState;
      this._setChip(r.state, disp, tone);
      r.state.style.display = "";
    } else {
      r.state.style.display = "none";
    }

    // SOC ring
    if (b.soc != null) {
      r.ringFg.setAttribute(
        "stroke-dashoffset",
        (r.ringCirc * (1 - this._clamp(b.soc, 0, 100) / 100)).toFixed(2)
      );
      r.ringVal.innerHTML = Math.round(b.soc) + "<span>%</span>";
    } else {
      r.ringVal.innerHTML = "—<span>%</span>";
    }
    const col = this._socColor(b.soc);
    r.ringFg.setAttribute("stroke", col);
    r.ringFg.style.filter = `drop-shadow(0 0 6px ${col})`;

    // power readout (+ charge / - discharge)
    const w = b.powerW;
    const charging = w != null && w > 30;
    const discharging = w != null && w < -30;
    const f = this._fmtPower(w == null ? null : Math.abs(w));
    r.pwrVal.textContent = f.v;
    r.pwrUnit.textContent = f.u ? " " + f.u : "";
    let lbl = this._t("idle"), pcol = "var(--ink)";
    if (charging) { lbl = this._t("charging"); pcol = "var(--battery)"; }
    else if (discharging) { lbl = this._t("discharging"); pcol = "var(--grid)"; }
    r.pwrLbl.textContent = lbl;
    r.pwrVal.style.color = pcol;
    let tcap = charging ? b.maxCharge : discharging ? b.maxDischarge : b.maxCharge || b.maxDischarge;
    if (!tcap) tcap = 2500;
    r.pwrBar.style.width = this._clamp((Math.abs(w || 0) / tcap) * 100, 0, 100) + "%";
    r.pwrBar.style.background = discharging ? "var(--grid)" : "var(--battery)";
    r.cap.textContent = `${this._nf(b.stored, 2)} / ${this._nf(b.capacity, 2)} kWh`;

    // off-grid power — only while the backup function switch is on
    if (b.backupOn && b.offgridW != null) {
      const fo = this._fmtPower(b.offgridW);
      r.ogVal.textContent = fo.v;
      r.ogUnit.textContent = fo.u ? " " + fo.u : "";
      r.ogWrap.style.display = "";
    } else {
      r.ogWrap.style.display = "none";
    }

    // health / cells
    const M = r.M;
    M.temp.textContent = b.temp != null ? `${this._nf(b.temp, 1)} °C` : "—";
    M.volt.textContent = b.voltage != null ? `${this._nf(b.voltage, 2)} V` : "—";
    M.cmax.textContent = b.cellMax != null ? `${this._nf(b.cellMax, 3)} V` : "—";
    M.cmin.textContent = b.cellMin != null ? `${this._nf(b.cellMin, 3)} V` : "—";
    if (b.cellDelta != null) {
      const d = b.cellDelta;
      M.cdelta.textContent = `${Math.round(d)} mV`;
      // tiers mirror const.py BALANCE_THRESHOLD_YELLOW/ORANGE/RED (raw delta)
      M.cdelta.style.color =
        d >= DELTA_MV_RED ? "oklch(0.7 0.18 25)"
        : d >= DELTA_MV_ORANGE ? "oklch(0.72 0.16 50)"
        : d >= DELTA_MV_YELLOW ? "oklch(0.82 0.14 75)"
        : "";
    } else {
      M.cdelta.textContent = "—";
      M.cdelta.style.color = "";
    }
    // cycles: prefer the BMS modbus register; fall back to the calculated sensor
    // when the model exposes no cycle-count register.
    const cyc = b.cycles != null ? b.cycles : b.cyclesCalc;
    M.cycles.textContent = cyc != null ? Math.round(cyc) : "—";
    M.rte.textContent = b.rte != null ? `${this._nf(b.rte, 1)} %` : "—";
    // charge hysteresis active state ("—" when the sensor isn't exposed)
    if (b.hysteresisActive == null) {
      M.hyst.textContent = "—";
      M.hyst.style.color = "";
    } else {
      M.hyst.textContent = b.hysteresisActive ? this._t("active") : this._t("inactive");
      M.hyst.style.color = b.hysteresisActive ? "oklch(0.82 0.14 75)" : "";
    }

    // energía hoy
    const u = `<span class="dim" style="font-size:11px"> kWh</span>`;
    const max = Math.max(b.dailyCharge || 0, b.dailyDischarge || 0, 0.1);
    r.chV.innerHTML = `${this._nf(b.dailyCharge, 2)}${u}`;
    r.chBar.style.width = ((b.dailyCharge || 0) / max) * 100 + "%";
    r.disV.innerHTML = `${this._nf(b.dailyDischarge, 2)}${u}`;
    r.disBar.style.width = ((b.dailyDischarge || 0) / max) * 100 + "%";

    // solar (MPPT)
    if (b.hasMppt) {
      r.mpptSect.style.display = "";
      r.mpptChips.innerHTML = b.mppt
        .map((v, i) =>
          v == null ? null : `<span class="chip mppt-chip">MPPT${i + 1} · ${this._fmtPowerStr(v)}</span>`
        )
        .filter(Boolean)
        .join("");
    } else {
      r.mpptSect.style.display = "none";
    }

    // info (firmware / wifi / mac)
    const rows = [];
    const addRow = (label, val) => {
      if (val != null && val !== "")
        rows.push(`<div class="info-row"><span class="muted">${label}</span><span>${val}</span></div>`);
    };
    addRow("BMS", b.info.bms);
    addRow("VMS", b.info.vms);
    addRow("EMS", b.info.ems);
    addRow(this._t("infoComm"), b.info.comm);
    let wifi = b.info.wifiSignal != null ? `${Math.round(b.info.wifiSignal)} dBm` : null;
    const wstat = this._sval(b.info.wifiStatus);
    if (wstat) {
      const wdisp =
        typeof this._hass.formatEntityState === "function"
          ? this._hass.formatEntityState(b.info.wifiStatus)
          : wstat;
      wifi = wifi ? `${wifi} · ${wdisp}` : wdisp;
    }
    addRow("WiFi", wifi);
    addRow("MAC", b.info.mac);
    r.infoGrid.innerHTML = rows.length ? rows.join("") : `<div class="dim">${this._t("noData")}</div>`;

    // controls (rebuilt when the available-control set changes; else value-patched)
    this._syncControls(r, b);
  }

  // ----- per-battery controls -----------------------------------------------
  /** Localized label for a select option (uses HA's state override formatter). */
  _fmtOption(stateObj, option) {
    if (typeof this._hass.formatEntityState === "function") {
      try { return this._hass.formatEntityState(stateObj, option); } catch (e) { /* fall through */ }
    }
    return option;
  }

  _syncControls(r, b) {
    const hass = this._hass;
    const avail = BAT_CONTROLS.filter((c) => {
      const id = b.entIds[c.key];
      return id && hass.states[id];
    });
    const sig = avail.map((c) => c.key).join("|");
    if (sig !== r.ctlSig) {
      r.ctlSig = sig;
      r.controls = {};
      r.ctlGrid.innerHTML = "";
      if (!avail.length) {
        const e = document.createElement("div");
        e.className = "dim ctl-empty";
        e.textContent = this._t("ctlEmpty");
        r.ctlGrid.appendChild(e);
      } else {
        for (const c of avail) r.ctlGrid.appendChild(this._buildControlRow(r, b, c));
      }
    }
    for (const c of avail) {
      const w = r.controls[c.key];
      if (w) this._patchControlRow(w, hass.states[b.entIds[c.key]]);
    }
  }

  /** Returns a fragment with the control's grid items (label + control, or a
   *  full-width button), so the parent .bat-ctl-grid aligns labels/controls
   *  across rows and every slider gets the same width. */
  _buildControlRow(r, b, c) {
    const id = b.entIds[c.key];
    const state = this._hass.states[id];
    const frag = document.createDocumentFragment();

    const cLabel = this._t(c.lk);
    if (c.domain === "button") {
      const btn = document.createElement("button");
      btn.className = "ctl-btn";
      btn.innerHTML = `<ha-icon icon="${c.icon}"></ha-icon>${cLabel}`;
      btn.addEventListener("click", () => {
        if (c.confirm && !window.confirm(`${cLabel}?`)) return;
        this._hass.callService("button", "press", { entity_id: id });
      });
      frag.appendChild(btn);
      r.controls[c.key] = { type: "button" };
      return frag;
    }

    const label = document.createElement("span");
    label.className = "ctl-k";
    label.innerHTML = `<ha-icon icon="${c.icon}"></ha-icon><span>${cLabel}</span>`;
    frag.appendChild(label);

    if (c.domain === "switch") {
      const btn = document.createElement("button");
      btn.className = "ctl-toggle";
      btn.innerHTML = `<span class="ctl-knob"></span>`;
      btn.addEventListener("click", () =>
        this._hass.callService("switch", "toggle", { entity_id: id })
      );
      frag.appendChild(btn);
      r.controls[c.key] = { type: "switch", el: btn };
    } else if (c.domain === "select") {
      const sel = document.createElement("select");
      sel.className = "ctl-select";
      sel.addEventListener("change", () =>
        this._hass.callService("select", "select_option", { entity_id: id, option: sel.value })
      );
      frag.appendChild(sel);
      r.controls[c.key] = { type: "select", el: sel };
    } else {
      // number → slider + value
      const wrap = document.createElement("div");
      wrap.className = "ctl-num";
      const range = document.createElement("input");
      range.type = "range";
      const valEl = document.createElement("span");
      valEl.className = "ctl-val";
      const a = (state && state.attributes) || {};
      const unit = a.unit_of_measurement || "";
      range.addEventListener("input", () => {
        valEl.textContent = `${Math.round(Number(range.value))}${unit ? " " + unit : ""}`;
      });
      range.addEventListener("change", () =>
        this._hass.callService("number", "set_value", {
          entity_id: id,
          value: Number(range.value),
        })
      );
      wrap.appendChild(range);
      wrap.appendChild(valEl);
      frag.appendChild(wrap);
      r.controls[c.key] = { type: "number", el: range, val: valEl };
    }
    return frag;
  }

  _patchControlRow(w, state) {
    if (!state || w.type === "button") return;
    const focused = this.shadowRoot && this.shadowRoot.activeElement === w.el;
    if (w.type === "switch") {
      w.el.classList.toggle("on", state.state === "on");
    } else if (w.type === "select") {
      const opts = Array.isArray(state.attributes.options) ? state.attributes.options : [];
      const sig = opts.join("|");
      if (w.el.__opts !== sig) {
        w.el.__opts = sig;
        w.el.innerHTML = opts
          .map((o) => `<option value="${o}">${this._fmtOption(state, o)}</option>`)
          .join("");
      }
      if (!focused) w.el.value = state.state;
    } else if (w.type === "number") {
      const a = state.attributes || {};
      if (a.min != null) w.el.min = a.min;
      if (a.max != null) w.el.max = a.max;
      if (a.step != null) w.el.step = a.step;
      const unit = a.unit_of_measurement || "";
      if (!focused) {
        const v = Number(state.state);
        if (!Number.isNaN(v)) w.el.value = v;
        w.val.textContent =
          state.state == null || state.state === "unknown" || state.state === "unavailable"
            ? "—"
            : `${Math.round(Number(w.el.value))}${unit ? " " + unit : ""}`;
      }
    }
  }

  // ===== Control view ========================================================
  // A sectioned list of system-level entities grouped by feature (switch + its
  // related CONFIG params), matched by translation_key and resolved by entity_id,
  // reusing the per-battery control widgets/CSS.

  _renderControl() {
    this._ctlStore = {};
    const { wrap, sig } = this._renderSysSections(SYS_SECTIONS, this._ctlStore, {
      icon: "mdi:tune-variant",
      title: this._t("sysEmptyTitle"),
      msg: this._t("sysEmptyMsg"),
    });
    this._ctlSig = sig;
    return wrap;
  }
  _patchControl() {
    this._patchSysView(SYS_SECTIONS, "_ctlStore", "_ctlSig", "control", () => this._renderControl());
  }

  /** Scan section defs against the live registry: which entities exist + a
   *  signature of the available set (so the view rebuilds when it changes). */
  _sysScan(defs) {
    const { byKey } = this._index();
    const sections = [];
    const sigParts = [];
    for (const sec of defs) {
      const rows = [];
      for (const item of sec.items) {
        const ids = byKey.get(item.key) || [];
        for (const id of ids) {
          if (this._hass.states[id]) rows.push({ item, id, multi: ids.length > 1 });
        }
      }
      if (rows.length) {
        sections.push({ sec, rows });
        sigParts.push(sec.tk + ":" + rows.map((r) => r.id).join(","));
      }
    }
    return { sections, sig: sigParts.join("|") };
  }

  /** Build the sectioned card stack into `store` (id -> widget). */
  _renderSysSections(defs, store, empty) {
    for (const k in store) delete store[k];
    const { sections, sig } = this._sysScan(defs);
    const wrap = document.createElement("div");
    wrap.className = "sys-stack";
    if (!sections.length) {
      const e = document.createElement("div");
      e.className = "placeholder";
      e.innerHTML =
        `<ha-icon icon="${empty.icon}"></ha-icon><h3>${empty.title}</h3><p>${empty.msg}</p>`;
      wrap.appendChild(e);
      return { wrap, sig };
    }
    // Build one card per live section, keyed by tk.
    const cardByTk = {};
    for (const { sec, rows } of sections) {
      const { card } = this._card(this._t(sec.tk), sec.icon || "mdi:cog-outline");
      const grid = document.createElement("div");
      grid.className = "bat-ctl-grid sys-grid";
      for (const r of rows) grid.appendChild(this._buildSysControl(r.item, r.id, store, r.multi));
      card.appendChild(grid);
      cardByTk[sec.tk] = card;
    }
    // Place cards per the layout blocks; skip empty columns/rows so the rest
    // stays flush (no gaps). Sections missing from the layout fall back to a
    // trailing single column.
    const placed = new Set();
    for (const block of SYS_LAYOUT) {
      if (block.pair) {
        const grid = document.createElement("div");
        grid.className = "sys-pair";
        for (const [a, b] of block.pair) {
          const ca = a && cardByTk[a];
          const cb = b && cardByTk[b];
          if (!ca && !cb) continue; // drop the whole row
          // emit exactly two cells so the two columns stay aligned row-by-row
          grid.appendChild(ca || this._pairSpacer());
          grid.appendChild(cb || this._pairSpacer());
          if (ca) placed.add(a);
          if (cb) placed.add(b);
        }
        if (grid.childNodes.length) wrap.appendChild(grid);
      } else {
        const col = document.createElement("div");
        col.className = "sys-col";
        for (const tk of block.col) {
          if (cardByTk[tk]) {
            col.appendChild(cardByTk[tk]);
            placed.add(tk);
          }
        }
        if (col.childNodes.length) wrap.appendChild(col);
      }
    }
    for (const { sec } of sections) {
      if (placed.has(sec.tk)) continue;
      const col = document.createElement("div");
      col.className = "sys-col";
      col.appendChild(cardByTk[sec.tk]);
      wrap.appendChild(col);
    }
    return { wrap, sig };
  }

  /** Invisible cell that holds a paired-grid column slot when a partner card is
   *  absent, so the two columns stay aligned row-by-row. */
  _pairSpacer() {
    const d = document.createElement("div");
    d.className = "sys-pair-spacer";
    d.setAttribute("aria-hidden", "true");
    return d;
  }

  /** Patch all widgets in a system view; rebuild it if the available set changed. */
  _patchSysView(defs, storeKey, sigKey, view, renderFn) {
    const store = this[storeKey];
    if (!store) return;
    const sig = this._sysScan(defs).sig;
    if (sig !== this[sigKey] && this._main && this._view === view) {
      this._main.innerHTML = "";
      this._main.appendChild(renderFn()); // resets store + sig
    }
    for (const [id, w] of Object.entries(this[storeKey])) {
      const st = this._hass.states[id];
      if (st) this._patchSysControl(w, st);
    }
  }

  /** Decimals implied by a number's step ("0.05" -> 2), capped at 3. */
  _stepDecimals(step) {
    const s = String(step);
    const i = s.indexOf(".");
    return i < 0 ? 0 : Math.min(3, s.length - i - 1);
  }
  _fmtCtlNum(value, step, unit) {
    const v = Number(value);
    const txt = Number.isNaN(v) ? "—" : v.toFixed(this._stepDecimals(step));
    return unit ? `${txt} ${unit}` : txt;
  }
  /** Friendly name minus the device prefix, for multi-instance controls. */
  _entityShortName(state, id) {
    let fn = (state && state.attributes && state.attributes.friendly_name) || id;
    const e = this._hass.entities[id];
    const dev = e && e.device_id && this._hass.devices && this._hass.devices[e.device_id];
    const dn = dev && (dev.name_by_user || dev.name);
    if (dn && fn.startsWith(dn + " ")) fn = fn.slice(dn.length + 1);
    return fn;
  }

  /** Build one system control's grid items (label + widget), keyed by entity_id
   *  in `store`. Mirrors _buildControlRow but resolves by id and formats numbers
   *  with step-derived decimals (PD params use fractional steps). */
  _buildSysControl(item, id, store, multi) {
    const hass = this._hass;
    const state = hass.states[id];
    const domain = item.domain || "number";
    const shortName = this._entityShortName(state, id);
    const t = this._t.bind(this);
    let label = this._t(item.lk);
    if (item.labelFn) label = item.labelFn(state, t) || shortName;
    else if (multi || item.useName) label = shortName;
    const frag = document.createDocumentFragment();

    if (domain === "button") {
      const btn = document.createElement("button");
      btn.className = "ctl-btn";
      btn.innerHTML = `<ha-icon icon="${item.icon}"></ha-icon>${label}`;
      btn.addEventListener("click", () => {
        if (item.confirm && !window.confirm(`${label}?`)) return;
        hass.callService("button", "press", { entity_id: id });
      });
      frag.appendChild(btn);
      store[id] = { type: "button" };
      return frag;
    }

    const k = document.createElement("span");
    k.className = "ctl-k";
    k.innerHTML = `<ha-icon icon="${item.icon || "mdi:cog-outline"}"></ha-icon><span>${label}</span>`;
    if (item.titleFn) {
      k.classList.add("ctl-k-info");
      // tap/click shows the detail popover — mobile has no hover. The native
      // `title` set in _patchSysControl still covers desktop hover.
      k.addEventListener("click", (e) => {
        e.stopPropagation();
        const st = (this._hass && this._hass.states && this._hass.states[id]) || state;
        this._showInfoPopover(k, item.titleFn(st, this._t.bind(this)));
      });
    }
    frag.appendChild(k);

    if (domain === "switch") {
      const btn = document.createElement("button");
      btn.className = "ctl-toggle";
      btn.innerHTML = `<span class="ctl-knob"></span>`;
      btn.addEventListener("click", () => hass.callService("switch", "toggle", { entity_id: id }));
      frag.appendChild(btn);
      store[id] = { type: "switch", el: btn };
    } else if (domain === "select") {
      const sel = document.createElement("select");
      sel.className = "ctl-select";
      sel.addEventListener("change", () =>
        hass.callService("select", "select_option", { entity_id: id, option: sel.value })
      );
      frag.appendChild(sel);
      store[id] = { type: "select", el: sel };
    } else {
      const wrap = document.createElement("div");
      wrap.className = "ctl-num";
      const range = document.createElement("input");
      range.type = "range";
      const valEl = document.createElement("span");
      valEl.className = "ctl-val";
      const a = (state && state.attributes) || {};
      const unit = a.unit_of_measurement || "";
      const step = Number(a.step) || 1;
      range.addEventListener("input", () => {
        valEl.textContent = this._fmtCtlNum(range.value, step, unit);
      });
      range.addEventListener("change", () =>
        hass.callService("number", "set_value", { entity_id: id, value: Number(range.value) })
      );
      wrap.appendChild(range);
      wrap.appendChild(valEl);
      frag.appendChild(wrap);
      store[id] = { type: "number", el: range, val: valEl, step, unit };
    }
    // optional hover tooltip (set on the label cell, kept fresh on patch)
    if (item.titleFn && store[id]) {
      store[id].titleEl = k;
      store[id].titleFn = item.titleFn;
    }
    return frag;
  }

  _patchSysControl(w, state) {
    if (!state || w.type === "button") return;
    if (w.titleEl && w.titleFn) w.titleEl.title = w.titleFn(state, this._t.bind(this)) || "";
    const focused = this.shadowRoot && this.shadowRoot.activeElement === w.el;
    if (w.type === "switch") {
      w.el.classList.toggle("on", state.state === "on");
    } else if (w.type === "select") {
      const opts = Array.isArray(state.attributes.options) ? state.attributes.options : [];
      const sig = opts.join("|");
      if (w.el.__opts !== sig) {
        w.el.__opts = sig;
        w.el.innerHTML = opts
          .map((o) => `<option value="${o}">${this._fmtOption(state, o)}</option>`)
          .join("");
      }
      if (!focused) w.el.value = state.state;
    } else if (w.type === "number") {
      const a = state.attributes || {};
      if (a.min != null) w.el.min = a.min;
      if (a.max != null) w.el.max = a.max;
      if (a.step != null) w.el.step = a.step;
      const step = Number(a.step) || w.step || 1;
      const unit = a.unit_of_measurement || w.unit || "";
      if (!focused) {
        const v = Number(state.state);
        if (!Number.isNaN(v)) w.el.value = v;
        w.val.textContent =
          state.state == null || state.state === "unknown" || state.state === "unavailable"
            ? "—"
            : this._fmtCtlNum(w.el.value, step, unit);
      }
    }
  }

  // Click/tap detail popover (works on touch, unlike hover `title`). One shared
  // node in the shadow root, repositioned per anchor; tap-again or tap-outside
  // closes it. Anchored under the label, flipped/clamped to stay on screen.
  _showInfoPopover(anchor, text) {
    if (!text) return;
    let pop = this._infoPop;
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "info-pop";
      this.shadowRoot.appendChild(pop);
      this._infoPop = pop;
      this._infoPopDismiss = (ev) => {
        const p = this._infoPop;
        if (!p || !p._open) return;
        const t = ev.target;
        if (p.contains(t) || (p._anchor && p._anchor.contains(t))) return;
        this._hideInfoPopover();
      };
    }
    // second tap on the same anchor toggles it closed
    if (pop._open && pop._anchor === anchor) {
      this._hideInfoPopover();
      return;
    }
    pop._anchor = anchor;
    pop.textContent = text;
    pop.style.maxWidth = Math.min(340, window.innerWidth - 24) + "px";
    pop.style.display = "block";
    pop.style.left = "0px";
    pop.style.top = "0px";
    pop._open = true;
    const r = anchor.getBoundingClientRect();
    const pr = pop.getBoundingClientRect();
    let left = r.left;
    if (left + pr.width > window.innerWidth - 12) left = window.innerWidth - pr.width - 12;
    if (left < 12) left = 12;
    let top = r.bottom + 6;
    if (top + pr.height > window.innerHeight - 12) top = r.top - pr.height - 6;
    if (top < 12) top = 12;
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    // defer so the opening click doesn't immediately dismiss it
    setTimeout(() => window.addEventListener("click", this._infoPopDismiss, true), 0);
  }

  _hideInfoPopover() {
    const pop = this._infoPop;
    if (!pop) return;
    pop.style.display = "none";
    pop._open = false;
    pop._anchor = null;
    window.removeEventListener("click", this._infoPopDismiss, true);
  }

  // Open Home Assistant's native more-info dialog for an entity (it includes the
  // history graph). Fired as a bubbling/composed event the HA frontend listens for.
  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true })
    );
  }

  // Mark an element as a more-info trigger (cursor + tooltip + click). No-op when
  // the entity is absent, so missing sensors stay non-clickable.
  _linkMoreInfo(el, entityId) {
    if (!el || !entityId) return;
    el.classList.add("clickable");
    el.title = this._t("moreInfo");
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      this._moreInfo(entityId);
    });
  }

  // --- styles ----------------------------------------------------------------
  _styleEl() {
    const style = document.createElement("style");
    style.textContent = `
      :host {
        --accent-h: 155;
        --accent: oklch(0.78 0.15 var(--accent-h));
        --accent-soft: oklch(0.78 0.15 var(--accent-h) / 0.14);
        --accent-line: oklch(0.78 0.15 var(--accent-h) / 0.35);
        --accent-ink: oklch(0.22 0.04 var(--accent-h));
        --solar: oklch(0.84 0.15 88);
        --grid: oklch(0.72 0.12 268);
        --home: oklch(0.82 0.07 220);
        --flow-purple: oklch(0.50 0.27 295);
        --flow-orange: oklch(0.75 0.17 58);
        --flow-blue: oklch(0.70 0.15 245);
        --flow-green: oklch(0.78 0.16 150);
        --battery: var(--accent);
        --font-ui: "Manrope", system-ui, sans-serif;
        --font-display: "Space Grotesk", system-ui, sans-serif;
        --gap: 18px; --pad: 22px; --radius: 20px; --radius-sm: 13px;
        display: block; height: 100%;
        font-family: var(--font-ui);
      }
      :host([data-theme="dark"]) {
        --bg-0: oklch(0.17 0.008 250); --bg-1: oklch(0.215 0.009 250);
        --bg-2: oklch(0.255 0.01 250); --bg-hover: oklch(0.30 0.012 250);
        --line: oklch(1 0 0 / 0.08); --line-strong: oklch(1 0 0 / 0.14);
        --ink: oklch(0.97 0.003 250); --ink-mid: oklch(0.74 0.008 250); --ink-dim: oklch(0.56 0.01 250);
        color-scheme: dark;
      }
      :host([data-theme="light"]) {
        --bg-0: oklch(0.965 0.004 250); --bg-1: oklch(0.995 0.002 250);
        --bg-2: oklch(0.975 0.003 250); --bg-hover: oklch(0.93 0.005 250);
        --line: oklch(0 0 0 / 0.09); --line-strong: oklch(0 0 0 / 0.16);
        --ink: oklch(0.25 0.01 250); --ink-mid: oklch(0.45 0.01 250); --ink-dim: oklch(0.6 0.01 250);
        color-scheme: light;
      }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      .num { font-family: var(--font-display); font-feature-settings: "tnum" 1; letter-spacing: -0.01em; }
      .muted { color: var(--ink-mid); } .dim { color: var(--ink-dim); }
      ha-icon { display: inline-flex; }

      .app {
        display: flex; flex-direction: column; height: 100%;
        background: radial-gradient(120% 80% at 80% -10%, oklch(0.78 0.15 var(--accent-h) / 0.06), transparent 60%), var(--bg-0);
        color: var(--ink);
      }
      .appbar {
        display: flex; align-items: center; gap: 26px; height: 66px; padding: 0 30px; flex-shrink: 0;
        border-bottom: 1px solid var(--line);
        background: color-mix(in oklab, var(--bg-1) 80%, transparent);
        backdrop-filter: blur(10px);
      }
      .brand { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
      .brand .logo {
        width: 36px; height: 36px; border-radius: 11px; display: grid; place-items: center; cursor: pointer;
        background: var(--accent); color: var(--accent-ink);
        font-family: var(--font-display); font-weight: 700; font-size: 17px;
        box-shadow: 0 5px 16px oklch(0.78 0.15 var(--accent-h) / 0.4);
      }
      .brand .bt-name { font-family: var(--font-display); font-size: 15px; font-weight: 600; }
      .brand .bt-sub { font-size: 11px; color: var(--ink-dim); }

      .tabs { display: flex; align-items: stretch; gap: 2px; height: 100%; overflow-x: auto; scrollbar-width: none; }
      .tabs::-webkit-scrollbar { display: none; }
      .tab {
        display: flex; align-items: center; gap: 9px; padding: 0 17px; height: 100%;
        border: none; background: none; cursor: pointer; color: var(--ink-mid);
        font-family: var(--font-ui); font-size: 14px; font-weight: 600;
        border-bottom: 2.5px solid transparent; transition: color 0.16s; white-space: nowrap;
        --mdc-icon-size: 18px;
      }
      .tab:hover { color: var(--ink); }
      .tab.active { color: var(--accent); border-bottom-color: var(--accent); }


      .main { flex: 1; overflow-y: auto; padding: 26px 30px 44px; }
      .main::-webkit-scrollbar { width: 10px; }
      .main::-webkit-scrollbar-thumb { background: var(--line-strong); border-radius: 10px; border: 3px solid transparent; background-clip: content-box; }

      .pill { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 999px;
        background: var(--bg-1); border: 1px solid var(--line); font-size: 13px; color: var(--ink-mid); }
      .pill .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
      .pill .dot.live { animation: mvpulse 2.4s ease-in-out infinite; }
      @keyframes mvpulse { 0%,100%{opacity:1;} 50%{opacity:.35;} }

      .card { background: var(--bg-1); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--pad); }
      .card-head { display: flex; align-items: center; gap: 9px; margin-bottom: 16px; --mdc-icon-size: 17px; }
      .card-head h2 { font-size: 13px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-mid); }
      .card-head .ic { color: var(--ink-dim); display: grid; place-items: center; }

      .res-stack { display: flex; flex-direction: column; gap: var(--gap); }
      /* lower row: Flujo (left) + 2×2 chart grid (right), equal height */
      .resumen-lower { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.6fr); gap: var(--gap); align-items: stretch; }
      /* top row = "Energía hoy" content height (min-content): Energía semanal
         stretches to match it (its own chart min-content is shorter, so it never
         inflates the track), the bottom row fills the rest. The right column thus
         drives the block height and Flujo follows/crops to it (see .scene-stage). */
      .charts-2x2 { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: min-content minmax(0, 1fr); gap: var(--gap); min-width: 0; }
      .charts-2x2 > .card { min-width: 0; }
      /* Energía hoy is a fixed list of rows — keep it at content height instead of
         stretching to the (taller) Flujo column, which left empty space below it. */
      .charts-2x2 > .daily-card { align-self: start; }
      @media (max-width: 1080px) { .resumen-lower { grid-template-columns: 1fr; } }
      @media (max-width: 720px) { .charts-2x2 { grid-template-columns: 1fr; grid-template-rows: none; } }

      /* chart cards (Potencias / Energía semanal / SOC hoy) */
      .chart-card { display: flex; flex-direction: column; min-height: 0; }
      .chart-plot { flex: 1 1 auto; min-height: 96px; position: relative; }
      .chart-canvas { display: flex; height: 100%; min-height: 0; }
      .chart-yaxis { display: flex; flex: 0 0 48px; flex-direction: column; align-items: flex-end; justify-content: space-between; padding: 1px 8px 1px 0; color: var(--ink-dim); font-size: 10px; line-height: 1; white-space: nowrap; }
      .chart-yaxis small { margin-left: 2px; color: var(--ink-dim); font-size: 9px; }
      .chart-surface { position: relative; flex: 1 1 auto; min-width: 0; min-height: 0; }
      /* absolute so the SVG's intrinsic (viewBox) height never feeds back into the
         grid's min-content sizing — otherwise Energía semanal would inflate the
         shared top row past Energía hoy instead of matching it. */
      .chart-svg { display: block; position: absolute; inset: 0; width: 100%; height: 100%; }
      .chart-hover { position: absolute; inset: 0; pointer-events: none; z-index: 4; display: none; }
      .hv-line { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--line-strong); transform: translateX(-0.5px); }
      .hv-dot { position: absolute; width: 7px; height: 7px; border-radius: 50%; transform: translate(-50%, -50%); box-shadow: 0 0 0 2px var(--bg-1); }
      .hv-tip { position: absolute; top: 4px; padding: 6px 8px; border-radius: var(--radius-sm); background: var(--bg-2);
        border: 1px solid var(--line-strong); color: var(--ink); font-size: 11px; line-height: 1.4; white-space: nowrap;
        box-shadow: 0 6px 18px oklch(0 0 0 / 0.35); }
      .hv-tip .hv-h { font-weight: 600; margin-bottom: 3px; color: var(--ink-mid); }
      .hv-tip .hv-r { display: flex; justify-content: space-between; gap: 14px; }
      .hv-tip .hv-k { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-mid); }
      .hv-tip .hv-k i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; flex-shrink: 0; }
      .hv-tip .hv-v { font-variant-numeric: tabular-nums; color: var(--ink); }
      .chart-grid { stroke: var(--line); stroke-width: 1; vector-effect: non-scaling-stroke; }
      .chart-zero { stroke: var(--line-strong); stroke-width: 1; vector-effect: non-scaling-stroke; }
      .chart-xaxis { display: flex; justify-content: space-between; margin-top: 6px; padding-left: 48px; font-size: 11px; }
      .chart-legend { display: inline-flex; gap: 12px; flex-wrap: wrap; }
      .legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--ink-mid); }
      .legend-dot { width: 9px; height: 9px; border-radius: 2px; display: inline-block; flex-shrink: 0; }
      .chart-empty { display: grid; place-items: center; height: 100%; min-height: 96px; font-size: 12px; }
      /* zoom: range buttons under the chart + drag-to-brush selection box */
      .chart-zoom { display: flex; gap: 4px; justify-content: flex-end; margin-top: 6px; padding-left: 48px; }
      .zoom-btn { font-family: var(--font-ui); font-size: 11px; color: var(--ink-mid); background: var(--bg-2);
        border: 1px solid var(--line); border-radius: 7px; padding: 2px 8px; cursor: pointer; line-height: 1.5; }
      .zoom-btn:hover { background: var(--bg-hover); color: var(--ink); }
      .zoom-btn.active { background: var(--accent-soft); border-color: var(--accent-line); color: var(--accent); }
      .chart-plot, .mini-spark { touch-action: pan-y; }
      .brush-box { position: absolute; top: 0; bottom: 0; background: var(--accent-soft);
        border-left: 1px solid var(--accent-line); border-right: 1px solid var(--accent-line);
        pointer-events: none; z-index: 5; }

      .stat-label { font-size: 12.5px; color: var(--ink-mid); font-weight: 600; display: flex; align-items: center; gap: 7px; --mdc-icon-size: 15px; }
      .stat-value { font-family: var(--font-display); font-weight: 600; letter-spacing: -0.02em; line-height: 1; font-size: 26px; }
      .stat-unit { color: var(--ink-dim); font-weight: 500; font-size: 0.5em; }

      /* flow — 3D-render scene with leader-line callouts */
      /* width-based square: fills the column width and stays square (never
         letterboxed). It anchors the block height; the 2×2 column matches it. */
      .flow-card { position: relative; overflow: hidden; }
      .flow-wrap { display: grid; place-items: center; }
      .scene-stage { position: relative; width: 100%; max-width: 540px; aspect-ratio: 1; margin: 0 auto; container-type: inline-size; }
      .scene-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; border-radius: 14px; user-select: none; -webkit-user-drag: none; }
      .lead-svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
      .lead { fill: none; stroke: #8b9197; stroke-width: 0.4; opacity: 0.55; stroke-linecap: round; stroke-linejoin: round; transition: opacity 0.4s, stroke-width 0.4s; }
      .lead.on { opacity: 0.9; stroke-width: 0.5; }
      .lead-end { fill: #c8ccd0; opacity: 0.5; transition: opacity 0.4s; }
      .lead-end.on { opacity: 0.95; }
      /* animated "snake": one dash (15% of the path) travels the whole polyline.
         pathLength=100 normalizes geometry so dasharray is the same on every edge. */
      /* two long colored dashes per path: dasharray sums to 50 → repeats twice
         over pathLength=100, so exactly two segments travel each gray line. */
      /* NOTE: no vector-effect:non-scaling-stroke here — it makes dasharray use
         screen pixels and breaks the pathLength=100 normalization (the dashes
         turn into many short segments). Plain user-unit stroke keeps exactly two
         dashes per path. Width/glow are in viewBox units (~5.4x on screen). */
      .lead-flow { fill: none; stroke: currentColor; color: var(--home); stroke-width: 0.6;
        stroke-linecap: round; stroke-linejoin: round;
        stroke-dasharray: 38 12; stroke-dashoffset: 0; opacity: 0; pointer-events: none;
        transition: opacity 0.45s ease;
        filter: drop-shadow(0 0 0.7px currentColor) drop-shadow(0 0 1.8px currentColor); }
      .lead-flow.on { opacity: 0.95; animation: mv-snake 1.6s linear infinite; }
      /* distinct animation-name (not just animation-direction) so a live direction
         flip restarts the animation and actually reverses travel in Chrome.
         One pattern period is 50, so animate the offset by 50 for a seamless loop. */
      .lead-flow.on.rev { animation-name: mv-snake-rev; }
      @keyframes mv-snake { from { stroke-dashoffset: 0; } to { stroke-dashoffset: 50; } }
      @keyframes mv-snake-rev { from { stroke-dashoffset: 50; } to { stroke-dashoffset: 0; } }
      @media (prefers-reduced-motion: reduce) { .lead-flow.on { animation: none; opacity: 0.6; } }
      .scene-lbl { position: absolute; transform: translate(-50%, -50%); display: flex; flex-direction: column; align-items: center; gap: 1px; text-align: center; pointer-events: none; text-shadow: 0 1px 4px rgba(0,0,0,0.85); }
      .lbl-val { font-size: clamp(12px, 3.52cqw, 19px); font-weight: 700; color: #fff; line-height: 1; white-space: nowrap; }
      .lbl-val .fn-unit { font-size: 0.58em; font-weight: 600; color: rgba(255,255,255,0.7); margin-left: 2px; }
      .lbl-cap { font-size: clamp(7px, 1.67cqw, 9px); letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.55); font-weight: 600; margin-top: 2px; }
      .lbl-badge { font-size: clamp(7.5px, 1.85cqw, 10px); color: rgba(255,255,255,0.7); }
      .scene-lbl:not(.active) .lbl-val { color: rgba(255,255,255,0.78); }
      .scene-self { position: absolute; left: 50%; bottom: 3%; transform: translateX(-50%); font-size: clamp(8px, 2.04cqw, 11px); color: rgba(255,255,255,0.6); letter-spacing: 0.03em; pointer-events: none; text-shadow: 0 1px 4px rgba(0,0,0,0.85); }
      .scene-self .hub-self { color: var(--accent); font-weight: 700; }

      /* soc hero — ring (SOC + capacity + power) left, diagnostics 2 cols right */
      .soc-card { display: flex; flex-direction: column; gap: 18px; }
      .soc-card .card-head { align-self: stretch; margin-bottom: 4px; }
      .soc-inner { display: flex; gap: 30px; align-items: stretch; }
      .soc-left { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; flex: 0 0 auto; }
      .soc-diag { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; justify-content: center; border-left: 1px solid var(--line); padding-left: 30px; }
      .soc-diag-title { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; font-size: 13px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-mid); --mdc-icon-size: 17px; }
      .soc-diag-title ha-icon { color: var(--ink-dim); }
      .diag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 30px; }
      .diag-cell { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; padding: 9px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
      .diag-cell-label { color: var(--ink-mid); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .diag-cell .chip { flex-shrink: 0; max-width: 58%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      @media (max-width: 860px) {
        .soc-inner { flex-direction: column; align-items: center; gap: 20px; }
        .soc-diag { align-self: stretch; border-left: none; padding-left: 0; border-top: 1px solid var(--line); padding-top: 18px; }
      }
      @media (max-width: 560px) { .diag-grid { grid-template-columns: 1fr; } }
      .ring { position: relative; }
      .ring .ring-fg { transition: stroke-dashoffset 0.8s cubic-bezier(.4,0,.2,1), stroke 0.6s ease; }
      .ring-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 2px; }
      .ring-val { font-size: 50px; font-weight: 600; line-height: 1; }
      .ring-val span { font-size: 0.42em; color: var(--ink-mid); }
      .ring-sub { font-size: 12px; }
      .soc-power { width: 100%; max-width: 300px; }
      .soc-power .pw-stats { display: flex; justify-content: space-between; gap: 16px; }
      .soc-power .stat-value { font-size: 23px; }
      .soc-power .pw-avail { font-size: 11px; margin-top: 6px; text-align: center; }

      /* chips */
      .chip { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; border: 1px solid var(--line); background: var(--bg-2); color: var(--ink-mid); }
      .chip-good { color: var(--accent); border-color: var(--accent-line); background: var(--accent-soft); }
      .chip-warn { color: oklch(0.82 0.14 75); border-color: oklch(0.82 0.14 75 / 0.35); background: oklch(0.82 0.14 75 / 0.12); }
      .chip-bad { color: oklch(0.7 0.18 25); border-color: oklch(0.7 0.18 25 / 0.4); background: oklch(0.7 0.18 25 / 0.12); }

      /* daily bars */
      .socbar { height: 8px; border-radius: 999px; background: var(--bg-2); overflow: hidden; }
      .socbar > span { display: block; height: 100%; border-radius: 999px; background: var(--battery); transition: width 0.8s cubic-bezier(.4,0,.2,1); }
      .daily-body { display: flex; flex-direction: column; gap: 10px; }
      .daily-row { display: flex; flex-direction: column; gap: 4px; }
      .daily-head { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; }

      .mini-spark { margin-top: 2px; flex: 1 1 auto; min-height: 96px; }
      .mini-axis { display: flex; justify-content: space-between; margin-top: 6px; padding-left: 48px; font-size: 11px; }

      .placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 80px 20px; color: var(--ink-mid); --mdc-icon-size: 48px; }
      .placeholder ha-icon { color: var(--ink-dim); }
      .placeholder h3 { font-family: var(--font-display); font-size: 22px; color: var(--ink); }
      .placeholder p { max-width: 360px; font-size: 14px; }

      /* ===== Baterías tab ===== */
      .bat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: var(--gap); align-items: start; }
      .bat-card { display: flex; flex-direction: column; gap: 16px; }
      .bat-head { display: flex; align-items: center; gap: 10px; }
      .bat-title { display: flex; align-items: center; gap: 9px; min-width: 0; flex: 1 1 auto; --mdc-icon-size: 18px; }
      .bat-title .ic { color: var(--ink-dim); display: grid; place-items: center; flex-shrink: 0; }
      .bat-name { font-family: var(--font-display); font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .bat-head .chip { flex-shrink: 0; }
      .bat-top { display: flex; align-items: center; gap: 18px; }
      .bat-ring { flex: 0 0 auto; }
      .bat-ring .ring-val { font-size: 30px; font-weight: 600; line-height: 1; }
      .bat-power { flex: 1 1 auto; min-width: 0; position: relative; }
      .bat-pwr { display: flex; align-items: baseline; gap: 1px; }
      .bat-pwr-val { font-family: var(--font-display); font-weight: 600; font-size: 26px; line-height: 1; letter-spacing: -0.02em; }
      .bat-pwr-unit { font-size: 13px; }
      .bat-pwr-lbl { font-size: 12px; margin-top: 3px; }
      .bat-pwr-track { width: 100%; }
      .bat-cap { font-size: 12px; margin-top: 6px; }
      /* off-grid power: right edge, aligned with the AC-power line */
      .bat-offgrid { position: absolute; top: 0; right: 0; text-align: right; }
      .bat-offgrid .bat-pwr { justify-content: flex-end; }
      .bat-og-val { font-size: 20px; color: oklch(0.75 0.17 58); }
      .bat-og-unit { font-size: 12px; }
      .bat-og-lbl { font-size: 11px; margin-top: 3px; }
      .bat-sect { display: flex; flex-direction: column; gap: 9px; }
      .bat-sect-t { font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-mid); }
      .bat-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 0 18px; }
      .metric { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
      .metric .m-k { color: var(--ink-mid); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .metric .m-v { flex-shrink: 0; font-size: 14px; }
      /* clickable values open HA more-info (history graph) */
      .clickable { cursor: pointer; }
      .metric.clickable:hover .m-v { color: var(--accent); }
      .bat-pwr.clickable:hover .bat-pwr-val { color: var(--accent); }
      .bat-cap.clickable:hover { color: var(--ink); }
      .daily-row.clickable:hover .daily-head .muted { color: var(--ink); }
      .ring.clickable:hover { filter: brightness(1.08); }
      .ring-sub.clickable:hover { color: var(--ink); }
      .statblock.clickable:hover .stat-value { filter: brightness(1.12); }
      .scene-lbl.clickable { pointer-events: auto; }
      .scene-lbl.clickable:hover .lbl-val { filter: brightness(1.15); }
      .diag-cell.clickable:hover .diag-cell-label { color: var(--ink); }
      .bat-mppt-chips { display: flex; flex-wrap: wrap; gap: 7px; }
      .mppt-chip { font-size: 11.5px; }
      .bat-info { border-top: 1px solid var(--line); padding-top: 10px; }
      .bat-info > summary { cursor: pointer; font-size: 12px; color: var(--ink-mid); font-weight: 600; list-style: none; display: flex; align-items: center; gap: 7px; }
      .bat-info > summary::-webkit-details-marker { display: none; }
      .bat-info > summary::before { content: "▸"; color: var(--ink-dim); transition: transform 0.2s; }
      .bat-info[open] > summary::before { transform: rotate(90deg); }
      .bat-info-grid { display: flex; flex-direction: column; gap: 5px; margin-top: 10px; }
      .info-row { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px; }
      .info-row span:first-child { white-space: nowrap; }
      .info-row span:last-child { font-variant-numeric: tabular-nums; color: var(--ink); text-align: right; word-break: break-all; }
      .bat-info > summary ha-icon { color: var(--ink-dim); --mdc-icon-size: 16px; }
      .m-tag { font-size: 9px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-dim); background: var(--bg-2); border: 1px solid var(--line); border-radius: 5px; padding: 1px 4px; margin-left: 5px; vertical-align: middle; font-family: var(--font-ui); }

      /* per-battery controls — 2-col grid so labels and controls align across
         rows and every slider/select gets the same width */
      .bat-ctl-grid { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 12px 14px; align-items: center; margin-top: 12px; }
      .ctl-k { display: inline-flex; align-items: center; gap: 7px; color: var(--ink-mid); font-size: 13px; --mdc-icon-size: 16px; white-space: nowrap; }
      .ctl-k ha-icon { color: var(--ink-dim); flex-shrink: 0; }
      .ctl-empty { grid-column: 1 / -1; font-size: 12px; line-height: 1.45; }
      .ctl-toggle { justify-self: start; position: relative; width: 40px; height: 22px; border-radius: 999px; border: 1px solid var(--line-strong); background: var(--bg-2); cursor: pointer; padding: 0; transition: background 0.2s, border-color 0.2s; }
      .ctl-toggle .ctl-knob { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--ink-dim); transition: transform 0.2s, background 0.2s; }
      .ctl-toggle.on { background: var(--accent-soft); border-color: var(--accent-line); }
      .ctl-toggle.on .ctl-knob { transform: translateX(18px); background: var(--accent); }
      .ctl-select { width: 100%; font-family: var(--font-ui); font-size: 13px; color: var(--ink); background: var(--bg-2); border: 1px solid var(--line-strong); border-radius: 9px; padding: 5px 8px; cursor: pointer; }
      .ctl-num { display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0; }
      .ctl-num input[type="range"] { flex: 1 1 auto; accent-color: var(--accent); cursor: pointer; min-width: 0; }
      .ctl-num .ctl-val { font-family: var(--font-display); font-variant-numeric: tabular-nums; font-size: 13px; color: var(--ink); white-space: nowrap; min-width: 56px; text-align: right; }
      .ctl-btn { grid-column: 1 / -1; display: inline-flex; align-items: center; justify-content: center; gap: 7px; width: 100%; padding: 8px 12px; border-radius: 11px; border: 1px solid var(--line-strong); background: var(--bg-2); color: var(--ink-mid); font-family: var(--font-ui); font-weight: 600; font-size: 13px; cursor: pointer; --mdc-icon-size: 16px; transition: background 0.15s, color 0.15s; }
      .ctl-btn:hover { background: var(--bg-hover); color: var(--ink); }
      @media (max-width: 480px) { .bat-grid { grid-template-columns: 1fr; } }

      /* ===== Control tab ===== */
      /* feature-grouped cards; pack into columns on wide screens (align-items:start
         so a tall section, e.g. PD, doesn't stretch its neighbours) */
      /* Control layout: a flex row of blocks. .sys-col is an independent
         vertical stack (cards pack tight, no shared heights). .sys-pair is a
         2-col grid whose rows DO share a height (align-items: stretch), so the
         first two columns line up card-for-card row by row. */
      .sys-stack { display: flex; gap: var(--gap); align-items: flex-start; }
      .sys-col { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: var(--gap); }
      .sys-pair { flex: 2 1 0; min-width: 0; display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); align-items: stretch; align-content: start; }
      .sys-pair > .card { height: 100%; }
      .sys-pair-spacer { min-width: 0; }
      .sys-stack > .placeholder { flex: 1 1 100%; }
      .sys-stack .card-head { margin-bottom: 0; }
      .sys-grid { margin-top: 14px; }
      /* label with a tap/hover detail popover (e.g. time-slot details) */
      .ctl-k-info { cursor: pointer; }
      .ctl-k-info > span { text-decoration: underline dotted var(--ink-dim); text-underline-offset: 3px; }
      .info-pop { position: fixed; z-index: 60; display: none; max-width: 340px; padding: 10px 12px;
        border-radius: var(--radius-sm); background: var(--bg-2); border: 1px solid var(--line-strong);
        color: var(--ink); font-family: var(--font-ui); font-size: 12px; line-height: 1.5; white-space: pre-line;
        box-shadow: 0 8px 24px oklch(0 0 0 / 0.4); }
      @media (max-width: 1200px) { .sys-stack { flex-wrap: wrap; } .sys-col { flex: 1 1 340px; } .sys-pair { flex: 1 1 700px; } }
      @media (max-width: 480px) { .sys-stack { flex-direction: column; } .sys-col { flex: none; } .sys-pair { flex: none; grid-template-columns: 1fr; } .sys-pair-spacer { display: none; } }

      @media (max-width: 720px) {
        .appbar { padding: 0 14px; gap: 14px; height: 60px; }
        .brand .btext { display: none; }
        .tab { padding: 0 12px; }
        .tab .tab-label { display: none; }
        .main { padding: 18px 14px 32px; }
      }
    `;
    return style;
  }
}

if (!customElements.get("marstek-venus-panel")) {
  customElements.define("marstek-venus-panel", MarstekVenusPanel);
}
