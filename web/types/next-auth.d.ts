import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken: string;
    user: {
      id: string;
      email: string;
      role: string;
      notify_carvana: boolean;
      created_at: string;
    };
  }

  interface User {
    id: string;
    email: string;
    role: string;
    notify_carvana: boolean;
    created_at: string;
    accessToken: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id: string;
    role: string;
    notify_carvana: boolean;
    created_at: string;
    accessToken: string;
  }
}
