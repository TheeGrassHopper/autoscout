import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

const handler = NextAuth({
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;
        try {
          const res = await fetch(`${BASE}/auth/login`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
            },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          });
          if (!res.ok) return null;
          const { token, user } = await res.json();
          return {
            id: String(user.id),
            email: user.email,
            role: user.role,
            notify_carvana: user.notify_carvana,
            created_at: user.created_at,
            accessToken: token,
          };
        } catch {
          return null;
        }
      },
    }),
  ],

  callbacks: {
    async jwt({ token, user }) {
      // user is only present on first sign-in
      if (user) {
        const u = user as unknown as Record<string, unknown>;
        token.id = u.id as string;
        token.role = u.role as string;
        token.notify_carvana = u.notify_carvana as boolean;
        token.created_at = u.created_at as string;
        token.accessToken = u.accessToken as string;
      }
      return token;
    },
    async session({ session, token }) {
      session.user.id = token.id;
      session.user.role = token.role;
      session.user.notify_carvana = token.notify_carvana;
      session.user.created_at = token.created_at;
      session.accessToken = token.accessToken;
      return session;
    },
  },

  pages: {
    signIn: "/login",
    error: "/login",
  },

  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },
});

export { handler as GET, handler as POST };
