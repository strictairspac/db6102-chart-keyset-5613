import { request } from "./http.js";

export const api = {
  config: () => request("/workbench"),
  login: data => request("/auth/login", {method: "POST", data}),
  cases: () => request("/cases"),
  createCase: data => request("/cases", {method: "POST", data}),
  runs: () => request("/runs"),
  run: (id, signal) => request(`/runs/${id}`, {signal}),
  enqueue: (id, data) => request(`/cases/${id}/runs`, {method: "POST", data}),
  review: id => request(`/runs/${id}/review`),
  submitReview: (id, data) => request(`/runs/${id}/review`, {method: "POST", data}),
  export: id => request(`/runs/${id}/export`, {raw: true}),
  audit: () => request("/audit", {signal: AbortSignal.timeout(5000)}),

  // 勘误簿（在线原件）
  notices: (includeWithdrawn = true) =>
    request(`/handover/notices?include_withdrawn=${includeWithdrawn ? "true" : "false"}`),
  createNotice: data => request("/handover/notices", {method: "POST", data}),
  updateNotice: (seq, data) => request(`/handover/notices/${seq}`, {method: "PATCH", data}),
  withdrawNotice: seq => request(`/handover/notices/${seq}`, {method: "DELETE"}),
  restoreNotice: seq => request(`/handover/notices/${seq}/restore`, {method: "POST", data: {}}),

  // 交班批 / 翻页凭据 / 核收单
  batches: () => request("/handover/batches"),
  batch: id => request(`/handover/batches/${id}`),
  openBatch: data => request("/handover/batches", {method: "POST", data}),
  claim: (id, data) => request(`/handover/batches/${id}/claim`, {method: "POST", data}),
  receipt: id => request(`/handover/batches/${id}/receipt`),
};
