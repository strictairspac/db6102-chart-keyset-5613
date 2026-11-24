import { api } from "../api/workbench.js";
import { errorText, field } from "./common/fields.js";
import { empty } from "./common/panel.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";

// 勘误簿在线原件：改签发日、撤回原件、补录旧件/签发新件（写操作按既有 RBAC 仅操作员）。
// 已经开批的批次持有独立快照，这里的任何写入都不会改动那些批次。
export async function errataBookSection(user) {
  const canEdit = user?.role === "operator";
  const feedback = el("p", {role: "status", class: "feedback", "data-testid": "errata-feedback"});
  const body = el("div", {"data-testid": "errata-book-body"}, el("p", {class: "empty"}, "勘误簿载入中…"));

  async function load() {
    try {
      const notices = await api.notices(true);
      body.replaceChildren(notices.length ? bookTable(notices) : empty("勘误簿还是空的，先补录一件。"));
    } catch (error) {
      body.replaceChildren(el("p", {role: "alert"}, `勘误簿载入失败：${error.message}`));
    }
  }

  function bookTable(notices) {
    const headings = canEdit
      ? ["流水号", "签发日（可改）", "海图", "勘误原文", "状态", "操作"]
      : ["流水号", "签发日", "海图", "勘误原文", "状态"];
    return el("div", {class: "table-scroll", tabindex: "0", "aria-label": "勘误簿", role: "region",
      "data-testid": "errata-book"},
      el("table", {},
        el("thead", {}, el("tr", {}, headings.map(h => el("th", {scope: "col"}, h)))),
        el("tbody", {}, notices.map(row => {
          const cells = [
            el("td", {}, el("strong", {}, String(row.seq))),
          ];
          if (canEdit) {
            const dateInput = el("input", {
              type: "date", name: "issue_date", value: row.issue_date,
              "aria-label": `修改 ${row.seq} 签发日`, "data-testid": `date-input-${row.seq}`,
            });
            const saveDate = el("button", {
              type: "button", class: "quiet", "data-testid": `save-date-${row.seq}`,
              onclick: async () => {
                saveDate.disabled = true;
                feedback.textContent = "";
                try {
                  await api.updateNotice(row.seq, {issue_date: dateInput.value});
                  feedback.textContent = `流水 ${row.seq} 的签发日已改为 ${dateInput.value}；已开批次仍保留开批时日期。`;
                  await load();
                } catch (error) {
                  feedback.textContent = error.message;
                  saveDate.disabled = false;
                }
              },
            }, "改签发日");
            const withdraw = el("button", {
              type: "button", class: "quiet", "data-testid": `withdraw-${row.seq}`,
              onclick: async () => {
                withdraw.disabled = true;
                feedback.textContent = "";
                try {
                  if (row.withdrawn) await api.restoreNotice(row.seq);
                  else await api.withdrawNotice(row.seq);
                  feedback.textContent = row.withdrawn ? `流水 ${row.seq} 已恢复。` : `原件 ${row.seq} 已撤回；已开批次仍保留该件原文。`;
                  await load();
                } catch (error) {
                  feedback.textContent = error.message;
                  withdraw.disabled = false;
                }
              },
            }, row.withdrawn ? "恢复原件" : "撤回原件");
            cells.push(el("td", {}, dateInput, saveDate));
            cells.push(el("td", {}, row.chart));
            cells.push(el("td", {}, row.notice));
            cells.push(el("td", {}, row.withdrawn ? el("span", {class: "status state-failed"}, "已撤回") :
              el("span", {class: "status state-done"}, "在簿")));
            cells.push(el("td", {class: "row-actions"}, withdraw));
          } else {
            cells.push(el("td", {}, row.issue_date));
            cells.push(el("td", {}, row.chart));
            cells.push(el("td", {}, row.notice));
            cells.push(el("td", {}, row.withdrawn ? el("span", {class: "status state-failed"}, "已撤回") :
              el("span", {class: "status state-done"}, "在簿")));
          }
          return el("tr", {"data-seq": row.seq, "data-withdrawn": row.withdrawn ? "true" : "false"}, ...cells);
        }))));
  }

  const today = new Date().toISOString().slice(0, 10);
  const seqInput = el("input", {name: "seq", type: "number", min: "1", max: "2147483647", required: true,
    placeholder: "如 108", "data-testid": "notice-seq"});
  const dateField = el("input", {name: "issue_date", type: "date", required: true, value: today,
    "data-testid": "notice-date"});
  const chartField = el("input", {name: "chart", maxlength: "24", required: true, placeholder: "如 CN-12311",
    "data-testid": "notice-chart"});
  const textField = el("input", {name: "notice", maxlength: "140", required: true, placeholder: "勘误内容",
    "data-testid": "notice-text"});
  const form = el("form", {id: "notice-form", "data-testid": "notice-form"},
    el("div", {class: "notice-form-grid"},
      field("收录流水号", seqInput),
      field("签发日（补录旧件可选过去日期）", dateField),
      field("海图编号", chartField),
      field("勘误原文", textField)),
    errorText(),
    el("div", {class: "button-row"},
      el("button", {type: "submit", "data-testid": "add-notice"}, "补录旧件 / 签发新件")));
  submit(form, async values => {
    feedback.textContent = "";
    try {
      await api.createNotice({
        seq: Number(values.get("seq")),
        issue_date: values.get("issue_date"),
        chart: values.get("chart"),
        notice: values.get("notice"),
      });
      form.reset();
      dateField.value = today;
      feedback.textContent = "已写入勘误簿；它不会混入此前已开的批次。";
      await load();
    } catch (error) {
      form.querySelector("[role=alert]").textContent = error.message;
    }
  });

  await load();
  return el("section", {class: "panel errata-panel", "data-testid": "errata-panel"},
    el("h2", {}, "勘误簿 · 签发与收录原件"),
    el("p", {class: "panel-hint"}, "这里可随时改签发日、撤回原件或补录旧件；开批时已把原文和顺序冻结进对应交班批，翻页领取不受影响，也不必等谁领完。"),
    feedback, body,
    canEdit ? form : el("p", {class: "empty", "data-testid": "errata-readonly-hint"},
      "当前账号为只读角色：勘误簿的改签发日、撤回与补录由资料操作员执行；任何角色都可开批、翻页领取与查看核收单。"));
}
