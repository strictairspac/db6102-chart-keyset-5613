import { api } from "../api/workbench.js";
import { errorText, field } from "./common/fields.js";
import { empty } from "./common/panel.js";
import { submit } from "../hooks/submit.js";
import { selectedBatchId, setSelectedBatchId } from "../stores/handover.js";
import { el } from "../utils/dom.js";
import { fullTime, isoTime, time } from "../utils/format.js";

function batchStatus(batch) {
  return el("span", {
    class: `status state-${batch.status}`,
    "data-testid": "batch-status",
    "data-state": batch.status,
  }, batch.completed ? "已领完" : "领件中");
}

function pageTable(page) {
  if (!page?.items?.length) return empty("这一页没有记录。");
  return el("div", {class: "table-scroll", tabindex: "0", "aria-label": "本批冻结页", role: "region",
    "data-testid": "page-items"},
    el("table", {},
      el("thead", {}, el("tr", {},
        ["页内名次", "流水号", "签发日", "海图", "勘误原文（开批时原文）"].map(h => el("th", {scope: "col"}, h)))),
      el("tbody", {}, page.items.map((item, index) => el("tr", {
        "data-seq": item.seq, "data-position": item.position,
      },
        el("td", {}, String(index + 1)),
        el("td", {}, el("strong", {}, String(item.seq))),
        el("td", {}, item.issue_date),
        el("td", {}, item.chart),
        el("td", {}, item.notice))))));
}

export async function handoverWorkspace(user) {
  const state = {
    batches: [],
    selectedId: selectedBatchId(),
    detail: null,
    page: null,
    lastCredential: null,
    mineOnly: false,
    loading: false,
  };

  const globalNote = el("p", {role: "status", class: "feedback", "data-testid": "workspace-note"});
  const listWrap = el("div", {"data-testid": "batch-list-wrap"}, el("p", {class: "empty"}, "批次载入中…"));
  const detailWrap = el("div", {"data-testid": "batch-detail-wrap"});

  // ------------------------------------------------------------ batch list
  function renderList() {
    const rows = state.batches
      .filter(batch => !state.mineOnly || batch.owner === user.username)
      .map(batch => el("tr", {
        "data-batch-id": batch.id,
        "data-owner": batch.owner,
        "aria-current": batch.id === state.selectedId ? "true" : null,
      },
        el("td", {}, el("code", {}, batch.code)),
        el("td", {}, batch.owner, batch.owner === user.username ? el("span", {class: "tag"}, "我") : null),
        el("td", {}, `${batch.claimed_count}/${batch.total} 件 · ${batch.claimed_pages}/${batch.total_pages} 页`),
        el("td", {}, batchStatus(batch)),
        el("td", {}, time(batch.created_at)),
        el("td", {}, batch.completed_at ?
          el("time", {datetime: isoTime(batch.completed_at), title: fullTime(batch.completed_at),
            "data-testid": `row-completed-${batch.id}`}, time(batch.completed_at)) : "—"),
        el("td", {}, el("button", {
          type: "button", class: "quiet", "data-testid": `open-batch-${batch.id}`,
          onclick: () => selectBatch(batch.id),
        }, batch.id === state.selectedId ? "当前批" : "打开 / 续领"))));

    listWrap.replaceChildren(state.batches.length ?
      el("div", {class: "table-scroll", tabindex: "0", "aria-label": "交班批次", role: "region",
        "data-testid": "batch-list"},
        el("table", {},
          el("thead", {}, el("tr", {},
            ["批号", "交班员", "进度", "状态", "开批时间", "领完时间", "操作"].map(h => el("th", {scope: "col"}, h)))),
          el("tbody", {}, rows))) :
      empty("还没有交班批，先在上方开批。"));
  }

  async function loadBatches(preferId) {
    state.batches = await api.batches();
    if (preferId && state.batches.some(b => b.id === preferId)) state.selectedId = preferId;
    if (!state.selectedId || !state.batches.some(b => b.id === state.selectedId)) {
      state.selectedId = state.batches[0]?.id ?? null;
    }
    setSelectedBatchId(state.selectedId);
    renderList();
    if (state.selectedId) await selectBatch(state.selectedId);
    else detailWrap.replaceChildren(empty("开批后，这里会显示冻结的第一页、翻页凭据和领取进度。"));
  }

  // ------------------------------------------------------------ selection
  async function selectBatch(id) {
    state.selectedId = id;
    setSelectedBatchId(id);
    state.page = null;
    state.lastCredential = null;
    globalNote.textContent = "";
    renderList();
    detailWrap.replaceChildren(el("p", {class: "empty"}, "正在读取批次与进度…"));
    try {
      const receipt = await api.receipt(id);
      state.detail = receipt;
      const lastTurn = receipt.turns?.[receipt.turns.length - 1];
      if (lastTurn) {
        state.lastCredential = lastTurn.credential;
        state.page = receipt.pages.find(p => p.page_no === lastTurn.page_no) ?? null;
        state.page = state.page ? {...state.page, credential: lastTurn.credential, historical: true} : null;
      }
      renderDetail();
    } catch (error) {
      detailWrap.replaceChildren(el("p", {role: "alert"}, `批次读取失败：${error.message}`));
    }
  }

  // ------------------------------------------------------------ claiming
  async function claim(credential, {fault = false} = {}) {
    if (!credential || state.loading) return;
    state.loading = true;
    // 关键：失败时“原凭据”就是本次发出的这一个，必须立刻记下，
    // 不能等成功响应才更新，否则出错后重试会错用上一页凭据。
    state.lastCredential = credential;
    renderDetail();
    globalNote.textContent = "";
    try {
      const payload = await api.claim(state.selectedId, {credential, simulate_failure: fault || undefined});
      state.detail = {...state.detail, ...payload};
      state.page = payload;
      state.lastCredential = payload.credential || credential;
      if (payload.replayed) {
        globalNote.textContent =
          `已用原凭据重放第 ${payload.page_no} 页（第 ${payload.replay_count} 次重试）：这一页与首次返回完全一致，进度没有多记一页。`;
      }
      await refreshListQuiet();
    } catch (error) {
      // 最关键的容错：请求失败不换凭据、不臆造进度；提示用原凭据重试，
      // 并从数据库拉回真实进度（服务端可能在响应丢失前已经记账）。
      globalNote.textContent =
        `翻页失败：${error.message} 请直接点“用原凭据重试”，凭据不变、不会多记一页。`;
      try {
        const fresh = await api.batch(state.selectedId);
        state.detail = {...state.detail, ...fresh};
      } catch { /* 保留旧视图，重试仍可进行 */ }
    } finally {
      state.loading = false;
      renderDetail();
      renderList();
    }
  }

  async function refreshListQuiet() {
    try {
      state.batches = await api.batches();
    } catch { /* 列表稍后随刷新恢复 */ }
  }

  // ------------------------------------------------------------ detail view
  function renderDetail() {
    const d = state.detail;
    if (!d) {
      detailWrap.replaceChildren(empty("开批后，这里会显示冻结页、凭据与进度。"));
      return;
    }
    const percent = d.progress?.percent ?? (d.total ? Math.round(100 * d.claimed_count / d.total) : 100);
    const done = d.status === "completed" || d.completed;
    const nextCredential = d.next_credential;
    const faultToggle = el("input", {type: "checkbox", "data-testid": "fault-toggle",
      "aria-label": "模拟下一次翻页失败"});

    const nextLabel = done ? "本批已领完"
      : state.loading ? "翻页中…"
      : nextCredential ? `翻页 · 领下一页（第 ${d.claimed_pages + 1}/${d.total_pages} 页）`
      : "没有更多页";
    const claimNext = el("button", {
      type: "button", "data-testid": "claim-next",
      disabled: done || state.loading || !nextCredential,
      onclick: () => claim(nextCredential, {fault: faultToggle.checked}),
    }, nextLabel);

    const retry = el("button", {
      type: "button", class: "quiet", "data-testid": "retry-credential",
      disabled: !state.lastCredential || state.loading,
      onclick: () => claim(state.lastCredential),
    }, "用原凭据重试本页");

    detailWrap.replaceChildren(
      el("div", {class: "batch-detail", "data-testid": "batch-detail", "data-batch-id": d.id},
        el("div", {class: "batch-meta"},
          el("div", {}, el("h3", {}, el("code", {}, d.code)),
            el("p", {class: "muted"}, `交班员：${d.owner} · 每页 ${d.page_size} 件 · 来源：${d.source || "勘误簿开批快照"}`)),
          batchStatus(d)),
        el("div", {"data-testid": "progress", "aria-live": "polite"},
          el("strong", {}, "已领 ",
            el("span", {"data-testid": "claimed-count"}, String(d.claimed_count)), "/",
            el("span", {"data-testid": "total-count"}, String(d.total)),
            ` 件 · 进度第 ${d.claimed_pages}/${d.total_pages} 页`),
          el("div", {
            class: "progress-track", role: "progressbar",
            "aria-valuemin": "0", "aria-valuemax": d.total, "aria-valuenow": d.claimed_count,
            "data-testid": "progress-bar",
          }, el("div", {class: "progress-fill", style: `width:${percent}%`}))),
        done ? el("div", {class: "completion-banner", "data-testid": "completion-banner"},
          el("h3", {"data-testid": "batch-done"}, "✓ 本批已全部领完"),
          el("div", {"data-testid": "finished-at"},
            el("p", {}, "核收完成时间（服务端持久化，重启不丢）："),
            el("time", {class: "completed-time", "data-testid": "completed-at",
              datetime: isoTime(d.completed_at), "data-completed-at": d.completed_at || ""},
              `领完时间：${fullTime(d.completed_at)}`)),
          el("a", {class: "button quiet", href: "#evidence", "data-testid": "goto-receipt"}, "前往勘误核收单")) : null,
        el("div", {class: "credential-row"},
          el("div", {class: "credential-box"},
            el("span", {class: "field-label"}, "本页原凭据（重试必须用它）"),
            el("code", {"data-testid": "credential"}, state.lastCredential || "领取第一页后生成")),
          nextCredential ? el("div", {class: "credential-box"},
            el("span", {class: "field-label"}, "下一页凭据"),
            el("code", {"data-testid": "next-credential"}, nextCredential)) : null),
        el("div", {class: "button-row claim-actions"}, claimNext, retry,
          el("label", {class: "fault-toggle"}, faultToggle, "模拟下一次翻页失败（服务端已记账但响应丢失）")),
        state.page?.historical ? el("p", {class: "muted"},
          `这是上次领到的第 ${state.page.page_no} 页；服务重启或隔天打开都可凭原凭据重领，进度不变。`) : null,
        pageTable(state.page),
        el("p", {}, el("a", {href: "#evidence"}, "在勘误核收单中查看本批冻结清单、凭据记录与领完时间 →"))));
  }

  // ------------------------------------------------------------ open form
  const sizeInput = el("input", {
    name: "page_size", type: "number", min: "1", max: "500", required: true, value: "2",
    "data-testid": "open-page-size", "aria-label": "每页条数",
  });
  const openForm = el("form", {id: "open-batch-form", "data-testid": "open-batch-form"},
    el("div", {class: "open-form-row"},
      field("每页条数", sizeInput, "开批后按这个条数固定分页。"),
      el("button", {type: "submit", "data-testid": "open-batch"}, "开批")),
    errorText());
  submit(openForm, async values => {
    globalNote.textContent = "";
    const batch = await api.openBatch({page_size: Number(values.get("page_size")) || 2});
    setSelectedBatchId(batch.id);
    state.selectedId = batch.id;
    await loadBatches(batch.id);
    globalNote.textContent = `已开批 ${batch.code}：开批时勘误簿 ${batch.total} 件的原文与顺序已冻结，之后勘误簿写入不影响本批。`;
  });

  const mineToggle = el("input", {type: "checkbox", "data-testid": "mine-only"});
  mineToggle.addEventListener("change", () => {
    state.mineOnly = mineToggle.checked;
    renderList();
  });

  try {
    await loadBatches();
  } catch (error) {
    listWrap.replaceChildren(el("p", {role: "alert"},
      `交班批次暂时载入失败：${error.message}。仍可开批，或稍后刷新续领。`));
    detailWrap.replaceChildren(empty("批次进度暂时不可用，请稍后刷新；进度已持久化在服务端。"));
  }

  return el("section", {class: "panel handover-panel", "data-testid": "handover-workspace"},
    el("div", {class: "handover-heading"},
      el("h2", {}, "勘误交班 · 开批取件"),
      el("label", {class: "mine-toggle"}, mineToggle, "只看我的批次")),
    el("p", {class: "panel-hint"},
      `当前交班员：${user.username}（${user.role}）。两位交班员可分别登录、各自开批，进度按批独立持久化；翻页失败后用原凭据重试，返回同一页且进度不多记一页；服务重启或隔天仍可续领。`),
    openForm,
    globalNote,
    el("h3", {}, "交班批次与各自进度"),
    listWrap,
    el("h3", {}, "翻页领取台"),
    detailWrap);
}
