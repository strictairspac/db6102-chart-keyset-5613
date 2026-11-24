export const States = Object.freeze({
  queued: "等待执行", done: "已完成", failed: "执行失败",
  open: "领件中", completed: "已领完",
});

export const Actions = Object.freeze({
  create_case: "登记资料", enqueue: "提交执行", done: "执行完成", failed: "执行失败", review: "复核签署",
  handover_open: "开批", handover_claim: "翻页领取", handover_retry: "原凭据重试",
  notice_create: "补录/签发勘误", notice_upsert: "写入勘误", notice_edit: "改签发日",
  notice_withdraw: "撤回原件", notice_restore: "恢复原件", notice_reset: "重置勘误簿",
});

export const HandoverStatus = Object.freeze({open: "领件中", completed: "已领完"});
