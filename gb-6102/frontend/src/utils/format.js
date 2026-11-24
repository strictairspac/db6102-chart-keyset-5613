const date = new Intl.DateTimeFormat("zh-CN", {dateStyle: "short", timeStyle: "short"});
const full = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

export function time(seconds) {
  return seconds ? date.format(new Date(seconds * 1000)) : "—";
}

// 核收页“领完时间”需要精确到秒、且始终能看到年月日。
export function fullTime(seconds) {
  return seconds ? full.format(new Date(seconds * 1000)) : "尚未领完";
}

export function isoTime(seconds) {
  return seconds ? new Date(seconds * 1000).toISOString() : null;
}

export function cell(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

export async function download(response, filename) {
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

// 直接把 JSON 对象存成核收文件（交班核收单导出）。
export function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
