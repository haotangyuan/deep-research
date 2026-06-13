export type BudgetValue = 'MEDIUM' | 'HIGH' | 'ULTRA';

export const BUDGET_OPTIONS: { value: BudgetValue; label: string; caption: string }[] = [
  {
    value: 'MEDIUM',
    label: '基础',
    caption: '2主题/2搜/并发1',
  },
  {
    value: 'HIGH',
    label: '进阶',
    caption: '4主题/3搜/并发2',
  },
  {
    value: 'ULTRA',
    label: '旗舰',
    caption: '6主题/4搜/并发3',
  },
];
