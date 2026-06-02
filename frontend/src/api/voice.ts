import client from "./client";

export interface VoiceChatResponse {
  response: string;
  session_id: number;
  citations: string[];
  duration_seconds: number;
}

export interface VoiceUsage {
  used_seconds: number;
  limit_seconds: number;
  unlimited: boolean;
  tier: string;
}

export interface VoiceSession {
  id: number;
  created_at: string;
  duration_seconds: number;
  message_count: number;
}

export const voiceChat = (message: string, session_id: number | null, context: string) =>
  client.post<VoiceChatResponse>("/voice/chat", { message, session_id, context }).then(r => r.data);

export const getVoiceUsage = () =>
  client.get<VoiceUsage>("/voice/usage").then(r => r.data);

export const listVoiceSessions = () =>
  client.get<VoiceSession[]>("/voice/sessions").then(r => r.data);

export const deleteVoiceSession = (id: number) =>
  client.delete(`/voice/sessions/${id}`);
