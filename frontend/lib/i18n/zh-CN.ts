/**
 * 用户可见字符串。所有 zh-CN 文案集中在这里（CLAUDE.md §1）。
 */
export const zhCN = {
  siteTitle: "汇率对比 · rate.005917.xyz",
  siteTagline: "为在马来西亚的中国留学生，比较 CNY → MYR 的换汇方案",
  comingSoon: "敬请期待",

  // Hero
  heroPrefix: "1 MYR =",
  heroSuffix: "CNY",
  heroTooltip: "中间价为理论参考，不可直接换汇",
  midmarketLabel: "中间价（参考）",

  // Amount input
  amountLabel: "我有",
  amountUnit: "CNY",
  amountSuffix: "，能换多少 MYR？",

  // Channel table
  tableHeaderChannel: "渠道",
  tableHeaderRate: "汇率（1 MYR = X CNY）",
  tableHeaderFee: "手续费",
  tableHeaderReceive: "你能拿到 (MYR)",
  tableHeaderUpdated: "更新于",
  unavailable: "暂时不可用",
  feeBOC: "约 50 CNY",
  feeMaybank: "约 10 MYR",
  feeCIMB: "约 10 MYR",
  feeNone: "—",
  feeNetworkMarkup: "已含 ~2% 网络加价",
  feeWise: "动态（见 Wise）",

  // Times
  justNow: "刚刚",
  minutesAgo: "分钟前",
  hoursAgo: "小时前",
  daysAgo: "天前",

  // Chart
  chartTitle: "近 30 日趋势",
  chartUnit: "MYR / 1 CNY",
  noHistoryData: "暂无历史数据",

  // Footer
  disclaimer:
    "本站汇率数据仅供参考，实际换汇以各渠道实时报价为准。本站不构成任何金融建议，不推荐特定换汇渠道。",
  dataSourcesLabel: "数据来源",
  lastUpdatedPrefix: "数据更新于",
  dataDelayedBanner: "数据更新延迟，以下为最近一次成功获取的数据。",

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
