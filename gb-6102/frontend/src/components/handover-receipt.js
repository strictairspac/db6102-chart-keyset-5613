import { api } from "../api/workbench.js";
import { empty } from "./common/panel.js";
import { selectedBatchId, setSelectedBatchId } from "../stores/handover.js";
import { el } from "../utils/dom.js";
import { downloadJson, fullTime, isoTime, time } from "../utils/format.js";

function completionBlock(receipt) {
  return el("div", {
    class: receipt.completed_at ? "completion-banner" : "completion-banner pending",
    "data-testid": "receipt-completion",
  },
    el("div", {},
      el("h3", {}, receipt.completed ? "本批已领完" : "本批仍在领取"),
      el("p", {"data-testid": "receipt-completed-at-label"},
        receipt.completed_at ? "领完时间（何时领完本批）" : "尚未领完，全部页领取后在此记录领完时间。")),
    receipt.completed_at
      ? el("div", {"data-testid": "finished-at"}, el("time", {
        class: "completed-time",
        "data-testid": "completed-at",
        datetime: isoTime(receipt.completed_at),
        "data-completed-at": receipt.completed_at,
      }, fullTime(receipt.completed_at)))
      : el("time", {class: "completed-time pending-time", "data-testid": "completed-at", datetime: ""}, "尚未领完"));
}

function frozenTable(items) {
  const head = el("thead", {}, el("tr", {},
    ["顺序", "页码", "流水号", "签发日", "海图", "勘误原文"].map(h => el("th", {scope: "col"}, h))));
  const body = el("tbody", {}, items.map((item, index) => el("tr", {"data-seq": item.seq},
    el("td", {}, String(index + 1)),
    el("td", {}, String(item.page_no)),
    el("td", {}, el("strong", {}, String(item.seq))),
    el("td", {}, item.issue_date),
    el("td", {}, item.chart),
    el("td", {}, item.notice))));
  return el("div", {class: "table-scroll", tabindex: "0", role: "region",
    "aria-label": "冻结核收清单", "data-testid": "receipt-items"},
    el("table", {}, head, body));
}

function turnsTable(turns) {
  const head = el("thead", {}, el("tr", {},
    ["页", "凭据", "重放次数", "首次领取时间"].map(h => el("th", {scope: "col"}, h))));
  const body = el("tbody", {}, turns.map(t => el("tr", {},
    el("td", {}, String(t.page_no ?? "—")),
    el("td", {}, el("code", {class: "credential-code", "data-credential": t.credential}, t.credential)),
    el("td", {}, String(t.replay_count)),
    el("td", {}, time(t.created_at)))));
  return el("div", {class: "table-scroll", tabindex: "0", role: "region",
    "aria-label": "翻页凭据记录", "data-testid": "receipt-turns"},
    el("table", {}, head, body));
}

// 勘误核收单：重点给出“本批什么时候领完”，并保留开批冻结顺序与翻页凭据记录。
export async function handoverReceipt() {
  const wrap = el("div", {"data-testid": "handover-receipt-wrap"}, el("p", {class: "empty"}, "交班核收单载入中…"));
  let batches = [];

  async function load(id) {
    try {
      const receipt = await api.receipt(id);
      setSelectedBatchId(receipt.id);
      render(receipt);
    } catch (error) {
      wrap.replaceChildren(el("p", {role: "alert"}, `核收单读取失败：${error.message}`));
    }
  }

  function render(receipt) {
    const selector = el("select", {
      "aria-label": "选择交班批核收单", "data-testid": "receipt-batch-select",
      onchange: event => load(Number(event.target.value)),
    }, batches.map(batch => el("option", {
      value: batch.id, selected: batch.id === receipt.id,
    }, `#${batch.id} ${batch.code} · ${batch.owner} · ${batch.completed ? "已领完" : "领件中"}`)));

    const exportButton = el("button", {
      type: "button", class: "quiet", "data-testid": "export-receipt",
      onclick: () => downloadJson(receipt, `handover-receipt-${receipt.code}.json`),
    }, "导出核收单 JSON");

    const children = [
      el("header", {class: "receipt-title"},
        el("div", {},
          el("h2", {}, `勘误核收单 ${receipt.code}`),
          el("p", {class: "muted", "data-testid": "receipt-owner"},
            `交班员：${receipt.owner} · 每页 ${receipt.page_size} 件 · 开批时间：${fullTime(receipt.created_at)}`)),
        el("span", {class: `status state-${receipt.status}`, "data-state": receipt.status,
          "data-testid": "receipt-status"}, receipt.completed ? "已领完" : "领件中")),
      completionBlock(receipt),
      el("dl", {class: "metrics receipt-metrics"},
        el("div", {}, el("dt", {}, "冻结总数"), el("dd", {}, String(receipt.total))),
        el("div", {}, el("dt", {}, "已核收"), el("dd", {"data-testid": "receipt-claimed"}, String(receipt.claimed_count))),
        el("div", {}, el("dt", {}, "页数进度"), el("dd", {}, `${receipt.claimed_pages}/${receipt.total_pages}`))),
      el("h3", {}, "开批时冻结的原文与顺序"),
      receipt.items.length ? frozenTable(receipt.items) : empty("此批为空簿开批。"),
      el("details", {},
        el("summary", {}, `翻页凭据与重试记录（${receipt.turns.length} 条）`),
        receipt.turns.length ? turnsTable(receipt.turns) : empty("尚未发生翻页领取。")),
    ];

    wrap.replaceChildren(
      el("div", {class: "receipt-head"}, selector, exportButton),
      el("section", {class: "panel receipt-panel", "data-testid": "handover-receipt", "data-batch-id": receipt.id},
        ...children));
  }

  try {
    batches = await api.batches();
  } catch (error) {
    wrap.replaceChildren(el("p", {role: "alert"}, `交班批载入失败：${error.message}`));
    return wrap;
  }
  if (!batches.length) {
    wrap.replaceChildren(el("section", {class: "panel"},
      el("h2", {}, "交班核收单"),
      empty("还没有交班批。先到“勘误交班”开批并翻页领取；领完后本页会显示领完时间。")));
    return wrap;
  }
  const preferred = selectedBatchId();
  const initial = batches.find(b => b.id === preferred)
    ?? batches.find(b => b.completed)
    ?? batches[0];
  await load(initial.id);
  return wrap;
}
