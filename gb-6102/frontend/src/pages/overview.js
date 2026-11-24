import { api } from "../api/workbench.js";
import { errataBookSection } from "../components/errata-book.js";
import { handoverWorkspace } from "../components/handover-workspace.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { Actions } from "../constants/states.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

export async function overview(config, user) {
  const workspace = await handoverWorkspace(user);
  const errata = await errataBookSection(user);

  // 原有“翻页策略回放工作台”的概览信息保持可见，保留既有资料/执行/审计入口与文案。
  const [cases, runs, audit] = await Promise.all([
    api.cases().catch(() => []),
    api.runs().catch(() => []),
    api.audit().catch(() => []),
  ]);
  const latest = runs[0];

  return el("div", {class: "page overview", "data-testid": "overview-page"},
    pageHeading(config.modules[0], config.team, el("a", {class: "button", href: "#cases"}, config.modules[1])),
    workspace,
    errata,
    el("div", {class: "feature"},
      el("div", {}, el("h2", {}, config.title), el("p", {}, config.description)),
      el("aside", {}, el("h3", {}, config.direction), el("p", {}, config.mechanism))),
    el("div", {class: "split"},
      section(`现有${config.unit}`,
        cases.length ? table(["编号", "名称", "登记人"], cases.slice(0, 4).map(item => [item.code, item.title, item.created_by]), "近期资料") : empty("进入资料页登记第一条资料。")),
      section("最近执行", latest ?
        el("div", {class: "stack"}, status(latest.status), el("strong", {}, latest.case_title),
          el("a", {href: `#runs/${latest.id}`}, "查看执行进度")) :
        empty("选择演示资料并提交执行，此处会显示处理进度。"))),
    section("操作记录", audit.length ?
      table(["动作", "账号", "对象编号", "时间"], audit.slice(0, 8).map(item =>
        [Actions[item.action] || item.action, item.actor, item.entity_id, time(item.created_at)]), "审计操作记录") :
      empty("登记、执行与签核会留下操作记录。")));
}
