import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import "./journey.css";
import "./result.css";

export const metadata: Metadata = {
  title: "Valor Visível",
  description: "Descubra e diga, com as suas palavras, o valor do que você faz."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
