import client from "./client";

export interface CFPSlot { datetime: string; available: boolean; }
export interface CFPBookingResult { confirmation_id: string; zoom_link: string; slot_datetime: string; calendar_invite_sent: boolean; topic: string; format: string; }
export interface CFPBookingItem { id: number; confirmation_id: string; slot_datetime: string; topic: string; format: string; zoom_link: string; status: string; }

export const getCFPAvailability = () =>
  client.get<{ slots: CFPSlot[] }>("/cfp/availability").then(r => r.data);

export const bookCFPSession = (slot_datetime: string, topic: string, format: string) =>
  client.post<CFPBookingResult>("/cfp/book", { slot_datetime, topic, format }).then(r => r.data);

export const getMyCFPBookings = () =>
  client.get<CFPBookingItem[]>("/cfp/my-bookings").then(r => r.data);
