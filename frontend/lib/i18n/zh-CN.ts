/**
 * 用户可见字符串。所有 zh-CN 文案集中在这里（CLAUDE.md §1）。
 * 后续 phase 直接往这里加 key，组件里不再硬编码。
 */
export const zhCN = {
  siteTitle: "汇率对比 · rate.005917.xyz",
  siteTagline: "为在马来西亚的中国留学生，比较 CNY → MYR 的换汇方案",
  comingSoon: "敬请期待",

  // §13 disclaimer — required visible in footer at all times.
  disclaimer:
    "本站汇率数据仅供参考，实际换汇以各渠道实时报价为准。本站不构成任何金融建议，不推荐特定换汇渠道。",
  dataSourcesLabel: "数据来源",
  lastUpdatedPrefix: "数据更新于",
  unavailable: "暂时不可用",

  // Admin
  adminLogin: "管理员登录",
  username: "用户名",
  password: "密码",
  loginButton: "登录",
  logoutButton: "登出",
  adminDashboardTitle: "管理后台",
  loginFailed: "登录失败，请检查用户名或密码",
  loadingDots: "...",
} as const;

export type I18nKey = keyof typeof zhCN;
