export type BudgetValue = 'MEDIUM' | 'HIGH' | 'ULTRA';

export const BUDGET_OPTIONS: { value: BudgetValue; label: string; caption: string }[] = [
  {
    value: 'MEDIUM',
    label: '基础',
    caption: '控制预算',
  },
  {
    value: 'HIGH',
    label: '进阶',
    caption: '均衡质量',
  },
  {
    value: 'ULTRA',
    label: '旗舰',
    caption: '质量优先',
  },
];
