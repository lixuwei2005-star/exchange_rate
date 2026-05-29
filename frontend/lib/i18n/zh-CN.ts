/**
 * 用户可见字符串。所有 zh-CN 文案集中在这里（CLAUDE.md §1）。
 */
export const zhCN = {
  siteTitle: "CNY → MYR Rate",
  siteTitleFull: "CNY → MYR Rate · rate.005917.xyz",
  siteTagline: "在马来西亚换汇，看哪家最划算。",
  comingSoon: "敬请期待",

  // Hero
  heroPrefix: "1 MYR =",
  heroSuffix: "CNY",
  heroTooltip: "中间价为理论参考，不可直接换汇",
  midmarketLabel: "中间市场汇率",

  // Amount input
  amountLabel: "我有",
  amountUnit: "CNY",
  amountSuffix: "，能换多少 MYR？",

  // Pure rate comparison (above the detailed table)
  rateOnlyTitle: "提供商 / Provider",
  rateOnlyHint: "仅展示各渠道汇率，不包含手续费等额外成本。",

  // Channel table
  tableHeaderChannel: "渠道",
  tableHeaderRate: "汇率（1 MYR = X CNY）",
  tableHeaderReceive: "你能拿到 (MYR)",
  tableHeaderUpdated: "最后更新",
  updatedAtPrefix: "更新于",
  unavailable: "暂时不可用",

  // Times
  justNow: "刚刚",
  minutesAgo: "分钟前",
  hoursAgo: "小时前",
  daysAgo: "天前",

  // Chart
  chartTitleIntraday: "实时趋势",
  chartSourceWise: "数据源：Wise",
  unitHour: "小时",
  chartTitle: "近 30 日趋势",
  chartTitleYear: "近一年趋势",
  chartSource: "数据源：银联国际",
  chartUnit: "1 MYR = X CNY",
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
