import { api } from "../api/workbench.js";
import { handoverReceipt } from "../components/handover-receipt.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { resultTable } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";
import { cell, download, time } from "../utils/format.js";

function reviewForm(id, saved) {
  const form = el("form", {id: "review-form"},
    field("复核意见", el("textarea", {name: "note", required: true, minlength: 3, maxlength: 500, rows: 3})),
    errorText(), el("button", {type: "submit"}, "签署复核"));
  submit(form, async values => saved(await api.submitReview(id, {note: values.get("note")})));
  return form;
}

function signature(review) {
  return el("div", {"data-testid": "reviewed", class: "signature"},
    el("strong", {}, `已签署 · ${review.actor}`), el("p", {}, review.note), el("time", {}, time(review.created_at)));
}

// 原“翻页回放”执行批次的证据与复核，保留在交班核收单下方。
async function runEvidence(config, user, route) {
  const runs = (await api.runs().catch(() => [])).filter(item => item.status === "done");
  const run = route.id ? await api.run(route.id).catch(() => null) : runs[0];
  if (!run?.result) {
    return [
      empty("成功执行一个批次后可以查看、签核和下载证据。"),
      el("p", {}, el("a", {href: "#runs"}, config.modules[2]))];
  }

  const review = await api.review(run.id).catch(() => null);
  const issue = errorText();
  const button = el("button", {type: "button", onclick: async () => {
    button.disabled = true;
    issue.textContent = "";
    try {
      await download(await api.export(run.id), `evidence-${run.id}.json`);
    } catch (error) {
      issue.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }}, "导出证据");
  const signing = el("div", {});
  signing.append(review ? signature(review) : user.role === "reviewer" ?
    reviewForm(run.id, data => signing.replaceChildren(signature(data))) : empty("待复核员签署。"));
  const options = el("select", {"aria-label": "选择已完成的回放批次", onchange: event => {
    location.hash = `evidence/${event.target.value}`;
  }}, runs.map(item => el("option", {value: item.id, selected: item.id === run.id}, `#${item.id} ${item.case_title}`)));
  return [
    options,
    el("section", {class: "feature evidence-summary"}, el("div", {}, el("h2", {}, "回放批次判定"), el("p", {}, run.result.summary)),
      el("details", {}, el("summary", {}, "证据摘要"), el("code", {}, run.digest))),
    el("dl", {class: "metrics"}, Object.entries(run.result.metrics).map(([label, value]) =>
      el("div", {}, el("dt", {}, label), el("dd", {}, cell(value))))),
    section("业务结果明细", run.result.rows.length ? resultTable(run.result.rows) : empty("此批次无明细。")),
    section("复核签署", signing),
  ];
}

export async function evidencePage(config, user, route) {
  const receipt = await handoverReceipt();
  const runBlocks = await runEvidence(config, user, route);
  return el("div", {class: "page evidence", "data-testid": "evidence-page"},
    pageHeading(config.modules[3], "交班批核收：开批冻结清单、领取进度与领完时间"),
    receipt,
    el("h2", {class: "subheading"}, "翻页策略回放核收"),
    ...(Array.isArray(runBlocks) ? runBlocks : [runBlocks]));
}
