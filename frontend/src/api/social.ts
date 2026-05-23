import client from "./client";

export interface SocialPost {
  id: number;
  user_id: number;
  username: string;
  symbol: string | null;
  content: string;
  likes_count: number;
  comments_count: number;
  is_memo: boolean;
  liked_by_me: boolean;
  created_at: string | null;
}

export interface SocialComment {
  id: number;
  post_id: number;
  user_id: number;
  username: string;
  content: string;
  created_at: string | null;
}

export const getFeed = (params?: { symbol?: string; memos_only?: boolean }): Promise<SocialPost[]> =>
  client.get("/api/social/feed", { params }).then((r) => r.data);

export const createPost = (body: { content: string; symbol?: string; is_memo?: boolean }): Promise<SocialPost> =>
  client.post("/api/social/posts", body).then((r) => r.data);

export const deletePost = (id: number): Promise<{ ok: boolean }> =>
  client.delete(`/api/social/posts/${id}`).then((r) => r.data);

export const toggleLike = (postId: number): Promise<{ liked: boolean; likes_count: number }> =>
  client.post(`/api/social/posts/${postId}/like`).then((r) => r.data);

export const getComments = (postId: number): Promise<SocialComment[]> =>
  client.get(`/api/social/posts/${postId}/comments`).then((r) => r.data);

export const addComment = (postId: number, content: string): Promise<SocialComment> =>
  client.post(`/api/social/posts/${postId}/comments`, { content }).then((r) => r.data);

export const toggleFollow = (userId: number): Promise<{ following: boolean }> =>
  client.post(`/api/social/follow/${userId}`).then((r) => r.data);

export const getFollowing = (): Promise<{ id: number; username: string }[]> =>
  client.get("/api/social/following").then((r) => r.data);
