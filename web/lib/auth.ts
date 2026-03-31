// web/lib/auth.ts — Auth types (session management handled by NextAuth)

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  notify_carvana: boolean;
  created_at: string;
}
