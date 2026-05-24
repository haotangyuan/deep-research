const DEFAULT_TIME_ZONE = 'Asia/Shanghai';

export const APP_TIME_ZONE = import.meta.env.VITE_APP_TIME_ZONE || DEFAULT_TIME_ZONE;

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

export const formatAppDateTime = (value?: string | number | Date | null) => {
  if (value === undefined || value === null) {
    return '--';
  }
  try {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '--';
    }
    return dateTimeFormatter.format(date);
  } catch (error) {
    return '--';
  }
};
