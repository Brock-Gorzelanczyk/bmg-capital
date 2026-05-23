export interface AlertConfig {
  id: number;
  symbol: string;
  signal_type: string;
  threshold: number | null;
  enabled: boolean;
  created_at: string;
}

export interface AlertTrigger {
  id: number;
  alert_config_id: number;
  signal_type: string;
  symbol: string;
  value: number | null;
  message: string;
  triggered_at: string;
}

export interface Notification {
  id: string;
  symbol: string;
  signal_type: string;
  message: string;
  value?: number;
  timestamp: string;
  read: boolean;
}
