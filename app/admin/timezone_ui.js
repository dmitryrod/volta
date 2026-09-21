/**
 * Глобальные часы админки Money Pulso: отображение времени в выбранной IANA-зоне.
 * Хранение: localStorage mp_admin_timezone. Сервер/API/БД без изменений (UTC).
 */
(function (global) {
  var LS_KEY = "mp_admin_timezone";
  var EV = "mp-admin-timezone-change";

  function validateTz(tz) {
    try {
      new Intl.DateTimeFormat(undefined, { timeZone: tz });
      return true;
    } catch (e) {
      return false;
    }
  }

  function getTimezone() {
    try {
      var v = global.localStorage.getItem(LS_KEY);
      if (v && validateTz(v)) return v;
    } catch (e) {}
    return "UTC";
  }

  function setTimezone(tz) {
    if (!validateTz(tz)) tz = "UTC";
    try {
      global.localStorage.setItem(LS_KEY, tz);
    } catch (e) {}
    global.dispatchEvent(new CustomEvent(EV, { detail: { timezone: tz } }));
  }

  function zonedParts(date, timeZone) {
    var f = new Intl.DateTimeFormat("en-US", {
      timeZone: timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
      hour12: false,
    });
    var parts = f.formatToParts(date);
    var o = {};
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p.type !== "literal") o[p.type] = p.value;
    }
    return o;
  }

  function pad2(x) {
    return String(x).padStart(2, "0");
  }

  function formatAxisLabel(isoOrTs, withSeconds) {
    var t = typeof isoOrTs === "number" ? isoOrTs : Date.parse(String(isoOrTs || ""));
    if (!Number.isFinite(t)) return String(isoOrTs || "");
    var d = new Date(t);
    var tz = getTimezone();
    var z = zonedParts(d, tz);
    var base = pad2(z.day) + "." + pad2(z.month) + " " + pad2(z.hour) + ":" + pad2(z.minute);
    if (withSeconds) base += ":" + pad2(z.second);
    return base;
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    var t = Date.parse(String(iso));
    if (!Number.isFinite(t)) return String(iso);
    var d = new Date(t);
    var tz = getTimezone();
    var z = zonedParts(d, tz);
    return (
      pad2(z.day) +
      "." +
      pad2(z.month) +
      "." +
      z.year +
      " " +
      pad2(z.hour) +
      ":" +
      pad2(z.minute) +
      ":" +
      pad2(z.second)
    );
  }

  function formatTime(iso) {
    if (!iso) return "";
    var t = Date.parse(String(iso));
    if (!Number.isFinite(t)) return String(iso);
    var d = new Date(t);
    var tz = getTimezone();
    var z = zonedParts(d, tz);
    return pad2(z.hour) + ":" + pad2(z.minute);
  }

  /** Компактная строка для таблицы аналитики (вместо сырого ISO). */
  function formatTriggerCompact(iso) {
    if (!iso) return "—";
    var t = Date.parse(String(iso));
    if (!Number.isFinite(t)) {
      return String(iso)
        .replace("T", " ")
        .replace(/Z|[+-]\d{2}:\d{2}$/, "");
    }
    var d = new Date(t);
    var tz = getTimezone();
    var z = zonedParts(d, tz);
    return (
      z.year +
      "-" +
      z.month +
      "-" +
      z.day +
      " " +
      z.hour +
      ":" +
      z.minute +
      ":" +
      z.second
    );
  }

  global.MpAdminTime = {
    LS_KEY: LS_KEY,
    EVENT_NAME: EV,
    validateTimezone: validateTz,
    getTimezone: getTimezone,
    setTimezone: setTimezone,
    formatAxisLabel: formatAxisLabel,
    formatDateTime: formatDateTime,
    formatTime: formatTime,
    formatTriggerCompact: formatTriggerCompact,
  };
})(typeof window !== "undefined" ? window : globalThis);
