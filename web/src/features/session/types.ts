export type SessionMode = "CHAT" | "AGENT" | "PREVIEW";

export type Session = {
  id: string;
  company_id: string;
  user_id: string;
  mode: SessionMode | string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
};

export type SessionEventData = Record<string, unknown>;

export type SessionEvent = {
  type: string;
  data: SessionEventData;
};

export type PostMessageResponse = {
  session: Session;
  messages: ChatMessage[];
  interrupted: boolean;
  mode: SessionMode | string;
  revision: number | null;
  pending_confirm: boolean;
  approval_token: string | null;
  events: SessionEvent[];
};

export type SessionSnapshot = {
  session_id: string;
  mode: SessionMode | string;
  status: string;
  state: Record<string, unknown>;
  revision: number | null;
  approval_token: string | null;
  image_url: string | null;
};
