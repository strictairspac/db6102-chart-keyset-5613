const KEY = "handover-selected-batch";

export function selectedBatchId() {
  const value = Number(sessionStorage.getItem(KEY) || "");
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function setSelectedBatchId(id) {
  if (id) sessionStorage.setItem(KEY, String(id));
  else sessionStorage.removeItem(KEY);
}
