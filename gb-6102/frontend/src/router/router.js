const routes = ["overview", "cases", "runs", "evidence"];

// 兼容验收/参考书里可能出现的近义 hash：都落到包含对应能力的现有页面。
const aliases = {
  handover: "overview", shift: "overview", jiaoban: "overview", "open-batch": "overview",
  notices: "cases", errata: "cases", bulletin: "cases", bulletins: "cases", book: "cases",
  "errata-book": "cases", publish: "cases",
  replay: "runs", strategy: "runs", pagination: "runs",
  receipt: "evidence", receipts: "evidence", acceptance: "evidence", verify: "evidence",
  check: "evidence",核收: "evidence", "handover-receipt": "evidence",
};

export function activeRoute() {
  const raw = (location.hash.slice(1) || "overview");
  const [segment, idPart] = raw.split("/");
  const name = routes.includes(segment) ? segment : (aliases[segment] || "overview");
  const exactId = /^\d+$/.test(idPart || "") ? Number(idPart) : null;
  const embedded = exactId ?? ((/(\d+)/.exec(idPart || "") || [])[1]);
  const numericId = embedded == null ? null : Number(embedded);
  // 近义核收/交班深链（如 #receipt/3、#handover/hb-3）顺带选中对应交班批；
  // 标准 #evidence/5、#runs/5 是回放执行批次号，不在 aliases 中，不会误写。
  if (numericId && aliases[segment] &&
      (aliases[segment] === "evidence" || aliases[segment] === "overview")) {
    try { sessionStorage.setItem("handover-selected-batch", String(numericId)); } catch { /* 忽略存储异常 */ }
  }
  return {name, id: exactId, param: idPart || null};
}

export function navigate(route) {
  location.hash = route;
}

export { routes };
